# Retrode3: first Debian 12 MIPS32EL hardware boot candidate

**Not hardware accepted. Do not merge into master or flash the installed SD.**
This development-only pipeline deliberately keeps the two user-visible tasks
separate: build/publish packages, then assemble an image from **already
published, signed APT packages**. The image script never invokes make, a
package compiler, or reprepro.

## Experimental source branches

- OS and OSCR: previously verified signed `testing` tag pair, built by
  `/srv/www/vhosts/retrode.com/package_develop.sh`.
- Kernel: `DragonBox-Shop/retrode3-kernel`,
  `feature/retrode3-mipsel-deb-packaging-20261125`. The FULLCONFIG lives
  in the same Git commit, not under buildserver/private.
- SPL/U-Boot: `DragonBox-Shop/retrode3-uboot`,
  `feature/retrode3-uboot-deb-packaging-20261125`.
- Image tooling: `DragonBox-Shop/retrode3`,
  `feature/source-built-x1600-uboot-image` after reviewed merge of
  the `feature/package-driven-boot-image-20261125` PR.

Both new source recipes produce **candidate-only** .deb packages. Installation
on a running device does not replace /boot, raw MMC sectors, or live modules:
payloads live in /usr/lib/retrode3/*-candidates/. Activation/rollback remains
a separate future feature. No candidate is auto-enabled by package postinst.

## Command 1: build new packages only when needed

On Amaterasu, as the existing unprivileged `retrode` user, with the
image feature checkout updated from Git:

```sh
BASE=/srv/www/vhosts/retrode.com/buildserver
IMG="$BASE/src/retrode3-image-dev"
bash "$IMG/buildserver/package-develop-all.sh" --build-only
```

The established package launchers publish the latest tagged OS/OSCR pair.
The platform component builders cache kernel and bootloader independently,
keyed by exact source commit, platform compiler Podman image ID and packaging
build-recipe SHA. A second identical run must show `CACHE HIT` for both
platform components and must not recompile the kernel. Candidate .debs are
under `$BASE/artifacts/platform/candidates/run.*/`. There are exactly
three platform packages: `retrode3-linux-image`,
`retrode3-linux-modules`, `retrode3-uboot-x1600`.

## Explicit testing APT publication

The first release of *untested boot components* to the public `testing`
suite requires an operator opt-in; this is not a customer release:

```sh
RETRODE3_ALLOW_EXPERIMENTAL_BOOT_PACKAGES=1 \
  bash "$IMG/buildserver/package-develop-all.sh" --publish-testing
```

The publisher verifies source SHAs, Debian control identity, checksums,
suite monotonicity, pool filename collisions and GPG signing authorization
**before** it changes the APT database. The passphrase remains in the
existing private 0600 file on the host, never in the Podman mounts or Git.
A successful reprepro export writes
`$BASE/cache/last-published-platform-develop.json`. If this step fails,
**do not start an image build**.

## Command 2: image from signed APT, no compilation

```sh
/srv/www/vhosts/retrode.com/build_image_develop.sh
```

It reads the exact published OS/OSCR and platform snapshots, bootstraps
Bookworm MIPSEL SysV, uses apt to install pinned Debian package versions
from `https://packages.retrode.com testing`, stages U-Boot/SPL and
matching uImage/DTB/modules from the installed packages, and assembles a
DOS-partition-table FAT32/ext4 SD image with the X1600 raw SPL sectors.
It outputs `$BASE/artifacts/images/develop/run.*/retrode3-develop.img.xz`
plus SHA256 and JSON manifests. It **never** writes /dev/mmcblk*, /dev/sd*
or a real SD card.

An optional `$BASE/private/image/develop/ssh.pub` enables SSH-key-only
USB NCM/ACM bring-up in the separate TEST SD image. Otherwise, serial
ttyS2 is the access path. Do not infer hardware success from CI, an image
file checksum, or a completed build: first power on using a spare SD and
capture serial output. Confirm kernel version, device tree, module
vermagic, SysV services and cartridge I/O before making any release.
