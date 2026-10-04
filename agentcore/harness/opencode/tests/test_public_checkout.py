"""Diagnostics must also work in a clean public checkout without local evidence."""

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify import identity


class FreshCheckoutTests(unittest.TestCase):
    def test_identity_probe_creates_evidence_directory_and_deletes_test_user(self):
        config = {
            "region": "us-east-1",
            "agent_client_id": "agent-client",
            "rogue_client_id": "rogue-client",
        }
        outputs = {
            "login_config": config,
            "cognito_user_pool_id": "test-pool",
            "gateway_url": "https://example.com/mcp",
            "runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test",
        }
        probe = 'data: {"type":"summary","status":"probe_passed"}\n\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(identity, "ROOT", root), patch.object(
                identity, "terraform_output", side_effect=outputs.__getitem__
            ), patch.object(identity, "aws") as aws, patch.object(
                identity, "token", side_effect=["agent-fixture", "rogue-fixture"]
            ), patch.object(
                identity,
                "invoke",
                side_effect=[(401, ""), (401, ""), (403, ""), (403, ""), (200, probe)],
            ), patch.object(
                sys, "argv", ["identity.py"]
            ), patch(
                "sys.stdout", io.StringIO()
            ):
                identity.main()
            evidence = json.loads(
                (root / "docs/evidence/runtime-probe.json").read_text()
            )
            self.assertTrue(all(evidence.values()))
            operations = [call.args[1] for call in aws.call_args_list]
            self.assertEqual(
                operations,
                ["admin-create-user", "admin-set-user-password", "admin-delete-user"],
            )


if __name__ == "__main__":
    unittest.main()
