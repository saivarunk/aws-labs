#!/usr/bin/env python3
"""Allowlisted build archive; ARM64 CodeBuild only, no local Docker daemon."""

if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import hashlib
import os
import subprocess
import time
import zipfile
from scripts.common import ROOT, aws, terraform_output


# Explicit include list excludes .git, Terraform, state, credentials and logs.
BUILD_INPUTS = (
    "harness/__init__.py",
    "harness/app.py",
    "harness/checks.py",
    "harness/config.py",
    "harness/events.py",
    "harness/gates.py",
    "harness/gateway_client.py",
    "harness/gateway_proxy.py",
    "harness/opencode_config.py",
    "harness/process.py",
    "harness/runner.py",
    "harness/tasks.py",
    "harness/workspace.py",
    "harness/Dockerfile",
    "harness/buildspec.yml",
    "harness/self_check.sh",
    "harness/requirements.txt",
    "specs/kvstore/SPEC.md",
    "specs/kvstore/TASK_PROMPT.md",
)


def archive_sources(root=ROOT):
    files = [root / name for name in BUILD_INPUTS]
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise SystemExit(
            "Build inputs must be regular files from the explicit include list"
        )
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    tag = "source-" + digest.hexdigest()[:24]
    builddir = root / "build"
    builddir.mkdir(exist_ok=True)
    archive = builddir / (tag + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, path.relative_to(root))
    os.chmod(archive, 0o600)
    return archive, tag


def start_build(config, archive, tag):
    key = "source/" + archive.name
    subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            str(archive),
            "s3://" + config["bucket"] + "/" + key,
            "--region",
            config["region"],
            "--only-show-errors",
        ],
        check=True,
    )
    result = aws(
        "codebuild",
        "start-build",
        config["region"],
        {
            "projectName": config["project"],
            "sourceLocationOverride": config["bucket"] + "/" + key,
            "environmentVariablesOverride": [
                {"name": "IMAGE_TAG", "value": tag, "type": "PLAINTEXT"}
            ],
        },
    )
    return result["build"]["id"]


def wait_build(config, identifier, tag, builddir):
    print("CodeBuild started: " + identifier, flush=True)
    deadline = time.monotonic() + 2100
    last = None
    while time.monotonic() < deadline:
        build = aws(
            "codebuild", "batch-get-builds", config["region"], {"ids": [identifier]}
        )["builds"][0]
        phase = build.get("currentPhase")
        if phase != last:
            print("Phase: " + str(phase), flush=True)
            last = phase
        if build["buildStatus"] != "IN_PROGRESS":
            if build["buildStatus"] != "SUCCEEDED":
                raise SystemExit(
                    "Build "
                    + build["buildStatus"]
                    + "; inspect its CloudWatch log (no credentials are supplied to build)"
                )
            images = aws(
                "ecr",
                "describe-images",
                config["region"],
                {
                    "repositoryName": config["repository"],
                    "imageIds": [{"imageTag": tag}],
                },
            )
            uri = (
                config["repository_url"]
                + "@"
                + images["imageDetails"][0]["imageDigest"]
            )
            (builddir / "image-uri.txt").write_text(uri + "\n")
            print("Immutable image URI saved to build/image-uri.txt", flush=True)
            return
        time.sleep(10)
    raise SystemExit("Build wait timed out; check CodeBuild before restarting")


def main():
    config = terraform_output("build_config")
    if not config:
        raise SystemExit("Enable and apply enable_harness first")
    archive, tag = archive_sources()
    identifier = start_build(config, archive, tag)
    wait_build(config, identifier, tag, ROOT / "build")


if __name__ == "__main__":
    main()
