# Retrode3 OS and Web: instructions for contributors and assistant chats

**Current Web v2 documentation:**
- [German developer guide](retrode3-web-control/v2/docs/developer-guide.de.md)
  or [English developer guide](retrode3-web-control/v2/docs/developer-guide.en.md)
- [Web v2 / shared CLI implementation contract](retrode3-web-control/v2/docs/cli-integration.md)
- [Debian packaging / image status](docs/DEBIAN-PACKAGING-TODO.md) and
  [packaging candidate instructions](packaging/README.md) on `develop`.

The older `docs/WEB-V2-HANDOFF.md` records the **historical migration**
from Web v1 and the feature branch. Do not treat its former TODOs,
feature-branch references or obsolete reader paths as active instructions.
Always inspect the current branch and installed CLI before changing code.

## Verbindliche Vorabpruefung vor GitHub-Pushes

Vor einem Push, der Web v2, Debian-Paketierung, Init-Dienste oder Build-
Metadaten aendert, im vollstaendigen lokalen Checkout zuerst
`./tools/preflight-ci.sh` ausfuehren. Das Skript reproduziert die
hardwarefreien Python-/JavaScript-/PHP-/Shell-/Paket-Mock-Pruefungen
aus den beiden CI-Workflows. Bei Fehlern nicht pushen, sondern lokal
reparieren und erneut testen. MIPS-Crossbuild und echte Hardwaretests
sind zusaetzliche, separate Freigabeschritte.

Ungetestete Zwischenstaende nicht direkt auf `develop` pushen. Werden
nur GitHub-Connector-Aktionen ohne lokalen Checkout angeboten, fuer
riskante Aenderungen einen kurzlebigen PR-Branch gegen `develop` nutzen
und erst nach gruener CI squash-mergen. Fehlerhafte CI-Checks niemals
mit `continue-on-error` oder abgeschalteten Tests kaschieren.
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
- Development **Debian package recipes and candidate builds** exist on
  `develop` under `packaging/`, but native package installation,
  rollback, APT publication and a complete customer SD-image are **not yet
  hardware accepted or released**. The package layout is specified at
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

The package implementation on `develop` now generates
**development candidates** for the native runtime/cores and Web v2.
Physical package acceptance, APT publication and the complete customer
SD-image remain unfinished. See
[`docs/DEBIAN-PACKAGING-TODO.md`](docs/DEBIAN-PACKAGING-TODO.md).
Source merged into `master` is not a published Debian package.

## Current develop: generic Core ABI v3, Web v2-only read protocol (2026-11-20)

`retrode3-oscr/develop` provides versioned `retrode3_core_get_operations_v3`
for **NES, MegaDrive and SNES**. The common CLI now emits
`get_capabilities.selection_schema`, `probe_result.candidates`/
`read_layouts`, `selection_required` and a physical `slot`.
NES MMC1 support is present in the standard core build, with physical
safety limitations described in the CLI repository. Battery-backed
MMC1 and unapproved mapper writes must remain blocked.

Web v2 on `develop` now drives **only** the generic v3 `selection`
object in `read_rom`. It contains no NES-v2-specific controls,
manual `mapper`/`prg_kib` handling or old SNES/MD mapping/size fields.
`get_capabilities` without a valid v3 schema is rejected for Web
reads. Candidate/layout selection and the explicitly enabled Override
come from schema metadata, not a list of consoles hardcoded into JS/Python.

The central CLI may retain ABI v1/v2 for other clients. Web
legacy reader binaries must never be resurrected. The Web's cached
event-triggered probes, shared bus lock and SysV boot model remain.
The v3 Web migration and its CI mocks are **not a real-device or
Debian-package acceptance**; do not promote it to `master` prematurely.
See [generic v3 Web specification](retrode3-web-control/v2/docs/generic-selection-v3.md)
and [CLI v3 contract](https://github.com/DragonBox-Shop/retrode3-oscr/blob/develop/docs/generic-cartridge-selection-v3.md).

## Current Web v2 development rules

- Read `retrode3-web-control/v2/docs/developer-guide.de.md` and the
  actual installed `/usr/bin/retrode3-cli` core registry before making
  reader, UI or integration changes. No independent console reader commands.
- Web v2 on `master` was verified with manual MegaDrive/NES flows and
  mock regressions; real package upgrade/reboot verification is separate.
- `master` is the stable Web-v2 source, `develop` is ongoing integration.
  **Do not promote unfinished Debian package candidates to `master`**
  merely as a side effect of a Web documentation change.
- The Web UI should never issue hardware operations on browser refresh.
  The Python backend serializes safe auto-probes and manual CLI reads.
- Check code and CI, verify against real hardware where a change affects
  cartridge IO, and keep users' ROMs, core enablement, USB services and
  shared `bus.lock` intact.
