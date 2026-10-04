"""Local MCP boundary: exact repository/branch, approved tools, pre-push gates.
Caller JWT remains in the parent process; OpenCode receives only a loopback URL.
Generated Go code can still access its process role credentials: IAM/network
controls remain the security boundary for arbitrary generated code.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .gates import GateRunner
from .tasks import KVSTORE


class Policy:
    def __init__(self, repo, branch, work, tools, env, remaining, task=KVSTORE):
        self.owner, self.repo = repo.split("/")
        self.branch, self.work, self.env, self.remaining = (
            branch,
            Path(work),
            env,
            remaining,
        )
        self.names = {v: k for k, v in tools.items()}
        self.pushed = False
        self.confirmed_pr_url = None
        self.task = task
        self.gate_runner = GateRunner(self.work, env, remaining, task)
        self.receipts = self.gate_runner.receipts
        self.lock = threading.Lock()

    def check(self, name, args):
        if name not in self.names:
            raise ValueError("Tool is not permitted")
        base = self.names[name]
        if base == "get_me":
            return
        if (
            str(args.get("owner", "")).lower() != self.owner.lower()
            or str(args.get("repo", "")).lower() != self.repo.lower()
        ):
            raise ValueError("Tool repository differs from deployed target")
        if (
            base in {"create_branch", "push_files"}
            and args.get("branch") != self.branch
        ):
            raise ValueError("Tool branch differs from session branch")
        if base == "create_pull_request":
            if args.get("head") != self.branch or not self.pushed:
                raise ValueError("PR requires this session branch and a confirmed push")
        if base == "push_files":
            if self.pushed:
                raise ValueError("Only one multi-file commit is allowed per run")
            files = args.get("files", [])
            if not isinstance(files, list) or not files:
                raise ValueError("Push requires deliverable files")
            seen = set()
            for item in files:
                path = item.get("path", "")
                p = Path(path)
                if not path or p.is_absolute() or ".." in p.parts or path in seen:
                    raise ValueError("Invalid push path")
                seen.add(path)
                if path in {"SPEC.md", "TASK_PROMPT.md"} or any(
                    x.startswith(".") and x != ".gitignore" for x in p.parts
                ):
                    raise ValueError("Private/task files cannot be pushed")
                if not (
                    p.suffix in self.task.allowed_suffixes
                    or path in self.task.required_files
                ):
                    raise ValueError("Push includes unexpected file type")
                local = (self.work / p).resolve()
                if (
                    not local.is_relative_to(self.work.resolve())
                    or not local.is_file()
                    or local.read_text() != item.get("content")
                ):
                    raise ValueError(
                        "Pushed content must match verified workspace files"
                    )
            if not self.task.required_files.issubset(seen):
                raise ValueError("Push is missing required deliverables")
            expected = {
                str(p.relative_to(self.work))
                for pattern in self.task.source_patterns
                for p in self.work.rglob(pattern)
                if p.is_file()
            }
            if not expected.issubset(seen):
                raise ValueError("Push must include all verified source and tests")
            self.gate_runner.run()
            # A test can mutate source files; compare again after executing it.
            for item in files:
                local = (self.work / item["path"]).resolve()
                if (
                    not local.is_relative_to(self.work.resolve())
                    or not local.is_file()
                    or local.read_text() != item["content"]
                ):
                    raise ValueError("Workspace changed while pre-push gates ran")


class Proxy:
    def __init__(self, forward, policy):
        self.forward, self.policy = forward, policy
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(405)
                self.end_headers()

            def do_POST(self):
                response_id = None
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4_000_000:
                        raise ValueError("Invalid MCP request size")
                    request = json.loads(self.rfile.read(size))
                    response_id = request.get("id")
                    method = request.get("method")
                    params = request.get("params", {})
                    if method == "notifications/initialized":
                        self.send_response(202)
                        self.end_headers()
                        return
                    if method not in {"initialize", "tools/list", "tools/call", "ping"}:
                        raise ValueError("Unsupported MCP operation")
                    with parent.policy.lock:
                        if method == "tools/call":
                            parent.policy.check(
                                params.get("name"), params.get("arguments", {})
                            )
                        result = parent.forward(method, params)
                        if method == "tools/list":
                            result = {
                                **result,
                                "tools": [
                                    t
                                    for t in result.get("tools", [])
                                    if t.get("name") in parent.policy.names
                                ],
                            }
                        if (
                            method == "tools/call"
                            and parent.policy.names[params["name"]] == "push_files"
                            and not result.get("isError", False)
                        ):
                            parent.policy.pushed = True
                        if (
                            method == "tools/call"
                            and parent.policy.names[params["name"]]
                            == "create_pull_request"
                            and not result.get("isError", False)
                        ):
                            match = re.search(
                                r"https://github\.com/"
                                + re.escape(
                                    parent.policy.owner + "/" + parent.policy.repo
                                )
                                + r"/pull/\d+",
                                json.dumps(result),
                            )
                            if match:
                                parent.policy.confirmed_pr_url = match.group()
                    body = {"jsonrpc": "2.0", "id": response_id, "result": result}
                except Exception as exc:
                    body = {
                        "jsonrpc": "2.0",
                        "id": response_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return "http://127.0.0.1:" + str(self.server.server_port) + "/mcp"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
