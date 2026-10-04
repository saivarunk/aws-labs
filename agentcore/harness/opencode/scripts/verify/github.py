#!/usr/bin/env python3
"""Read-only Gateway identity/repository check; no provider token is retrieved."""
if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy direct-file entry point.

import argparse
import json
import sys

from scripts.common import ROOT, aws, read_token_file, terraform_output, write_evidence
from harness.events import redact
from harness.gateway_client import GatewayClient
from harness.tasks import KVSTORE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", default="build/user-a.jwt")
    parser.add_argument("--expected-login", default=None)
    parser.add_argument("--out", default="docs/evidence/github-read-check.json")
    args = parser.parse_args()
    token = read_token_file(ROOT / args.token_file)
    url = terraform_output("gateway_url")
    # Read deployed configuration, not caller-supplied repository arguments.
    region = terraform_output("login_config")["region"]
    gateway_id = url.split("//", 1)[1].split(".", 1)[0]
    targets = aws(
        "bedrock-agentcore-control",
        "list-gateway-targets",
        region,
        {"gatewayIdentifier": gateway_id},
    )
    target = next(t for t in targets["items"] if t["name"] == "github")
    client = GatewayClient(url, "Bearer " + token)
    report = {"target_status": target["status"], "writes_attempted": False}
    # The target repo is available in the deployed Runtime's non-secret environment.
    arn = terraform_output("runtime_arn")
    runtime = aws(
        "bedrock-agentcore-control",
        "get-agent-runtime",
        region,
        {"agentRuntimeId": arn.rsplit("/", 1)[-1]},
    )
    repo = runtime["environmentVariables"]["TARGET_REPO"]
    report["repo"] = repo
    owner, name = repo.split("/")
    try:
        names = client.discover(KVSTORE.required_tools, KVSTORE.optional_tools)
        for tool, arguments in [
            ("get_me", {}),
            ("get_file_contents", {"owner": owner, "repo": name, "path": "/"}),
        ]:
            result = client.call(
                "tools/call", {"name": names[tool], "arguments": arguments}
            )
            texts = [
                c.get("text", "")
                for c in result.get("content", [])
                if c.get("type") == "text"
            ]
            check = {"ok": not result.get("isError", False)}
            if not check["ok"]:
                check["error"] = redact("\n".join(texts), token)[:1000]
            elif tool == "get_me":
                check["login"] = json.loads(texts[0])["login"]
                if args.expected_login:
                    check["ok"] = check["login"] == args.expected_login
            else:
                check["result_text_count"] = len(texts)
            report[tool] = check
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["message"] = redact(str(exc), token)
    report["passed"] = all(
        report.get(tool, {}).get("ok", False)
        for tool in ["get_me", "get_file_contents"]
    )
    rendered = json.dumps(report, indent=2) + "\n"
    write_evidence(ROOT / args.out, report)
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
