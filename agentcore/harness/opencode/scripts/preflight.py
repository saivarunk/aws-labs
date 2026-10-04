#!/usr/bin/env python3
"""Read-only regional/model spike. Does not invoke a model or create resources."""


if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import argparse
from scripts.common import aws_cli as aws, redact
import json
import subprocess
import sys

# AZ IDs are stable across accounts; AZ names are not. Recheck AWS supported
# zones before adding another region or changing the private subnet topology.
SUPPORTED_AZ_IDS = {"us-east-1": {"use1-az1", "use1-az2", "use1-az4"}}
SERVICES = (
    "bedrock-runtime",
    "ecr.api",
    "ecr.dkr",
    "logs",
    "s3",
    "bedrock-agentcore.gateway",
)


def check_model(model):
    if "ON_DEMAND" not in model.get("inferenceTypesSupported", []):
        raise RuntimeError("Model does not support on-demand inference")
    arn = model.get("modelArn")
    if not arn:
        raise RuntimeError("Foundation model ARN is missing")
    return [arn]


def run(region, model, profile):
    if region not in SUPPORTED_AZ_IDS:
        raise RuntimeError(
            "Supported AgentCore AZ IDs have not been verified for this region"
        )
    azs = aws(
        ["ec2", "describe-availability-zones", "--all-availability-zones"],
        region,
        profile,
    )
    by_id = {
        az["ZoneId"]: az["ZoneName"]
        for az in azs["AvailabilityZones"]
        if az["State"] == "available"
    }
    supported = sorted(SUPPORTED_AZ_IDS[region] & by_id.keys())
    if len(supported) < 2:
        raise RuntimeError("Fewer than two supported AgentCore AZs are available")
    names = [f"com.amazonaws.{region}.{service}" for service in SERVICES]
    details = aws(
        ["ec2", "describe-vpc-endpoint-services", "--service-names", *names],
        region,
        profile,
    )
    returned = {
        service["ServiceName"]: service for service in details["ServiceDetails"]
    }
    missing = sorted(set(names) - returned.keys())
    if missing:
        raise RuntimeError(
            "Required VPC endpoint services unavailable: " + ", ".join(missing)
        )
    # Every interface endpoint must support both chosen subnets. S3 is a gateway
    # endpoint and has no interface ENIs/AZ constraint.
    compatible = set(supported)
    for name, service in returned.items():
        if name.endswith(".s3"):
            continue
        compatible &= {
            zone
            for zone in supported
            if by_id[zone] in service.get("AvailabilityZones", [])
        }
    if len(compatible) < 2:
        raise RuntimeError("Required interface endpoints lack two shared supported AZs")
    if model.startswith("us."):
        source = aws(
            [
                "bedrock",
                "get-inference-profile",
                "--inference-profile-identifier",
                model,
            ],
            region,
            profile,
        )
        if source.get("status") != "ACTIVE" or not source.get("models"):
            raise RuntimeError("Inference profile is not active or has no models")
        models = [item["modelArn"] for item in source["models"]]
        selected = source["inferenceProfileId"]
    else:
        source = aws(
            ["bedrock", "get-foundation-model", "--model-identifier", model],
            region,
            profile,
        )
        models = check_model(source["modelDetails"])
        selected = source["modelDetails"]["modelId"]
    print(
        json.dumps(
            {
                "status": "PASS",
                "region": region,
                "supported_az_ids": sorted(compatible),
                "endpoint_services": sorted(returned),
                "model_id": selected,
                "foundation_model_arns": [redact(value) for value in models],
                "limits": "Discovery only: invocation/model entitlement, private JWT traffic, consent, and session isolation remain VERIFY.",
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--model", default="us.moonshotai.kimi-k3")
    parser.add_argument(
        "--profile", help="AWS CLI profile; omitted means the existing credential chain"
    )
    args = parser.parse_args()
    try:
        run(args.region, args.model, args.profile)
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as exc:
        print("FAIL: " + redact(str(exc)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
