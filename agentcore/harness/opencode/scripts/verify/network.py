#!/usr/bin/env python3
"""Live read-only checks for private subnets, routes, endpoint SG egress."""
if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy direct-file entry point.

import json
from scripts.common import ROOT, aws, terraform_output, write_evidence


def main():
    n = terraform_output("private_network")
    cfg = terraform_output("login_config")
    region = cfg["region"]
    subnets = aws("ec2", "describe-subnets", region, {"SubnetIds": n["subnets"]})[
        "Subnets"
    ]
    routes = aws(
        "ec2",
        "describe-route-tables",
        region,
        {"RouteTableIds": [n["private_route_table"]]},
    )["RouteTables"][0]["Routes"]
    rules = aws(
        "ec2",
        "describe-security-group-rules",
        region,
        {"Filters": [{"Name": "group-id", "Values": [n["runtime_sg"]]}]},
    )["SecurityGroupRules"]
    egress = [r for r in rules if r["IsEgress"]]
    checks = {
        "two_supported_private_subnets": len(subnets) == 2
        and all(
            s["AvailabilityZoneId"] in ["use1-az1", "use1-az2", "use1-az4"]
            and not s["MapPublicIpOnLaunch"]
            for s in subnets
        ),
        "no_internet_default_route": all(
            r.get("DestinationCidrBlock") != "0.0.0.0/0"
            and r.get("DestinationIpv6CidrBlock") != "::/0"
            and not r.get("NatGatewayId")
            and not r.get("GatewayId", "").startswith("igw-")
            for r in routes
        ),
        "https_endpoint_only_egress": len(egress) == 2
        and all(
            r.get("IpProtocol") == "tcp"
            and r.get("FromPort") == r.get("ToPort") == 443
            and (
                r.get("ReferencedGroupInfo", {}).get("GroupId") == n["endpoint_sg"]
                or r.get("PrefixListId")
            )
            and not r.get("CidrIpv4")
            and not r.get("CidrIpv6")
            for r in egress
        ),
    }
    print(json.dumps(checks, indent=2))
    assert all(checks.values()), checks
    write_evidence(ROOT / "docs/evidence/network-live-check.json", checks)


if __name__ == "__main__":
    main()
