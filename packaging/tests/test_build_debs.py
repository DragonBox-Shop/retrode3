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
    def fixture_stage(self, root, cores=("snes", "md", "nes", "sms-md")):
        stage = root / "stage"
        paths = dict(pkg.MODES)
        for core in cores:
            for extension in (".so", ".core"):
                paths[pkg.CORE_DIRECTORY + "/" + core + extension] = 0o644
        for rel, mode in paths.items():
            path = stage / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".core"):
                core = path.stem
                slot = "md" if core in ("sms-md", "sg-1000") else core
                path.write_text("id={}\nname=Test {}\nversion=1\nslot={}\n".format(
                    core, core, slot))
            else:
                # MIPS ELF fixture, not executable on the build host.
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
            native = pkg.verify_stage(stage, LAYOUT, check_symbols=False)
            self.assertEqual(set(native), {
                "retrode3-core-runtime", "retrode3-core-snes",
                "retrode3-core-md", "retrode3-core-nes",
                "retrode3-core-sms-md"})
            changed = stage / "usr/bin/retrode3-cli"
            changed.write_bytes(b"ELF but wrong architecture")
            with self.assertRaises(ValueError):
                pkg.verify_stage(stage, LAYOUT, check_symbols=False)

    def test_mock_packages_and_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = self.fixture_stage(root)
            native = pkg.verify_stage(stage, LAYOUT, check_symbols=False)
            for name in tuple(native) + (pkg.WEB,):
                filename, built = pkg.build_one(root, name, LAYOUT, LOCK,
                                                stage, 1795132800, native)
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
                    self.assertIn("./etc/apache2/conf-available/retrode3-prefork.conf", contents)
                    self.assertIn("Architecture: all", info)
                    self.assertIn("/etc/apache2/conf-available/retrode3-prefork.conf",
                                  pkg.CONFFILES[pkg.WEB])
                elif name == pkg.RUNTIME:
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

    def test_future_core_is_discovered_without_builder_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = self.fixture_stage(Path(tmp),
                                       cores=("snes", "md", "nes",
                                              "sms-md", "sg-1000"))
            native = pkg.verify_stage(stage, LAYOUT, check_symbols=False)
            self.assertIn("retrode3-core-sms-md", native)
            self.assertIn("retrode3-core-sg-1000", native)
            name, built = pkg.build_one(Path(tmp), "retrode3-core-sg-1000",
                                        LAYOUT, LOCK, stage, 1795132800, native)
            self.assertIn("retrode3-core-sg-1000", name)
            self.assertTrue(built.is_file())

    def test_incomplete_or_unapproved_core_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = self.fixture_stage(Path(tmp))
            (stage / pkg.CORE_DIRECTORY / "sms-md.core").unlink()
            with self.assertRaises(ValueError):
                pkg.verify_stage(stage, LAYOUT, check_symbols=False)

        with tempfile.TemporaryDirectory() as tmp:
            stage = self.fixture_stage(Path(tmp))
            (stage / pkg.CORE_DIRECTORY / "unapproved.txt").write_text("wrong")
            with self.assertRaises(ValueError):
                pkg.verify_stage(stage, LAYOUT, check_symbols=False)

        with tempfile.TemporaryDirectory() as tmp:
            stage = self.fixture_stage(Path(tmp))
            (stage / pkg.CORE_DIRECTORY / "sms-md.core").write_text(
                "id=sms-md\nname=SMS\nversion=1\nslot=../md\n")
            with self.assertRaises(ValueError):
                pkg.verify_stage(stage, LAYOUT, check_symbols=False)

    def test_apache_prefork_profile_preserves_distribution_config(self):
        # Exact limits tested on a real 50-MiB Retrode3, and no upstream
        # /etc/apache2/mods-available/mpm_prefork.conf file is packaged.
        path = ROOT / "packaging/assets/retrode3-prefork.conf"
        contents = path.read_text(encoding="utf-8")
        self.assertIn("<IfModule mpm_prefork_module>", contents)
        import re
        options = dict(re.findall(
            r"^\s*(StartServers|MinSpareServers|MaxSpareServers|"
            r"MaxRequestWorkers|MaxConnectionsPerChild)\s+(\d+)\s*$",
            contents, re.MULTILINE))
        self.assertEqual(options, {
            "StartServers": "2", "MinSpareServers": "1",
            "MaxSpareServers": "2", "MaxRequestWorkers": "4",
            "MaxConnectionsPerChild": "100"})
        self.assertFalse(any("mods-available" in target
                             for _, target, _ in pkg.WEB_EXTRA))
        install = (ROOT / "retrode3-web-control/v2/install-on-retrode.sh").read_text()
        postinst = (ROOT / "packaging/maintainer/web.postinst").read_text()
        prerm = (ROOT / "packaging/maintainer/web.prerm").read_text()
        self.assertIn("a2enconf retrode3-prefork", install)
        self.assertIn("apache2ctl configtest", install)
        self.assertIn("a2enconf retrode3-prefork", postinst)
        self.assertIn("apache2ctl configtest", postinst)
        self.assertIn("a2disconf retrode3-prefork", prerm)

    def test_static_privilege_rules(self):
        policy = (ROOT / "packaging/assets/retrode3-corectl.sudoers").read_text()
        self.assertNotIn("*", policy)
        self.assertNotIn(" ALL\n", policy)
        self.assertEqual(policy.count("/usr/sbin/retrode3-corectl "), 8)
        self.assertIn("/usr/sbin/retrode3-corectl enable sms-md", policy)
        self.assertIn("/usr/sbin/retrode3-corectl disable sms-md", policy)
        self.assertIn("RETRODE3_CORE_CONTROL_ENABLED=0",
                      (ROOT / "packaging/assets/retrode3-web-v2.default").read_text())
        init = (ROOT / "retrode3-web-control/v2/service/retrode3-web-v2.init").read_text()
        self.assertIn("--chuid www-data", init)
        self.assertIn("retrode3-core-runtime", init)


if __name__ == "__main__":
    unittest.main()
