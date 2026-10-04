"""Packaging and import contracts for local command-line helpers."""

import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.build_image import BUILD_INPUTS, archive_sources


class ScriptContracts(unittest.TestCase):
    def test_archive_contains_package_but_excludes_local_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in BUILD_INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            (root / "build").mkdir()
            (root / "build/user-a.jwt").write_text("private fixture")
            archive, tag = archive_sources(root)
            with zipfile.ZipFile(archive) as source:
                self.assertEqual(set(source.namelist()), set(BUILD_INPUTS))
                self.assertIn("harness/workspace.py", source.namelist())
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            self.assertTrue(tag.startswith("source-"))

    def test_verification_imports_do_not_run_commands(self):
        with patch("subprocess.run") as command:
            for name in (
                "identity",
                "leftover_enis",
                "network",
                "github",
                "secret_scan",
            ):
                importlib.reload(importlib.import_module("scripts.verify." + name))
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
