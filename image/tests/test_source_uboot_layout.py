"""Only synthetic source-built bootloader files; never real SD contents."""
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_uboot_layout import (
    source_preboot, SECTOR, SPL_START, UBOOT_START, PREBOOT_SIZE)


class SourceBuiltBootloaderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.combo = base / "u-boot-with-spl-mbr-gpt.bin"
        self.spl = base / "u-boot-spl.bin"
        self.uboot = base / "u-boot.bin"
        self.spl.write_bytes(b"S" * 8192)
        self.uboot.write_bytes(b"U" * 96 * 1024)
        payload = bytearray(UBOOT_START + self.uboot.stat().st_size)
        payload[:446] = b"B" * 446
        payload[510:512] = b"\x55\xaa"
        payload[SECTOR:SECTOR+8] = b"EFI PART"
        payload[SPL_START:SPL_START+8192] = self.spl.read_bytes()
        payload[UBOOT_START:] = self.uboot.read_bytes()
        self.combo.write_bytes(payload)

    def test_extract_ignores_vendor_gpt_and_partition_records(self):
        result = source_preboot(self.combo, self.spl, self.uboot)
        self.assertEqual(len(result), PREBOOT_SIZE)
        self.assertEqual(result[:446], b"B" * 446)
        self.assertEqual(result[446:SPL_START], bytes(SPL_START - 446))
        self.assertEqual(result[SPL_START:SPL_START+8192], b"S" * 8192)
        self.assertEqual(result[UBOOT_START:UBOOT_START+8192], b"U" * 8192)
        self.assertEqual(result[UBOOT_START+96*1024:], bytes(PREBOOT_SIZE-UBOOT_START-96*1024))
        self.assertNotIn(b"EFI PART", result[:SPL_START])

    def test_combined_spl_must_match(self):
        self.spl.write_bytes(b"X" * 8192)
        with self.assertRaisesRegex(ValueError, "matching SPL"):
            source_preboot(self.combo, self.spl, self.uboot)

    def test_combined_uboot_must_match(self):
        self.uboot.write_bytes(b"X" * (96 * 1024))
        with self.assertRaisesRegex(ValueError, "matching U-Boot"):
            source_preboot(self.combo, self.spl, self.uboot)

    def test_reject_unknown_gpt_layout(self):
        combined = bytearray(self.combo.read_bytes())
        combined[SECTOR:SECTOR+8] = b"not GPT!"
        self.combo.write_bytes(combined)
        with self.assertRaisesRegex(ValueError, "unknown Ingenic GPT"):
            source_preboot(self.combo, self.spl, self.uboot)

    def test_reject_moved_payload(self):
        self.combo.write_bytes(b"\0" * SECTOR + self.combo.read_bytes())
        with self.assertRaisesRegex(ValueError, "vendor MBR signature|unexpected source U-Boot combined image size|combined U-Boot layout"):
            source_preboot(self.combo, self.spl, self.uboot)

    def test_reject_oversize_bootloader(self):
        self.uboot.write_bytes(b"U" * (513 * 1024))
        with self.assertRaisesRegex(ValueError, "outside board"):
            source_preboot(self.combo, self.spl, self.uboot)

    def test_reject_symlink_input(self):
        link = self.combo.with_name("symlink.bin")
        link.symlink_to(self.combo)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            source_preboot(link, self.spl, self.uboot)


if __name__ == "__main__":
    unittest.main()
