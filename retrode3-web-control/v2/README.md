# Retrode3 Web Control v2: shared CLI integration

## Write Cartridge via the shared CLI

Read and Write Cartridge use the **same Web job manager**, the **same**
`/usr/bin/retrode3-cli` and dynamic core capabilities. There is no
special privileged bridge, unlock button, lab-only core or extra
confirmation prompt.

The installed MegaDrive `md.so` advertises `probe_flash`,
`write_flash` and `verify_flash` alongside ordinary ROM reading.
The kernel permits the Flash ioctls through existing
`/dev/slot-md` device permissions (`retrode3-reader` group). The
SysV Web service already configures that group for device files
and the core's scoped hardware-voltage profiles.

The customer workflow:

1. Insert a Flash cartridge and select the supported core in Write Cart
2. Detect Flash to identify the manufacturer/device ID and CFI geometry
3. Select and upload a ROM from the browser's native file requester
4. Independently check **Erase**, **Write** and/or **Verify** (all three
   are checked by default). Select 1..99 complete Verify passes and
   press the **single Start button**.
   - Erase alone with no uploaded image erases the entire chip.
   - Erase with an uploaded image only erases overlapping sectors.
   - Write alone programs an already erased chip.
   - Verify alone reads and compares the existing chip contents.
   - When Verify is unchecked, completion is explicitly `not_checked`,
     never reported as `verified`.

The shared CLI reports actual `bytes_per_second` and `elapsed_ms` in
Write/Verify progress events using a monotonic phase clock. The
Web page displays a measured `KiB/s` rate alongside the bytes
completed. No browser-refresh-based speed estimates are used.
The write rate is reset at Write start, and the Verify rate starts
from zero when Verify begins. Erase reports sector count, not a
made-up byte transfer speed.

The Flash CLI/Core now uses one open device FD throughout a job;
the matching updated kernel must be installed with the updated
`md.so` and shared CLI. Old and new session behaviors must **not**
be mixed, because the kernel now requires an Identify on the same
open FD before Erase/Write.

The kernel does *not* scan every word after each sector erase. It only
polls the Flash's command-completion status. Full byte comparison takes
place in the optional Verify phase **after all Write chunks**, repeating
the entire image on each requested pass. Progress counts real sector
erasures, programmed bytes and compared bytes, with a pass number.

An **unrecognized or unsupported** chip will not be writable. The
kernel/core check actual chip identity, power/slot and geometry on every
destructive operation. The CLI owns exclusive bus serialization,
cancellation and genuine per-phase progress. No additional approval or
root privilege step is required to use normal Web features.

The code stays on feature branches until device tests pass, without
special *runtime* test switches. The Web installer does not install
kernel or native core binaries and has no persistent rollback command.

> **Development integration (2026-11-20):** `develop`
> now uses the regular NES `nes.so` with MMC1 mapper-1 ROM
> support and a database-driven candidate/layout selector in Web v2.
> The 1024-byte auto-detect remains read-only; ROM banking starts
> only when a user clicks Read ROM. Unknown layouts can be set
> manually, while battery-backed MMC1 boards remain disabled until
> the kernel can switch MMC1 without threatening save RAM.
> These changes have not been shipped to `master` or deployed
> onto the real Retrode3 yet.

**Release source:** merged via `develop` to `master` after manual Web v2 MegaDrive/NES reader tests and passing mocked CI. Full production image / Debian runtime packaging remains a separate release gate.
The current developer commands and runtime contract are documented in
[Deutsch](docs/developer-guide.de.md) and
[English](docs/developer-guide.en.md). The historical
`docs/WEB-V2-HANDOFF.md` is an archived feature-branch handoff.

## Architecture

- The Web backend (Python 3.4-compatible) runs on `127.0.0.1:8765`
  under `www-data`; PHP supplies the same-origin authenticated/CSRF gateway.
- The **only** native cartridge process is `/usr/bin/retrode3-cli`,
  discovered with `--list-cores --protocol ndjson-v1` and executed with
  `--protocol ndjson-v1 --interactive`.
- The OS-owned administrative core toggle is `/usr/sbin/retrode3-corectl`;
  web controls are disabled unless restricted privilege delegation is set up.
- SNES, MegaDrive and NES are all delivered as enabled shared CLI cores,
  not separate executables. No legacy OSCR reader fallback or binary
  installation occurs during Web deployment.
- The tested SysV boot script `/etc/init.d/retrode3-core-runtime` owns
  creation and permissions of `/run/lock/retrode3/bus.lock`.
- The Web backend provides slot insertion/removal monitoring, safe read-only
  auto-probe, job serialization, cancellable reads and restricted file/network
  operations. Physical presence is not cartridge identity.
- All three stage-1 read-only cores are hardware-tested through the CLI.
  The Web v2 MegaDrive/NES workflows, automatic detection and reader switching
  were manually exercised on the development device. Unsupported
  mappers, special chips, SRAM/flash writes and unknown adapters remain blocked.

## Generic core selection / override (develop only)

Web v2 can now render a **versioned generic v3 selection schema** from
`get_capabilities.selection_schema` for any registered core. A physical slot
comes exclusively from CLI core registry metadata, not the system name.
Candidate and layout choices come from `probe_result` and are displayed
without console-specific mapping logic. Different layouts require an explicit
supported choice; title-only ambiguity permits automatic safe reading.

A per-cartridge **Override** checkbox reveals generic enum, integer,
boolean and string fields with declarative constraints and dependency rules.
The frontend sends one `selection` object to the Python job manager, which
validates its version/schema/mode before forwarding it to the shared CLI.
The actual dynamic core still authorizes the read; browser options cannot
override blocked mapper or save/flash operations.

All Web ROM reads now use this **single v3 selection path** for NES,
MegaDrive, SNES and future systems. The old NES-v2 UI and legacy mapping/size
read fields have been removed from Web v2; the native CLI's own additive ABI
compatibility is unchanged. The full v3 Web contract and test matrix are in
[docs/generic-selection-v3.md](docs/generic-selection-v3.md).
This code is on `develop`, not a hardware-accepted `master` release.

## Storage and limitations

ROM files are managed beneath `/usr/local/games/ROMs/` and exposed by the
existing Samba games share. The existing USB mass-storage FAT image is separate
and is not automatically synchronized with the Web/Samba files.
The Web SysV startup temporarily restores restricted device-group
permissions after each boot; permanent udev packaging remains pending.
Production hardening, full USB/network checks,
and secure file-manager race review remain outstanding.

## Install and update directly from Git on the Retrode

The tested Web v2 installation replaced the development device's legacy web UI, with a backup.
The Retrode has direct Internet access, so there is no need to clone on another
machine and transfer source via scp. Perform these commands **on the Retrode**
over SSH, as root.

First checkout:

    git --version
    git clone --depth 1 --single-branch --branch master \
      https://github.com/DragonBox-Shop/retrode3.git /root/retrode3-web-src
    sh /root/retrode3-web-src/retrode3-web-control/v2/install-on-retrode.sh

On a Debian-8/Apache 2.4 development device, the installer also
enables the low-memory `retrode3-prefork` configuration from
`packaging/assets/retrode3-prefork.conf` (maximum four prefork workers).
It does not replace the Debian-owned `mpm_prefork.conf` and preserves
an existing manually edited override file. Apache is syntax-checked
and reloaded when possible. These limits are also packaged into the
new Web Debian development candidate.

The installer preflights Python 3.4+, PHP, Python/PHP syntax and the webroot.
It configures a no-login-by-default development UI, a localhost
backend service and an on-device updater, but requires the preinstalled
shared CLI and restricted helper; it never installs native reader binaries. It does not change the installed CLI or cores,
the native OSCR source, or the main branch. The previously installed web UI is copied to
/var/backups/retrode3-web-v2/ before the new webroot is activated.

Later updates, **one command on the Retrode**:

    retrode3-web-v2-update

That command runs a fast-forward-only Git pull of the checkout's allowed branch (normally `master`), then
installs the new frontend and backend, checks service health, and retains a
rollback copy. It refuses a dirty working tree, an unexpected branch, or an
active native cartridge read. The Git checkout is stored under /root rather
than within the publicly served /var/www/html; only deployable assets are
copied into the webroot. A plain git pull alone does not restart the Python
backend or deploy copied PHP/CSS/JS, so use the updater rather than just pull.

The installer still works manually when code has been supplied without a Git
checkout, but that method does not install the Git-updater command. If the
checkout directory already exists from a previous attempt, inspect its state
first rather than recloning into it.

Access the new site at http://172.31.255.1/ on the trusted USB/device network.
The interface requires **no password by default**; enable optional authentication
with `retrode3-web-v2-auth enable` or remove it using `retrode3-web-v2-auth disable`.
Even with optional Basic auth, HTTP does not encrypt credentials; **do not expose
this development UI to the public Internet or untrusted networks**. The device
may have Internet access without being publicly reachable, but use a trusted
connection and do not forward its HTTP port.

Diagnostics:

    service retrode3-web-v2 status
    tail -n 80 /var/log/retrode3-web-v2.log
    python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8765/api/health").read())'

Optional login (run on Retrode as root):

    retrode3-web-v2-auth enable
    retrode3-web-v2-auth disable

Login name when enabled: admin. The optional setup accepts any nonempty password, without imposing a minimum length.

Rollback on the device:

    /usr/local/sbin/retrode3-web-v2-rollback

Rollback restores the prior webroot and stops/disables the v2 service; it
leaves the OS-installed shared CLI, cores and existing ROM files alone. Released source is not the same as a finished customer image: the native CLI/core
Debian packages, full image upgrade, and broader USB/Windows compatibility still
require their own release validation. USB mass storage
still uses an independent FAT image and is not synchronized automatically
with Samba/Web.

## Local health check on older Debian / proxy-configured shells

The install and update scripts use Python stdlib `http.client.HTTPConnection` to contact the locally bound backend directly. This deliberately bypasses `urllib`'s automatic environment proxy discovery, which could otherwise make a healthy backend appear unreachable.

If health check fails, use:

    python3 -c 'import http.client; c=http.client.HTTPConnection("127.0.0.1",8765,timeout=3); c.request("GET","/api/health"); r=c.getresponse(); print(r.status, r.read())'

Expected status: 200, JSON `{"ok": true, "service": "retrode3-web-v2"}`. Service/listener presence alone does not prove successful responses. If the direct connection succeeds but install still fails, paste the exact installer output and backend logs.

## Shared CLI and automatic slot handling (2026-11-19)

The Plugins tab uses the installed `/usr/bin/retrode3-cli` registry and
supports all three ready cores (SNES, MD, NES). The backend starts a single
shared CLI interactive job per operation, always passing the core ID.
Neither CLI, core modules nor legacy readers are installed by this Web
installer. `retrode3-core-runtime` must start at boot before Web v2.

The backend watches kernel slot events and reconciles passive sense values,
debounces insertion and initiates read-only probes only when a single usable
reader maps to the occupied slot. On removal, cached cartridge data is cleared
and affected jobs are cancelled. Unsupported/ambiguous adapters require
manual selection and safety checks.

The browser consumes `/api/slots`, `/api/capabilities`, `/api/cores`
and the job endpoints. Shared CLI error messages are retained and displayed.
No JavaScript cartridge hardware operations or per-core executables exist.

For final image acceptance, verify all three known-good cartridges,
automatic insert/remove, reader permissions after reboot, cancellation,
file management, Wi-Fi/network and USB gadget behavior. Mock tests are not
a replacement for device tests. See `docs/cli-integration.md` and
`docs/slot-discovery.md`.

## Branch promotion and legacy Web v1 retirement

- Web v2 is the maintained source for future Retrode3 OS releases.
- The previous PHP UI at `retrode3-web-control/var/www/html` is retained only
  as historical source; its QuantumSTEP package target is disabled and its
  dependency was removed from the legacy `retrode3` meta-package and `make-all`.
- This does **not** imply that the old QuantumSTEP image builder automatically
  produces a new Web v2 Debian package. The CLI/core runtime and Web v2 Debian
  package dependencies and a tested customer-image upgrade path must be built
  before shipping a new image. Do not fall back to the old PHP frontend.
- Existing development checkouts on `feature/web-control-v2` must be switched
  explicitly to `master` to receive future stable updates:

      git -C /root/retrode3-web-src fetch origin master
      git -C /root/retrode3-web-src checkout -B master FETCH_HEAD
      retrode3-web-v2-update

  Do this only while no cartridge operation is active and no local source edits
  need preservation. The updater never silently switches branches.

### GBx-0011 and GBA adapter note

The GBA-MD core is a **separate dynamic** `gba-md.so` even though its
physical connector is the MD slot. Its earlier working source was on
`feature/gba-md-v3-plugin` and was merged into the Flash CLI branch.
Rebuild/install and enable this core as well as the normal `md.so`.
The currently tested GBx kernel adapter still uses `gbx_md_test` mode;
the mode resets on module replacement, requires 3.3V and the initial
GBx arm cycle before insertion. Passive physical MD `sense` may remain
`empty` with this adapter, so auto-detection on insertion alone is not
yet reliable. That hardware transport mode must be made cleanly
switchable before customer release. Do not mistake this limitation for
a generic browser/plugin identification bug.
