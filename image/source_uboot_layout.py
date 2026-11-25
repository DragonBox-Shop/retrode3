"""Prepare source-built Ingenic X1600 MMC0 bootstrap for our DOS SD layout.

Never copy the vendor GPT/MBR partition map into a new image. Inputs must be
from the *same* lx16_uImage_msc0 build; never touches block devices.
"""
from pathlib import Path

SECTOR = 512
PREBOOT_SIZE = 1024 * 1024
VENDOR_GPT_SECTORS = 34
SPL_PAD_SIZE = 26624
SPL_START = VENDOR_GPT_SECTORS * SECTOR
UBOOT_START = 86 * SECTOR
UBOOT_MAX = 1024 * SECTOR  # CONFIG_SYS_U_BOOT_MAX_SIZE_SECTORS
assert SPL_START + SPL_PAD_SIZE == UBOOT_START


def source_preboot(combined, spl, uboot):
    """Return 1MiB of first-stage code without legacy GPT or DOS partitions."""
    combined, spl, uboot = (Path(p) for p in (combined, spl, uboot))
    for path in (combined, spl, uboot):
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing or unsafe source-built U-Boot input: " + str(path))
    data, spl_bytes, uboot_bytes = (
        combined.read_bytes(), spl.read_bytes(), uboot.read_bytes())
    if not 512 + SPL_PAD_SIZE + 4096 <= len(data) <= PREBOOT_SIZE:
        raise ValueError("unexpected source U-Boot combined image size")
    if len(spl_bytes) < 256 or len(spl_bytes) > SPL_PAD_SIZE:
        raise ValueError("SPL size exceeds board's 26624-byte reservation")
    if not 4096 <= len(uboot_bytes) <= UBOOT_MAX:
        raise ValueError("U-Boot size outside board's 512KiB reservation")
    if len(data) != UBOOT_START + len(uboot_bytes):
        raise ValueError("combined U-Boot layout differs from expected MMC0 offsets")
    if data[510:512] != b"\x55\xaa":
        raise ValueError("vendor MBR signature missing")
    if data[SECTOR:SECTOR + 8] != b"EFI PART":
        raise ValueError("unknown Ingenic GPT container; refusing guessed offsets")
    if data[SPL_START:SPL_START + len(spl_bytes)] != spl_bytes:
        raise ValueError("combined file does not contain the matching SPL")
    if data[UBOOT_START:UBOOT_START + len(uboot_bytes)] != uboot_bytes:
        raise ValueError("combined file does not contain the matching U-Boot")
    if not any(data[:446]):
        raise ValueError("missing Ingenic ROM bootstrap header")

    # The first 446 bytes carry the vendor bootstrap header (including the
    # parameters fixed by spl_params_fixer). The DOS partition entries at
    # bytes 446..509 are written by sfdisk in assemble-sd-image.py.
    # Sectors 1..33 contain the *obsolete* vendor GPT, not executable SPL.
    # Keep only verified SPL and U-Boot bytes at documented offsets.
    result = bytearray(PREBOOT_SIZE)
    result[:446] = data[:446]
    result[SPL_START:len(data)] = data[SPL_START:]
    if result[SECTOR:SECTOR + 8] == b"EFI PART":
        raise ValueError("source-built preboot still contains GPT")
    return bytes(result)
