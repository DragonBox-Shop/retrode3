# Retrode3 OS and Web: instructions for contributors and assistant chats

**Read [docs/WEB-V2-HANDOFF.md](docs/WEB-V2-HANDOFF.md) for the Web v2
source contract, and [docs/DEBIAN-PACKAGING-TODO.md](docs/DEBIAN-PACKAGING-TODO.md)
for the separate unfinished Debian package / update / image tasks.**
If this branch does not yet contain that document, see the same path on
the OS repo's `develop` branch. This file is deliberately copied into
the currently active web feature branch so its development chat gets the
correct native paths immediately, without relying on earlier messages.

## Repository responsibilities (preserve Nikolaus' original structure)

- `DragonBox-Shop/retrode3-oscr` owns native cartridge-reader **source**:
  common `retrode3-cli`, `retrode3-corectl`, typed HAL/ABI,
  source-derived Sanni SNES/MD/NES `.so` cores and staging.
  The original OSCR/retrode3-lib source stays there.
- **This repository**, `DragonBox-Shop/retrode3`, is Nikolaus'
  existing Debian OS/package repository: original
  `make-all`, QuantumSTEP `.qcodeproj` package files,
  OS init services and Web UI. Do not duplicate native CLI source here.
  The new Web v2 source is `retrode3-web-control/v2/`.
- `retrode3-kernel` owns slot drivers and timing.
  `retrode3-hardware` owns boards, plugins and pinouts.
- The new core-runtime and individual console Debian packages
  and full SD-image builder are **not yet implemented/published**.
  The production .deb package layout is specified at
  `packaging/retrode3-core-layout.json`.

## Verified installed runtime contract (real Retrode3 2.9.5)

- Shared CLI: **`/usr/bin/retrode3-cli`**, not
  `/usr/local/bin/retrode3-cli`.
- Administrative core toggle: **`/usr/sbin/retrode3-corectl`**.
- Cores + static manifests:
  **`/usr/lib/retrode3/cores-available/{snes,md,nes}.{so,core}`**.
- Root-owned enablement symlinks:
  **`/etc/retrode3/cores-enabled/{snes,md,nes}.so`**.
- Bus lock: **`/run/lock/retrode3/bus.lock`**.
- Boot system: **SysV init, no systemd or systemd-tmpfiles**.
  The tested OS init script is
  `retrode3-core-runtime/etc/init.d/retrode3-core-runtime`
  (installed destination `/etc/init.d/retrode3-core-runtime`).
  Ensure deployment and reboot persistence separately.

User verified all SNES/MD/NES cores enabled and ready using
`/usr/bin/retrode3-cli --list-cores`. Physical CRCs through shared
CLI: SNES Terranigma `6FB8A4DF`, MD Snake Rattle n Roll
`543BED30`, NES Excitebike `F749E780`. Stage-1 only:
no unspecified mappers, special chips, SRAM save or flash writes.

**Do not restore the removed legacy reader binaries** at
`/usr/local/bin/oscr`, `/usr/local/bin/retrode3-read`,
`/usr/local/bin/retrode3-dump`,
`/usr/local/bin/retrode3-info`. The old web's dependencies
must be migrated to the central CLI rather than resurrected.

## Current release status (2026-11-20)

Web Control v2 source **has been tested and squash-promoted into OS
`master`**, then `develop` was aligned to the same release commit
`5b2b5f6`. The old `feature/web-control-v2` branch may contain
later experimental changes; do not assume those are automatically in
the release. The older section below records its prior migration
requirements, **not its current release status**.

Native runtime and per-core `.deb` package recipes, the Web v2 Debian
package, modernized `make-all`, APT publication, and customer
SD-image verification remain **unfinished**. See
[`docs/DEBIAN-PACKAGING-TODO.md`](docs/DEBIAN-PACKAGING-TODO.md)
for an executable handoff. Source merged into master is not a
published Debian package.

## Historical Web v2 integration instructions (superseded)

The existing web feature branch `feature/web-control-v2`
has older defaults/fallbacks: its Python backend expects
`/usr/local/bin/retrode3-cli`, and its installer tries to
install an extra CLI / standalone readers. Correct those to use
**only the already installed** `/usr/bin/retrode3-cli`
and `/usr/sbin/retrode3-corectl`. Confirm via actual device tests
on SNES/MD/NES, auto insert/remove/probe, reader permissions,
error handling, background SysV service, cancellation, and no
regression in local file/network management.

`master` is stable, `develop` is the shared integration branch.
Feature branches are temporary and are **not** separate permanent
console/CLI branches. The Web branch is not yet in `develop`;
reconcile its old base with the verified SysV/init improvements
before promotion. Integrate into `develop`, then use a reviewed,
hardware-accepted **squash PR** into `master`. Align `develop`
back to master afterward without losing other work. No raw
feature-branch merge into master without tests.

New chats must read the current source/CI before changing anything;
do not trust old branch-specific README status statements over
this contract. Avoid unrelated refactors and never treat a green
mock CI as a physical cartridge test.
