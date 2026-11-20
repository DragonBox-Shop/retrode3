# Retrode3 OS and Web: instructions for contributors

**Current Web v2 development instructions:**
[German CLI developer guide](retrode3-web-control/v2/docs/developer-guide.de.md),
[English CLI developer guide](retrode3-web-control/v2/docs/developer-guide.en.md),
and [the shared CLI integration contract](retrode3-web-control/v2/docs/cli-integration.md).

The older [Web v2 handoff](docs/WEB-V2-HANDOFF.md) is a **historical
migration record**, not a current task list. Inspect the actual branch,
CLI and repository state before coding. Do not resurrect standalone
cartridge-reader executables or use former feature-branch instructions.

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

## Current Web v2 and release boundaries

Web Control v2 has been promoted through `develop` to `master` after
manual device acceptance of MegaDrive and NES UI flows and passing mocked
tests. The supported reader executable is the one shared
`/usr/bin/retrode3-cli`; the Web frontend is
`retrode3-web-control/v2/`. The browser never probes a cartridge merely
because a page is refreshed.

`master` is stable source and `develop` is the active OS integration
branch. Development Debian package candidates exist on `develop` and
are **not automatically released** into `master`. Hardware installation,
upgrade/rollback, APT publication and customer SD image verification are
separate release gates. Check their current status on `develop` rather
than copying unfinished packaging into a Web documentation-only PR.

Use SysV init, keep core enablement and the shared `bus.lock` inode
intact, and never assume an occupied slot identifies an electrical adapter.
Review the current CLI metadata and CI, and confirm hardware behavior for
changes affecting cartridge IO.
