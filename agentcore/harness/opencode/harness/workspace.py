"""Per-run files and an ephemeral OpenCode home, removed on every exit."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class Workspace:
    work: Path
    home: Path
    environment: dict[str, str]
    opencode_config: Path

    def write_config(self, value):
        fd = os.open(self.opencode_config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)


@contextmanager
def create_workspace(root, request, task, instructions):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=root) as directory:
        work = Path(directory) / "work"
        home = Path(directory) / "home"
        work.mkdir()
        home.mkdir(mode=0o700)
        (work / "SPEC.md").write_text(request.spec)
        (work / "TASK_PROMPT.md").write_text(instructions)
        environment = {
            **os.environ,
            "PWD": str(work),
            "HOME": str(home),
            **dict(task.environment),
        }
        for key, folder in [
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_STATE_HOME", "state"),
        ]:
            environment[key] = str(home / folder)
        config_path = home / "config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, mode=0o700)
        yield Workspace(work, home, environment, config_path)
