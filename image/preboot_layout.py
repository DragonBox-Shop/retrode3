"""Validate an X1600 SD preboot snapshot and retire its stale legacy GPT.

Only operates on a caller-supplied regular-file snapshot. Never opens devices.
"""
import struct
import zlib

SECTOR_SIZE = 512
SNAPSHOT_SIZE = 1024 * 1024
BOARD_BOOT_START = 6144   # Actual Retrode3 development SD's first FAT LBA.
EXPECTED_LEGACY_GPT_NAMES = (
    "boot", "recovery", "pretest", "reserved", "misc", "cache", "system", "data"
)


def _fail(message):
    raise ValueError(message)


def _mbr_partition(data, number):
    entry = data[446 + number * 16:462 + number * 16]
    return entry[4], struct.unpack_from("<I", entry, 8)[0], struct.unpack_from("<I", entry, 12)[0]


def prepare_preboot(data, migrate_stale_gpt=False):
    """Return (clean 1MiB snapshot, did_migrate_legacy_gpt).

    The known board image contains a valid *obsolete* Android GPT which
    overlaps its simultaneously present Linux MBR partitions. Leaving its
    primary header behind would let GPT-aware bootloaders/kernels ignore the
    new MBR. Retire only the GPT metadata after explicit opt-in and checks.
    """
    if len(data) != SNAPSHOT_SIZE:
        _fail("expected exactly 1 MiB of the working Retrode3 SD")
    if data[510:512] != b"\x55\xaa":
        _fail("working SD does not have a DOS partition-table signature")
    first_type, first_start, first_size = _mbr_partition(data, 0)
    second_type, second_start, second_size = _mbr_partition(data, 1)
    if (first_type != 0x0c or first_start != BOARD_BOOT_START or first_size == 0 or
            second_type != 0x83 or second_start < first_start + first_size or
            second_size == 0):
        _fail("unexpected original Retrode3 MBR layout; inspect the source card")
    if data[SECTOR_SIZE:SECTOR_SIZE + 8] != b"EFI PART":
        return bytes(data), False
    if not migrate_stale_gpt:
        _fail("legacy GPT detected: explicit --migrate-stale-gpt required")

    header = data[SECTOR_SIZE:2 * SECTOR_SIZE]
    header_size = struct.unpack_from("<I", header, 12)[0]
    if not 92 <= header_size <= SECTOR_SIZE:
        _fail("unsafe legacy GPT header size")
    expected_crc = struct.unpack_from("<I", header, 16)[0]
    hdr = bytearray(header[:header_size])
    hdr[16:20] = b"\0" * 4
    if zlib.crc32(hdr) != expected_crc:
        _fail("invalid legacy GPT header CRC")
    my_lba = struct.unpack_from("<Q", header, 24)[0]
    entries_lba, count, size, entries_crc = struct.unpack_from("<QIII", header, 72)
    if (my_lba != 1 or entries_lba < 2 or entries_lba > 32 or
            count < len(EXPECTED_LEGACY_GPT_NAMES) or count > 128 or
            size != 128):
        _fail("unsupported legacy GPT metadata geometry")
    begin = entries_lba * SECTOR_SIZE
    end = begin + count * size
    if end > SNAPSHOT_SIZE or end > BOARD_BOOT_START * SECTOR_SIZE:
        _fail("legacy GPT entries outside safe preboot area")
    entries = data[begin:end]
    if zlib.crc32(entries) != entries_crc:
        _fail("invalid legacy GPT partition entry CRC")
    names = []
    for i in range(count):
        entry = entries[i*size:(i+1)*size]
        if entry[:16] != b"\0"*16:
            names.append(entry[56:128].decode("utf-16le").rstrip("\0"))
    if tuple(names) != EXPECTED_LEGACY_GPT_NAMES:
        _fail("unknown GPT partition names; refusing to erase a potentially active GPT")
    # GPT metadata sectors must not have any unrelated bootloader bytes.
    entries_end_aligned = ((end + SECTOR_SIZE - 1) // SECTOR_SIZE) * SECTOR_SIZE
    if any(header[header_size:]) or any(data[end:entries_end_aligned]):
        _fail("GPT metadata sectors contain unrelated data")
    clean = bytearray(data)
    clean[SECTOR_SIZE:2*SECTOR_SIZE] = b"\0" * SECTOR_SIZE
    clean[begin:entries_end_aligned] = b"\0" * (entries_end_aligned - begin)
    return bytes(clean), True
