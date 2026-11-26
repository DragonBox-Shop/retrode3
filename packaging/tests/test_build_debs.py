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
            for name in tuple(native) + pkg.BOOKWORM_ALL + (pkg.META,):
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
                    self.assertIn("./var/www/retrode3-lighttpd/assets/app.js", contents)
                    self.assertIn("./var/www/retrode3-lighttpd/index.html", contents)
                    self.assertIn("./opt/retrode3-web-v2/backend/http_gateway.py", contents)
                    self.assertNotIn(".php", contents)
                    conf = "/etc/lighttpd/conf-available/99-retrode3-lighttpd.conf"
                    self.assertIn("." + conf, contents)
                    self.assertIn(conf, pkg.CONFFILES[pkg.WEB])
                    self.assertIn("Architecture: all", info)
                elif name == pkg.TOOLS:
                    self.assertIn("./usr/local/bin/retrode3-admin", contents)
                    self.assertIn("./usr/local/bin/retrode3-wlan", contents)
                    self.assertIn("./etc/sudoers.d/retrode3", contents)
                    self.assertIn("Architecture: all", info)
                    self.assertNotIn("letux-config-etc", info)
                    self.assertNotIn("ucon64", info)
                elif name == pkg.UDEV:
                    self.assertIn("./etc/udev/rules.d/70-retrode3-cartridge.rules", contents)
                    self.assertIn("Architecture: all", info)
                elif name == pkg.META:
                    self.assertIn("Architecture: mipsel", info)
                    self.assertIn("./usr/share/doc/retrode3-cores/README", contents)
                    depends = subprocess.check_output(
                        ["dpkg-deb", "-f", str(built), "Depends"], text=True).strip()
                    self.assertEqual(depends, pkg.meta_dependencies(native, LOCK))
                    self.assertEqual(depends.count("retrode3-core-runtime ("), 1)
                    self.assertIn("retrode3-core-sms-md (= ", depends)
                elif name == pkg.RUNTIME:
                    self.assertIn("Provides: retrode3-core-abi-1", info)
                    self.assertIn("./etc/init.d/retrode3-core-runtime", contents)
                    self.assertIn("Architecture: mipsel", info)
                else:
                    self.assertIn("retrode3-core-abi-1", info)
                    core = name[len(pkg.CORE_PREFIX):]
                    self.assertIn("./usr/lib/retrode3/cores-available/" +
                                  core + ".so", contents)
                    self.assertIn("./usr/lib/retrode3/cores-available/" +
                                  core + ".core", contents)

    def test_package_directories_under_private_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = self.fixture_stage(root)
            native = pkg.verify_stage(stage, LAYOUT, check_symbols=False)
            previous = os.umask(0o077)
            try:
                _, built = pkg.build_one(root, pkg.RUNTIME, LAYOUT, LOCK,
                                         stage, 1795132800, native)
            finally:
                os.umask(previous)
            self.assertTrue(built.is_file())
            for parent, dirs, _ in os.walk(str(root / pkg.RUNTIME)):
                self.assertEqual(stat.S_IMODE(os.stat(parent).st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)

    def test_bookworm_dependencies_are_native_and_complete(self):
        web = pkg.control_text(pkg.WEB, LOCK)
        self.assertIn("python3, lighttpd", web)
        self.assertNotIn("php8.2", web)
        self.assertIn("Conflicts: apache2", web)
        self.assertIn("retrode3-tools (>= ", web)
        self.assertIn("retrode3-udev-rules (>= ", web)
        for obsolete in ("letux-httpd", "php5", "letux-config-etc"):
            self.assertNotIn(obsolete, web)
        self.assertEqual(pkg.package_arch(pkg.TOOLS), "all")
        self.assertEqual(pkg.package_arch(pkg.UDEV), "all")
        self.assertEqual(pkg.package_version(pkg.TOOLS, LOCK), LOCK["web_version"])
        rules = (ROOT / "packaging/assets/70-retrode3-cartridge.rules").read_text()
        self.assertIn("retrode3-reader", rules)
        self.assertNotIn("systemctl", rules.replace("# Do not invoke systemctl", ""))
        sudoers = (ROOT / "packaging/assets/retrode3-tools.sudoers").read_text()
        self.assertNotIn("retrode3-admin", sudoers)
        self.assertNotIn(" connect", sudoers)
        self.assertNotIn(" disconnect", sudoers)

    def test_postinst_respects_chroot_service_policy(self):
        runtime = (ROOT / "packaging/maintainer/runtime.postinst").read_text()
        web = (ROOT / "packaging/maintainer/web.postinst").read_text()
        self.assertIn("invoke-rc.d retrode3-core-runtime start", runtime)
        self.assertIn("invoke-rc.d retrode3-core-runtime start", web)
        self.assertIn("invoke-rc.d retrode3-web-v2", web)
        self.assertIn("invoke-rc.d lighttpd restart", web)
        self.assertNotIn("/etc/init.d/retrode3-core-runtime start", runtime)
        self.assertNotIn("/etc/init.d/retrode3-core-runtime start", web)

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

    def test_lighttpd_profile_preserves_distribution_config(self):
        conf = (ROOT / "packaging/assets/99-retrode3-lighttpd.conf").read_text()
        self.assertIn('server.document-root := "/var/www/retrode3-lighttpd"', conf)
        self.assertIn('server.modules += ( "mod_proxy" )', conf)
        self.assertIn('127.0.0.1', conf)
        self.assertIn('server.stream-request-body = 2', conf)
        self.assertFalse(any(target == "etc/lighttpd/lighttpd.conf"
                             for _, target, _ in pkg.WEB_EXTRA))

    def test_static_privilege_rules(self):
        policy = (ROOT / "packaging/assets/retrode3-corectl.sudoers").read_text()
        self.assertNotIn(" ALL\n", policy)
        self.assertEqual(policy.count("/usr/sbin/retrode3-corectl "), 1)
        self.assertIn("^(enable|disable) [a-z][a-z0-9-]*$", policy)
        self.assertIn("RETRODE3_CORE_CONTROL_ENABLED=1",
                      (ROOT / "packaging/assets/retrode3-web-v2.default").read_text())
        init = (ROOT / "retrode3-web-control/v2/service/retrode3-web-v2.init").read_text()
        self.assertIn("--chuid www-data", init)
        self.assertIn("retrode3-core-runtime", init)


if __name__ == "__main__":
    unittest.main()
