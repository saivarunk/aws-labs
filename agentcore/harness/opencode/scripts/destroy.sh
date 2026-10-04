#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Review this saved destructive plan locally before applying. Keep the same
# TF_VAR GitHub values/profile used for deployment; state/plans contain secrets.
mkdir -p build
terraform -chdir=terraform plan -destroy -out=../build/destroy.tfplan
chmod 600 build/destroy.tfplan
printf 'Apply the reviewed destroy plan? Type destroy: '
read -r answer
[ "$answer" = destroy ] || exit 1
if terraform -chdir=terraform apply ../build/destroy.tfplan; then
  exit 0
fi
printf 'Destroy failed. Inspect leftover ENIs before retrying; do not detach service-managed ENIs.\n'
python3 scripts/verify/leftover_enis.py
# Do not silently regenerate or apply a changed destroy plan.
printf 'Wait for AWS ENI release, then rerun this script to review a fresh plan.\n'
exit 1
