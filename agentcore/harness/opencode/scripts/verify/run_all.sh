#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
terraform -chdir=terraform fmt -check
terraform -chdir=terraform validate
python3 -m unittest discover -s tests -v
python3 scripts/verify/secret_scan.py
python3 scripts/verify/network.py
python3 scripts/verify/identity.py
# --model is explicit because it invokes paid Bedrock inference.
# Destroy, a real expired token, two-session isolation, and GitHub writes require
# separate end-to-end evidence; this script does not certify those criteria.
