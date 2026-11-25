# Web v2 contract: retrode3-cli is the sole NDJSON publisher

## Current Web read interface: generic core ABI v3 (`develop`, 2026-11-20)

The NES, MegaDrive and SNES adapters in `retrode3-oscr/develop` now
export the same generic v3 ABI. Web v2 uses a **single, system-independent**
read path, per [generic v3 Web contract](generic-selection-v3.md).

- `get_capabilities` provides the physical `slot` and versioned
  `selection_schema` with the parameter fields and allowed modes.
  Web v2 **requires** this schema for ROM reads; it does not fall back
  to NES-v2 manual mapper fields or the former SNES/MD `mapping` and
  `size_bytes` fields.
- The browser offers `candidate` and `layout` choices from the
  cached `probe_result`; an explicit **Override** checkbox reveals
  the core-supplied `parameters`. All reads send exactly one
  `selection` object with version, mode and schema ID to the
  common CLI through the backend job manager.
- `identification_status:unknown` does not itself prohibit reading:
  header-only SNES and MegaDrive probes can still return a supported
  `read_layout` usable in `auto` mode. Unknown hardware without
  a safe layout instead requires a core-approved manual override.
- Web checks the envelope and schema revision; the dynamic core
  retains final authority on combinations, mapper writes and safety.
  The older ABI remains available **inside the common CLI** for other
  clients but is no longer driven by Web v2.

The CLI/core and Web changes are development source only until real
Retrode3 v3 smoke tests and package/upgrade acceptance. The ROM probe
never performs an automatic unsafe bank-write operation on insertion.
Battery-backed MMC1 and other unapproved mapper writes remain blocked.

Decision: 2026-11-18. The central **retrode3-cli**, not individual
cartridge-system plugins, will provide the browser-facing NDJSON stream,
progress events and job control. The Web UI must not impose a requirement
that each SNES/MD/NES/adapter core implement the same streaming protocol.

## Current architecture

Browser (Read tab) <-> web HTTP gateway / job manager
<-> **retrode3-cli** (one versioned command/event protocol)
<-> registered system readers / adapters (OSCR core libraries)
<-> Retrode3 HAL and kernel devices.

The CLI is the single owner of:
- capability discovery / registry of installed, supported readers;
- executing reviewed core-specific cartridge probes; the Web backend owns
  kernel-event handling, passive slot state and automatic probe scheduling;
- read job life cycle, progress accounting, cancellation and error codes;
- NDJSON schemas / event correlation / source of truth for command validation;
- identifying allowed advanced options per core, not enumerated by the UI;
- paths, safe output publication and hardware/slot exclusivity as defined by the
  CLI and OS contract. Avoid duplicating these behaviors independently in PHP
  or JavaScript.

The web backend still owns web-specific concerns: a safe local process
transport, HTTP sessions/CSRF if enabled, service lifecycle / reconnect,
filesystem UI permissions and conversion of CLI messages to HTTP responses.
The browser consumes capabilities and status without knowing plugin internals.

## Installed shared CLI contract (2026-11-19)

Read `AGENTS.md` and the current [developer guide](developer-guide.en.md) first. The development
Retrode3 2.9.5 has one OS-installed runtime, **`/usr/bin/retrode3-cli`**,
and the restricted administrative toggle at **`/usr/sbin/retrode3-corectl`**.
SNES, MegaDrive and NES cores are installed at
`/usr/lib/retrode3/cores-available/{snes,md,nes}.{so,core}` and their
enabled links are under `/etc/retrode3/cores-enabled/`.

All three report enabled, `ready`, usable and `probe`/`read_rom` through
`/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1`. The Web backend
starts only `/usr/bin/retrode3-cli --protocol ndjson-v1 --interactive`.
Every `probe` or `read_rom` request specifies the CLI core ID. The one
CLI publishes `ready` with `system:"multi"` and correlated NDJSON events.
No standalone reader, legacy Web v2 reader fallback, copied CLI, or extra
per-console executable is supported. Advanced read parameters are available
only through a valid, core-owned generic v3 `selection_schema`.

Physical read-only ROM CRC references: SNES Terranigma `6FB8A4DF`,
MegaDrive Snake Rattle n Roll `543BED30`, NES Excitebike `F749E780`.
These stage-1 cores do not imply special-chip, additional NES mapper,
SRAM, flash, or write support. Web v2 MegaDrive/NES workflows were tested
on real hardware; complete package/reboot and all-core Web acceptance
remain separate release gates.

The device uses **SysV init**, not systemd. The tested OS-owned
`/etc/init.d/retrode3-core-runtime` prepares
`/run/lock/retrode3/bus.lock`. The lock directory is root:root 0755 and the
lock file is root:www-data 0660. Never unlink a live lock file. The Web
installer checks/registers this service; the Web SysV init temporarily restores restricted `/dev/slot-*` permissions
at startup; permanent ownership belongs to the OS/udev package. Test Web jobs as
`www-data` and after a reboot.

## Slot and plugin detection

A physical slot's kernel `sense` value does **not** identify the inserted
system or adapter. Passive polling may display occupancy; full classification
is delegated to approved CLI discovery logic (safe, no blind bus writes).
When the CLI cannot identify a cartridge, the Web advanced selector must show
only the CLI-reported supported readers and supported fields applicable to
that slot. Do not infer cartridge voltage from an untrusted or unknown adapter
signature.

This document supersedes previous instructions in this branch that asked
each system's binary to implement its own NDJSON progress interface.

## Core registry UI

The Plugins tab requests `GET /api/cores`. The backend runs the fixed
`retrode3-cli --list-cores --protocol ndjson-v1` executable and validates
its sole `cores` NDJSON event. This displays preinstalled modules (including
disabled ones), versions, required slots, ABI state, and actual operations.
It never loads modules directly or checks plugin existence from PHP.

`POST /api/cores/toggle` accepts exactly `{"id":"md","enabled":true}`
(or false). The backend validates the CLI-provided installed core ID,
refuses changes during cartridge jobs, then invokes the fixed
`retrode3-corectl enable|disable <id>` helper with an argv array, never
via a shell. It immediately re-queries the CLI and verifies the new state.
The PHP gateway provides existing same-origin CSRF validation.

Core controls are intentionally **disabled by default**. The device image installs CLI and helper at `/usr/bin/retrode3-cli` and
`/usr/sbin/retrode3-corectl` respectively. Browser requests never accept
an executable path. Enable optional web authentication
(`retrode3-web-v2-auth enable`) and configure a narrowly scoped
non-interactive privilege delegation for this one helper. Only then set
`RETRODE3_CORE_CONTROL_ENABLED=1` in the backend service environment.
`RETRODE3_CORECTL_SUDO=0` is for explicitly privileged integration tests;
never grant arbitrary sudo/shell access. Protect the management interface
on a trusted network (and use HTTPS for remote authentication).

**Do not conflate discovery with operation support:** only cores whose
CLI metadata explicitly reports installed, enabled, ready and usable and
supports the requested action are exposed. The Web installer never installs
or rebuilds the CLI or cores. Hardware, Web permissions, reboot, cancellation
and device access require real Retrode3 acceptance.

## Dynamic readers and kernel-triggered autoprobes (2026-11-19)

The Web reader API has **no installed-core ID allowlist**. `GET /api/capabilities`
takes each entry from `retrode3-cli --list-cores --protocol ndjson-v1`
and derives its ID, display name, `slot` and supported commands. A
newly installed core appears without editing Python/JavaScript.
The `PHYSICAL_SLOTS` list is **only** for familiar connector labels;
other kernel-exported `/sys/class/retrode3/slot-*/sense` devices are
enumerated dynamically. The CLI's `slot` names the physical connector,
not the system's electrical safety or automatically detected adapter.
ROM output is grouped by logical console in shared ROM storage, not
necessarily by the adapter-specific core ID. If the core ID ends in its
physical slot suffix, such as `gba-md` or `gba-snes`, the suffix is
removed for the output folder: both save into `ROMs/GBA/` with `.gba`
extension. The full core ID is unchanged for selection and bus safety.
Unknown formats retain the generic `.bin` extension. A future CLI
metadata field for the output folder and extension could replace this
conservative naming convention without hard-coding systems in the Web UI.

The kernel's existing `KOBJ_CHANGE` event provides `SLOT=slot-...`
and `SENSE=active|empty`. A single background thread in the loopback
backend listens for these events via Linux netlink group 1. It rechecks
the sysfs sense and invalidates identity only for a **confirmed transition**;
repeated same-state or stale events do not trigger a fresh full ROM probe;
loss of netlink permission/events is handled by a 300ms passive sense
reconciliation loop. An occupied slot is debounced for 350ms and
submitted as a read-only `probe` via the **same shared JobManager**
and common CLI. If exactly one active ready core has a `probe`
operation for that `slot`, it is selected automatically; if several
cores claim a slot, the CLI performs its electrically gated `probe_slot`
operation. A manual choice remains available if no safe match is found.
Opt-in cores declaring `probe_without_sense` may perform bounded header
probes on apparently empty slots while the bus is idle (GBx adapters).
The backend observes changes to the core enablement directory, invalidates
cached identities and re-probes occupied slots without reinsertion. The
browser observes the registry revision and refreshes reader capabilities.
On removal of a sense-dependent cartridge the displayed title
is discarded, and an active cartridge job for that slot is cancelled.
The browser only displays the backend's observed slot state and cached
probe metadata; it polls the lightweight endpoint every 1.5s. There is
no competing browser-side hardware probe and no long-lived PHP push
connection. Server-Sent Events could be added later if response latency
requires it, without changing the kernel or CLI contract.

Pending auto-probes wait passively while a manual hardware job is active,
without repeatedly launching CLI registry processes. A browser refresh
never triggers cartridge reads.

There is no standalone reader compatibility fallback. Missing or invalid
central CLI metadata makes a core unavailable. Automatic probing remains
read-only and does not identify unknown cartridge adapter voltages.
