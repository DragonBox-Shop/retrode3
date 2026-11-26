"""Exercise the real source-selection block with isolated local Git histories.
No build, network connection, APT write, or live repository modification.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "buildserver/auto-package.sh").read_text()
BLOCK = SOURCE.split("failure_stage=source-selection\n", 1)[1].split(
    "failure_stage=release-worktree\n", 1)[0]
BLOCK = BLOCK.replace(
    "oscr_url=https://github.com/DragonBox-Shop/retrode3-oscr.git",
    'oscr_url="$TEST_OSCR_URL"')


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args],
                                   text=True, stderr=subprocess.PIPE).strip()


class SourceModeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        (self.base / "cache").mkdir()
        self.os = self.base / "os"
        self.oscr = self.base / "oscr"
        for repo in (self.os, self.oscr):
            repo.mkdir()
            git(repo, "init", "-b", "develop")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
            git(repo, "commit", "--allow-empty", "-m", "first")
        self.script = 'set -euo pipefail\n' + BLOCK + (
            '\nprintf "%s|%s|%s|%s\\n" "$os_tag" "$os_sha" "$oscr_tag" "$oscr_sha"\n')

    def select(self, mode):
        env = dict(os.environ, base=str(self.base), checkout=str(self.os),
                   branch="develop", suite="testing", source_mode=mode,
                   script_dir=str(ROOT / "buildserver"), TEST_OSCR_URL=str(self.oscr))
        return subprocess.run(["bash", "-c", self.script], env=env,
                              capture_output=True, text=True)

    def result(self, mode):
        result = self.select(mode)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().splitlines()[-1].split("|")

    def test_branch_no_tags_and_image_requires_both(self):
        self.assertEqual(self.result("branch"),
                         ["", git(self.os, "rev-parse", "HEAD"),
                          "", git(self.oscr, "rev-parse", "HEAD")])
        self.assertNotEqual(self.select("tag").returncode, 0)
        git(self.os, "tag", "apt-test")
        self.assertNotEqual(self.select("tag").returncode, 0)
        git(self.oscr, "tag", "oscr-test")
        self.assertEqual(self.result("tag"),
                         ["apt-test", git(self.os, "rev-parse", "HEAD"),
                          "oscr-test", git(self.oscr, "rev-parse", "HEAD")])

    def test_new_branch_commit_and_older_image_refused(self):
        git(self.os, "tag", "apt-test")
        git(self.oscr, "tag", "oscr-test")
        old = self.result("tag")
        git(self.oscr, "commit", "--allow-empty", "-m", "new mapper")
        new = self.result("branch")
        self.assertEqual(new[1], old[1])
        self.assertNotEqual(new[3], old[3])
        self.assertEqual(self.result("tag"), old)
        (self.base / "cache/last-published-develop.json").write_text(
            json.dumps({"os_commit": new[1], "oscr_commit": new[3]}))
        self.assertEqual(self.result("branch"), new)
        refused = self.select("tag")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Refusing source rollback", refused.stderr)


if __name__ == "__main__":
    unittest.main()
