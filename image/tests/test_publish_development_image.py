"""Public image publication tests with an isolated fake Git repo and webroot."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

path = Path(__file__).resolve().parents[2] / "buildserver/publish-development-image.py"
spec = importlib.util.spec_from_file_location("image_publish", path)
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


class PublishDevelopmentImageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.run = root / "run"
        self.run.mkdir()
        self.web = root / "httpdocs"
        (self.web / "wp-admin").mkdir(parents=True)
        self.tag = "apt-2026.11.26-rc3"
        self.notes = b"# Changelog\n\n## 2026.11.26-rc3\n\n- A user-facing change.\n"
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "CHANGELOG.md").write_bytes(self.notes)
        self.git("add", "CHANGELOG.md")
        self.git("commit", "-qm", "Release")
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.git("tag", self.tag)
        (self.repo / "CHANGELOG.md").write_text("Future unpublished notes")
        self.git("commit", "-qam", "Future")
        self.image = self.run / pub.IMAGE
        self.image.write_bytes(b"fake test image")
        self.manifest = {
            "branch": "develop", "apt_suite": "testing", "os_tag": self.tag,
            "os_commit": self.commit, "hardware_accepted": False,
            "customer_releasable": False,
            "files": {pub.IMAGE: hashlib.sha256(self.image.read_bytes()).hexdigest()},
        }
        self.save_manifest()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def save_manifest(self):
        (self.run / "full-image-manifest.json").write_text(json.dumps(self.manifest))

    def publish(self):
        return pub.publish(self.repo, self.run, self.web, self.tag, self.commit)

    def test_public_files_from_exact_tag_and_idempotence(self):
        dest = self.publish()
        self.assertEqual(dest, self.web / "downloads/develop/2026.11.26-rc3")
        self.assertEqual((dest / "CHANGELOG.md").read_bytes(), self.notes)
        self.assertEqual(set(p.name for p in dest.iterdir()),
                         {pub.IMAGE, "SHA256SUMS", "README.txt", "CHANGELOG.md"})
        self.assertEqual((dest / pub.IMAGE).stat().st_mode & 0o777, 0o644)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.publish(), dest)

    def test_bad_hash_and_wrong_tag(self):
        self.image.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.publish()
        self.manifest["os_tag"] = "apt-2026.11.26-rc9"
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "expected unreleased"):
            self.publish()
        self.assertFalse((self.web / "downloads").exists())

    def test_existing_release_never_overwritten(self):
        dest = self.publish()
        self.image.write_bytes(b"different image")
        self.manifest["files"][pub.IMAGE] = pub.digest(self.image)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "never overwrite"):
            self.publish()
        self.assertEqual((dest / pub.IMAGE).read_bytes(), b"fake test image")

    def test_no_stable_or_symlink_publication(self):
        self.manifest["customer_releasable"] = True
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.publish()
        self.manifest["customer_releasable"] = False
        self.save_manifest()
        (self.web / "downloads").symlink_to(self.run, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Unsafe directory"):
            self.publish()


if __name__ == "__main__":
    unittest.main()
