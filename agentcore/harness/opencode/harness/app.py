"""AgentCore HTTP endpoints and streaming event delivery."""

from contextlib import closing
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import RunConfig, RunRequest
from .events import activity_log, opencode_log, redact
from .gateway_client import AuthorizationRequired
from .runner import run

LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log headers, request bodies, or query strings.

    def json_response(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/ping":
            self.json_response(
                200, {"status": "HealthyBusy" if LOCK.locked() else "Healthy"}
            )
        else:
            self.json_response(404, {"error": "Unknown path"})

    def do_POST(self):
        if self.path != "/invocations":
            return self.json_response(404, {"error": "Unknown path"})
        authorization = self.headers.get("Authorization", "")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 120_000:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            config = RunConfig.from_environment()
            request = RunRequest.parse(payload, authorization, config)
        except (ValueError, TypeError) as exc:
            return self.json_response(
                400 if authorization else 401, {"error": str(exc)}
            )
        if not LOCK.acquire(blocking=False):
            return self.json_response(
                409, {"error": "Session already has an active run"}
            )
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        status = "failed"
        steps = 0
        activity_log(
            "invocation_started",
            run_id=run_id,
            mode=payload.get("mode", "run"),
            engine="opencode",
        )
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                with closing(run(request, authorization, config)) as events:
                    for event in events:
                        kind = event.get("type")
                        if kind == "opencode_event":
                            opencode_log(run_id, event["event"], authorization[7:])
                        if kind == "self_check":
                            activity_log(
                                "self_check",
                                run_id=run_id,
                                checks_passed=all(event["checks"].values()),
                            )
                        elif kind == "gateway_tools":
                            activity_log(
                                "gateway_discovered",
                                run_id=run_id,
                                tool_count=len(event["names"]),
                            )
                        elif kind == "github_access":
                            activity_log("github_access_verified", run_id=run_id)
                        elif (
                            kind == "opencode_event"
                            and event["event"].get("type") == "step_start"
                        ):
                            steps += 1
                            activity_log("agent_step", run_id=run_id, step=steps)
                        elif kind == "summary":
                            status = event["status"]
                            activity_log(
                                "invocation_summary",
                                run_id=run_id,
                                status=status,
                                push_confirmed=event.get("push_confirmed", False),
                            )
                        self.wfile.write(
                            (
                                "data: "
                                + redact(json.dumps(event), authorization[7:])
                                + "\n\n"
                            ).encode()
                        )
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                status = "client_disconnected"
            except AuthorizationRequired as exc:
                status = "authorization_required"
                activity_log("authorization_required", run_id=run_id)
                self.wfile.write(
                    (
                        "data: "
                        + json.dumps({"type": status, "message": str(exc)})
                        + "\n\n"
                    ).encode()
                )
                self.wfile.flush()
            except Exception as exc:
                activity_log(
                    "invocation_error", run_id=run_id, error_type=type(exc).__name__
                )
                event = {
                    "type": "error",
                    "message": redact(str(exc), authorization[7:]),
                }
                self.wfile.write(
                    (
                        "data: " + redact(json.dumps(event), authorization[7:]) + "\n\n"
                    ).encode()
                )
                self.wfile.flush()
        finally:
            activity_log(
                "invocation_finished",
                run_id=run_id,
                status=status,
                elapsed_seconds=round(time.monotonic() - started, 1),
            )
            LOCK.release()


def main():
    activity_log("server_started")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
