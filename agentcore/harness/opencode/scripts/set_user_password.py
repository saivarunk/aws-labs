#!/usr/bin/env python3
"""Set a Cognito demo user's permanent password without logging it."""


if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import argparse
import getpass
import subprocess
import sys

from scripts.common import aws, terraform_output
from scripts.common import redact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, choices=["user-a", "user-b"])
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    try:
        pool = terraform_output("cognito_user_pool_id")
        if not pool or pool == "null":
            raise RuntimeError("Deploy Cognito before setting a test-user password")
        password = getpass.getpass(
            "Permanent password (12+ chars, upper/lowercase, number, symbol): "
        )
        if password != getpass.getpass("Confirm password: "):
            raise RuntimeError("Passwords do not match")
        aws(
            "cognito-idp",
            "admin-set-user-password",
            args.region,
            {
                "UserPoolId": pool,
                "Username": args.user,
                "Password": password,
                "Permanent": True,
            },
        )
        print(
            "Permanent password set for " + args.user + "; sign in using that username."
        )
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
