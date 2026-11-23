#!/usr/bin/env python3
"""No flash tooling: test SD archive validation and the boot-bundle gates."""
import importlib.util
import base64
import struct
from pathlib import Path
import tarfile
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / "assemble-sd-image.py"
spec = importlib.util.spec_from_file_location("retrode3_image_assembler", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REL = "7.3.0-rc5-letux-mips-retrode3+"


class ImageSafety(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.bundle = self.base / "kernel.tar.gz"

    def create_bundle(self, invalid=None):
        root = self.base / "payload"
        files = {
            "boot/uImage": bytes.fromhex("27051956") + b"\0"*25 + b"\x05" + b"\0"*34,
            "boot/bootargs.scr": b"boot args\n",
            "boot/ingenic/" + module.DTB_NAME: bytes.fromhex("d00dfeed") + b"\0"*60,
            "lib/modules/" + REL + "/modules.dep": b"",
            "lib/modules/" + REL + "/test.ko": b"\x7fELF",
        }
        for name, contents in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(contents)
        with tarfile.open(self.bundle, "w:gz") as archive:
            for path in sorted(root.rglob("*")):
                archive.add(path, arcname=str(path.relative_to(root)))
            if invalid:
                meta = tarfile.TarInfo(invalid)
                meta.size = 0
                archive.addfile(meta)
        return root

    def test_valid_trusted_boot_bundle(self):
        self.create_bundle()
        module.check_archive(self.bundle, bundle=True, release=REL)
        module.verify_boot_files(self.base / "payload", REL)

    def test_reject_path_traversal(self):
        self.create_bundle("../../outside")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            module.check_archive(self.bundle, bundle=True, release=REL)

    def test_reject_unknown_firmware(self):
        self.create_bundle("etc/shadow")
        with self.assertRaisesRegex(ValueError, "unexpected boot bundle path"):
            module.check_archive(self.bundle, bundle=True, release=REL)

    def test_reject_wrong_kernel_header(self):
        root = self.create_bundle()
        (root / "boot/uImage").write_bytes(b"\0" * 64)
        with self.assertRaisesRegex(ValueError, "U-Boot"):
            module.verify_boot_files(root, REL)

    def test_reject_missing_module_dependency(self):
        root = self.create_bundle()
        (root / "lib/modules" / REL / "modules.dep").unlink()
        with self.assertRaisesRegex(ValueError, "modules.dep"):
            module.verify_boot_files(root, REL)

    def test_explicit_ssh_key_installs_only_test_service(self):
        root = self.base / "root"
        root.mkdir()
        (root / "etc/init.d").mkdir(parents=True)
        (root / "etc/rc2.d").mkdir(parents=True)
        blob = (struct.pack(">I", 11) + b"ssh-ed25519" +
                struct.pack(">I", 32) + b"0" * 32)
        key = self.base / "id_ed25519.pub"
        key.write_text("ssh-ed25519 " + base64.b64encode(blob).decode() + " test\n")
        module.provision_test_access(root, key)
        self.assertEqual((root / "root/.ssh/authorized_keys").stat().st_mode & 0o777, 0o600)
        self.assertTrue((root / "etc/rc2.d/S02retrode3-bringup-usb").is_symlink())
        self.assertIn("dropbear -R -s",
                      (root / "etc/init.d/retrode3-bringup-usb").read_text())

    def test_invalid_test_ssh_key_rejected(self):
        root = self.base / "root"
        root.mkdir()
        bad = self.base / "bad.pub"
        bad.write_text("not-a-real-public-key\n")
        with self.assertRaisesRegex(ValueError, "public key"):
            module.provision_test_access(root, bad)

    def test_fixed_partition_layout(self):
        self.assertEqual(module.ROOT_START, 264192)
        self.assertEqual(module.BOOT_SECTORS * 512, 128 * 1024**2)
        self.assertEqual(module.ROOT_SECTORS * 512, 1024**3)


if __name__ == "__main__":
    unittest.main()
