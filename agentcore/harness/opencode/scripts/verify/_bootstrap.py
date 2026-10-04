"""Support legacy direct-file CLI invocation; prefer python -m scripts.<command>."""

from pathlib import Path
import sys

for parent in Path(__file__).resolve().parents:
    if (parent / "harness" / "__init__.py").is_file():
        sys.path.insert(0, str(parent))
        break
else:
    raise RuntimeError("Repository package root was not found")
