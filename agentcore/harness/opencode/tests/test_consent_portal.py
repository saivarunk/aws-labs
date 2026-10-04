from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import consent_portal as portal


class ConsentPortalTests(unittest.TestCase):
    def test_eventually_consistent_deleted_portal_is_absent(self):
        calls = [
            {"consentPortals": [{"name": "demo", "consentPortalId": "id"}]},
            portal.AwsError("ResourceNotFoundException"),
        ]
        with patch.object(portal, "aws", side_effect=calls):
            self.assertIsNone(portal.lookup({"name": "demo", "region": "us-east-1"}))

    def test_callback_update_preserves_oauth_settings_and_removes_secret(self):
        client = {
            "ClientId": "client",
            "UserPoolId": "pool",
            "ClientSecret": "do-not-copy",
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": ["openid"],
            "AllowedOAuthFlowsUserPoolClient": True,
            "CallbackURLs": ["old"],
            "CreationDate": "yesterday",
        }
        writable = set(client) - {"ClientSecret", "CreationDate"}
        updated = portal.client_update_payload(
            client, writable, "https://portal.example/callback"
        )
        self.assertEqual(updated["AllowedOAuthFlows"], ["code"])
        self.assertTrue(updated["AllowedOAuthFlowsUserPoolClient"])
        self.assertEqual(updated["CallbackURLs"], ["https://portal.example/callback"])
        self.assertNotIn("ClientSecret", updated)
        self.assertNotIn("CreationDate", updated)

    def test_delete_absent_portal_has_no_delete_call(self):
        with patch.object(portal, "lookup", return_value=None), patch.object(
            portal, "aws"
        ) as api:
            portal.delete({"name": "demo", "region": "us-east-1"})
        api.assert_not_called()

    def test_foreign_gateway_is_not_adopted_or_deleted(self):
        with self.assertRaisesRegex(RuntimeError, "different Gateway"):
            portal.assert_owned(
                {"sources": [{"identifier": "ours"}]},
                {"sources": [{"identifier": "other"}]},
            )

    def test_failed_portal_never_configures_callback(self):
        with patch.object(
            portal,
            "aws",
            return_value={"status": "FAILED", "statusReason": "test failure"},
        ):
            with self.assertRaisesRegex(RuntimeError, "FAILED"):
                portal.wait_active({"region": "us-east-1"}, "portal")

    def test_active_plaintext_portal_url_is_rejected(self):
        with patch.object(
            portal,
            "aws",
            return_value={"status": "ACTIVE", "portalUrl": "http://portal.example"},
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                portal.wait_active({"region": "us-east-1"}, "portal")

    def test_aws_payload_file_is_private_deleted_and_secret_not_in_argv(self):
        result = type("Result", (), {"returncode": 0, "stdout": "{}"})()
        paths = []

        def execute(command, **kwargs):
            path = Path(
                command[command.index("--cli-input-json") + 1].removeprefix("file://")
            )
            paths.append(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("test-secret", path.read_text())
            self.assertNotIn("test-secret", " ".join(command))
            return result

        with patch.object(portal.subprocess, "run", side_effect=execute):
            portal.aws(
                "cognito-idp",
                "admin-set-user-password",
                "us-east-1",
                {"Password": "test-secret"},
            )
        self.assertFalse(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
