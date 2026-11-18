# Retrode3 slot and reader discovery (web v2)

Status: development branch `feature/web-control-v2`, first implementation. The SNES web reader has been tested on physical hardware by the user; this discovery layer has only been prepared for mock/CI testing until a separate on-device test confirms it.

## Three different facts

1. **Physical presence:** `/sys/class/retrode3/slot-{md,snes,nes}/sense` is read passively every three seconds by the browser via `GET /api/slots`. `active` means the *connector* is occupied; `empty` means the sense line reports empty. A missing/unrecognized/unreadable sense value is `unavailable`/`unknown`, never guessed. No cart bus read, voltage change or adapter probe is performed.
2. **Reader compatibility:** `GET /api/capabilities` starts the *fixed, registered* native reader only in `--protocol ndjson-v1 --interactive` to obtain a `ready` event followed by `get_capabilities`. Only a validated protocol version 1 handshake, matching system ID and the required read-only commands permit selection. This is independent of whether a cartridge is inserted. No arbitrary executable paths are accepted from browsers.
3. **Game identification:** Happens only after a user explicitly requests `probe` of a compatible reader. The slot's physical form factor alone does not identify an adapter, game, voltage or mapper. The UI must never display a detected game system or adapter ID from a mere sense signal.

The Web backend includes registered SNES and MegaDrive reader descriptors. The physical NES slot is displayed even without a native NES reader. When a compatible native NES reader is implemented, register it using the same descriptor pattern. Do not expose unsupported systems to the advanced reader selector.

### MegaDrive stage 1 is not yet a Web core

On `DragonBox-Shop/retrode3-oscr`, branch `feature/native-md-stage1`, the native MegaDrive partial core has passed real hardware read-only tests. It currently accepts `--action probe|read-rom` and produces *one-shot* JSON. It does **not** accept the SNES native NDJSON v1 handshake or provide streaming progress/cancel events. Therefore the v2 backend correctly marks it `native_protocol_unavailable`. As soon as a reviewed MegaDrive native implementation supports the same verified protocol (including read-only capabilities and command validation), the web UI will display the MD reader automatically when the binary is installed at the known path. We deliberately do not invent read progress or silently call legacy scripts.

### Adapter and plugin support

Retrode2 GBx/N64/SMS adapters use the MegaDrive slot and do not have unique IDs. Modern Sanni expansion adapters may use the SNES slot; no universal safe ID contact has been established for Retrode3 3.0. Some adapters repurpose SNES contacts, so blind bus probing and assumed resistor ID pins are unsafe. Refer to `retrode3-oscr/docs/snes-plugin-id-audit.md`.

Future plugin descriptors need at minimum:
- stable `reader_id`, display name, physical `slot_id` and safe hardware profile
- a signed/trusted, installed binary entrypoint, protocol version and live `get_capabilities`
- explicit supported `probe` / `read_rom` commands and allowed advanced fields/values
- an adapter identification strategy with bounded read-only probe semantics, if physically possible
- a separate voltage/power safety contract before any nonstandard adapter operation
- independent explicit authorization for SRAM/flash/cart writes (never through the generic read tab)

The UI's advanced selector deliberately offers **only live-compatible readers**, including manually selected systems for unknown cartridges. A manually selected core does not imply an adapter was electronically identified.

## Manual acceptance (real Retrode3)

1. Keep a known SNES cartridge in the SNES slot; check `/api/slots` reports SNES `occupied` and selects the supported SNES reader automatically, without triggering a ROM probe.
2. Remove it. The SNES slot should change to `empty` after up to three seconds; no ROM reads or voltage changes should occur.
3. Insert a regular MegaDrive cartridge. MD should report occupied. If the native MD executable is still one-shot, the UI should show no compatible MD web reader, not an incorrect SNES/MD autodetection.
4. In Advanced settings, the system selector should list only installed NDJSON-v1-capable readers. Test manual selection when kernel sense is unknown or when a plugin is not identified.
5. Verify an SNES probe and full read still complete with byte-based progress and that cancellation continues working.
6. If two slots report occupied, do not auto-select an ambiguous reader. Manual selection is required.
7. Test missing `/sys` sense paths as `unavailable`, not as empty.

Do **not** test a write-dependent special cartridge or change voltage on the basis of slot detection.

## Correction: protocol responsibility (2026-11-18)

The final NDJSON transport and progress reporting belong to the **central
retrode3-cli**, not to each OSCR system core or adapter plugin. The per-reader
handshake and executable registry described above are a temporary bridge used
by the development Web prototype, not a plugin API requirement. When
retrode3-cli provides capability/slot/job messages, replace this shim with
one CLI client; keep passive hardware sense distinct from actual game or
adapter identification. Refer to `cli-integration.md` for the authoritative
plan; do not require the MegaDrive plugin itself to emit NDJSON.
