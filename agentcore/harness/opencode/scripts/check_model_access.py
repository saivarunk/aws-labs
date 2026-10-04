#!/usr/bin/env python3
"""Read-only check of the selected Bedrock model account-level access prerequisite."""

if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import argparse
import json
import sys
from scripts.common import aws_cli as aws


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--model", default="us.moonshotai.kimi-k3")
    args = parser.parse_args()
    model = args.model.removeprefix("us.")
    result = aws(
        ["bedrock", "get-foundation-model-availability", "--model-id", model],
        args.region,
        args.profile,
    )
    print(json.dumps(result, indent=2))
    ready = (
        result.get("agreementAvailability", {}).get("status") == "AVAILABLE"
        and result.get("authorizationStatus") == "AUTHORIZED"
        and result.get("entitlementAvailability") == "AVAILABLE"
        and result.get("regionAvailability") == "AVAILABLE"
    )
    if not ready:
        print(
            "Model access is incomplete. An administrator must enable the selected model "
            "in Bedrock Model catalog before a coding run.",
            file=sys.stderr,
        )
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
