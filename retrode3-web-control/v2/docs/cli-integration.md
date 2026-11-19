# Web v2 contract: retrode3-cli is the sole future NDJSON publisher

Decision: 2026-11-18. The central **retrode3-cli**, not individual
cartridge-system plugins, will provide the browser-facing NDJSON stream,
progress events and job control. The Web UI must not impose a requirement
that each SNES/MD/NES/adapter core implement the same streaming protocol.

## Target architecture

Browser (Read tab) <-> web HTTP gateway / job manager
<-> **retrode3-cli** (one versioned command/event protocol)
<-> registered system readers / adapters (OSCR core libraries)
<-> Retrode3 HAL and kernel devices.

The CLI is the single owner of:
- capability discovery / registry of installed, supported readers;
- safe slot and adapter probing and selection, where physically supported;
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

## Shared CLI integration status (2026-11-19)

The common CLI's operation runtime is now implemented and real Retrode3 2.9.5
hardware has returned matching ROM CRCs for the original-OSCR-derived
stage-1 SNES (`snes.so`) and Mega Drive (`md.so`) read-only adapters.
Both modules report `status:"ready"`, `usable:true`, and
`actions:["probe","read_rom"]` in the central `cores` event.

Web v2 reads this registry and exposes only enabled, `ready`, usable
cores with their actual actions. The web job manager starts
`retrode3-cli --protocol ndjson-v1 --interactive` and sends
`{"command":"probe","core":"snes","request_id":"..."}` or
`{"command":"read_rom","core":"md","request_id":"...","output":"..."}`
through stdin, forwarding correlated result/progress/error messages to the
browser. The real CLI's `ready` event has `system:"multi"`, not the
individual system ID. The frontend must not require separate per-plugin
NDJSON handlers. The central CLI currently offers neither custom mapping
nor ROM-size overrides, so the web must hide them for this transport.

The former `oscr-snes-native` NDJSON runner remains a temporary fallback
**only when the central CLI is absent**. With an installed common CLI, an
unregistered, disabled, incompatible or unusable module is never replaced by
an unrelated legacy runner. The tested read-only SNES/MD capability scope is
limited to the original accepted standard stage-1 ROM types. This is still
a development interface: hardware-specific web service permissions, full
physical Web UI acceptance and release packaging remain pending.

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

## Core registry UI, staged implementation

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

Core controls are intentionally **disabled by default**. The device image
must install CLI and helper at `/usr/local/bin/retrode3-cli` and
`/usr/sbin/retrode3-corectl` respectively, or set fixed environment
variables `RETRODE3_CLI_BINARY` and `RETRODE3_CORECTL_BINARY` in the
backend service. Enable optional web authentication
(`retrode3-web-v2-auth enable`) and configure a narrowly scoped
non-interactive privilege delegation for this one helper. Only then set
`RETRODE3_CORE_CONTROL_ENABLED=1` in the backend service environment.
`RETRODE3_CORECTL_SUDO=0` is for explicitly privileged integration tests;
never grant arbitrary sudo/shell access. Protect the management interface
on a trusted network (and use HTTPS for remote authentication).

**Do not conflate discovery with operation support:** `ready` and
`usable:true` are required for a core to become a Web reader. An
`enabled:true` module may still lack usable read operations. The active
CLI can read through the common core ABI, but Stage-1 SNES/MD support is
not the complete original Sanni firmware feature set. The installer now
copies an existing built CLI to `/usr/local/bin/retrode3-cli` if needed.
It also grants the dedicated `retrode3-reader` group access to the
MD/SNES character devices and the shared `/run/lock/retrode3/bus.lock`;
device file permissions may reset at reboot pending permanent udev packaging.
Real target Web read/cancel acceptance remains mandatory.

## Dynamic readers and kernel-triggered autoprobes (2026-11-19)

The Web reader API has **no installed-core ID allowlist**. `GET /api/capabilities`
takes each entry from `retrode3-cli --list-cores --protocol ndjson-v1`
and derives its ID, display name, `slot` and supported commands. A
newly installed core appears without editing Python/JavaScript.
The `PHYSICAL_SLOTS` list is **only** for familiar connector labels;
other kernel-exported `/sys/class/retrode3/slot-*/sense` devices are
enumerated dynamically. The CLI's `slot` names the physical connector,
not the system's electrical safety or automatically detected adapter.
For a new core, ROM output goes to a separate per-core folder under
shared ROM storage, with generic `.bin` extension unless a known
format has a conventional suffix. This is a filename preference only,
not a core admission policy. A future CLI metadata field for the output
extension would remove even that small presentation mapping.

The kernel's existing `KOBJ_CHANGE` event provides `SLOT=slot-...`
and `SENSE=active|empty`. A single background thread in the loopback
backend listens for these events via Linux netlink group 1. On each
event it invalidates cached identity, then **re-checks kernel sysfs**;
loss of netlink permission/events is handled by a 300ms passive sense
reconciliation loop. An occupied slot is debounced for 350ms and
submitted as a read-only `probe` via the **same shared JobManager**
and common CLI. If exactly one active ready core has a `probe`
operation for that `slot`, it is selected automatically; if several
cores claim a slot, no speculative probe occurs, and the user must
select an adapter/reader manually. On removal the displayed title
is discarded, and an active cartridge job for that slot is cancelled.
The browser only displays the backend's observed slot state and cached
probe metadata; it polls the lightweight endpoint every 1.5s. There is
no competing browser-side hardware probe and no long-lived PHP push
connection. Server-Sent Events could be added later if response latency
requires it, without changing the kernel or CLI contract.

The old direct SNES/MD development binaries form a separate,
explicit compatibility fallback **only if the common CLI is missing**.
They do not restrict any installed central CLI core. The automatic
probe is read-only and does not detect adapter voltage; do not use an
unknown multi-protocol adapter without explicit safety metadata.
