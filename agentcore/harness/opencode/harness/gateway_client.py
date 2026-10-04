"""Stateful MCP client; caller credentials stay outside the agent process."""

import json
import re
import urllib.request
import uuid
from .events import redact

MCP_VERSION = "2025-11-25"


class AuthorizationRequired(RuntimeError):
    pass


def rpc(url, authorization, method, params=None, session=None):
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
    }
    if session:
        headers["Mcp-Session-Id"] = session
    # GitHub's discovered schemas mirror repository routing arguments into
    # SEP-2243 headers. Derive them from arguments after the proxy policy check;
    # never accept arbitrary headers from the agent.
    if method == "tools/call":
        for name in ("owner", "repo"):
            value = (params or {}).get("arguments", {}).get(name)
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+", value
                ):
                    raise ValueError("Invalid repository routing parameter")
                headers["Mcp-Param-" + name] = value
    message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not method.startswith("notifications/"):
        message["id"] = uuid.uuid4().hex
    req = urllib.request.Request(
        url, data=json.dumps(message).encode(), headers=headers
    )

    # Do not forward credentials across a redirect to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise RuntimeError("Gateway response exceeds limit")
        text = raw.decode()
        if not text and method.startswith("notifications/"):
            return {}, response.headers.get("Mcp-Session-Id", session)
        if response.headers.get("Content-Type", "").startswith("text/event-stream"):
            objects = [
                json.loads(line[6:])
                for line in text.splitlines()
                if line.startswith("data: ")
            ]
            result = next(
                (item for item in objects if "result" in item or "error" in item), {}
            )
        else:
            result = json.loads(text)
        if "error" in result:
            if result["error"].get("code") == -32042:
                raise AuthorizationRequired(
                    "GitHub authorization required. Reconnect the same user in the managed consent portal, then retry."
                )
            raise RuntimeError(
                "Gateway MCP request failed: "
                + redact(json.dumps(result["error"]), authorization[7:])
            )
        return result.get("result", {}), response.headers.get("Mcp-Session-Id", session)


class GatewayClient:
    def __init__(self, url, authorization):
        if not url.startswith("https://"):
            raise ValueError("Gateway URL must use HTTPS")
        self.url = url
        self.authorization = authorization
        self.session = None

    def call(self, method, params=None):
        result, self.session = rpc(
            self.url, self.authorization, method, params, self.session
        )
        return result

    def initialize(self):
        result = self.call(
            "initialize",
            {
                "protocolVersion": MCP_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "coding-harness", "version": "0.1.0"},
            },
        )
        self.call("notifications/initialized", {})
        return result

    def forward(self, method, params):
        return (
            self.initialize() if method == "initialize" else self.call(method, params)
        )

    def discover(self, required, optional=()):
        self.initialize()
        tools = []
        cursor = None
        for _ in range(20):
            result = self.call("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        else:
            raise RuntimeError("Gateway tool pagination exceeds limit")
        names = {}
        for tool in tools:
            name = tool.get("name", "")
            base = name.split("___")[-1]
            if base in set(required) | set(optional) and isinstance(
                tool.get("inputSchema"), dict
            ):
                if base in names:
                    raise RuntimeError("Ambiguous Gateway tool name: " + base)
                names[base] = name
        missing = set(required) - names.keys()
        if missing:
            raise RuntimeError(
                "Gateway discovery not ready; missing tools: "
                + ", ".join(sorted(missing))
            )
        return names

    def check_repository_access(self, repo, names):
        owner, repository = repo.split("/")
        self.initialize()
        result = self.call(
            "tools/call",
            {
                "name": names["get_file_contents"],
                "arguments": {"owner": owner, "repo": repository, "path": ""},
            },
        )
        if result.get("isError") or not result.get("content"):
            raise RuntimeError(
                "Gateway GitHub access check failed; resolve the user connection or target error before running the coding agent"
            )
