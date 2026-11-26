#!/usr/bin/env python3
"""Fail closed if this is not a completed Debian 12 MIPSEL SysV userspace."""
import argparse
import os
import re
import sys
from pathlib import Path

REQUIRED = (
    "base-files", "base-passwd", "libc6", "dpkg", "apt", "dash",
    "sysvinit-core", "sysv-rc", "initscripts", "udev", "kmod",
    "ifupdown", "iproute2", "e2fsprogs", "dropbear-bin",
)
FORBIDDEN = ("systemd-sysv", "openssh-server", "rsyslog", "retrode3-web-control")


def package_db(root):
    status = (root / "var/lib/dpkg/status").read_text(encoding="utf-8")
    packages = {}
    for stanza in re.split(r"\n\s*\n", status):
        record = {}
        for line in stanza.splitlines():
            if not line or line[0].isspace() or ":" not in line:
                continue
            key, value = line.split(":", 1)
            record[key] = value.strip()
        if record.get("Status") == "install ok installed":
            name = record.get("Package")
            if not name or name in packages:
                raise ValueError("duplicate or unnamed installed package")
            packages[name] = record
    return packages


def verify_memory_service(root):
    # The image must use the package-owned service, not a copied overlay.
    service = root / "etc/init.d/retrode3-memory"
    owner = root / "var/lib/dpkg/info/retrode3-tools.list"
    if (service.is_symlink() or not service.is_file()
            or not service.stat().st_mode & 0o111
            or "/etc/init.d/retrode3-memory" not in owner.read_text().splitlines()):
        raise ValueError("missing executable package-owned memory service")
    links = list((root / "etc/rc2.d").glob("S[0-9][0-9]retrode3-memory"))
    if (len(links) != 1 or not links[0].is_symlink()
            or os.readlink(links[0]) != "../init.d/retrode3-memory"):
        raise ValueError("missing or duplicate memory service boot registration")
    if "sysctl -w" in service.read_text():
        raise ValueError("memory service depends on missing sysctl")
    return links[0]


def verify(root, with_retrode3=False):
    if not root.is_dir():
        raise ValueError("missing rootfs")
    version = (root / "etc/debian_version").read_text(encoding="utf-8").strip()
    if not version.startswith("12."):
        raise ValueError("not Debian 12: " + version)
    packages = package_db(root)
    for name in REQUIRED:
        if name not in packages:
            raise ValueError("missing essential package: " + name)
    for name in FORBIDDEN:
        if name in packages and (name != "retrode3-web-control" or not with_retrode3):
            raise ValueError("forbidden base package: " + name)
    if with_retrode3:
        for name in ("retrode3-core-runtime", "retrode3-web-control",
                     "retrode3-tools", "retrode3-udev-rules",
                     "lighttpd", "fake-hwclock", "wireless-regdb", "chrony",
                     "resolvconf", "avahi-daemon", "openssh-sftp-server", "wpasupplicant"):
            if name not in packages:
                raise ValueError("missing Retrode3 image package: " + name)
        verify_memory_service(root)
        for name in packages:
            if name.startswith(("apache2", "php", "libapache2-mod-php")):
                raise ValueError("legacy Web package in Lighttpd image: " + name)
    for name, record in packages.items():
        if record.get("Architecture") not in ("mipsel", "all"):
            raise ValueError("unexpected package architecture: " + name)
    for name in ("etc/fstab", "etc/inittab", "etc/hostname", "etc/hosts"):
        if not (root / name).is_file():
            raise ValueError("missing configuration: " + name)
    for name in ("usr/bin/qemu-mipsel-static", "usr/sbin/policy-rc.d"):
        if (root / name).exists():
            raise ValueError("build helper leaked: " + name)
    if (root / "debootstrap").exists():
        raise ValueError("foreign bootstrap did not complete")
    inittab = (root / "etc/inittab").read_text(encoding="utf-8")
    if not re.search(r"^id:2:initdefault:", inittab, re.MULTILINE):
        raise ValueError("missing SysV runlevel")
    for level in (0, 2, 6):
        entry = "l{0}:{0}:wait:/etc/init.d/rc {0}".format(level)
        if entry not in inittab.splitlines():
            raise ValueError("missing SysV runlevel action: " + entry)
    if "ttyS2" not in inittab:
        raise ValueError("missing serial console")
    fstab = (root / "etc/fstab").read_text(encoding="utf-8")
    if "/dev/mmcblk0p2 / ext4" not in fstab or "/dev/mmcblk0p1 /boot vfat" not in fstab:
        raise ValueError("unexpected partition plan")
    dash = next((root / p for p in ("bin/dash", "usr/bin/dash")
                 if (root / p).is_file()), None)
    if dash is None:
        raise ValueError("missing shell binary")
    with dash.open("rb") as file:
        header = file.read(20)
    # ELF32, little-endian, e_machine=EM_MIPS (8)
    if (len(header) < 20 or header[:4] != b"\x7fELF" or
            header[4:6] != b"\x01\x01" or header[18:20] != b"\x08\x00"):
        raise ValueError("shell is not ELF32 little-endian MIPS")
    return packages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--with-retrode3", action="store_true",
                        help="accept a fully populated Retrode3 release rootfs")
    args = parser.parse_args()
    packages = verify(args.root, with_retrode3=args.with_retrode3)
    print("Verified Bookworm MIPSEL SysV base: {} installed packages".format(len(packages)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
