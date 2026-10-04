#!/usr/bin/env python3
"""Scan publishable source, never state or ignored run artifacts; no secret output."""
import re
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    paths = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    patterns = [
        rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
        rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b",
        rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}",
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    ]
    failed = []
    for name in paths:
        if not name:
            continue
        path = root / name.decode()
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if any(re.search(p, data) for p in patterns):
            failed.append(str(path.relative_to(root)))
    if failed:
        raise SystemExit(
            "Credential-shaped values found; inspect files locally: "
            + ", ".join(failed)
        )
    print(
        "No credential-shaped values found in publishable files. State/image checks are separate."
    )


if __name__ == "__main__":
    main()
