"""Shared local CLI operations, deployment outputs, and private token files."""

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from harness.events import redact as redact_credentials

ROOT = Path(__file__).resolve().parent.parent


class AwsError(RuntimeError):
    pass


def redact(text):
    return re.sub(r"\b\d{12}\b", "<account-id>", redact_credentials(text))


def aws(
    service, operation, region, payload=None, skeleton=False, profile=None, arguments=()
):
    command = [
        "aws",
        service,
        operation,
        *arguments,
        "--region",
        region,
        "--output",
        "json",
        "--no-cli-pager",
    ]
    if profile:
        command.extend(["--profile", profile])
    if skeleton:
        command.extend(["--generate-cli-skeleton", "input"])

    def execute():
        return subprocess.run(command, capture_output=True, text=True, timeout=60)

    if payload is not None and not skeleton:
        # The packaged AWS CLI on this host does not read /dev/stdin reliably.
        # Use a mode-0600 transient file outside the repository, removed even
        # on errors. Sensitive values never appear in command arguments/logs.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="agentcore-cli-"
        ) as request:
            os.fchmod(request.fileno(), 0o600)
            json.dump(payload, request)
            request.flush()
            command.extend(["--cli-input-json", "file://" + request.name])
            result = execute()
    else:
        result = execute()
    if result.returncode:
        raise AwsError(redact(result.stderr.strip()))
    return json.loads(result.stdout) if result.stdout.strip() else {}


def aws_cli(arguments, region, profile=None):
    return aws(
        arguments[0], arguments[1], region, profile=profile, arguments=arguments[2:]
    )


def terraform_output(name, root=ROOT):
    result = subprocess.run(
        ["terraform", "-chdir=" + str(root / "terraform"), "output", "-json", name],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def read_token_file(path):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise ValueError("Token must be a regular mode-0600 file")
    return path.read_text().strip()


def write_private_token(path, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(token + "\n")


def write_evidence(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")
