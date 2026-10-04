"""Validated deployment settings and invocation data."""

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
import uuid
from .tasks import KVSTORE, TaskDefinition


@dataclass(frozen=True)
class RunConfig:
    target_repo: str
    gateway_url: str
    region: str
    model: str
    timeout_seconds: int = 2700
    max_steps: int = 180
    workspace_root: Path = Path("/workspace")

    def __post_init__(self):
        if not 60 <= self.timeout_seconds <= 7200 or not 1 <= self.max_steps <= 300:
            raise ValueError("Invalid harness execution limits")

    @classmethod
    def from_environment(cls):
        return cls(
            os.environ.get("TARGET_REPO", ""),
            os.environ.get("GATEWAY_URL", ""),
            os.environ.get("AWS_REGION", ""),
            os.environ.get("OPENCODE_MODEL_ID", ""),
            int(os.environ.get("HARNESS_TIMEOUT_SECONDS", "2700")),
            int(os.environ.get("HARNESS_MAX_STEPS", "180")),
        )


@dataclass(frozen=True)
class RunRequest:
    repo: str
    spec: str = field(repr=False)
    suffix: str = ""
    mode: str = "run"

    @classmethod
    def parse(cls, payload, authorization, config, task=KVSTORE):
        if not re.fullmatch(r"Bearer [A-Za-z0-9_.-]{20,16384}", authorization):
            raise ValueError("A forwarded bearer token is required")
        repo = payload.get("target_repo", config.target_repo)
        if (
            not isinstance(repo, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or repo != config.target_repo
        ):
            raise ValueError("target_repo must match the deployed repository")
        spec = payload["spec"] if "spec" in payload else task.default_spec()
        if not isinstance(spec, str) or not 1 <= len(spec.encode()) <= 100_000:
            raise ValueError("spec must be text of at most 100000 bytes")
        suffix = payload.get("branch_suffix", uuid.uuid4().hex[:12])
        if not isinstance(suffix, str) or not re.fullmatch(r"[a-z0-9-]{3,40}", suffix):
            raise ValueError("Invalid branch_suffix")
        mode = payload.get("mode", "run")
        if mode not in {"run", "probe", "model_probe"}:
            raise ValueError("mode must be run, probe, or model_probe")
        return cls(repo, spec, suffix, mode)

    def branch(self, task: TaskDefinition):
        return task.branch_prefix + self.suffix


@dataclass(frozen=True)
class RunResult:
    status: str
    pr_url: str | None
    reported_pr_url: str | None
    push_confirmed: bool
    gate_receipts: list[dict] = field(repr=False)
    elapsed_seconds: float
    acceptance: str
    engine: str = "opencode"

    def to_event(self):
        return {"type": "summary", **asdict(self)}
