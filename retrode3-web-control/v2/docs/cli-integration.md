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

## Migration without a regression

- **Currently deployed:** SNES web reads and progress work via the native
  `oscr-snes-native` NDJSON v1 compatibility path.
- **Current development branch:** `v2/backend/service.py` temporarily
  validates NDJSON v1 for individual core binaries to avoid enabling a
  one-shot CLI inadvertently. This is a temporary shim, **not** the intended
  plugin architecture.
- **Planned:** Once `retrode3-cli` publishes its versioned protocol and is
  installed, replace the per-core probing and process spawning with a single
  well-defined CLI client in the backend. Switch the capabilities endpoint
  to the CLI's descriptor list. Do not add NDJSON transport to MegaDrive or
  every later cartridge plugin solely to satisfy the current Web prototype.
- Preserve the working SNES path until the new central path passes physical
  SNES and MegaDrive read/cancel/progress tests.
- Never invent protocol commands or advertise a native core without CLI
  confirmation. The exact binary path, JSON schema, version negotiation and
  error types are still to be supplied by retrode3-cli.

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
