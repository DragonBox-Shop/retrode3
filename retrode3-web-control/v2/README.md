# Retrode3 Web Control v2: shared CLI integration

Branch: `feature/web-control-v2`. Hardware end-to-end acceptance is pending.
The OS-installed runtime contract is defined in repository `AGENTS.md`
and `docs/WEB-V2-HANDOFF.md`.

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
- All three stage-1 read-only cores are hardware-tested through the CLI,
  but the **Web v2 integration is not yet hardware accepted**. Unsupported
  mappers, special chips, SRAM/flash writes and unknown adapters remain blocked.

## Storage and limitations

ROM files are managed beneath `/usr/local/games/ROMs/` and exposed by the
existing Samba games share. The existing USB mass-storage FAT image is separate
and is not automatically synchronized with the Web/Samba files.
The Web SysV startup temporarily restores restricted device-group
permissions after each boot; permanent udev packaging remains pending.
Production hardening, full USB/network checks,
and secure file-manager race review remain outstanding.

## Install and update directly from Git on the Retrode

The user approved replacing the existing development device's web UI, with a backup.
The Retrode has direct Internet access, so there is no need to clone on another
machine and transfer source via scp. Perform these commands **on the Retrode**
over SSH, as root.

First checkout:

    git --version
    git clone --depth 1 --single-branch --branch feature/web-control-v2 \
      https://github.com/DragonBox-Shop/retrode3.git /root/retrode3-web-src
    sh /root/retrode3-web-src/retrode3-web-control/v2/install-on-retrode.sh

The installer preflights Python 3.4+, PHP, Python/PHP syntax and the webroot.
It configures a no-login-by-default development UI, a localhost
backend service and an on-device updater, but requires the preinstalled
shared CLI and restricted helper; it never installs native reader binaries. It does not change the installed CLI or cores,
the native OSCR source, or the main branch. The previously installed web UI is copied to
/var/backups/retrode3-web-v2/ before the new webroot is activated.

Later updates, **one command on the Retrode**:

    retrode3-web-v2-update

That command runs a fast-forward-only Git pull of feature/web-control-v2, then
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

Access the new site at http://192.168.0.202/ on the trusted USB/device network.
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
leaves the OS-installed shared CLI, cores and existing ROM files alone. New
versions remain development builds until tested with Web v2 on real SNES,
MegaDrive and NES hardware. USB mass storage
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

For Web hardware acceptance, verify all three known-good cartridges,
automatic insert/remove, reader permissions after reboot, cancellation,
file management, Wi-Fi/network and USB gadget behavior. Mock tests are not
a replacement for device tests. See `docs/cli-integration.md` and
`docs/slot-discovery.md`.
