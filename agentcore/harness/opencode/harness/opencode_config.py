"""Ephemeral OpenCode V2 adapter with task-owned permissions."""

from pathlib import Path
from .tasks import KVSTORE


def configuration(
    work, proxy_url, names, region, model, probe=False, max_steps=180, task=KVSTORE
):
    work = Path(work).resolve()
    rules = [{"action": "*", "resource": "*", "effect": "deny"}]
    if not probe:
        rules += [
            {"action": action, "resource": "*", "effect": "allow"}
            for action in ["read", "glob", "grep"]
        ]
        rules += [
            {
                "action": "external_directory",
                "resource": str(work) + "/*",
                "effect": "allow",
            }
        ]
        # Only deliverables can be edited; generated project configuration must
        # not change the agent's permissions or load additional MCP/plugins.
        for pattern in task.edit_patterns:
            rules += [
                {"action": "edit", "resource": pattern, "effect": "allow"},
                {
                    "action": "edit",
                    "resource": str(work) + "/" + pattern,
                    "effect": "allow",
                },
            ]
        rules += [
            {"action": "shell", "resource": command + " *", "effect": "allow"}
            for command in task.shell_commands
        ]
        rules += [
            {"action": "gateway_" + name, "resource": "*", "effect": "allow"}
            for name in names.values()
        ]
        for pattern in [
            "*.env*",
            "*/.aws/*",
            "*/.git-credentials",
            "*/.netrc",
            "*opencode.json*",
            "*/.opencode/*",
        ]:
            rules += [
                {"action": action, "resource": pattern, "effect": "deny"}
                for action in ["read", "edit"]
            ]
    selected = "amazon-bedrock/" + model
    return {
        "$schema": "https://opencode.ai/config.json",
        "update": "disable",
        "snapshots": False,
        "share": "disabled",
        "model": selected,
        "default_agent": "harness",
        "providers": {"amazon-bedrock": {"settings": {"region": region}}},
        "permissions": rules,
        "agents": {
            "harness": {
                "mode": "primary",
                "steps": 1 if probe else max_steps,
                "system": (
                    "Reply exactly BEDROCK_OK without tools."
                    if probe
                    else task.system_prompt
                ),
                "permissions": rules,
            }
        },
        "mcp": {
            "servers": (
                {}
                if probe
                else {
                    "gateway": {
                        "type": "remote",
                        "url": proxy_url,
                        "oauth": False,
                        "codemode": False,
                        "protocol": "legacy",
                        "timeout": {
                            "startup": 30000,
                            "catalog": 30000,
                            "execution": 240000,
                        },
                    }
                }
            )
        },
    }
