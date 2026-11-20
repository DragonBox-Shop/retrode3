# Retrode3 Web v2: Developer guide

**November 2026.** This is the technical reference for the **shared Retrode3 CLI** and its Web v2 integration. For browser usage, see the [user guide](user-guide.en.md). Treat the installed CLI's `--list-cores` result as authoritative for available operations.

## 1. Architecture

```text
Browser (PHP/JavaScript)
  -> PHP gateway / Python backend (127.0.0.1:8765)
     -> JobManager / automatic detection / bus serialization
        -> /usr/bin/retrode3-cli (NDJSON v1)
           -> dynamic core: snes.so | md.so | nes.so
              -> Retrode3 HAL and Linux kernel slot driver
```

- The **single shared CLI** owns cartridge operations, progress and NDJSON events. Dynamic cores implement the versioned C ABI; they are **not separate reader executables** and do not implement their own JSON/HTTP transport.
- The Python backend watches kernel `KOBJ_CHANGE` notifications, checks passive sysfs `sense`, runs a read-only `probe` when one usable core matches, and caches the result.
- The browser polls `GET /api/slots` every 1.5 seconds without triggering hardware reads. Jobs are serialized by the backend and a shared bus lock.
- Native CLI/core sources belong to [`retrode3-oscr`](https://github.com/DragonBox-Shop/retrode3-oscr). The [OS repository](https://github.com/DragonBox-Shop/retrode3) owns the Web UI, system services and Debian packaging. Kernel and hardware changes are maintained separately.

## 2. Installed runtime paths

| Purpose | Path |
| --- | --- |
| Single CLI binary | `/usr/bin/retrode3-cli` |
| Privileged core toggle | `/usr/sbin/retrode3-corectl` |
| Core binaries and manifests | `/usr/lib/retrode3/cores-available/<id>.so`, `<id>.core` |
| Enabled core links | `/etc/retrode3/cores-enabled/<id>.so` |
| Shared bus lock | `/run/lock/retrode3/bus.lock` |
| Passive slot state | `/sys/class/retrode3/slot-<slot>/sense` |
| Backend service code | `/opt/retrode3-web-v2/backend/service.py` |
| Local API | `http://127.0.0.1:8765/api/...` |
| Web-managed ROM directory | `/usr/local/games/ROMs/` |

Known stage-1 IDs on the development hardware are `snes` (ordinary LoROM/HiROM), `md` (standard linear Mega Drive), and `nes` (NROM, mapper 0). They do **not** provide arbitrary mappers, special chips, SRAM restore, flash or other cartridge writes. A populated slot is not an adapter identity or voltage guarantee.

## 3. Discover cores

Run on the Retrode3 via SSH or USB serial console:

```sh
/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1
```

The CLI emits a `cores` event with `protocol:"retrode3-ndjson"`, `version:1` and a core list. Inspect `id`, `slot`, `installed`, `enabled`, `status`, `usable`, and `actions`. A core is usable only when it is installed, enabled, ABI-compatible, `ready`, and advertises the requested action. Listing cores does not require a cartridge or read the bus.

## 4. One-shot commands

Use a known-safe supported cartridge and ensure no web job owns the shared hardware bus:

```sh
# Read-only probes
/usr/bin/retrode3-cli --protocol ndjson-v1 --core snes --action probe
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md --action probe
/usr/bin/retrode3-cli --protocol ndjson-v1 --core nes --action probe

# Read a complete Mega Drive ROM to a NEW absolute output path
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md \
  --action read-rom --output /tmp/retrode3-md-test.md
```

On success, `probe` emits `probe_result` (title, mapping, size, core-specific checksum). `read-rom` emits `progress` and finally `result` with `bytes_written`, `crc32` and `output`, or an `error` event.

The CLI rejects relative output paths and existing destination files, but **does not enforce the Web UI's output root**. Direct callers must choose an appropriate safe directory and ensure write permission. One-shot commands cannot receive a live stdin `cancel` request. Do not run CLI hardware operations concurrently with a web-initiated read; a non-blocking lock prevents simultaneous bus access.

## 5. Interactive NDJSON v1

Web v2 uses the interactive mode, writing **one JSON object per input line**:

```sh
/usr/bin/retrode3-cli --protocol ndjson-v1 --interactive
```

Example commands (send each as its own line, **not** as one array):

```json
{"command":"list_cores","request_id":"list1"}
{"command":"get_capabilities","core":"md","request_id":"caps1"}
{"command":"probe","core":"md","request_id":"probe1"}
{"command":"read_rom","core":"md","request_id":"rom1","output":"/tmp/retrode3-interactive.md"}
```

The CLI starts with a `ready` event (`system:"multi"`), then publishes correlated `cores`, `capabilities`, `probe_result`, `progress`, `result` and `error` events. During an active read, `{"command":"cancel","request_id":"rom1"}` asks the host to cancel that matching job.

The one-shot option is `--action read-rom`; the interactive JSON command is `"read_rom"`. A result containing `verified:null` means the shared host has no global database verification yet; the NES mapper-0 core performs its own catalog/CRC match.

## 6. Core management and SysV init

```sh
# Root only; deliberate administrative operation
/usr/sbin/retrode3-corectl enable md
/usr/sbin/retrode3-corectl disable md

service retrode3-core-runtime status
service retrode3-web-v2 status

# Passive diagnostics; these do not trigger a ROM probe
cat /sys/class/retrode3/slot-md/sense
wget -qO- http://127.0.0.1:8765/api/slots
```

Retrode3 uses **SysV init, not systemd**. The runtime service prepares `/run/lock/retrode3/bus.lock`, which the CLI acquires via `flock`. **Never remove or replace the lock file while readers might hold it.** Web v2 runs as `www-data` with restricted cartridge-device permissions. Web-based core toggles are disabled by default and must not be enabled through unrestricted root or sudo access.

The Web v2 installer does not compile, copy or install the CLI or any core binaries; those belong to the OS/runtime packages. Installing a new core does not automatically enable it or validate its physical adapter.

## 7. Backend HTTP API and automatic detection

The Python backend listens only on `127.0.0.1:8765`. The browser must use the intended PHP gateway (`api.php`) with same-origin checks and CSRF protection for changes.

| Method | API route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service liveness |
| GET | `/api/cores` | CLI core inventory |
| GET | `/api/capabilities` | Available UI actions |
| GET | `/api/slots` | Passive occupancy and cached identity |
| GET | `/api/jobs/active` | Active or most recent job |
| POST | `/api/jobs` | `{"system":"md","command":"probe"}` or `read_rom` |
| POST | `/api/jobs/<job-id>/cancel` | Request cancellation |
| POST | `/api/cores/toggle` | Only with restricted admin delegation |

The background worker debounces new occupancy, ignores duplicate unchanged slot events, and schedules read-only probes **sequentially**. Manual ROM reads take priority; waiting auto-probes do not repeatedly spawn expensive core-inventory processes. The browser's slot polling never initiates hardware access. Do not expose the loopback backend directly on a public network.

## 8. Developing an additional core

1. In [`retrode3-oscr`](https://github.com/DragonBox-Shop/retrode3-oscr), follow the existing headers `include/retrode3/core_descriptor_v1.h` and `core_operations_v1.h`, plus the typed HAL under `src/retrode3/`.
2. Export a descriptor (`id`, `name`, `version`, `slot`) and only reviewed supported operations. The root-owned `<id>.core` manifest must exactly match the descriptor.
3. Verify mapper, signal and voltage safety against actual hardware. Occupancy alone never authorizes writes or guesses a mapper.
4. Build/stage in the shared OSCR pipeline, then deliver as an independently upgradable OS package. An installed core requires deliberate enablement with `retrode3-corectl`.
5. Web v2 discovers the core from CLI metadata. No extra console-specific subprocess, HTTP API or JSON streaming protocol is needed.

## 9. Source and release boundaries

- **`retrode3/master`**: released Web-v2 source.
- **`retrode3/develop`**: current integration, including Debian package candidates under `packaging/`. Device upgrades/rollbacks and image acceptance are separate gates.
- **`retrode3-oscr`**: native host, core and staging source.
- [Detailed CLI integration contract](cli-integration.md).
- [Debian candidate packaging (develop)](https://github.com/DragonBox-Shop/retrode3/blob/develop/packaging/README.md).

A passing CI run or source merge to `master` does **not** mean the latest candidate Debian packages or customer SD image have passed real hardware acceptance.
