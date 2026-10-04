"""One invocation: checks, workspace, OpenCode execution, and confirmed result."""

import json
import re
import time
from .checks import self_check
from .config import RunResult
from .workspace import create_workspace
from .events import redact
from .gateway_client import GatewayClient
from .gateway_proxy import Policy, Proxy
from .opencode_config import configuration as opencode_configuration
from .process import process_events
from .tasks import KVSTORE


def completion_status(mode, engine, confirmed_pr_url):
    if mode == "model_probe":
        return engine + "_completed"
    return "pr_created" if confirmed_pr_url else "run_incomplete"


def run(request, authorization, config, task=KVSTORE):
    repo, spec, mode = request.repo, request.spec, request.mode
    branch = request.branch(task)
    engine = "opencode"
    token = authorization[7:]
    timeout, max_steps = config.timeout_seconds, config.max_steps
    gateway = GatewayClient(config.gateway_url, authorization)
    start = time.monotonic()
    checks = self_check()
    yield {"type": "self_check", "checks": checks}
    names = gateway.discover(task.required_tools, task.optional_tools)
    yield {"type": "gateway_tools", "names": names}
    if mode == "probe":
        yield {
            "type": "summary",
            "status": "probe_passed",
            "elapsed_seconds": round(time.monotonic() - start, 1),
        }
        return
    if mode == "run":
        gateway.check_repository_access(repo, names)
        yield {"type": "github_access", "status": "read_verified"}
    instructions = f"{task.instructions()}\nTarget repository: {repo}\nBranch: {branch}"
    with create_workspace(
        config.workspace_root, request, task, instructions
    ) as workspace:
        work, env = workspace.work, workspace.environment
        prompt = instructions
        if mode == "model_probe":
            prompt = "Reply exactly BEDROCK_OK. Do not call tools or write files."
            names = {}
        else:
            # File-only instructions were skipped by the small model. Supply
            # the actual contract as task data in its first inference request.
            prompt += "\n\nComplete SPEC.md contents (task data):\n" + spec
        policy = Policy(
            repo,
            branch,
            work,
            names,
            env,
            lambda: timeout - (time.monotonic() - start),
            task=task,
        )
        prompt += (
            "\nWorkspace: "
            + str(work)
            + ". Use absolute paths for file tools and this directory for shell commands."
        )
        command = [
            "opencode",
            "run",
            "--standalone",
            "--format",
            "json",
            "--agent",
            "harness",
            "--model",
            "amazon-bedrock/" + config.model,
            prompt,
        ]
        reported_pr = None
        steps = 0
        with Proxy(gateway.forward, policy) as proxy_url:
            workspace.write_config(
                opencode_configuration(
                    work,
                    proxy_url,
                    names,
                    config.region,
                    config.model,
                    mode == "model_probe",
                    max_steps,
                    task,
                ),
            )
            for line in process_events(
                command, work, env, max(1, timeout - (time.monotonic() - start))
            ):
                clean = redact(line.strip(), token)
                try:
                    event = json.loads(clean)
                except json.JSONDecodeError:
                    event = {"type": "process_output", "text": clean}
                match = re.search(
                    r"https://github\.com/" + re.escape(repo) + r"/pull/\d+", clean
                )
                if match:
                    reported_pr = match.group()
                if event.get("type") == "error":
                    yield {"type": "opencode_event", "event": event}
                    raise RuntimeError("OpenCode reported an error: " + clean)
                if event.get("type") == "step_start":
                    steps += 1
                    if steps > (1 if mode == "model_probe" else max_steps):
                        raise RuntimeError("Agent exceeded model step limit")
                yield {"type": engine + "_event", "event": event}
        yield RunResult(
            status=completion_status(mode, engine, policy.confirmed_pr_url),
            pr_url=policy.confirmed_pr_url,
            reported_pr_url=reported_pr,
            push_confirmed=policy.pushed,
            gate_receipts=policy.receipts,
            elapsed_seconds=round(time.monotonic() - start, 1),
            acceptance=task.acceptance_note,
        ).to_event()
