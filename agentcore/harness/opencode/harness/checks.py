"""Runtime credential and network self-checks."""

import json
import os
import socket
from pathlib import Path


def self_check():
    credential_names = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ]
    present = [name for name in credential_names if os.environ.get(name)]
    paths = [
        Path.home() / ".git-credentials",
        Path.home() / ".netrc",
        Path.home() / ".aws" / "credentials",
    ]
    try:
        with socket.create_connection(("example.com", 443), timeout=3):
            internet_blocked = False
    except OSError:
        internet_blocked = True
    result = {
        "credential_environment_absent": not present,
        "credential_files_absent": not any(path.exists() for path in paths),
        "arbitrary_internet_blocked": internet_blocked,
    }
    if not all(result.values()):
        raise RuntimeError("Sandbox self-check failed: " + json.dumps(result))
    return result
