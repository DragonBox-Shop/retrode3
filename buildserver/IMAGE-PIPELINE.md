# Retrode3: autonomous SD image build contract

Status: one-command candidate builder implemented in buildserver/run-image.sh and
buildserver/build-image-container.sh, **not yet run or hardware-accepted on
Amaterasu**. See buildserver/README.md for private inputs and launchers.
The temporary donor-SPL path is deliberate and must not be described as a
source-built U-Boot release.

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

- The X1600 board-specific U-Boot source, exact commit, defconfig and
  raw SD boot-sector map have not been verified. Goldelico's public
  letux-uboot master appears to be an older 2016 line, not a proven
  Retrode3 X1600 source. A donor-card SPL is not an autonomous build.
- The working MIPS32EL kernel compiler (Bootlin GCC 8.2.0) and the
  device's FULLCONFIG must be made available to the server and pinned.
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

The server scripts now launch the existing package pipeline first and
produce a kernel build, staged rootfs and image candidate for a selected
channel. They reject unverified donor checksums and unsigned/unavailable
APT packages. The donor has a guarded legacy-GPT migration identical to
the first successful SD experiment. The U-Boot code is still NOT compiled
from source; see the required private-input documentation in README.md.

No run of the complete new pipeline on Amaterasu has been verified yet.
Physical checks of newly built modules and the combined image must be
completed before approving master or customer publication. Until then,
the scripts fail closed on missing input or package dependencies rather
than claiming a completed image.
