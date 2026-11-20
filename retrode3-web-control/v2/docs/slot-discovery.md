# Retrode3 Web v2: physical slots versus CLI core discovery

Status: Web v2 source released on `master` after device tests for MD/NES
flows; full Debian package and customer-image acceptance remain separate.
See [developer-guide.en.md](developer-guide.en.md) for installed CLI paths.

## Independent states

1. Kernel `/sys/class/retrode3/slot-*/sense` reports only physical
   occupancy. Missing or invalid data is `unavailable`/`unknown`; it does
   not identify a game, adapter, supported voltage, or mapper.
2. `GET /api/capabilities` derives readers exclusively from
   `/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1`. Only explicitly
   enabled, ready, usable cores and their advertised operations are offered.
   No per-system executables, old-reader fallback or ID allowlist exist.
3. Game identification is a read-only `probe` through
   `/usr/bin/retrode3-cli --protocol ndjson-v1 --interactive`. The same CLI
   manages all SNES, MegaDrive and NES operations and progress.

## Auto detection

A backend worker watches kernel KOBJ_CHANGE events and reconciles slot
sense periodically. Repeated unchanged events do not invalidate a completed
probe. While another reader job occupies the bus, pending automatic probes
wait without repeatedly querying the CLI core registry. After an insertion settles, it submits a probe using the
same single-job manager only if exactly one enabled, usable reader is mapped
to that physical slot. Multiple candidates require user selection. Inserting
a module cannot authorize unsupported mapper, save or flash operations.
Removal invalidates cached game data and cancels the matching job.
The browser polls `/api/slots` for state changes.

## Read-only scope

Physical CRC acceptance through the CLI: SNES Terranigma `6FB8A4DF`,
MegaDrive Snake Rattle n Roll `543BED30`, NES Excitebike `F749E780`
(full NES output including its header). Only standard SNES LoROM/HiROM,
standard linear MegaDrive and NES NROM mapper 0 are stage-1 supported.
Sanni adapter and alternate mapper capability requires separate safety
review and physical tests.

## Device test checklist

- Confirm `/usr/bin/retrode3-cli --list-cores` and reader discovery.
- Verify `/etc/init.d/retrode3-core-runtime status`, including after reboot.
- Verify `www-data` access to `/dev/slot-*` and the shared lock file.
- Insert a known supported cartridge in SNES, MD and NES in turn; check
  physical presence, automatic probe, title, size and checksum.
- Remove each cartridge; verify cleared identity and job cancellation.
- Exercise a manual probe, complete read, byte progress, CRC, cancellation
  and no-overwrite output behavior for each supported core.
- Verify ambiguous or unsupported adapters do not receive automatic probes.
- Verify network, Wi-Fi, ROM file manager and USB features separately.

No browser-only signal can establish electrical adapter safety.
