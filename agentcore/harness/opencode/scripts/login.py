#!/usr/bin/env python3
"""Public Cognito client login with PKCE; passwords stay in Cognito's browser UI."""

if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy python scripts/... entry point.

import argparse
from scripts.common import terraform_output, write_private_token
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client", choices=["agent", "rogue"], default="agent")
    p.add_argument("--out", default="build/user-a.jwt")
    args = p.parse_args()
    cfg = terraform_output("login_config")
    callback = urllib.parse.urlsplit(cfg["callback_url"])
    if callback.hostname not in {"localhost", "127.0.0.1"} or callback.scheme != "http":
        raise SystemExit("This helper requires a registered HTTP loopback callback")
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    values = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path != callback.path or q.get("state") != [state]:
                self.send_response(400)
                self.end_headers()
                return
            if "code" in q:
                values["code"] = q["code"][0]
            else:
                values["error"] = "Cognito authorization was denied"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Authorization received. Return to your terminal.")

    with HTTPServer(("127.0.0.1", callback.port or 8765), Handler) as server:
        server.timeout = 1
        client = cfg[args.client + "_client_id"]
        url = (
            cfg["authorization_url"]
            + "?"
            + urllib.parse.urlencode(
                {
                    "client_id": client,
                    "response_type": "code",
                    "redirect_uri": cfg["callback_url"],
                    "scope": "openid email profile",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        print(
            "Opening Cognito sign-in. Use user-a (or user-b for isolation tests).",
            flush=True,
        )
        webbrowser.open(url)
        deadline = time.monotonic() + 180
        while not values and time.monotonic() < deadline:
            server.handle_request()
    if "code" not in values:
        raise SystemExit(values.get("error", "Login timed out; retry"))
    request = urllib.request.Request(
        cfg["token_url"],
        data=urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": client,
                "code": values["code"],
                "redirect_uri": cfg["callback_url"],
                "code_verifier": verifier,
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        token = json.load(response)["access_token"]
    write_private_token(args.out, token)
    print("Access token saved locally with mode 0600; never share or commit it.")


if __name__ == "__main__":
    main()
