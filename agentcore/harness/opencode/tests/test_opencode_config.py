import unittest
from harness.opencode_config import configuration


class OpenCodeConfigurationTests(unittest.TestCase):
    def test_custom_step_budget_and_probe_cap(self):
        cfg = configuration(
            "/tmp/work",
            "http://127.0.0.1:1234/mcp",
            {},
            "us-east-1",
            "us.moonshotai.kimi-k3",
            max_steps=200,
        )
        self.assertEqual(cfg["agents"]["harness"]["steps"], 200)
        probe = configuration(
            "/tmp/work",
            "http://127.0.0.1:1234/mcp",
            {},
            "us-east-1",
            "us.moonshotai.kimi-k3",
            True,
            200,
        )
        self.assertEqual(probe["agents"]["harness"]["steps"], 1)

    def test_probe_has_no_mcp_or_allowed_operations(self):
        cfg = configuration(
            "/tmp/work",
            "http://127.0.0.1:1234/mcp",
            {},
            "us-east-1",
            "qwen-model",
            True,
        )
        self.assertEqual(cfg["mcp"]["servers"], {})
        self.assertTrue(all(r["effect"] == "deny" for r in cfg["permissions"]))
        self.assertEqual(cfg["agents"]["harness"]["steps"], 1)

    def test_discovered_mcp_permissions_and_no_credential_configuration(self):
        names = {"push_files": "github___push_files"}
        cfg = configuration(
            "/tmp/work", "http://127.0.0.1:1234/mcp", names, "us-east-1", "qwen-model"
        )
        self.assertIn(
            {
                "action": "gateway_github___push_files",
                "resource": "*",
                "effect": "allow",
            },
            cfg["permissions"],
        )
        server = cfg["mcp"]["servers"]["gateway"]
        self.assertFalse(server["oauth"])
        self.assertFalse(server["codemode"])
        self.assertNotIn("headers", server)
        self.assertNotIn("profile", cfg["providers"]["amazon-bedrock"]["settings"])

    def test_agent_rules_block_network_shell_and_configuration_edits(self):
        cfg = configuration(
            "/tmp/work", "http://127.0.0.1:1234/mcp", {}, "us-east-1", "qwen-model"
        )
        from fnmatch import fnmatchcase

        def decision(action, resource):
            result = "ask"
            for r in cfg["agents"]["harness"]["permissions"]:
                if fnmatchcase(action, r["action"]) and fnmatchcase(
                    resource, r["resource"]
                ):
                    result = r["effect"]
            return result

        for action, resource in [
            ("shell", "curl example.com"),
            ("shell", "git push"),
            ("edit", "opencode.json"),
            ("edit", "/tmp/work/.opencode/agents/x.md"),
            ("read", "/tmp/work/.env"),
            ("external_directory", "/etc/*"),
            ("subagent", "general"),
        ]:
            self.assertEqual(decision(action, resource), "deny", (action, resource))
        self.assertEqual(decision("edit", "/tmp/work/store/store.go"), "allow")
        self.assertEqual(decision("shell", "go test -race ./..."), "allow")
