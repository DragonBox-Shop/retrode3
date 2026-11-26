#!/usr/bin/env python3
"""Compose a regular-file, test-only Retrode3 SD image. Never accesses block devices."""
import argparse
import base64
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

from preboot_layout import prepare_preboot
from source_uboot_layout import source_preboot

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
            if not parts:
                # GNU tar -C root -cf ... . emits a harmless ./ root entry.
                if not bundle and member.isdir() and member.name in (".", "./"):
                    continue
                fail("unsafe archive pathname: " + member.name)
            if p.is_absolute() or ".." in parts:
                fail("unsafe archive pathname: " + member.name)
            if bundle and (member.isdev() or member.isfifo() or member.islnk()):
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


def check_preboot(path, migrate_stale_gpt=False):
    """Retain the board's raw SD loader, but not its old partition table."""
    if not path.is_file() or path.stat().st_size != BOOT_START * SECTOR_SIZE:
        fail("expected exactly the first 1 MiB of the working Retrode3 SD")
    return prepare_preboot(path.read_bytes(), migrate_stale_gpt=migrate_stale_gpt)[0]


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


def ensure_legacy_sysv_order(root):
    """Preserve the tested SysV numeric ordering, rejecting unsafe markers."""
    marker = root / "etc/init.d/.legacy-bootordering"
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        fail("unsafe SysV legacy boot-order marker")
    marker.touch(exist_ok=True)


def provision_test_access(root, key_file):
    """Test-only NCM/ACM/DHCP and key-only SSH, never enabled by default."""
    line = key_file.read_text(encoding="utf-8").strip()
    tokens = line.split()
    if len(tokens) < 2 or tokens[0] not in (
            "ssh-ed25519", "ecdsa-sha2-nistp256", "ssh-rsa"):
        fail("SSH key must be a supported one-line public key")
    try:
        raw = base64.b64decode(tokens[1], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        fail("invalid public SSH key encoding: " + str(exc))
    if len(raw) < 20 or len(raw) > 8192 or "\n" in line or "\r" in line:
        fail("invalid SSH public key length or whitespace")
    if (root / "etc/init.d/retrode3-bringup-usb").exists():
        fail("unexpected existing test USB service")
    if not (root / "usr/sbin/dnsmasq").is_file():
        fail("USB DHCP requires dnsmasq-base in the Bookworm rootfs")
    inittab = root / "etc/inittab"
    if not inittab.is_file() or inittab.is_symlink():
        fail("missing or unsafe SysV inittab for USB ACM")
    table = inittab.read_text(encoding="utf-8")
    if "ttyGS0" in table or re.search(r"^g0:", table, flags=re.MULTILINE):
        fail("USB ACM getty already configured")
    key_dir = root / "root/.ssh"
    key_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    authorized = key_dir / "authorized_keys"
    if authorized.exists():
        fail("refusing to overwrite SSH authorized_keys")
    authorized.write_text(line + "\n", encoding="utf-8")
    os.chmod(authorized, 0o600)
    service = root / "etc/init.d/retrode3-bringup-usb"
    shutil.copyfile(Path(__file__).with_name("assets") /
                    "retrode3-bringup-usb.init", service)
    os.chmod(service, 0o755)
    link = root / "etc/rc2.d/S02retrode3-bringup-usb"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        fail("test USB init symlink already exists")
    link.symlink_to("../init.d/retrode3-bringup-usb")
    # A normal serial login still requires valid credentials.
    inittab.write_text(table.rstrip("\n") +
                       "\ng0:2:respawn:/sbin/getty -L 115200 ttyGS0 vt102\n",
                       encoding="utf-8")


def provision_usb_gadget(root):
    """Install normal USB services independently of SSH or developer keys."""
    assets = Path(__file__).with_name("assets")
    if not (root / "usr/sbin/dnsmasq").is_file():
        fail("USB DHCP requires dnsmasq-base")
    inittab = root / "etc/inittab"
    if not inittab.is_file() or inittab.is_symlink():
        fail("missing or unsafe SysV inittab for USB ACM")
    table = inittab.read_text(encoding="utf-8")
    if "ttyGS0" in table or re.search(r"^g0:", table, flags=re.MULTILINE):
        fail("USB ACM getty already configured")
    old_service = root / "etc/init.d/retrode3-bringup-usb"
    if old_service.exists() or old_service.is_symlink():
        fail("legacy SSH bring-up service not permitted in package image")
    authorized = root / "root/.ssh/authorized_keys"
    if authorized.exists() or authorized.is_symlink():
        fail("unexpected embedded SSH developer key in package image")
    service = root / "etc/init.d/retrode3-usb-gadget"
    link = root / "etc/rc2.d/S02retrode3-usb-gadget"
    disk = root / "usr/share/retrode3/usb-welcome.img"
    for path in (service, link, disk):
        if path.exists() or path.is_symlink():
            fail("unexpected preexisting USB gadget payload: " + str(path))
    for source, target, mode in (
            ("retrode3-usb-network", "usr/sbin/retrode3-usb-network", 0o755),):
        dest = root / target
        if dest.exists() or dest.is_symlink():
            fail("unexpected preexisting USB network payload: " + str(dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(assets / source, dest)
        os.chmod(dest, mode)
    disk.parent.mkdir(parents=True, exist_ok=True)
    call("truncate", "-s", "4M", str(disk))
    call("mkfs.fat", "-F", "12", "-n", "RETRODE3", str(disk))
    for name in ("START.html", "START.de.html"):
        call("mcopy", "-i", str(disk), str(assets / "usb-welcome" / name),
             "::/" + name)
    call("fsck.fat", "-n", str(disk))
    os.chmod(disk, 0o644)
    shutil.copyfile(assets / "retrode3-usb-gadget.init", service)
    os.chmod(service, 0o755)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to("../init.d/retrode3-usb-gadget")
    inittab.write_text(table.rstrip("\n") +
                       "\ng0:2:respawn:/sbin/getty -L 115200 ttyGS0 vt102\n",
                       encoding="utf-8")


def compose(args):
    if not RELEASE.fullmatch(args.kernel_release):
        fail("invalid kernel release name")
    if os.geteuid() != 0:
        fail("run inside a disposable build container/runner as root to preserve filesystem ownership")
    source = args.rootfs.resolve(strict=True)
    kernel = args.kernel_bundle.resolve(strict=True)
    if args.uboot_combined:
        if args.migrate_stale_gpt:
            fail("--migrate-stale-gpt is valid only for legacy donor snapshots")
        preboot = source_preboot(args.uboot_combined, args.uboot_spl,
                                args.uboot_binary)
        loader_source = "source-built Ingenic X1600 MMC0, legacy GPT stripped"
        loader_digest = digest(args.uboot_combined)
    else:
        preboot = check_preboot(args.sd_preboot.resolve(strict=True), args.migrate_stale_gpt)
        loader_source = "temporary reviewed 1 MiB donor; not source-built"
        loader_digest = digest(args.sd_preboot)
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
        verify_args = ([sys.executable, str(Path(__file__).with_name("verify-rootfs.py"))] +
                       (["--with-retrode3"] if args.with_retrode3 else []) + [str(root)])
        call(*verify_args)
        # The proven SysV numeric ordering must also apply when the base
        # archive predates the first successful Debian 12 hardware boot.
        ensure_legacy_sysv_order(root)
        call("tar", "--numeric-owner", "-xzf", str(kernel), "-C", str(boot))
        verify_boot_files(boot, args.kernel_release)
        rootmodules = root / "lib/modules"
        # Debian Bookworm can use merged /usr: preserve the rootfs symlinks.
        rootmodules.mkdir(parents=True, exist_ok=True)
        if (rootmodules / args.kernel_release).exists():
            fail("rootfs already has this kernel's modules")
        call("cp", "-a", str(boot / "lib/modules" / args.kernel_release),
             str(rootmodules / args.kernel_release))
        if args.with_retrode3:
            if args.ssh_authorized_key:
                fail("developer SSH keys are not supported in package images")
            provision_usb_gadget(root)
            # The memory service belongs to retrode3-tools. Keep exactly one
            # early runlevel-2 start link in the legacy numeric boot order.
            memory = root / "etc/init.d/retrode3-memory"
            if not memory.is_file() or memory.is_symlink():
                fail("missing packaged memory service")
            links = list((root / "etc/rc2.d").glob("S[0-9][0-9]retrode3-memory"))
            if len(links) != 1 or not links[0].is_symlink() or os.readlink(links[0]) != "../init.d/retrode3-memory":
                fail("missing or unexpected packaged memory service boot link")
            early = root / "etc/rc2.d/S01retrode3-memory"
            if links[0] != early:
                links[0].rename(early)
        elif args.ssh_authorized_key:
            # Explicit historical donor-image test only, not the normal pipeline.
            provision_test_access(root, args.ssh_authorized_key.resolve(strict=True))

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
            ("boot/ingenic/" + DTB_NAME, "::/ingenic/lx16.dtb"),
        ):
            call("mcopy", "-i", str(bootfs), str(boot / src), dest)
        call("fsck.fat", "-n", str(bootfs))
        call("truncate", "-s", str(ROOT_SECTORS * SECTOR_SIZE), str(rootfs))
        call("mke2fs", "-q", "-F", "-t", "ext4", "-m", "1", "-L", "rootfs",
             "-d", str(root), str(rootfs))
        call("e2fsck", "-fn", str(rootfs))
        call("truncate", "-s", str(TOTAL_SECTORS * SECTOR_SIZE), str(disk))
        # X1600 boots its SPL from raw SD sectors. The validated 1 MiB
        # preboot contains source-built SPL/U-Boot, not the old vendor GPT.
        # The legacy donor route remains opt-in for historical boot tests.
        layout = (
            "label: dos\nunit: sectors\n"
            "start={}, size={}, type=c\n"
            "start={}, size={}, type=83\n"
        ).format(BOOT_START, BOOT_SECTORS, ROOT_START, ROOT_SECTORS)
        call("sfdisk", "--wipe", "never", str(disk), input_data=layout)
        with disk.open("r+b") as stream:
            new_mbr = stream.read(SECTOR_SIZE)
            # Keep the X1600 ROM header (bytes 0..445), but always use
            # the new DOS partition entries and 0x55aa generated by sfdisk.
            stream.seek(0)
            stream.write(preboot[:446] + new_mbr[446:512] + preboot[512:])
            stream.seek(SECTOR_SIZE)
            if stream.read(BOOT_START * SECTOR_SIZE - SECTOR_SIZE) != preboot[512:]:
                fail("raw SD bootstrap copy verification failed")
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
            "status": ("FULL_IMAGE_HARDWARE_UNTESTED" if args.with_retrode3
                       else "FIRST_BOOT_TEST_ONLY"),
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
            "sd_preboot_sha256": loader_digest,
            "legacy_gpt_migrated": bool(args.migrate_stale_gpt),
            "bootloader_source_built": bool(args.uboot_combined),
            "raw_loader_source": loader_source,
            "image_sha256": digest(compressed),
            "partition_table": "dos",
            "sector_size": SECTOR_SIZE,
            "boot": {"start_sector": BOOT_START, "sectors": BOOT_SECTORS, "filesystem": "FAT32"},
            "root": {"start_sector": ROOT_START, "sectors": ROOT_SECTORS, "filesystem": "ext4"},
            "userland_access": (
                "ttyS2, USB NCM fixed 172.31.255.1/29 with USB-only DHCP, USB ACM ttyGS0, read-only welcome disk"
                if args.with_retrode3 else
                ("ttyS2, USB NCM, ACM and SSH-key-only Dropbear"
                 if args.ssh_authorized_key else "ttyS2 serial console only")),
            "usb_gadget_functions": (["ncm", "acm", "mass_storage"]
                                     if args.with_retrode3 else []),
            "sysv_boot_order": "legacy numeric runlevel order (hardware bring-up workaround)",
            "test_ssh_enabled": bool(args.ssh_authorized_key),
            "bootloader_note": "Source-built X1600 U-Boot still requires separate SD hardware boot test",
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
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--sd-preboot", type=Path,
                        help="legacy read-only 1MiB donor snapshot, for old test images only")
    inputs.add_argument("--uboot-combined", type=Path,
                        help="source-built lx16_uImage_msc0/u-boot-with-spl-mbr-gpt.bin")
    parser.add_argument("--uboot-spl", type=Path,
                        help="matching source-built spl/u-boot-spl.bin")
    parser.add_argument("--uboot-binary", type=Path,
                        help="matching source-built u-boot.bin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-retrode3", action="store_true",
                        help="assemble a rootfs with Retrode3 packages already installed")
    parser.add_argument("--migrate-stale-gpt", action="store_true",
                        help="remove validated obsolete primary GPT header/table from copied preboot area")
    parser.add_argument("--ssh-authorized-key", type=Path,
                        help="public key to enable SSH over USB NCM in FIRST-BOOT TEST IMAGE ONLY")
    args = parser.parse_args()
    if args.with_retrode3 and args.ssh_authorized_key:
        parser.error("package images must not contain developer SSH keys")
    if args.uboot_combined and (not args.uboot_spl or not args.uboot_binary):
        parser.error("--uboot-combined requires --uboot-spl and --uboot-binary")
    if args.sd_preboot and (args.uboot_spl or args.uboot_binary):
        parser.error("legacy donor snapshots cannot be combined with source-built U-Boot")
    try:
        compose(args)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
