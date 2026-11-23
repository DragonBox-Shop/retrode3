# Retrode3 Debian 12 MIPSEL rootfs (experimental, stage 1)

This directory begins the new SD image pipeline. This first artifact is a
Debian 12 Bookworm MIPSEL root filesystem **only**. It is **not** a bootable
SD image, contains no kernel or bootloader, and must not be installed on
the production Retrode3. No block-device access or SD writing is implemented.

## Base-image decisions

- Debian 12 Bookworm, mipsel (MIPS32 little-endian).
- SysV-Init (sysvinit-core), runlevel 2 and serial ttyS2 at 115200 baud.
- udev, minimal network tools, ext4 utilities and APT.
- Planned ext4 root with noatime; FAT boot partition.
- No SSH server, Web UI, cartridge cores, developer tools or rsyslog in base.
- No SD swapfile. zram and RAM-only diagnostics follow after RAM measurements.

The normal Web UI will be optionally password-free. Developer settings
will always require a configured administrator password and independent,
server-side authorization for privileged API calls.

## Build and test

GitHub Actions runs the bookworm-rootfs workflow from this repository.
It installs debootstrap, qemu-user-static and binfmt_misc on an isolated
runner, executes the first and second MIPSEL bootstrap stages, and checks
ELF format, dpkg architecture, SysV-Init, serial console and absence of
build-only QEMU binaries.

Three build artifacts are clearly marked **UNBOOTABLE**:

- retrode3-bookworm-mipsel-rootfs.tar.xz
- retrode3-bookworm-mipsel-manifest.json
- SHA256SUMS

A manual build must run inside an isolated Linux container or CI VM
with working QEMU MIPSEL binfmt registration:

    sudo apt-get install debootstrap qemu-user-static binfmt-support debian-archive-keyring xz-utils
    sudo update-binfmts --enable qemu-mipsel
    sudo bash image/build-bookworm-rootfs.sh "$(pwd)/build/bookworm-rootfs"

**Never run this command on the Retrode3.** The future Amaterasu Podman
wrapper must not mount host block devices or enable --privileged merely
to make emulation work. The script refuses to overwrite existing files
and only creates output archives in the supplied directory.

The Debian package mirror is currently live; a truly bit-for-bit
reproducible release requires a pinned, signed package snapshot.

## Still missing before a bootable image

1. Integrate tested matching kernel, modules, uImage and Retrode3 DTB
   from the controlled kernel source plus the correct U-Boot script.
2. Create FAT/ext4 partition images without auto-flashing devices.
3. Migrate only required reviewed ConfigFS Gadget, USB networking,
   DHCP, mass storage, HID and udev rules. Ignore accidental ad-hoc
   modifications on the development Retrode.
4. Install and test signed Retrode3 APT packages and Web stack.
5. Implement secure first-run admin provisioning, developer settings,
   optional SSH, bounded in-RAM logs and a measured zram policy.
6. Plan independent security maintenance for Debian 12/MIPSEL:
   this architecture has no official Debian LTS security coverage.
7. Verify cold boot and rollback using a **separate** SD card.

This phase has not passed a physical boot test and is not customer-ready.
