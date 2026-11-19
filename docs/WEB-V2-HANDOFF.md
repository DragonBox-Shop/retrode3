# Web v2 handoff: final native Retrode3 runtime paths

Date: 2026-11-19. Read this with the repository root `AGENTS.md`.
This is a **handoff for the chat working on
`feature/web-control-v2`**, not a claim that Web v2 is already
integrated, hardware-tested end-to-end, or released.

## Actual installed paths on the development Retrode3

| Function | Correct filesystem path |
| --- | --- |
| One shared NDJSON CLI | `/usr/bin/retrode3-cli` |
| Root-only core enable/disable helper | `/usr/sbin/retrode3-corectl` |
| Installed root-owned modules and metadata | `/usr/lib/retrode3/cores-available/` |
| Enabled exact-target symlinks | `/etc/retrode3/cores-enabled/` |
| Shared bus lock | `/run/lock/retrode3/bus.lock` |
| OS-level SysV boot preparation | `/etc/init.d/retrode3-core-runtime` (source: `retrode3-core-runtime/etc/init.d/retrode3-core-runtime`) |

Available cores: `snes.so/.core`, `md.so/.core`, `nes.so/.core`.
The user verified `/usr/bin/retrode3-cli --list-cores` on the
real Retrode3 2.9.5: all three `installed:true`,
`enabled:true`, `status:"ready"`, `usable:true`,
`actions:["probe","read_rom"]`. These are stage-1 readers:
SNES ordinary HiROM/LoROM, MegaDrive ordinary linear ROMs,
NES NROM mapper 0. Real physical ROM CRC references are
SNES Terranigma `6FB8A4DF`, MD Snake Rattle n Roll
`543BED30`, and NES Excitebike `F749E780` (including
16-byte iNES header). No other cartridge types or write operations
are implicitly approved.

The user already removed these **installed legacy programs**:
`/usr/local/bin/oscr`, `/usr/local/bin/retrode3-read`,
`/usr/local/bin/retrode3-dump`,
`/usr/local/bin/retrode3-info`.
**Do not reinstall them; do not create symlinks to retired
`oscr-snes-native` or `oscr-md-native` executables.**
Old source files remain in Git for reference.

## Exact tasks for the Web v2 development chat

1. In `retrode3-web-control/v2/backend/service.py`, change
   `CLI_BIN` default from `/usr/local/bin/retrode3-cli` to
   **`/usr/bin/retrode3-cli`**. Its
   `CORECTL_BIN` default is already correctly
   **`/usr/sbin/retrode3-corectl`**.
2. In `retrode3-web-control/v2/install-on-retrode.sh` and its
   updater/rollback/service integration, **remove** the old
   CLI-copy-to-`/usr/local/bin` and standalone-reader symlink
   installation. Require/check the installed central CLI at
   `/usr/bin/retrode3-cli`; never silently fall back to an old
   per-core reader. Do not overwrite or recompile it as part of the
   web installation. The OSCR build/package owns the CLI.
3. Review every default, environment override, sudo rule,
   test fixture, documentation string and user-facing operation
   for the removed paths and per-console subprocesses. In particular,
   update the older `retrode3-web-control/v2/README.md` and
   `docs/cli-integration.md`. Existing `retrode3-wlan`/admin
   utilities are separate OS concerns, not a reason to restore
   legacy ROM reader scripts.
4. The backend should discover usable/read-only actions dynamically
   from the single central CLI; one interactive NDJSON v1 process
   is the shared per-job protocol, not independent console CLIs.
   `/usr/bin/retrode3-cli --list-cores` works independently
   of a cartridge insertion. `retrode3-corectl enable|disable <id>`
   requires carefully restricted root delegation and does not
   itself grant arbitrary browser sudo access.
5. The device uses **SysV init, NOT systemd**. The CLI itself uses
   `open(O_CREAT)` and nonblocking `flock()` for
   `/run/lock/retrode3/bus.lock`, but it does not create its
   parent directory. The OS repo's verified SysV script prepares
   that directory at boot. Ensure boot script is actually installed
   and registered on the device; the source file in Git alone does
   not do that. The directory must be `root:root 0755`, and the
   lock file `root:www-data 0660` if web jobs run as www-data.
   Never unlink a live `bus.lock`.
6. Kernel hotplug event/sense data are merely physical presence;
   avoid probing unknown cartridge adapters, assuming safe voltages,
   or writing mapper/save/flash controls based on the sense line.
   Confirm NES/MD/SNES insertion, auto-probe and removal UI state
   on the real device, including concurrent job cancellation and
   access to `/dev/slot-*` (persistent permissions not yet
   fully packaged).
7. The USB/gadget, network, game-storage and safe-file-manager
   concerns in the Web v2 branch still require their own checks;
   do not claim the web is released solely because the core CLI works.

## Git branching and promotion

- `DragonBox-Shop/retrode3-oscr`: shared CLI and native modules
  (source development on `develop`, stable in `master`).
- `DragonBox-Shop/retrode3`: Web v2 and OS service/package integration.
  The web feature is currently in **`feature/web-control-v2`**;
  the tested SysV init is in OS `master` at commit
  `111f61a6` and inherited by `develop` (which may also contain
  newer documentation and integration commits). The web branch diverged before the SysV
  lock change. **Bring the SysV fix from `develop` into the web
  work before integration, but do not blindly force-reset or
  overwrite ongoing Web v2 changes.**
- Finish Web v2 on its existing feature branch or integrate through a
  reviewed PR to `develop`. Test lint, mocked backend, real-device
  API/USB-network/reboot and physical cartridge behavior, then
  **squash-promote to `master` only after user acceptance**.
  Sync `develop` back to the resulting stable commit without
  discarding unrelated in-progress work.
- An OSCR source merge is **not** a deployed Debian package. The
  newer `retrode3-core-runtime` + per-core Debian packages and
  flashable SD image build are planned, not yet built/published.

Useful commands on Retrode3:

```sh
/usr/bin/retrode3-cli --list-cores
/usr/bin/retrode3-cli --protocol ndjson-v1 --core snes --action probe
/usr/sbin/retrode3-corectl enable snes
ls -l /usr/lib/retrode3/cores-available/
/etc/init.d/retrode3-core-runtime status
```

Only use known-safe ordinary cartridges for read tests; preserve user
ROM data and do not silently replace installed binaries.
