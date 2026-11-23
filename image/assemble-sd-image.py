#!/usr/bin/env python3
"""Compose a regular-file, test-only Retrode3 SD image. Never accesses block devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

SECTOR_SIZE = 512
BOOT_START = 2048
BOOT_SECTORS = 262144        # 128 MiB
ROOT_START = BOOT_START + BOOT_SECTORS
ROOT_SECTORS = 2097152       # 1 GiB
TOTAL_SECTORS = ROOT_START + ROOT_SECTORS + 2048
DTB_NAME = "lx16-retrode-2.9.5.dtb"
RELEASE = re.compile(r"^[A-Za-z0-9.+_-]{1,100}$")


def fail(message):
    raise ValueError(message)


def call(*argv, input_data=None):
    subprocess.run(argv, input=input_data, text=input_data is not None, check=True)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_archive(path, bundle=False, release=""):
    with tarfile.open(path, mode="r:*") as archive:
        names = set()
        for member in archive:
            p = PurePosixPath(member.name)
            parts = [part for part in p.parts if part != "."]
            if not parts or p.is_absolute() or ".." in parts:
                fail("unsafe archive pathname: " + member.name)
            if member.isdev() or member.isfifo() or member.islnk():
                fail("unexpected special or hardlinked file: " + member.name)
            if bundle:
                normalized = "/".join(parts)
                if not (normalized in (
                    "boot", "boot/ingenic", "boot/uImage",
                    "boot/bootargs.scr", "boot/ingenic/" + DTB_NAME,
                    "lib", "lib/modules", "lib/modules/" + release)
                    or normalized.startswith("lib/modules/" + release + "/")):
                    fail("unexpected boot bundle path: " + member.name)
                if member.issym():
                    # Kernel module build/source links are not part of runtime.
                    fail("symlink in boot bundle: " + member.name)
            names.add("/".join(parts))
        if bundle:
            required = {
                "boot/uImage", "boot/bootargs.scr",
                "boot/ingenic/" + DTB_NAME,
                "lib/modules/" + release,
            }
            if not required.issubset(names):
                fail("boot bundle missing files: " + ", ".join(sorted(required - names)))


def verify_boot_files(bundle, release):
    image = bundle / "boot/uImage"
    dtb = bundle / "boot/ingenic" / DTB_NAME
    with image.open("rb") as file:
        header = file.read(64)
    if len(header) != 64 or header[:4] != bytes.fromhex("27051956"):
        fail("uImage is not a U-Boot legacy kernel image")
    # The U-Boot legacy image header stores MIPS architecture at byte 29.
    if header[29] != 5:
        fail("uImage architecture is not MIPS")
    with dtb.open("rb") as file:
        if file.read(4) != bytes.fromhex("d00dfeed"):
            fail("not a flattened device tree")
    if not (bundle / "lib/modules" / release / "modules.dep").is_file():
        fail("missing modules.dep for selected running kernel")


def compose(args):
    if not RELEASE.fullmatch(args.kernel_release):
        fail("invalid kernel release name")
    source = args.rootfs.resolve(strict=True)
    kernel = args.kernel_bundle.resolve(strict=True)
    output = args.output.absolute()
    if output.suffix != ".xz" or not output.name.endswith(".img.xz"):
        fail("output must have .img.xz extension")
    if output.exists() or output.is_symlink():
        fail("refusing to overwrite an existing output")
    if not output.parent.is_dir() or output.parent.is_symlink():
        fail("output parent must be a regular existing directory")
    if str(output.parent.resolve()) in ("/", "/dev", "/boot", "/etc", "/usr", "/var"):
        fail("unsafe output directory")
    if not source.is_file() or not kernel.is_file():
        fail("expected regular rootfs and kernel bundle archives")
    check_archive(source)
    check_archive(kernel, bundle=True, release=args.kernel_release)
    for tool in ("mke2fs", "mkfs.fat", "mcopy", "mmd", "sfdisk",
                 "dd", "xz", "e2fsck", "fsck.fat"):
        if shutil.which(tool) is None:
            fail("missing image tool: " + tool)

    with tempfile.TemporaryDirectory(prefix=".sd-build-", dir=str(output.parent)) as tmp:
        work = Path(tmp)
        root = work / "root"
        boot = work / "kernel"
        root.mkdir()
        boot.mkdir()
        call("tar", "--numeric-owner", "-xJf", str(source), "-C", str(root))
        # Verify the stage *before* injecting a specific kernel.
        call(sys.executable, str(Path(__file__).with_name("verify-rootfs.py")), str(root))
        call("tar", "--numeric-owner", "-xzf", str(kernel), "-C", str(boot))
        verify_boot_files(boot, args.kernel_release)
        rootmodules = root / "lib/modules"
        # Debian Bookworm can use merged /usr: preserve the rootfs symlinks.
        rootmodules.mkdir(parents=True, exist_ok=True)
        if (rootmodules / args.kernel_release).exists():
            fail("rootfs already has this kernel's modules")
        call("cp", "-a", str(boot / "lib/modules" / args.kernel_release),
             str(rootmodules / args.kernel_release))

        bootfs = work / "boot.fat"
        rootfs = work / "root.ext4"
        disk = work / "disk.img"
        call("truncate", "-s", str(BOOT_SECTORS * SECTOR_SIZE), str(bootfs))
        call("mkfs.fat", "-F", "32", "-n", "boot", str(bootfs))
        call("mmd", "-i", str(bootfs), "::/ingenic")
        for src, dest in (
            ("boot/uImage", "::/uImage"),
            ("boot/bootargs.scr", "::/bootargs.scr"),
            ("boot/ingenic/" + DTB_NAME, "::/ingenic/" + DTB_NAME),
        ):
            call("mcopy", "-i", str(bootfs), str(boot / src), dest)
        call("fsck.fat", "-n", str(bootfs))
        call("truncate", "-s", str(ROOT_SECTORS * SECTOR_SIZE), str(rootfs))
        call("mke2fs", "-q", "-F", "-t", "ext4", "-m", "1", "-L", "rootfs",
             "-d", str(root), str(rootfs))
        call("e2fsck", "-fn", str(rootfs))
        call("truncate", "-s", str(TOTAL_SECTORS * SECTOR_SIZE), str(disk))
        layout = (
            "label: dos\nunit: sectors\n"
            "start={}, size={}, type=c\n"
            "start={}, size={}, type=83\n"
        ).format(BOOT_START, BOOT_SECTORS, ROOT_START, ROOT_SECTORS)
        call("sfdisk", "--wipe", "never", str(disk), input_data=layout)
        # seek is in 1 MiB blocks, and both partitions are aligned.
        call("dd", "if=" + str(bootfs), "of=" + str(disk),
             "bs=1M", "seek=1", "conv=notrunc", "status=none")
        call("dd", "if=" + str(rootfs), "of=" + str(disk),
             "bs=1M", "seek=129", "conv=notrunc", "status=none")
        compressed = work / "result.img.xz"
        with compressed.open("wb") as stream:
            subprocess.run(["xz", "-T1", "-1", "-c", str(disk)],
                           stdout=stream, check=True)
        manifest = {
            "schema": 1,
            "status": "FIRST_BOOT_TEST_ONLY",
            "hardware_accepted": False,
            "customer_releasable": False,
            "architecture": "mipsel",
            "distribution": "Debian 12 Bookworm",
            "init": "SysV",
            "kernel_release": args.kernel_release,
            "kernel_source": "trusted development Retrode3 boot bundle",
            "kernel_uimage_sha256": digest(boot / "boot/uImage"),
            "kernel_dtb_sha256": digest(boot / "boot/ingenic" / DTB_NAME),
            "rootfs_archive_sha256": digest(source),
            "kernel_bundle_sha256": digest(kernel),
            "image_sha256": digest(compressed),
            "partition_table": "dos",
            "sector_size": SECTOR_SIZE,
            "boot": {"start_sector": BOOT_START, "sectors": BOOT_SECTORS, "filesystem": "FAT32"},
            "root": {"start_sector": ROOT_START, "sectors": ROOT_SECTORS, "filesystem": "ext4"},
            "userland_access": "serial console only; no SSH, Web or USB network yet",
            "bootloader_note": "Existing board U-Boot is assumed; boot path not yet physically validated",
        }
        manifest_path = output.with_name(output.name[:-7] + ".manifest.json")
        checksum_path = output.with_name(output.name[:-7] + ".SHA256SUMS")
        for path in (manifest_path, checksum_path):
            if path.exists() or path.is_symlink():
                fail("refusing existing sidecar: " + str(path))
        # Publish all results only once both images and their checks pass.
        shutil.copyfile(compressed, output)
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        checksum_path.write_text(
            "{}  {}\n{}  {}\n".format(digest(output), output.name,
                digest(manifest_path), manifest_path.name))
    print("SD image candidate: " + str(output))
    print("Manifest: " + str(manifest_path))
    print("BOOT TEST ONLY: no customer features, no unattended flash operation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--kernel-bundle", type=Path, required=True)
    parser.add_argument("--kernel-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        compose(args)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
