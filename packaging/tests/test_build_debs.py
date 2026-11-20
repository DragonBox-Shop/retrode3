#!/usr/bin/env python3
"""Mock-stage package smoke tests; NEVER a MIPS hardware acceptance test."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "packaging/build-debs.py"
spec = importlib.util.spec_from_file_location("retrode3_build_debs", str(BUILDER))
pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pkg)
LAYOUT = json.loads((ROOT / "packaging/retrode3-core-layout.json").read_text())
LOCK = json.loads((ROOT / "packaging/native-source-lock.json").read_text())


class TestPackaging(unittest.TestCase):
    def fixture_stage(self, root):
        stage = root / "stage"
        for rel, mode in pkg.MODES.items():
            path = stage / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".core"):
                core = path.stem
                path.write_text("id={}\nname=Test {}\nversion=1\nslot={}\n".format(
                    core, core, core))
            else:
                # Minimal ELF32 little-endian MIPS *fixture*, not runnable code.
                header = bytearray(52)
                header[:6] = b"\x7fELF\x01\x01"
                header[16:18] = (3 if rel.endswith(".so") else 2).to_bytes(
                    2, "little")
                header[18:20] = (8).to_bytes(2, "little")
                path.write_bytes(header)
            os.chmod(str(path), mode)
        return stage

    def test_mock_stage_and_negative_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = self.fixture_stage(Path(tmp))
            pkg.verify_stage(stage, LAYOUT, check_symbols=False)
            changed = stage / "usr/bin/retrode3-cli"
            changed.write_bytes(b"ELF but wrong architecture")
            with self.assertRaises(ValueError):
                pkg.verify_stage(stage, LAYOUT, check_symbols=False)

    def test_mock_packages_and_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = self.fixture_stage(root)
            pkg.verify_stage(stage, LAYOUT, check_symbols=False)
            for name in pkg.NATIVE + (pkg.WEB,):
                filename, built = pkg.build_one(root, name, LAYOUT, LOCK,
                                                stage, 1795132800)
                self.assertTrue(filename.endswith(".deb"))
                self.assertTrue(built.is_file())
                contents = subprocess.check_output(
                    ["dpkg-deb", "--contents", str(built)]).decode("utf-8")
                info = subprocess.check_output(
                    ["dpkg-deb", "--field", str(built)]).decode("utf-8")
                self.assertIn("Package: " + name, info)
                self.assertNotIn("./usr/local/bin/oscr", contents)
                self.assertNotIn("./usr/local/bin/retrode3-read", contents)
                self.assertNotIn("./etc/retrode3/cores-enabled/", contents)
                if name == pkg.WEB:
                    self.assertIn("./etc/init.d/retrode3-web-v2", contents)
                    self.assertIn("./var/www/html/assets/app.js", contents)
                    self.assertIn("Architecture: all", info)
                elif name == pkg.NATIVE[0]:
                    self.assertIn("Provides: retrode3-core-abi-1", info)
                    self.assertIn("./etc/init.d/retrode3-core-runtime", contents)
                    self.assertIn("Architecture: mipsel", info)
                else:
                    self.assertIn("retrode3-core-abi-1", info)
                    core = name.rsplit("-", 1)[1]
                    self.assertIn("./usr/lib/retrode3/cores-available/" +
                                  core + ".so", contents)
                    self.assertIn("./usr/lib/retrode3/cores-available/" +
                                  core + ".core", contents)

    def test_static_privilege_rules(self):
        policy = (ROOT / "packaging/assets/retrode3-corectl.sudoers").read_text()
        self.assertNotIn("*", policy)
        self.assertNotIn(" ALL\n", policy)
        self.assertEqual(policy.count("/usr/sbin/retrode3-corectl "), 6)
        self.assertIn("RETRODE3_CORE_CONTROL_ENABLED=0",
                      (ROOT / "packaging/assets/retrode3-web-v2.default").read_text())
        init = (ROOT / "retrode3-web-control/v2/service/retrode3-web-v2.init").read_text()
        self.assertIn("--chuid www-data", init)
        self.assertIn("retrode3-core-runtime", init)


if __name__ == "__main__":
    unittest.main()
