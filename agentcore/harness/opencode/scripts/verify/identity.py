"""Live OAuth identity diagnostics; temporary users are deleted on every exit."""

if __package__ in (None, ""):
    import _bootstrap  # noqa: F401 - Legacy direct-file entry point.

import argparse
import base64
import hashlib
import http.cookiejar
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from scripts.common import ROOT, aws, redact, terraform_output, write_evidence
from harness.gateway_client import AuthorizationRequired, GatewayClient
from harness.tasks import KVSTORE


class Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}

    def handle_starttag(self, t, a):
        d = dict(a)
        if t == "form" and d.get("name") == "cognitoSignInForm":
            self.action = d["action"]
        if t == "input" and d.get("name") and d.get("type") == "hidden":
            self.fields[d["name"]] = d.get("value", "")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def token(client, cfg, user, password):
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(32)
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
    cookies = http.cookiejar.CookieJar()
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    r = o.open(url, timeout=20)
    f = Form()
    f.feed(r.read().decode())
    assert f.action
    f.fields.update(username=user, password=password, signInSubmitButton="Sign in")
    post = urllib.request.Request(
        urllib.parse.urljoin(r.url, f.action),
        data=urllib.parse.urlencode(f.fields).encode(),
    )
    nofollow = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies), NoRedirect()
    )
    try:
        r = nofollow.open(post, timeout=20)
    except urllib.error.HTTPError as e:
        r = e
    q = urllib.parse.parse_qs(
        urllib.parse.urlsplit(r.headers.get("Location", "")).query
    )
    assert q.get("state") == [state] and q.get(
        "code"
    ), "Cognito login did not return the expected code/state"
    req = urllib.request.Request(
        cfg["token_url"],
        data=urllib.parse.urlencode(
            {
                "client_id": client,
                "grant_type": "authorization_code",
                "code": q["code"][0],
                "redirect_uri": cfg["callback_url"],
                "code_verifier": verifier,
            }
        ).encode(),
    )
    return json.load(urllib.request.urlopen(req, timeout=20))["access_token"]


def invoke(url, jwt=None, payload=None, session=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if jwt:
        h["Authorization"] = "Bearer " + jwt
    if session:
        h["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=180)
        return r.code, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, redact(e.read().decode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="store_true")
    parser.add_argument(
        "--github",
        action="store_true",
        help="Check an unconsented user cannot create a branch",
    )
    args = parser.parse_args()
    cfg = terraform_output("login_config")
    pool = terraform_output("cognito_user_pool_id")
    gateway = terraform_output("gateway_url")
    arn = terraform_output("runtime_arn")
    user = "runtime-probe-" + secrets.token_hex(5)
    password = "Aa1!" + secrets.token_urlsafe(30)
    created = False
    try:
        aws(
            "cognito-idp",
            "admin-create-user",
            cfg["region"],
            {"UserPoolId": pool, "Username": user, "MessageAction": "SUPPRESS"},
        )
        created = True
        aws(
            "cognito-idp",
            "admin-set-user-password",
            cfg["region"],
            {
                "UserPoolId": pool,
                "Username": user,
                "Password": password,
                "Permanent": True,
            },
        )
        agent = token(cfg["agent_client_id"], cfg, user, password)
        rogue = token(cfg["rogue_client_id"], cfg, user, password)
        print("PKCE agent/rogue logins succeeded", flush=True)
        url = (
            "https://bedrock-agentcore."
            + cfg["region"]
            + ".amazonaws.com/runtimes/"
            + urllib.parse.quote(arn, safe="")
            + "/invocations?qualifier=demo"
        )
        checks = {}
        init = {
            "jsonrpc": "2.0",
            "id": "check",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "1"},
            },
        }
        for name, jwt in [("missing", None), ("rogue", rogue)]:
            status, _ = invoke(gateway, jwt, init)
            checks["gateway_" + name + "_rejected"] = status in [401, 403]
            status, _ = invoke(url, jwt, {"mode": "probe"}, str(uuid.uuid4()))
            checks["runtime_" + name + "_rejected"] = status in [401, 403]
            print(name, "negative checks", checks, flush=True)
        status, body = invoke(
            url,
            agent,
            {"mode": "model_probe" if args.model else "probe"},
            str(uuid.uuid4()),
        )
        print("Runtime valid status:", status, flush=True)
        print(redact(body.replace(agent, "[JWT]").replace(rogue, "[JWT]")), flush=True)
        checks["runtime_valid_http"] = status == 200
        events = [
            json.loads(line[6:])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        summaries = [event for event in events if event.get("type") == "summary"]
        checks["private_probe_passed"] = (
            (
                bool(summaries)
                and summaries[-1].get("engine") == "opencode"
                and summaries[-1].get("status")
                == summaries[-1]["engine"] + "_completed"
                and summaries[-1].get("push_confirmed") is False
                and "BEDROCK_OK" in body
            )
            if args.model
            else "probe_passed" in body
        )
        if args.github:
            client = GatewayClient(gateway, "Bearer " + agent)
            names = client.discover(KVSTORE.required_tools, KVSTORE.optional_tools)
            runtime = aws(
                "bedrock-agentcore-control",
                "get-agent-runtime",
                cfg["region"],
                {"agentRuntimeId": arn.rsplit("/", 1)[-1]},
            )
            owner, repo = runtime["environmentVariables"]["TARGET_REPO"].split("/")
            checks["unconsented_branch_create_rejected"] = False
            try:
                client.call(
                    "tools/call",
                    {
                        "name": names["create_branch"],
                        "arguments": {
                            "owner": owner,
                            "repo": repo,
                            "branch": "harness/unconsented-" + secrets.token_hex(6),
                        },
                    },
                )
            except AuthorizationRequired:
                checks["unconsented_branch_create_rejected"] = True
            print(
                "Fresh unconsented user branch-create requires authorization:",
                checks["unconsented_branch_create_rejected"],
                flush=True,
            )
            write_evidence(
                ROOT / "docs/evidence/github-unconsented-user.json",
                {
                    "fresh_diagnostic_user": True,
                    "branch_create_authorization_required": checks[
                        "unconsented_branch_create_rejected"
                    ],
                },
            )
        write_evidence(
            ROOT
            / (
                "docs/evidence/runtime-model-probe.json"
                if args.model
                else "docs/evidence/runtime-probe.json"
            ),
            checks,
        )
        assert all(checks.values()), checks
    finally:
        if created:
            aws(
                "cognito-idp",
                "admin-delete-user",
                cfg["region"],
                {"UserPoolId": pool, "Username": user},
            )
            print("Temporary diagnostic user deleted", flush=True)


if __name__ == "__main__":
    main()
