"""Regression tests for the legacy GPT in the X1600 preboot snapshot.

Only generated fixtures are used; no board bootloader bytes are committed.
"""
import importlib.util
import struct
import unittest
import zlib
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "preboot_layout.py"
spec = importlib.util.spec_from_file_location("preboot_layout", path)
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


def snapshot(gpt=False, names=layout.EXPECTED_LEGACY_GPT_NAMES):
    data = bytearray(layout.SNAPSHOT_SIZE)
    data[:4] = b"INGE"
    data[510:512] = b"\x55\xaa"
    struct.pack_into("<B", data, 450, 0x0c)
    struct.pack_into("<II", data, 454, 6144, 209408)
    struct.pack_into("<B", data, 466, 0x83)
    struct.pack_into("<II", data, 470, 215552, 59190751)
    data[38*512:38*512+8] = b"BOOTCODE"
    if gpt:
        entries = bytearray(9*128)
        for i, name in enumerate(names):
            off = i*128
            entries[off:off+16] = b"\x01"*16
            encoded = name.encode("utf-16le")
            entries[off+56:off+56+len(encoded)] = encoded
        data[1024:1024+len(entries)] = entries
        header = bytearray(512)
        header[:8] = b"EFI PART"
        struct.pack_into("<I", header, 8, 0x10000)
        struct.pack_into("<I", header, 12, 92)
        struct.pack_into("<Q", header, 24, 1)
        struct.pack_into("<Q", header, 32, 8388607)
        struct.pack_into("<Q", header, 72, 2)
        struct.pack_into("<I", header, 80, 9)
        struct.pack_into("<I", header, 84, 128)
        struct.pack_into("<I", header, 88, zlib.crc32(entries))
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
        data[512:1024] = header
    return bytes(data)


class PrebootLayoutTests(unittest.TestCase):
    def test_plain_mbr_unchanged(self):
        source = snapshot()
        self.assertEqual(layout.prepare_preboot(source), (source, False))

    def test_gpt_requires_explicit_migration(self):
        with self.assertRaisesRegex(ValueError, "--migrate-stale-gpt"):
            layout.prepare_preboot(snapshot(gpt=True))

    def test_preserve_bootloader_when_removing_verified_stale_gpt(self):
        original = snapshot(gpt=True)
        clean, migrated = layout.prepare_preboot(original, migrate_stale_gpt=True)
        self.assertTrue(migrated)
        self.assertEqual(clean[:512], original[:512])
        self.assertEqual(clean[512:5*512], b"\0" * (4*512))
        self.assertEqual(clean[5*512:], original[5*512:])

    def test_reject_corrupted_gpt(self):
        damaged = bytearray(snapshot(gpt=True))
        damaged[1080] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            layout.prepare_preboot(damaged, migrate_stale_gpt=True)

    def test_reject_unknown_gpt(self):
        with self.assertRaisesRegex(ValueError, "partition names"):
            layout.prepare_preboot(
                snapshot(gpt=True, names=("boot", "other")),
                migrate_stale_gpt=True,
            )

    def test_reject_unknown_mbr_layout(self):
        damaged = bytearray(snapshot())
        struct.pack_into("<I", damaged, 454, 2048)
        with self.assertRaisesRegex(ValueError, "MBR layout"):
            layout.prepare_preboot(damaged)

    def test_reject_wrong_size(self):
        with self.assertRaisesRegex(ValueError, "exactly 1 MiB"):
            layout.prepare_preboot(b"")


if __name__ == "__main__":
    unittest.main()
