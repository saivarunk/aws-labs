import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import invoke


class InvokeTests(unittest.TestCase):
    def test_interrupt_stops_the_same_oauth_session_without_printing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("private-caller-token")
            token.chmod(0o600)
            response = MagicMock()
            response.__enter__.return_value.status = 200
            outputs = [
                SimpleNamespace(
                    stdout=json.dumps(
                        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/demo"
                    )
                ),
                SimpleNamespace(stdout=json.dumps({"region": "us-east-1"})),
            ]
            stream = io.StringIO()
            with patch.object(
                sys, "argv", ["invoke.py", "--token-file", str(token)]
            ), patch(
                "scripts.common.subprocess.run", side_effect=outputs
            ), patch.object(
                invoke.urllib.request,
                "urlopen",
                side_effect=[KeyboardInterrupt, response],
            ) as opener, patch(
                "sys.stdout", stream
            ):
                with self.assertRaises(SystemExit) as caught:
                    invoke.main()
            self.assertEqual(caught.exception.code, 130)
            invocation, stop = [call.args[0] for call in opener.call_args_list]
            self.assertIn("/stopruntimesession?qualifier=demo", stop.full_url)
            self.assertEqual(
                stop.get_header("X-amzn-bedrock-agentcore-runtime-session-id"),
                invocation.get_header("X-amzn-bedrock-agentcore-runtime-session-id"),
            )
            self.assertEqual(
                stop.get_header("Authorization"), "Bearer private-caller-token"
            )
            self.assertNotIn("private-caller-token", stream.getvalue())
