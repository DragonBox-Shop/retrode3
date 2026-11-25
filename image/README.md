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
- No running SSH server, Web UI, cartridge cores, developer tools or rsyslog in base.
  The small dropbear-bin package is present but never starts without an
  explicitly provisioned SSH public key in a test image.
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

## Full development SD image with source-built X1600 U-Boot

The new `build_image_develop.sh` path builds U-Boot/SPL from
`DragonBox-Shop/retrode3-uboot/develop`, target `lx16_uImage_msc0`,
and a matching kernel+DTB+modules from `retrode3-kernel/develop`.
The original 1 MiB donor bootloader dump is now **reference only**.
A generated `u-boot-with-spl-mbr-gpt.bin` is not copied wholesale:
the source-built container verifies its contents against the separate
SPL and U-Boot binaries, keeps the 446-byte Ingenic first-stage header,
removes the vendor GPT, and writes the verified SPL at sector 34 and U-Boot
at sector 86. The SD assembler writes a fresh DOS partition table.

The X1600-v5 U-Boot boot command expects `/uImage` and
`/ingenic/lx16.dtb`, both present in the FAT partition. The kernel
rootfs uses `/dev/mmcblk0p2`. An actual board cold boot is still
required before calling this image bootable. The legacy donor route below
is kept for documenting our earlier test-card approach.

## First SD-card test image (historical donor-based path)

The separate image assembler **only writes an image file**. It never
accesses /dev/sd*, /dev/mmcblk*, USB storage devices or the running SD
card. It requires the reviewed Bookworm MIPSEL rootfs tarball and a
snapshot of the current **working** kernel, board-specific DTB and its
complete matching module tree.

On the running development Retrode3, with its boot partition mounted:

    KREL="$(uname -r)"
    tar -C / \
      --exclude="lib/modules/$KREL/build" \
      --exclude="lib/modules/$KREL/source" \
      -czf "/root/retrode3-kernel-$KREL.tar.gz" \
      boot/uImage boot/bootargs.scr \
      boot/ingenic/lx16-retrode-2.9.5.dtb \
      "lib/modules/$KREL"
    sha256sum "/root/retrode3-kernel-$KREL.tar.gz"

The same checked procedure is available in capture-current-kernel.sh.
The Ingenic X1600 may load its SPL directly from raw sectors of the SD card,
before the FAT partition. Also capture the first 1 MiB of the working card:

    dd if=/dev/mmcblk0 of=/root/retrode3-sd-preboot-1MiB.bin bs=512 count=2048
    sha256sum /root/retrode3-sd-preboot-1MiB.bin

The same read-only procedure is in capture-sd-preboot.sh. Copy **both**
files to the build host using SCP. Do not commit the raw preboot dump to
Git or upload it as a public CI artifact, as it may include board-specific
bootloader data. No firmware flashing or writes to the existing SD occur.

On a Linux builder with Python 3, GNU tar, util-linux fdisk/sfdisk,
mtools, dosfstools, e2fsprogs, xz and coreutils:

    sudo python3 image/assemble-sd-image.py \
      --rootfs /path/to/retrode3-bookworm-mipsel-rootfs.tar.xz \
      --kernel-bundle /path/to/retrode3-kernel-7.3.0-rc5-letux-mips-retrode3+.tar.gz \
      --kernel-release '7.3.0-rc5-letux-mips-retrode3+' \
      --sd-preboot /path/to/retrode3-sd-preboot-1MiB.bin \
      --ssh-authorized-key /home/user/.ssh/id_ed25519.pub \
      --output /path/to/retrode3-bookworm-test.img.xz

The tool verifies the U-Boot uImage magic and MIPS architecture, DTB
header, matching modules.dep, SysV/MIPSEL rootfs, original MBR
signature and both filesystem images. It preserves raw SD bootstrap
bytes 0..445 and sectors 1..2047, changing only the four MBR partition
entries. It creates a regular-file MBR image with 128 MiB FAT32 boot
and 1 GiB ext4 root, aligned at 1 MiB. The image is labelled
FIRST_BOOT_TEST_ONLY. It is **not** a complete consumer image.

**The current boot sequence has not yet been confirmed on the new
SD card.** The existing bootargs.scr is a generic Letux/Beagle-era
script and may not be the script used to boot this specific board.
The raw preboot backup covers the first 1 MiB only; if the original
loader uses additional raw sectors, the source image must be inspected
before claiming the candidate can boot.
Before claiming a successful boot, verify actual U-Boot search paths
and device-tree choice on the physical device.

**Test-only USB console and networking (not customer configuration):**
Without `--ssh-authorized-key` the test image has only the ttyS2 serial
console. When an SSH public key is explicitly supplied, the assembler
installs a SysV service that enables the following composite gadget:

- USB NCM on `172.31.255.1/29` with a DHCP pool
  `172.31.255.2` to `172.31.255.6` (no DNS service or default gateway).
- USB CDC ACM as `/dev/ttyGS0` on Retrode3 and usually `/dev/ttyACM*`
  on the Linux host. Login still requires valid credentials.
- Dropbear SSH with key-only authentication on `172.31.255.1:22`.
  SSH host keys are generated on first boot, not included in the image.

The host may obtain its USB NCM address with DHCP. For a manual fallback,
assign `172.31.255.2/29` and connect to `root@172.31.255.1` with the
matching private SSH key. The numeric SysV boot ordering marker is retained
as an experimental workaround from a successful first-boot test; the full
NCM+ACM+DHCP combination still requires its own physical cold-boot test.
The normal Retrode3 Web interface and final USB gadget configuration are
separate work. Never ship this test service in customer images.

To write the candidate on a separate card, use a tool that makes you
explicitly choose and verify the destination, such as a GUI image
writer that understands .img.xz. The assembler intentionally offers no
raw-device writing function and will not overwrite a previous image.

## Kernel Debian packages and safe boot updates

The later APT suite should include two distinct MIPSEL packages:

- **retrode3-linux-image**: a versioned uImage, board DTB(s),
  supported U-Boot scripts and signed/source-identified metadata.
- **retrode3-linux-modules**: /lib/modules/<exact-kernel-release>
  tied to the image package version, including depmod metadata.

Regular package installation must never overwrite the only known-good
boot files unconditionally. Package payloads should stage into a
versioned path first. A separate kernel boot manager will atomically
stage a candidate to FAT /boot, retain a recoverable previous kernel,
check image/module/DTB version equality, and require an explicit test
and confirmation before switching. An unexpected power loss during a
kernel upgrade must not destroy the sole bootable slot.

The current first-boot test deliberately uses a kernel copied from
the development device. It is *not* yet a newly source-built kernel
Debian package. Future release packages must be generated from a
known revision in retrode3-kernel and verified against matching
Module.symvers/config and a real Retrode3 board boot.

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
