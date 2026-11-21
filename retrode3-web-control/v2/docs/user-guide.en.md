# Retrode3: User guide (Web Control v2)

> **New on `develop`:** NES mapper 1 (MMC1) ROM reading
> is integrated into the standard NES core. The automatic read-only
> detector provides Sanni database game candidates; the regular Read
> ROM panel offers layout selection where ambiguous and a manual
> mapper/PRG/CHR override for unknown titles. Battery-backed
> MMC1 cartridges remain unavailable pending SRAM-safe kernel
> timings. These changes are not yet in the released `master` build.

This guide describes the Web v2 interface from the Retrode3 OS `master` branch (November 2026). See the [developer guide](developer-guide.en.md) for the actual `retrode3-cli` commands and interfaces.

## 1. Connecting

Connect Retrode3 to your computer over USB and open `http://172.31.255.1/`. This is the address of the current USB network setup, not a guarantee for every future image.

The existing development device runs the web UI without a password by default. Owners can enable optional authentication using `retrode3-web-v2-auth enable`. Do not expose the UI to the public internet. Basic Auth over unencrypted HTTP does not protect credentials against eavesdropping.

## 2. Automatic detection and ROM reading

1. Insert a supported cartridge into its matching physical slot.
2. The Web v2 backend watches kernel slot events and starts a **read-only automatic probe** if exactly one installed, usable core matches the occupied slot. You normally do not need to click **Detect cartridge**.
3. Select the occupied slot and review the detected title, mapping and ROM size. The suggested file name follows the selected slot and can be edited.
4. Click **Read ROM** and monitor byte-based progress.
5. Open the **File Manager** to find or download the finished file.

If the automatic slot probe cannot identify the system unambiguously, a **Select system manually** dropdown appears directly inside the occupied slot card. It offers only active, available readers for that physical slot. This chooses a reader, but does not verify an adapter or change voltage. A kernel `occupied` indication identifies **neither the system nor adapter nor its safe voltage**.

Removing a cartridge clears its identity from the UI and cancels an active read for that slot. Reloading the browser does **not** initiate new hardware probing: the UI merely asks the backend for its cached state. All real cartridge jobs are serialized through the single shared CLI.

Do not remove cartridges during reads or force unsupported mappers or voltages.

## 3. Currently supported systems

These **stage-1 cores** were physically tested with the shared CLI on a development Retrode3:

| Console | Core ID | Supported scope |
| --- | --- | --- |
| Super Nintendo | `snes` | Ordinary LoROM/HiROM; no special chips or SRAM operations |
| Mega Drive / Genesis | `md` | Standard linear ROMs; no specialty mappers or save writes |
| NES / Famicom | `nes` | NROM (mapper 0) and no-battery MMC1 (mapper 1) on develop; no save/flash writes |

Actual availability depends on the installed, enabled and `ready` modules. A software core does not establish electrical compatibility with a physical adapter.

**Write Cartridge** is a placeholder; SRAM restoration, flash operations and other cartridge writes are not available. The NES output includes the catalog-derived 16-byte iNES header.

## 4. Advanced settings and software cores

**Advanced settings** lets you select installed compatible readers manually. Mapping and ROM-size overrides are shown only when explicitly advertised by the core; current stage-1 cores do not accept arbitrary overrides.

**Plugins** shows the installed cores, enablement and ABI compatibility plus supported operations. Core enable/disable controls are disabled by default and need a separately secured administrative privilege configuration.

## 5. Files and networking

Completed dumps are under `/usr/local/games/ROMs/`, for example `ROMs/MD/`, `ROMs/SNES/` and `ROMs/NES/`. The web file manager can download, rename, move and delete them. The Samba share `retrode` exports `/usr/local/games`.

**Important:** USB mass storage currently uses a separate backing image. Web/Samba files are not automatically copied there. Never mount the same filesystem writable on both host and device at the same time.

**General Settings** includes Wi-Fi status, scanning and connection controls where a supported device and the installed `retrode3-wlan` helper are available.

## 6. Troubleshooting

Run these commands on Retrode3 (SSH or USB serial console):

```sh
service retrode3-core-runtime status
service retrode3-web-v2 status
/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1
wget -qO- http://127.0.0.1:8765/api/slots
tail -n 50 /var/log/retrode3-web-v2.log
iw dev
```

A reported `occupied` slot does not guarantee successful game identification. An unavailable core is not silently replaced by a previous-generation standalone cartridge reader.

## 7. For developers: the common CLI

All cartridge operations use **`/usr/bin/retrode3-cli`** and enabled dynamic cores. For a supported cartridge with the shared hardware bus free:

```sh
# Discover cores and their actual actions
/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1

# Read-only Mega Drive probe
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md --action probe

# Read the complete ROM to a NEW destination file
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md \
  --action read-rom --output /tmp/retrode3-test.md
```

Do not run these commands concurrently with a web-triggered read. The CLI uses `/run/lock/retrode3/bus.lock`. Output paths must be absolute and may not overwrite an existing file; direct CLI callers are responsible for choosing a safe output directory.

The [full developer guide](developer-guide.en.md) documents the interactive NDJSON v1 protocol (`ready`, `probe_result`, `progress`, `result`, `error`), core registry, `retrode3-corectl`, SysV init, Web API and adding cores. There are **no separate SNES, Mega Drive or NES reader executables in the supported runtime architecture**.

## 8. Source and documentation

- [Retrode3 OS, Web v2 and Debian packaging](https://github.com/DragonBox-Shop/retrode3)
- [Shared CLI and OSCR cores](https://github.com/DragonBox-Shop/retrode3-oscr)
- [Kernel and slot drivers](https://github.com/DragonBox-Shop/retrode3-kernel)
- [Hardware and adapters](https://github.com/DragonBox-Shop/retrode3-hardware)
- [Web v2 / CLI integration contract](cli-integration.md)

Web v2 source has been promoted to `master`. Debian package candidates are tested separately on `develop`; source promotion does not imply a fully verified customer SD image.
