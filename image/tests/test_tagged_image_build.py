"""Image build release-gate tests: no moving userland, no private kernel config."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "verify_image_snapshot", ROOT / "buildserver/verify-image-snapshot.py")
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)
OS_SHA = "a" * 40
OSCR_SHA = "b" * 40
SANNI_SHA = "c" * 40


def published():
    return {
        "release_channel": "testing", "oscr_branch": "develop",
        "os_tag": "apt-2026.11.25-rc1", "os_commit": OS_SHA,
        "oscr_tag": "apt-2026.11.25-rc1", "oscr_commit": OSCR_SHA,
        "sanni_commit": SANNI_SHA, "auto_versioned": True,
        "native_version": "0.3.0~dev", "web_version": "2.0.0~dev",
        "packages": [{"package": name} for name in (
            "retrode3-core-runtime", "retrode3-web-control",
            "retrode3-tools", "retrode3-udev-rules",
            "retrode3-core-md", "retrode3-core-snes")],
    }


def check(doc, **kwargs):
    a = dict(suite="testing", branch="develop",
             os_tag="apt-2026.11.25-rc1", os_sha=OS_SHA,
             oscr_tag="apt-2026.11.25-rc1", oscr_sha=OSCR_SHA)
    a.update(kwargs)
    return snap.verify(doc, **a)


class TaggedImageContractTests(unittest.TestCase):
    def test_accepts_published_exact_tag_pair(self):
        self.assertEqual(check(published())["os_commit"], OS_SHA)

    def test_rejects_wrong_os_tag_and_sha(self):
        for options in ({"os_tag": "new-rc"}, {"os_sha": "d" * 40}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                check(published(), **options)

    def test_rejects_wrong_oscr_tag_and_sha(self):
        for options in ({"oscr_tag": "new-rc"}, {"oscr_sha": "d" * 40}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                check(published(), **options)

    def test_rejects_candidate_or_missing_sources(self):
        for key, value in (("auto_versioned", False), ("sanni_commit", ""),
                           ("packages", []), ("native_version", "")):
            doc = published()
            doc[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check(doc)

    def test_rejects_mismatched_suite_and_package_set(self):
        doc = published()
        doc["release_channel"] = "stable"
        with self.assertRaises(ValueError):
            check(doc)
        doc = published()
        doc["packages"].append({"package": "retrode3-tools"})
        with self.assertRaises(ValueError):
            check(doc)

    def test_image_uses_published_tags_and_separate_tooling_checkout(self):
        runner = (ROOT / "buildserver/run-image.sh").read_text()
        self.assertIn('verify-image-snapshot.py', runner)
        self.assertIn('selector="$base/automation/select-release-tag.py"', runner)
        self.assertIn('image_checkout="$(cd "$(dirname "$0")/.." && pwd)"', runner)
        self.assertIn('image_builder_sha="$(git -C "$image_checkout" rev-parse HEAD)"', runner)
        self.assertIn('-v "$image_checkout:/src:ro"', runner)
        self.assertNotIn('os_sha="$(git -C "$checkout" rev-parse HEAD)"', runner)
        self.assertNotIn('--repo "$checkout" --base "$published_sha"', runner)
        self.assertNotIn('-v "$private:/private:ro"', runner)

    def test_kernel_config_is_checked_in_to_exact_source(self):
        container = (ROOT / "buildserver/build-image-container.sh").read_text()
        self.assertIn('/work/kernel-src/arch/mips/configs/retrode3_full.config', container)
        self.assertIn('"$actual" == "$RETRODE3_KERNEL_SHA"', container)
        self.assertIn('CONFIG_MODVERSIONS=y', container)
        self.assertIn('CONFIG_CPU_MIPS32_R2=y', container)
        self.assertIn('CONFIG_CPU_LITTLE_ENDIAN=y', container)
        self.assertNotIn('/private/FULLCONFIG', container)
        self.assertIn('"kernel_config_source":', container)

    def test_installer_does_not_rewrite_package_launchers(self):
        installer = (ROOT / "buildserver/install-image-launcher.sh").read_text()
        self.assertIn('target="$vhost/build_image_develop.sh"', installer)
        self.assertNotIn('target="$vhost/package_develop.sh"', installer)
        self.assertNotIn('target="$vhost/build_image_master.sh"', installer)
        self.assertIn("feature/source-built-x1600-uboot-image", installer)


if __name__ == "__main__":
    unittest.main()
