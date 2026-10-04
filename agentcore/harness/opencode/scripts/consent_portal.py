#!/usr/bin/env python3
"""Narrow AWS CLI lifecycle adapter for the Terraform consent-portal gap."""


if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import argparse
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlsplit


from scripts.common import AwsError, aws, redact


def lookup(config):
    result = aws("bedrock-agentcore-control", "list-consent-portals", config["region"])
    matches = [
        portal
        for portal in result.get("consentPortals", [])
        if portal["name"] == config["name"]
    ]
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple portals match the configured name; refusing an ambiguous mutation"
        )
    if not matches:
        return None
    try:
        return aws(
            "bedrock-agentcore-control",
            "get-consent-portal",
            config["region"],
            {"consentPortalIdentifier": matches[0]["consentPortalId"]},
        )
    except AwsError as exc:
        # List can lag deletion while Get already reports absence.
        if "ResourceNotFoundException" in str(exc):
            return None
        raise


def wait_active(config, identifier, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        portal = aws(
            "bedrock-agentcore-control",
            "get-consent-portal",
            config["region"],
            {"consentPortalIdentifier": identifier},
        )
        if portal["status"] == "ACTIVE":
            url = portal.get("portalUrl", "")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.query
                or parsed.fragment
            ):
                raise RuntimeError(
                    "ACTIVE portal did not return a valid HTTPS portal URL"
                )
            return portal
        if portal["status"] not in {"CREATING", "UPDATING"}:
            raise RuntimeError(
                "Consent portal status: "
                + portal["status"]
                + "; "
                + redact(portal.get("statusReason") or "")
            )
        time.sleep(5)
    raise RuntimeError(
        "Consent portal did not become ACTIVE within the bounded 600-second wait"
    )


def client_update_payload(client, allowed_fields, callback):
    # DescribeUserPoolClient contains ClientSecret and timestamps; neither may
    # be sent back in UpdateUserPoolClient or exposed in logs.
    payload = {key: value for key, value in client.items() if key in allowed_fields}
    payload.pop("ClientSecret", None)
    payload["CallbackURLs"] = [callback]
    # Keep an existing default redirect consistent if one was configured.
    if payload.get("DefaultRedirectURI"):
        payload["DefaultRedirectURI"] = callback
    return payload


def configure_callback(config, portal):
    callback = portal["portalUrl"].rstrip("/") + "/callback"
    client = aws(
        "cognito-idp",
        "describe-user-pool-client",
        config["region"],
        {"UserPoolId": config["pool_id"], "ClientId": config["client_id"]},
    )["UserPoolClient"]
    if client.get("CallbackURLs") == [callback]:
        return
    fields = aws(
        "cognito-idp", "update-user-pool-client", config["region"], skeleton=True
    )
    payload = client_update_payload(client, fields, callback)
    payload.update({"UserPoolId": config["pool_id"], "ClientId": config["client_id"]})
    aws("cognito-idp", "update-user-pool-client", config["region"], payload)


def harden_trust(config, portal):
    role_arn = config["executionRoleArn"]
    account = role_arn.split(":")[4]
    role_name = role_arn.rsplit("/", 1)[-1]
    desired = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": portal["consentPortalArn"]},
                },
            }
        ],
    }
    role = aws("iam", "get-role", config["region"], {"RoleName": role_name})["Role"]
    if role.get("AssumeRolePolicyDocument") != desired:
        aws(
            "iam",
            "update-assume-role-policy",
            config["region"],
            {"RoleName": role_name, "PolicyDocument": json.dumps(desired)},
        )


def assert_owned(config, portal):
    if portal.get("sources") != config["sources"]:
        raise RuntimeError(
            "Existing portal has different Gateway sources; refusing adoption or deletion"
        )


def upsert(config):
    portal = lookup(config)
    desired = {
        key: config[key] for key in ["executionRoleArn", "idpConfig", "description"]
    }
    if portal:
        assert_owned(config, portal)
        portal = wait_active(config, portal["consentPortalId"])
        if any(portal.get(key) != value for key, value in desired.items()):
            aws(
                "bedrock-agentcore-control",
                "update-consent-portal",
                config["region"],
                {**desired, "consentPortalIdentifier": portal["consentPortalId"]},
            )
    else:
        portal = aws(
            "bedrock-agentcore-control",
            "create-consent-portal",
            config["region"],
            {
                **desired,
                "name": config["name"],
                "sources": config["sources"],
                "tags": config["tags"],
            },
        )
    portal = wait_active(config, portal["consentPortalId"])
    configure_callback(config, portal)
    harden_trust(config, portal)
    print(
        "Managed consent portal ACTIVE; Cognito callback configured and role trust narrowed."
    )


def delete(config):
    portal = lookup(config)
    if not portal:
        print("Consent portal already absent.")
        return
    assert_owned(config, portal)
    if portal["status"] != "DELETING":
        aws(
            "bedrock-agentcore-control",
            "delete-consent-portal",
            config["region"],
            {"consentPortalIdentifier": portal["consentPortalId"]},
        )
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if lookup(config) is None:
            print("Consent portal deleted.")
            return
        time.sleep(5)
    raise RuntimeError(
        "Portal deletion not confirmed within 600 seconds; keep dependencies intact and retry"
    )


def read(config):
    portal = lookup(config)
    if portal is None or portal.get("status") != "ACTIVE":
        raise RuntimeError(
            "Consent portal missing or not ACTIVE; run Terraform apply to reconcile"
        )
    print(
        json.dumps(
            {
                "portal_url": portal["portalUrl"].rstrip("/"),
                "portal_id": portal["consentPortalId"],
                "portal_arn": portal["consentPortalArn"],
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["upsert", "delete", "read"])
    args = parser.parse_args()
    try:
        config = (
            json.load(sys.stdin)
            if args.operation == "read"
            else json.loads(os.environ["PORTAL_CONFIG"])
        )
        {"upsert": upsert, "delete": delete, "read": read}[args.operation](config)
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as exc:
        print("Consent portal operation failed: " + redact(str(exc)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
