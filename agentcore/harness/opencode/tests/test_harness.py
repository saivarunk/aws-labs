import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from harness import events, gateway_client as gateway, process, runner
from harness.config import RunConfig, RunRequest
from harness.gateway_proxy import Policy
from harness.tasks import KVSTORE

REQUIRED = KVSTORE.required_tools


class HarnessTests(unittest.TestCase):
    def test_full_opencode_logs_preserve_output_and_redact_credentials(self):
        event = {
            "type": "tool_use",
            "part": {
                "state": {
                    "output": "go test: PASS\nBearer opaque-secret ghp_secretvalue caller-token",
                    "input": {
                        "command": "go test ./...",
                        "password": "private-password",
                    },
                }
            },
        }
        output = io.StringIO()
        with patch("sys.stdout", output):
            events.opencode_log("run-one", event, "caller-token")
        record = json.loads(output.getvalue())
        self.assertEqual(record["run_id"], "run-one")
        self.assertIn("go test: PASS", record["data"]["part"]["state"]["output"])
        self.assertEqual(
            record["data"]["part"]["state"]["input"]["command"], "go test ./..."
        )
        for secret in (
            "opaque-secret",
            "ghp_secretvalue",
            "caller-token",
            "private-password",
        ):
            self.assertNotIn(secret, output.getvalue())

    def test_large_opencode_logs_reassemble_without_truncation(self):
        event = {
            "type": "process_output",
            "text": "Unicode 😀 command output\n" * 10000,
        }
        output = io.StringIO()
        with patch("sys.stdout", output):
            events.opencode_log("run-large", event)
        lines = output.getvalue().splitlines()
        records = [json.loads(line) for line in lines]
        self.assertGreater(len(records), 1)
        self.assertEqual(len({record["event_id"] for record in records}), 1)
        self.assertTrue(all(len(line.encode()) < 256000 for line in lines))
        self.assertEqual(
            [record["chunk_index"] for record in records], list(range(len(records)))
        )
        self.assertEqual(
            json.loads("".join(record["chunk_data"] for record in records)), event
        )

    def test_repository_arguments_are_mirrored_without_accepting_agent_headers(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"result": {}}'
        response.headers = {"Content-Type": "application/json"}
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(gateway.urllib.request, "build_opener", return_value=opener):
            gateway.rpc(
                "https://example.com/mcp",
                "Bearer token",
                "tools/call",
                {
                    "arguments": {"owner": "owner", "repo": "demo"},
                    "headers": {"Mcp-Param-owner": "attacker"},
                },
            )
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_header("Mcp-param-owner"), "owner")
            self.assertEqual(request.get_header("Mcp-param-repo"), "demo")
            with self.assertRaises(ValueError):
                gateway.rpc(
                    "https://example.com/mcp",
                    "Bearer token",
                    "tools/call",
                    {"arguments": {"owner": "owner\r\nInjected: value"}},
                )

    def test_notification_transport_omits_id_and_preserves_session(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b""
        response.headers = {}
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(gateway.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(
                gateway.rpc(
                    "https://example.com/mcp",
                    "Bearer token",
                    "notifications/initialized",
                    {},
                    "session-id",
                ),
                ({}, "session-id"),
            )
        request = opener.open.call_args.args[0]
        self.assertNotIn("id", json.loads(request.data))
        self.assertEqual(request.get_header("Mcp-session-id"), "session-id")

    def test_consent_error_does_not_expose_authorization_url(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {
                "error": {
                    "code": -32042,
                    "message": "https://example.com/?request_uri=private-state",
                }
            }
        ).encode()
        response.headers = {"Content-Type": "application/json"}
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(gateway.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(gateway.AuthorizationRequired) as caught:
                gateway.rpc("https://example.com/mcp", "Bearer token", "tools/call")
        self.assertNotIn("private-state", str(caught.exception))

    def test_activity_logs_exclude_request_and_agent_data(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            events.activity_log(
                "invocation_started",
                run_id="safe-id",
                mode="probe",
                authorization="secret-token",
                specification="private spec",
                agent_output="private generated content",
            )
        record = json.loads(output.getvalue())
        self.assertEqual(set(record), {"service", "event", "run_id", "mode"})
        self.assertNotIn("secret-token", output.getvalue())
        self.assertNotIn("private", output.getvalue())

    def test_gateway_handshake_initializes_the_negotiated_session(self):
        with patch.dict(
            os.environ, {"GATEWAY_URL": "https://example.com/mcp"}
        ), patch.object(
            gateway,
            "rpc",
            side_effect=[
                ({"protocolVersion": gateway.MCP_VERSION}, "session-id"),
                ({}, "session-id"),
            ],
        ) as rpc:
            client = gateway.GatewayClient("https://example.com/mcp", "Bearer token")
            result = client.initialize()
            session = client.session
        self.assertEqual(session, "session-id")
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertEqual(
            rpc.call_args_list[1].args[2:],
            ("notifications/initialized", {}, "session-id"),
        )

    def test_github_access_check_rejects_discovery_only_success(self):
        with patch.dict(
            os.environ, {"GATEWAY_URL": "https://example.com/mcp"}
        ), patch.object(
            gateway,
            "rpc",
            side_effect=[
                ({}, "session"),
                ({}, "session"),
                ({"isError": True, "content": [{"text": "internal error"}]}, "session"),
            ],
        ) as rpc:
            with self.assertRaisesRegex(
                RuntimeError, "Gateway GitHub access check failed"
            ):
                gateway.GatewayClient(
                    "https://example.com/mcp", "Bearer token"
                ).check_repository_access(
                    "owner/demo", {"get_file_contents": "github___get_file_contents"}
                )
            self.assertEqual(
                rpc.call_args.args[3]["arguments"],
                {"owner": "owner", "repo": "demo", "path": ""},
            )

    def test_unconfirmed_model_claim_cannot_complete_a_coding_run(self):
        self.assertEqual(
            runner.completion_status("run", "opencode", None), "run_incomplete"
        )
        self.assertEqual(
            runner.completion_status(
                "run", "opencode", "https://github.com/owner/demo/pull/1"
            ),
            "pr_created",
        )
        self.assertEqual(
            runner.completion_status("model_probe", "opencode", None),
            "opencode_completed",
        )

    def test_input_cannot_override_deployed_repo_or_escape_branch(self):
        with patch.dict(os.environ, {"TARGET_REPO": "owner/demo"}):
            for payload in [
                {"target_repo": "attacker/other"},
                {"branch_suffix": "../../bad"},
            ]:
                with self.assertRaises(ValueError):
                    RunRequest.parse(
                        payload, "Bearer " + "x" * 30, RunConfig.from_environment()
                    )

    def test_missing_forwarded_token_fails_closed(self):
        with self.assertRaises(ValueError):
            RunRequest.parse({}, "", RunConfig.from_environment())

    def test_redaction_removes_exact_token_and_authorization_query(self):
        clean = events.redact(
            "secret-value https://example.com/?request_uri=secret-state", "secret-value"
        )
        self.assertNotIn("secret-value", clean)
        self.assertNotIn("secret-state", clean)

    def test_discovery_requires_actual_catalog_and_rejects_ambiguous_tools(self):
        tools = [
            {"name": "github___" + x, "inputSchema": {"type": "object"}}
            for x in REQUIRED
        ]
        with patch.dict(
            os.environ, {"GATEWAY_URL": "https://example.com/mcp"}
        ), patch.object(
            gateway,
            "rpc",
            side_effect=[({}, None), ({}, None), ({"tools": tools}, None)],
        ):
            self.assertEqual(
                set(
                    gateway.GatewayClient(
                        "https://example.com/mcp", "Bearer token"
                    ).discover(REQUIRED)
                ),
                REQUIRED,
            )
        tools.append({"name": "other___create_branch", "inputSchema": {}})
        with patch.dict(
            os.environ, {"GATEWAY_URL": "https://example.com/mcp"}
        ), patch.object(
            gateway,
            "rpc",
            side_effect=[({}, None), ({}, None), ({"tools": tools}, None)],
        ):
            with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
                gateway.GatewayClient(
                    "https://example.com/mcp", "Bearer token"
                ).discover(REQUIRED)

    def test_timeout_kills_process_group(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            list(
                process.process_events(
                    [sys.executable, "-c", "import time;time.sleep(10)"],
                    ".",
                    os.environ.copy(),
                    0.15,
                )
            )
        self.assertLess(time.monotonic() - started, 2)

    def test_tool_policy_rejects_other_repo_branch_and_premature_pr(self):
        with tempfile.TemporaryDirectory() as d:
            policy = Policy(
                "owner/demo",
                "harness/kvd-run",
                d,
                {x: "github___" + x for x in REQUIRED},
                {},
                lambda: 60,
            )
            for name, args in [
                (
                    "create_branch",
                    {"owner": "other", "repo": "demo", "branch": "harness/kvd-run"},
                ),
                ("create_branch", {"owner": "owner", "repo": "demo", "branch": "main"}),
                (
                    "create_pull_request",
                    {"owner": "owner", "repo": "demo", "head": "harness/kvd-run"},
                ),
            ]:
                with self.assertRaises(ValueError):
                    policy.check("github___" + name, args)

    def test_push_cannot_include_task_files_or_different_content(self):
        with tempfile.TemporaryDirectory() as d:
            policy = Policy(
                "owner/demo",
                "harness/kvd-run",
                d,
                {"push_files": "github___push_files"},
                {},
                lambda: 60,
            )
            for files in [
                [{"path": "SPEC.md", "content": "secret"}],
                [{"path": "../../escape.go", "content": "bad"}],
                [{"path": "main.go", "content": "not the local content"}],
            ]:
                with self.assertRaises(ValueError):
                    policy.check(
                        "github___push_files",
                        {
                            "owner": "owner",
                            "repo": "demo",
                            "branch": "harness/kvd-run",
                            "files": files,
                        },
                    )


if __name__ == "__main__":
    unittest.main()
