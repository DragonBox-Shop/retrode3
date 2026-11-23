#!/usr/bin/env python3
"""Pure and real-Git tests for APT build no-op decisions."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "retrode3_release_changes", str(ROOT / "buildserver/release-changes.py"))
changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changes)


class TestReleaseChanges(unittest.TestCase):
    def test_known_nonpackage_changes(self):
        ignored = (
            "README.md", "docs/architecture.md", "AGENTS.md",
            ".github/workflows/debian-mipsel-candidates.yml",
            "buildserver/README.md", "buildserver/publish-debs.sh",
            "buildserver/auto-package.sh", "buildserver/install-launchers.sh",
            "buildserver/release-changes.py", "buildserver/tests/test_git.py",
            "packaging/tests/test_build_debs.py",
            "retrode3-web-control/v2/docs/developer-guide.de.md",
            "retrode3-web-control/v2/tests/test_web.py",
            "tools/preflight-ci.sh",
        )
        for path in ignored:
            with self.subTest(path=path):
                self.assertFalse(changes.affects_packages(path))

    def test_build_inputs_and_unknown_paths_rebuild(self):
        inputs = (
            "packaging/native-source-lock.json", "packaging/build-debs.py",
            "packaging/maintainer/web.postinst", "packaging/assets/retrode3-prefork.conf",
            "buildserver/build-debs.sh", "buildserver/run-debs.sh",
            "buildserver/Containerfile", "retrode3-core-runtime/etc/init.d/retrode3-core-runtime",
            "retrode3-web-control/v2/backend/service.py",
            "retrode3-web-control/v2/web/assets/app.js", "new-unrecognized-component/example.txt"
        )
        for path in inputs:
            with self.subTest(path=path):
                self.assertTrue(changes.affects_packages(path))

    def test_git_changes_and_ancestry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            def commit(path, content):
                dst = root / path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content)
                git("add", "--", path)
                git("commit", "-m", "fixture")
                return git("rev-parse", "HEAD")
            git("init", "-q")
            git("config", "user.email", "test@example.org")
            git("config", "user.name", "Fixture")
            old = commit("retrode3-web-control/v2/web/assets/app.js", "initial")
            docs = commit("docs/new-note.md", "note")
            self.assertTrue(changes.only_nonpackage_changes(root, old, docs))
            ci = commit(".github/workflows/ci.yml", "workflow")
            self.assertTrue(changes.only_nonpackage_changes(root, old, ci))
            code = commit("retrode3-web-control/v2/web/assets/app.js", "changed")
            self.assertFalse(changes.only_nonpackage_changes(root, old, code))
            self.assertFalse(changes.only_nonpackage_changes(root, docs, code))
            with self.assertRaises(subprocess.CalledProcessError):
                changes.changed_paths(root, code, old)
            with self.assertRaises(ValueError):
                changes.changed_paths(root, "not-a-sha", code)


if __name__ == "__main__":
    unittest.main()
