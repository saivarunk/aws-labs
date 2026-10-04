#!/usr/bin/env python3
"""Read-only leftover ENI report scoped to the local deployment state."""
if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy direct-file entry point.

import json
from scripts.common import ROOT, aws, redact


def main():
    root = ROOT
    s = json.loads((root / "terraform/terraform.tfstate").read_text())
    vpcs = [
        i["attributes"]["id"]
        for r in s["resources"]
        if r["type"] == "aws_vpc" and r["name"] == "harness"
        for i in r["instances"]
    ]
    if not vpcs:
        raise SystemExit("No harness VPC remains in state")
    region = next(
        r["instances"][0]["attributes"]["region"]
        for r in s["resources"]
        if r["type"] == "aws_bedrockagentcore_gateway"
    )
    r = aws(
        "ec2",
        "describe-network-interfaces",
        region,
        {"Filters": [{"Name": "vpc-id", "Values": vpcs}]},
    )
    print(
        redact(
            json.dumps(
                [
                    {
                        "id": e["NetworkInterfaceId"],
                        "status": e["Status"],
                        "type": e.get("InterfaceType"),
                        "description": e.get("Description"),
                    }
                    for e in r["NetworkInterfaces"]
                ],
                indent=2,
            )
        )
    )


if __name__ == "__main__":
    main()
