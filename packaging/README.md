# Retrode3 Debian packages: offline development candidates

This directory is the **package implementation**, not an APT publication or
a verified customer image. Work only on OS `develop`, never promote to
`master` until testing on the physical Retrode3. Do not run the old
`make-all -b`: it is deliberately retired because it rebuilt OSCR readers
and previously supported automatic device installation.

## Source pin and reproducible MIPS stage

`native-source-lock.json` fixes:

- OSCR `DragonBox-Shop/retrode3-oscr` commit
  `04e75c89698684b18a491943b7ff7fe78a85166d`
- Sanni submodule `third_party/oscr-firmware` gitlink
  `e5a08326dfc8fff67193f7fc5a7bc36b5282b28c`
- Discovery and operation ABI v1, and one development package revision.

The release staging producer is **only** `retrode3-oscr`, not this OS repo.
Use an offline **mipsel** build environment or a verified mipsel
cross-toolchain that can run its tests; never mistake x86 mock binaries for
device-compatible artifacts.

```sh
git clone https://github.com/DragonBox-Shop/retrode3-oscr.git
cd retrode3-oscr
git checkout 04e75c89698684b18a491943b7ff7fe78a85166d
git submodule update --init --recursive
git rev-parse HEAD:third_party/oscr-firmware
git -C third_party/oscr-firmware rev-parse HEAD

make -f Makefile.migration test-all-shared-cores
make -f Makefile.migration test-release-stage
```

The second test builds the release stage at
`build/migration/stage/`. Ensure **the stage binaries are mipsel**, not
host-architecture ELF files. If using cross-compilation, verify the compiler,
target libc/libstdc++ ABI and sysroot, and run the mock binaries on the
appropriate target or emulator. A green host test alone is not sufficient.
The packaging command will reject non-mipsel ELF32 files, unexpected
paths, mismatched core metadata, missing dynamic ABI symbols and an OSCR
checkout that differs from the pin.

From the OS repo checkout, on a build host with modern `dpkg-deb`
and `readelf`:

```sh
python3 packaging/build-debs.py \
  --oscr-source ../retrode3-oscr \
  --stage ../retrode3-oscr/build/migration/stage \
  --output ./build/debian-candidates

for deb in build/debian-candidates/*.deb; do
    dpkg-deb --info "$deb"
    dpkg-deb --contents "$deb"
done
sha256sum build/debian-candidates/*.deb
```

**No automatic `dpkg -i`, `dl-deb`, SSH, upload, activation,
or SD-card writing occurs.** Set `SOURCE_DATE_EPOCH` to a recorded
Unix timestamp for a deterministic package build. The build manifest
records checksums and source pins. It deliberately states
`hardware_accepted: false` and `apt_published: false`.

## Package ownership

| Package | Arch | Files and activation |
| --- | --- | --- |
| retrode3-core-runtime | mipsel | `/usr/bin/retrode3-cli`, `/usr/sbin/retrode3-corectl`, `/etc/init.d/retrode3-core-runtime` |
| retrode3-core-snes | mipsel | `snes.so` + `snes.core` in `/usr/lib/retrode3/cores-available` |
| retrode3-core-md | mipsel | `md.so` + `md.core` in the same directory |
| retrode3-core-nes | mipsel | `nes.so` + `nes.core` in the same directory |
| retrode3-web-control | all | `/opt/retrode3-web-v2/backend`, `/var/www/html`, `/etc/init.d/retrode3-web-v2`, auth helper, default settings and exact-argument sudoers policy |

The Web package deliberately reuses Nikolaus' earlier
`retrode3-web-control` package name to allow Debian to upgrade the v1
payload rather than install a second owner for `/var/www/html`.
It does **not** ship a second native CLI or any old Reader/OSCR binary.

The runtime provides the virtual interface `retrode3-core-abi-1`.
Each individually upgradable core depends on that ABI and on an
adequate runtime version. A new core revision may be installed
without changing the other cores only if its ABI/runtime constraints
are met. Core enablement in `/etc/retrode3/cores-enabled` is **mutable
device policy**, not a package-managed link. New packages do not
create enabled links; existing enabled links are not modified.
Only `retrode3-corectl` manages links.

## Boot and permissions

Retrode3 boots via **SysV init**, not systemd. The runtime installs and
registers the checked lock-init script. It prepares the persistent
lock *inode* for the current boot at `/run/lock/retrode3/bus.lock`
(root:www-data, mode 0660; parent root:root 0755). Stopping a service
does not unlink the lock while readers may be holding it.

The restricted `retrode3-reader` group is created during runtime
configuration. `www-data` is added to it; a Web restart is required
before the effective supplementary groups change. Existing udev rules
are augmented to apply group/0660 to `/dev/slot-*` on add/change.
The Web SysV service also prepares these permissions at startup for
older kernels/udev races. **Do not run the backend as root.**

Web core control is disabled in
`/etc/default/retrode3-web-v2` by default. The separate sudoers file
permits exactly the six SNES/MD/NES enable/disable invocations, not
arbitrary arguments, shell commands or `sudo retrode3-cli`.
Enable that Web feature **only after securing authentication and
the trusted device network**; changing the config alone is not
a substitute for authorization.

The install/upgrade script refuses to replace the backend during
an active or uninspectable native ROM job. It backs up the current
webroot to `/var/backups/retrode3-web-control/`. It never removes
`/usr/local/games`, existing ROMs, saves, login credentials, or
pre-existing backup files. A package upgrade may replace the
development installer version of Web v2: keep and verify the backup.

## Physical acceptance and rollback (not yet performed)

**Preparation:** save `dpkg -l`, `dpkg -S` for any shared file,
`/etc/retrode3` core links, `/etc/init.d` permissions,
`/var/www/html`, `/etc/sudoers.d`, and downloaded prior .debs.
First check the installed **existing** version of
`retrode3-web-control` to ensure the new Debian version is higher.
Keep a console/SSH session open for recovery. Use a private staging
copy of the webroot and do not wipe unknown files.

**Installation:** only on a maintenance window with no running reader,
install runtime then the three core packages, then Web. Confirm
`dpkg -S` file ownership, `dpkg-deb --contents`, `dpkg --audit`,
`service retrode3-core-runtime status`,
`service retrode3-web-v2 status`, and
`/usr/bin/retrode3-cli --list-cores`. Enable known safe cores manually
if they were not already enabled. Check that **only** those intentionally
enabled remain enabled after each upgrade/removal/reinstall.

**Reboot:** verify `/run/lock/retrode3` and `bus.lock` owner/modes,
unchanged lock inode across service restart, `/dev/slot-*`
group/modes, permissions for `www-data`, and browser/backend startup.
Confirm USB/RNDIS, Samba and WLAN administration still work.
Check that cancelled/active jobs are handled safely.

**Read-only hardware tests:** use known-safe SNES Terranigma
(6FB8A4DF), MegaDrive Snake Rattle n Roll (543BED30),
and NES Excitebike Europe including iNES header (F749E780).
Verify auto insert/remove, probe, filename selection, read-only dumps,
CRC32, cancellation and UI file management. Do not test unsupported
mappers, SRAM, flash or writes as a package smoke test.

**Rollback:** retain the previous signed .deb versions and webroot
backup. Stop the Web service *only while idle*; install the prior
packages using the saved .debs and `dpkg -i`, restore the previous
webroot/configuration if required, re-run SysV init and verify
hardware permissions. Check core link targets remain valid.
Never remove a live `bus.lock` and never purge user ROMs.

## Release gates

1. Source pinned / stage tests (this repository contains the recipe).
2. Actual mipsel `.deb` built and its file lists/dependencies verified.
3. Physical install/upgrade/reboot/read/rollback acceptance.
4. Separately: signed APT repository, versioned development and
   release suites, `Release`/`InRelease`/GPG key, upgrade testing.
5. Separately: reproducible pinned Debian rootfs, kernel/DTB/bootloader,
   customer SD-card image and full physical reboot verification.
6. Only with explicit approval: reviewed squash PR from `develop`
   into `master` and customer release publication.

No APT signing key, production repository or SD-image is fabricated
by these scripts. Existing OS source and QuantumSTEP recipes remain
for compatibility, but their retired reader deployment path is no
longer part of the default build.
