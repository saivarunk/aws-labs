#!/bin/sh
set -eu
# Prints only booleans; tokens and role credentials are never displayed.
python3 -c 'import sys,json;sys.path.insert(0,"/opt/harness");from app import self_check;print(json.dumps(self_check()))'
