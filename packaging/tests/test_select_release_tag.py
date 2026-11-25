#!/usr/bin/env python3
"""Tag selection is tested against actual Git repositories, without network."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "buildserver/select-release-tag.py"
spec = importlib.util.spec_from_file_location("select_release_tag", str(SCRIPT))
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


class TestTaggedReleases(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("checkout", "-qb", "develop")
        self.git("config", "user.email", "build-test@example.org")
        self.git("config", "user.name", "Build test")

    def git(self, *args, date="2026-11-25T09:00:00+0000"):
        env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], env=env,
            text=True, stderr=subprocess.STDOUT).strip()

    def commit(self, label, date):
        (self.root / "file.txt").write_text(label)
        self.git("add", "file.txt", date=date)
        self.git("commit", "-qm", label, date=date)
        return self.git("rev-parse", "HEAD", date=date)

    def tagged(self, name, date, annotated=True):
        if annotated:
            self.git("tag", "-am", name, name, date=date)
        else:
            self.git("tag", name, date=date)

    def test_no_tag_does_not_build_unstable_head(self):
        self.commit("unreleased", "2026-11-25T09:00:00+0000")
        with self.assertRaisesRegex(ValueError, "no eligible release tag"):
            selector.latest_tag(str(self.root), "develop")

    def test_tagged_checkpoint_ignores_subsequent_development(self):
        self.commit("first", "2026-11-25T09:00:00+0000")
        self.tagged("v0.1.0", "2026-11-25T09:05:00+0000")
        old = self.commit("second", "2026-11-25T09:08:00+0000")
        self.tagged("v0.2.0", "2026-11-25T09:09:00+0000")
        self.commit("broken-experiment", "2026-11-25T09:10:00+0000")
        tag, sha = selector.latest_tag(str(self.root), "develop")
        self.assertEqual((tag, sha), ("v0.2.0", old))
        self.assertNotEqual(sha, self.git("rev-parse", "HEAD"))

    def test_master_only_selects_its_own_history(self):
        self.commit("base", "2026-11-25T09:00:00+0000")
        self.git("branch", "master")
        self.tagged("v0.1.0", "2026-11-25T09:01:00+0000")
        self.commit("experimental", "2026-11-25T09:02:00+0000")
        self.tagged("v0.2.0", "2026-11-25T09:03:00+0000")
        self.assertEqual(selector.latest_tag(str(self.root), "master")[0], "v0.1.0")
        self.assertEqual(selector.latest_tag(str(self.root), "develop")[0], "v0.2.0")

    def test_archive_and_unmerged_tags_are_ignored(self):
        self.commit("base", "2026-11-25T09:00:00+0000")
        self.tagged("v0.1.0", "2026-11-25T09:01:00+0000")
        self.tagged("archive/legacy", "2026-11-25T09:10:00+0000")
        self.git("checkout", "-qb", "other")
        self.commit("other", "2026-11-25T09:02:00+0000")
        self.tagged("v99.0.0", "2026-11-25T09:15:00+0000")
        self.assertEqual(selector.latest_tag(str(self.root), "develop")[0], "v0.1.0")

    def test_lightweight_tag_is_supported(self):
        sha = self.commit("light", "2026-11-25T09:01:00+0000")
        self.tagged("v1.0.0", "2026-11-25T09:02:00+0000", annotated=False)
        self.assertEqual(selector.latest_tag(str(self.root), "develop"),
                         ("v1.0.0", sha))

    def test_invalid_branch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid release branch"):
            selector.latest_tag(str(self.root), "experimental")


if __name__ == "__main__":
    unittest.main()
