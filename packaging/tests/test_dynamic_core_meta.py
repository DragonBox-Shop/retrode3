"""The meta-package follows new staged core recipes without hard-coded IDs."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("builder", ROOT / "packaging/build-debs.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DynamicCoreMetaTests(unittest.TestCase):
    def test_new_plugin_changes_meta_dependencies_automatically(self):
        native = {
            builder.RUNTIME: ("usr/bin/retrode3-cli", "usr/sbin/retrode3-corectl"),
            "retrode3-core-md": ("usr/lib/retrode3/cores-available/md.so",),
            "retrode3-core-snes": ("usr/lib/retrode3/cores-available/snes.so",),
            "retrode3-core-lynx": ("usr/lib/retrode3/cores-available/lynx.so",),
        }
        lock = {
            "native_version": "0.3.0~dev-5", "web_version": "2.0.0~dev-5",
            "release_channel": "testing", "oscr_commit": "a" * 40,
            "sanni_commit": "b" * 40,
            "core_discovery_abi": 1, "core_operations_abi": 1
        }
        control = builder.control_text(builder.META, lock, native)
        self.assertIn("Package: retrode3-cores", control)
        self.assertIn("retrode3-core-lynx (= 0.3.0~dev-5)", control)
        self.assertIn("retrode3-core-md (= 0.3.0~dev-5)", control)
        self.assertIn("retrode3-core-snes (= 0.3.0~dev-5)", control)
        self.assertIn("retrode3-core-runtime (= 0.3.0~dev-5)", control)
        self.assertIn("Architecture: mipsel", control)
        self.assertNotIn("cores-enabled", control)

    def test_meta_is_not_an_individual_core(self):
        self.assertNotIn(builder.META, builder.BOOKWORM_ALL)
        self.assertEqual(builder.package_arch(builder.META), "mipsel")

    def test_plugin_recipe_staging_is_dynamic(self):
        script = (ROOT / "buildserver/stage-oscr-plugins.sh").read_text()
        self.assertIn('"$recipes"/*.core', script)
        self.assertIn('"stage-$id-module"', script)
        self.assertNotIn('"stage-sms-md-module"', script)
        self.assertNotIn("retrode3-core-lynx", script)


if __name__ == "__main__":
    unittest.main()
