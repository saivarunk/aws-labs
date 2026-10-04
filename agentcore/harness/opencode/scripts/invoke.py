#!/usr/bin/env python3
"""OAuth Runtime invoke; token file is never printed, SSE events are redacted."""

if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import argparse
from scripts.common import terraform_output, read_token_file
import json
from pathlib import Path
import urllib.parse
import urllib.request
import uuid
from scripts.common import redact


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token-file", default="build/user-a.jwt")
    p.add_argument("--mode", choices=["probe", "model_probe", "run"], default="probe")
    p.add_argument("--spec")
    p.add_argument("--session-id", default=None)
    args = p.parse_args()
    token = read_token_file(args.token_file)
    arn = terraform_output("runtime_arn")
    cfg = terraform_output("login_config")
    if not arn:
        raise SystemExit("Deploy the built Runtime first")
    session = args.session_id or str(uuid.uuid4())
    if not 33 <= len(session) <= 256:
        raise SystemExit("Session ID must have 33–256 characters")
    payload = {"mode": args.mode}
    if args.spec:
        payload["spec"] = Path(args.spec).read_text()
    url = (
        "https://bedrock-agentcore."
        + cfg["region"]
        + ".amazonaws.com/runtimes/"
        + urllib.parse.quote(arn, safe="")
        + "/invocations?qualifier=demo"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session,
        },
    )
    print("Runtime session: " + session, flush=True)
    try:
        with urllib.request.urlopen(request, timeout=7500) as response:
            for line in response:
                print(
                    redact(line.decode().replace(token, "[JWT]")).rstrip(), flush=True
                )
    except KeyboardInterrupt:
        # Closing the streaming client alone does not terminate the microVM.
        stop = urllib.request.Request(
            url.replace("/invocations?", "/stopruntimesession?"),
            data=b"{}",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session,
            },
        )
        try:
            with urllib.request.urlopen(stop, timeout=30) as response:
                print(
                    "Runtime session stopped (HTTP " + str(response.status) + ").",
                    flush=True,
                )
        except Exception as exc:
            print(
                "Could not confirm session stop: " + type(exc).__name__ + ".",
                flush=True,
            )
        raise SystemExit(130)


if __name__ == "__main__":
    main()
