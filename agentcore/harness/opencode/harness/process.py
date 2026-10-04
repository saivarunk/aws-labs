"""Bounded subprocess streaming and process-group cleanup."""

import os
import queue
import signal
import subprocess
import threading
import time


def process_events(command, cwd, env, timeout):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    events = queue.Queue(maxsize=128)

    def read():
        try:
            for line in iter(lambda: process.stdout.readline(1_000_001), ""):
                if len(line) > 1_000_000:
                    events.put(("error", "Agent output exceeds event limit"))
                    return
                events.put(("line", line))
        finally:
            events.put(("done", None))

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Harness exceeded wall-clock timeout")
            try:
                kind, value = events.get(timeout=min(remaining, 1))
            except queue.Empty:
                continue
            if kind == "done":
                code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                if code:
                    raise RuntimeError("Agent exited with status " + str(code))
                break
            if kind == "error":
                raise RuntimeError(value)
            yield value
    finally:
        # Kill the complete process group, including descendants left after exit.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
