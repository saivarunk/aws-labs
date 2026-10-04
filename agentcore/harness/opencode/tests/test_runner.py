"""Contract checks for the refactored orchestration and HTTP boundaries."""

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from harness import app, runner
from harness.config import RunConfig, RunRequest
from harness.gates import GateRunner
from harness.opencode_config import configuration
from harness.tasks import Gate, KVSTORE


class RunnerTests(unittest.TestCase):
    def test_task_definition_drives_permissions_environment_branch_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specs = root / "specs"
            specs.mkdir()
            (specs / "TASK_PROMPT.md").write_text(
                "Write a Python program and validate it."
            )
            task = replace(
                KVSTORE,
                name="python-example",
                spec_directory=specs,
                branch_prefix="harness/python-",
                environment=(("PYTHONUNBUFFERED", "1"),),
                edit_patterns=("*.py", "*.md"),
                shell_commands=("python3",),
                source_patterns=("*.py",),
                allowed_suffixes=frozenset({".py", ".md"}),
            )
            cfg = RunConfig(
                "owner/demo",
                "https://example.com/mcp",
                "us-east-1",
                "test-model",
                workspace_root=root / "runs",
            )
            request = RunRequest("owner/demo", "A tiny Python task", "test", "run")
            token = "caller-secret-" + "x" * 30
            names = {name: "github___" + name for name in task.required_tools}
            work_seen = []

            def cli_events(command, work, environment, timeout):
                work_seen.append(work)
                self.assertIn("amazon-bedrock/test-model", command)
                self.assertIn("Branch: harness/python-test", command[-1])
                self.assertEqual(environment["PYTHONUNBUFFERED"], "1")
                config_path = (
                    Path(environment["XDG_CONFIG_HOME"]) / "opencode/opencode.json"
                )
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(token, config_path.read_text())
                self.assertEqual((work / "SPEC.md").read_text(), request.spec)
                yield json.dumps(
                    {
                        "type": "text",
                        "part": {"text": "https://github.com/owner/demo/pull/1"},
                    }
                )

            with patch.object(
                runner, "self_check", return_value={"safe": True}
            ), patch.object(runner, "GatewayClient") as client, patch.object(
                runner, "process_events", side_effect=cli_events
            ):
                client.return_value.discover.return_value = names
                events = list(runner.run(request, "Bearer " + token, cfg, task))
            self.assertEqual(events[-1]["status"], "run_incomplete")
            self.assertIsNone(events[-1]["pr_url"])
            self.assertFalse(work_seen[0].exists())
            adapter = configuration(
                "/tmp/work",
                "http://127.0.0.1:1",
                names,
                "us-east-1",
                "test-model",
                task=task,
            )
            self.assertTrue(
                any(r.get("resource") == "*.py" for r in adapter["permissions"])
            )
            self.assertFalse(
                any(r.get("resource") == "*.go" for r in adapter["permissions"])
            )

    def test_gate_coverage_is_checked_for_each_required_package(self):
        command = (
            sys.executable,
            "-c",
            "print('ok mod/store coverage: 79.0% of statements'); print('ok mod/api coverage: 98.0% of statements')",
        )
        task = replace(
            KVSTORE,
            gates=(
                Gate(command, coverage_packages=("store", "api"), minimum_coverage=80),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "store requires at least 80%"):
                GateRunner(directory, os.environ.copy(), lambda: 30, task).run()

    def test_http_stream_contract_keeps_credentials_out_of_events(self):
        token = "x" * 30
        config = RunConfig(
            "owner/demo", "https://example.com/mcp", "us-east-1", "test-model"
        )

        def events(request, authorization, settings):
            self.assertIsInstance(request, RunRequest)
            self.assertEqual(authorization, "Bearer " + token)
            self.assertEqual(settings, config)
            yield {"type": "opencode_event", "event": {"type": "text", "text": token}}
            yield {"type": "summary", "status": "probe_passed"}

        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/invocations",
                data=json.dumps({"mode": "probe", "spec": "test spec"}).encode(),
                headers={"Authorization": "Bearer " + token},
            )
            with patch.object(
                app.RunConfig, "from_environment", return_value=config
            ), patch.object(app, "run", side_effect=events), patch(
                "sys.stdout", io.StringIO()
            ) as log:
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(
                        response.headers["Content-Type"], "text/event-stream"
                    )
                    body = response.read().decode()
                self.assertNotIn(token, body)
                self.assertNotIn(token, log.getvalue())
                self.assertIn("probe_passed", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
