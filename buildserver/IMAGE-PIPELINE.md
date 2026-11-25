# Retrode3: autonomous SD image build contract

Status: one-command candidate builder implemented in buildserver/run-image.sh and
buildserver/build-image-container.sh, **not yet run or hardware-accepted on
Amaterasu**. See buildserver/README.md for private inputs and launchers.
The new development candidate uses source-built X1600 SPL/U-Boot. The saved
donor 1 MiB stays a private comparison/rollback reference, not a build input.

## Tag-locked development image pipeline (2026-11-25)

The development image script now lives in a **dedicated checkout** of
`feature/source-built-x1600-uboot-image`, separate from the
`retrode3-testing-pr` APT automation checkout. It is experimental image
builder tooling and MUST NOT be merged into `master` until a device boot
has been proven.

An image build first runs the installed `package_develop.sh` wrapper,
which builds/publishes **only the latest matching OS and OSCR tags** (or
detects the already-published tag pair). The image runner then selects
those same tags from the APT automation caches and requires the exact
OS tag, OSCR tag, commits, Sanni gitlink, channel and package set in
`cache/last-published-develop.json`. A floating OS develop HEAD is never
used as the image userland source. Build tooling uses the separately
pinned image-builder Git commit, recorded in the final manifest.

Kernel source remains a deliberately frozen **exact SHA of the kernel
`develop` branch at image launch**, not yet a hardware-approved release
tag. The kernel configuration MUST be committed alongside that source as
`arch/mips/configs/retrode3_full.config` in
`DragonBox-Shop/retrode3-kernel`. The container clones that exact
commit, requires MIPS32 R2 little-endian, `CONFIG_MODVERSIONS=y` and
`CONFIG_RETRODE3=m`, and builds the complete kernel, DTB and modules.
It fails if the Git configuration is absent or mismatched. The previous
private `FULLCONFIG` is not consulted or mounted. Git config and
effective olddefconfig hashes are recorded in the image manifest.

**One-time prerequisite:** The current approved `FULLCONFIG` on
Amaterasu at
`/srv/www/vhosts/retrode.com/buildserver/private/image/develop/FULLCONFIG`
has NOT been added to the kernel repository yet. Review and commit its
exact contents to the path above on `retrode3-kernel/develop` before
attempting a complete image build. No substitute generic defconfig is
acceptable. This is a source snapshot requirement, not approval to
overwrite the boot-tested kernel.

On Amaterasu, as `retrode`, **after** the image-development PR is
merged into the existing feature branch:

```sh
BASE=/srv/www/vhosts/retrode.com/buildserver
git clone --branch feature/source-built-x1600-uboot-image \
  https://github.com/DragonBox-Shop/retrode3.git \
  "$BASE/src/retrode3-image-dev"
bash "$BASE/src/retrode3-image-dev/buildserver/install-image-launcher.sh"
# APT is tag-locked and already signed; source-built image remains a candidate:
 /srv/www/vhosts/retrode.com/build_image_develop.sh
```

Do not overwrite an existing `retrode3-image-dev` checkout: update it
with `git fetch` and `git merge --ff-only` instead. The dedicated
image launcher only replaces `build_image_develop.sh`, never package
launchers or `build_image_master.sh`.

Only public keyring/fingerprint files and an optional test SSH public key
are mounted from private host inputs. Signing secrets and legacy donor
SPL files remain unavailable inside the image container.
The generated `*.img.xz` is **never** written directly to an SD device.
Cold-boot testing on a spare SD is a separate required milestone.

## Target: one command on Amaterasu

The eventual buildserver/auto-image.sh develop|master must:

1. Lock one run and resolve exact Git commits of retrode3, retrode3-oscr
   (including the Sanni gitlink), retrode3-kernel and the board's U-Boot
   source. Record compiler, configuration and revision digests.
2. Invoke the existing constrained rootless-Podman Debian package build.
   Resolve and lock the exact candidate package versions. Do not confuse
   a successful .deb build with a published or tested release.
3. Build the correct X1600 U-Boot/SPL from source with a pinned board
   configuration. Package its SD raw-loader bytes at verified sectors,
   never by blindly reusing the 1 MiB donor-card first-boot snapshot.
4. Build the full MIPS32EL Linux kernel from a pinned kernel commit
   and approved FULLCONFIG: uImage, modules, DTBs and modules_install.
   Pin the cross compiler and verify CONFIG_MODVERSIONS, kernel release
   and matching module vermagic. Do not rebuild a full kernel merely
   for a later single-driver development change.
5. Bootstrap Debian 12 MIPSEL with QEMU/binfmt in a disposable Podman
   build environment. Add Debian and the signed packages.retrode.com
   source with a pinned public-key fingerprint. Select testing for
   develop and stable for master, then install the exact frozen .deb
   versions plus the complete dependency set. Missing dependencies
   must fail the image build.
6. Assemble an SD image file (FAT32, ext4, bootloader, kernel, DTB,
   modules, userland), verify bootfile paths and partition boundaries,
   and publish an image .xz, a manifest and SHA256SUMS. Never write
   directly to /dev/sd* or other block devices.
7. Test a fresh separate SD on a real Retrode3 before release.
   Kernel/bootloader and tested package versions may be promoted to
   master only after explicit physical approval.

## Existing components

The package build and reprepro publishing already exist in
buildserver/run-debs.sh, buildserver/auto-package.sh and
buildserver/publish-debs.sh (develop -> testing; master -> stable).
The separate first-boot rootfs and SD assembler exist under image/.
They are not yet connected to an unattended kernel and U-Boot build.

## Signed APT source: first implemented foundation

The new image/configure-apt-source.py installs a public key and an APT
source into an offline rootfs. It never downloads public keys, updates
packages or installs .debs. The key is validated against an explicit
full 40-hex-character primary signing fingerprint.

The APT source line for a development image is:

    deb [arch=mipsel signed-by=/usr/share/keyrings/retrode3-archive-keyring.gpg] https://packages.retrode.com testing main

The stable image uses stable in place of testing.

The release administrator must export the **public** signing key
from the server's controlled signing keyring, never a private key:

    gpg --homedir /srv/www/vhosts/retrode.com/buildserver/repository/gnupg --export FINGERPRINT > /secure/retrode3-archive.gpg

After independently verifying the exact full signing fingerprint,
the standalone rootfs build may supply all three settings:

    export RETRODE3_APT_PUBLIC_KEY=/secure/retrode3-archive.gpg
    export RETRODE3_APT_FINGERPRINT=THE_40_HEX_CHARACTER_FINGERPRINT
    export RETRODE3_APT_SUITE=testing
    bash image/build-bookworm-rootfs.sh /absolute/output/directory

The public key must be reachable from the *rootfs build container*,
not merely from the host shell. No key is fetched with curl and
trusted blindly; no apt trusted=yes fallback is permitted. Build
without these settings remains a plain Debian rootfs.

## Open prerequisites before claiming one-command readiness

- The correct X1600 source is now `DragonBox-Shop/retrode3-uboot/develop`
  based on Letux `ingenic-x1600-v5`, with `lx16_uImage_msc0` target.
  Its documented raw layout places SPL at sector 34, U-Boot at sector 86.
  CI must prove the source build and the real SD cold boot must prove the
  bootloader/DDR/board configuration before a release.
- Use Debian Bookworm's MIPSEL cross GCC for kernel and U-Boot. The exact
  compiler executable SHA256 is recorded in each candidate manifest.
  FULLCONFIG must be imported into the kernel Git revision as described
  above. Its compatibility with the source still needs a complete build.
- Bookworm development package candidates now include `retrode3-tools` and
  `retrode3-udev-rules`; Web depends on Debian 12 Apache/PHP rather than
  `letux-httpd`. Verify signed publication and test the entire APT
  dependency closure in a fresh MIPSEL rootfs before considering this done.
  WLAN connect/disconnect still require a safe replacement for the legacy
  `/root/wlan-*` scripts before device acceptance.
- Confirm the public signed testing/stable InRelease endpoints and
  their key fingerprints from the server. No external availability
  or signature validation has yet been observed here.
- Debian kernel-image/modules packaging, safe rollback and real
  SD-image acceptance remain separate release gates.
- QEMU/binfmt registration usable within restricted rootless Podman
  is a controlled host prerequisite, never an excuse for arbitrary
  privileged mounts.

Until all these gates pass, builds must fail explicitly rather than
fall back to floating sources, missing libraries, unsigned repos or
non-reproducible bootloader snapshots.


## Current implementation boundary

The separate image builder now invokes the tag-based APT package publisher
first, then uses only that exact published OS/OSCR source snapshot for the
rootfs, and builds a kernel, rootfs and image candidate for develop. They reject unverified donor checksums and unsigned/unavailable
APT packages. The old donor-GPT migration remains only for historical assembler tests.
The new development pipeline instead builds and checks X1600 SPL/U-Boot from
Git, strips vendor GPT sectors and writes a fresh DOS partition table. It
never reads from or writes directly to any SD device.

No run of the complete source-built pipeline on Amaterasu has been verified yet.
Physical checks of newly built modules and the combined image must be
completed before approving master or customer publication. Until then,
the scripts fail closed on missing input or package dependencies rather
than claiming a completed image.
