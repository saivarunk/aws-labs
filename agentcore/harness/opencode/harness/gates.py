"""Run trusted task gates and retain actual command receipts."""

import os
import re
import signal
import subprocess


class GateRunner:
    def __init__(self, work, env, remaining, task):
        self.work = work
        self.env = env
        self.remaining = remaining
        self.task = task
        self.receipts = []

    def run(self):
        for gate in self.task.gates:
            command = list(gate.command)
            timeout = min(180, self.remaining())
            if timeout <= 0:
                raise RuntimeError("Harness deadline exceeded before push")
            process = subprocess.Popen(
                command,
                cwd=self.work,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            output = stdout + stderr
            if process.returncode or (gate.require_empty_output and stdout.strip()):
                raise RuntimeError("Pre-push gate failed: " + " ".join(command))
            if gate.coverage_packages:
                coverage = dict(
                    re.findall(
                        r"(\S+)\s+[^\n]*coverage: ([0-9.]+)% of statements", output
                    )
                )
                for package in gate.coverage_packages:
                    matches = [
                        float(value)
                        for name, value in coverage.items()
                        if name == package or name.endswith("/" + package)
                    ]
                    if len(matches) != 1 or matches[0] < gate.minimum_coverage:
                        raise RuntimeError(
                            f"{package} requires at least {gate.minimum_coverage:g}% coverage"
                        )
            self.receipts.append(
                {
                    "command": " ".join(command),
                    "exit_code": process.returncode,
                    "output": output[-16000:],
                }
            )
