"""Package-driven boot image regression tests; no hardware required."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "platform", ROOT / "buildserver/verify-platform-snapshot.py")
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


def candidate():
    kinds = ("retrode3-linux-image", "retrode3-linux-modules",
             "retrode3-uboot-x1600")
    return {
        "schema": 1, "suite": "testing", "hardware_accepted": False,
        "apt_published": True,
        "sources": {"kernel": "a" * 40, "uboot": "b" * 40},
        "packages": [{
            "name": name,
            "version": "7.3.0~rc5+git20261125+example-1",
            "filename": name + "_7.3.0~rc5+git20261125+example-1_mipsel.deb",
            "sha256": "c" * 64,
        } for name in kinds],
    }


class PackageOnlyImageTests(unittest.TestCase):
    def check(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "published-platform.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            return platform.verify(path, "testing")

    def test_valid_pinned_kernel_and_uboot(self):
        self.assertEqual(len(self.check(candidate())["packages"]), 3)

    def test_missing_package_fails_closed(self):
        doc = candidate()
        doc["packages"].pop()
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_incorrect_or_unsigned_metadata_fails_closed(self):
        for field, value in (("suite", "stable"), ("apt_published", False),
                             ("hardware_accepted", True)):
            doc = candidate()
            doc[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(doc)

    def test_mismatched_modules_image_version_rejected(self):
        doc = candidate()
        doc["packages"][1]["version"] = "0.1.0-1"
        doc["packages"][1]["filename"] = (
            "retrode3-linux-modules_0.1.0-1_mipsel.deb")
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_new_image_has_no_compilation_or_git_clone(self):
        image = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        host = (ROOT / "buildserver/run-image.sh").read_text()
        for forbidden in ("git clone", "kernel_make", "make -C",
                          "u-boot-src", "kernel-src"):
            self.assertNotIn(forbidden, image)
        self.assertIn("apt-get -y --no-install-recommends install", image)
        self.assertIn("published-platform.json", image)
        self.assertIn("build-image-from-packages.sh", host)
        self.assertIn("verify-platform-snapshot.py", host)
        self.assertNotIn("kernel_url=https", host)

    def test_package_producer_cache_and_source_recipe_contract(self):
        producer = (ROOT / "buildserver/package-platform-develop.sh").read_text()
        self.assertIn("platform-cache.py", producer)
        self.assertIn("CACHE HIT", producer)
        self.assertIn("CACHE MISS", producer)
        self.assertIn("platform-package-set.json", producer)
        builder = (ROOT / "buildserver/build-platform-component.sh").read_text()
        self.assertIn("/work/source/packaging/retrode3/build-debs.sh", builder)
        self.assertIn('[[ "$sha" == "$RETRODE3_COMPONENT_SHA" ]]', builder)


if __name__ == "__main__":
    unittest.main()
