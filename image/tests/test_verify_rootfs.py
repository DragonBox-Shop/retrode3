#!/usr/bin/env python3
"""Offline checks for the Bookworm candidate rootfs acceptance gate."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / "verify-rootfs.py"
spec = importlib.util.spec_from_file_location("verify_rootfs", source)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class TestRootfsGate(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

        def put(path, body):
            dest = self.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body)

        put("etc/debian_version", "12.15\n")
        put("etc/inittab", "id:2:initdefault:\ns2:2345:respawn:/sbin/getty -L 115200 ttyS2 vt102\n")
        put("etc/fstab", "/dev/mmcblk0p2 / ext4 defaults 0 1\n/dev/mmcblk0p1 /boot vfat defaults 0 0\n")
        put("etc/hostname", "retrode3\n")
        put("etc/hosts", "127.0.0.1 localhost\n")
        binary = self.root / "usr/bin/dash"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"\x7fELF\x01\x01" + b"\0" * 12 + b"\x08\x00" + b"\0" * 40)
        self.names = list(verify.REQUIRED)
        self.save_db()

    def save_db(self):
        status = self.root / "var/lib/dpkg/status"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text("\n\n".join(
            "Package: {0}\nVersion: 1\nArchitecture: mipsel\nStatus: install ok installed".format(name)
            for name in self.names
        ))

    def test_valid(self):
        self.assertIn("sysvinit-core", verify.verify(self.root))

    def test_no_sysv(self):
        self.names.remove("sysvinit-core")
        self.save_db()
        with self.assertRaisesRegex(ValueError, "missing essential"):
            verify.verify(self.root)

    def test_wrong_arch(self):
        db = self.root / "var/lib/dpkg/status"
        db.write_text(db.read_text().replace("Architecture: mipsel", "Architecture: amd64", 1))
        with self.assertRaisesRegex(ValueError, "architecture"):
            verify.verify(self.root)

    def test_systemd_as_pid1(self):
        self.names.append("systemd-sysv")
        self.save_db()
        with self.assertRaisesRegex(ValueError, "forbidden"):
            verify.verify(self.root)

    def test_qemu_leak(self):
        (self.root / "usr/bin/qemu-mipsel-static").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "helper"):
            verify.verify(self.root)

    def test_wrong_serial_console(self):
        (self.root / "etc/inittab").write_text("id:2:initdefault:\n")
        with self.assertRaisesRegex(ValueError, "serial console"):
            verify.verify(self.root)

    def test_big_endian_elf(self):
        binary = self.root / "usr/bin/dash"
        b = bytearray(binary.read_bytes())
        b[5] = 2
        binary.write_bytes(b)
        with self.assertRaisesRegex(ValueError, "little-endian"):
            verify.verify(self.root)


if __name__ == "__main__":
    unittest.main()
