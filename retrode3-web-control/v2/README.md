# Retrode3 Web Control v2: development prototype

Branch: feature/web-control-v2 in DragonBox-Shop/retrode3. Status: development prototype, not deployed or included in Debian packaging. Existing web UI and master are unchanged.

## Architecture
- OS, original PHP UI, WLAN helper, Samba, USB storage: DragonBox-Shop/retrode3
- Native cartridge reader and NDJSON v1: DragonBox-Shop/retrode3-oscr, migration/oscr-firmware
- A Python 3.4-compatible backend on 127.0.0.1:8765 owns a single hardware job, validates input and paths, forwards native events, and provides guarded file/WLAN operations.
- A PHP gateway with HTTP Basic auth, session and CSRF validation mediates all browser requests; it refuses requests if an administrator password hash is missing.
- Vanilla JS/CSS frontend, language files in web/locales/de.json and en.json. Navigation: Read, File Manager, Write (disabled), Settings.
- Only native SNES LoROM/HiROM probe/read/cancel/get_capabilities are supported. No claims about CRDB game matches, auto-detect, save RAM, other cores or cartridge writes.

## Storage
Managed ROM files are under /usr/local/games/ROMs/SNES, later additional system subfolders. Samba already shares /usr/local/games. The web file manager is restricted to ROMs and cannot recursively delete nonempty folders. This restriction needs a further filesystem race/symlink review before production.

IMPORTANT: Existing USB mass storage exposes /var/storage0.img, a separately generated FAT image populated from /media/usb-storage, NOT a live view of /usr/local/games. USB and Samba/Web therefore do not yet share files. Never mount the same FAT filesystem read-write at once on the host and on Linux. Decide on a safe synchronized/exclusive USB strategy before deployment. USB network with Samba access is a possible live-share alternative.

## Prototype start (development system only)
Requirements: Python 3.4+, a PHP runtime with sessions, password_verify and stream_socket_client, and the matching OSCR native binary.

1. Host v2/web separately from the existing /var/www/html (test vhost or subpath), without replacing the old site.
2. Install/copy the backend and start manually with RETRODE3_GAMES_ROOT=/path/to/test/games RETRODE3_SNES_BINARY=/path/to/oscr-snes-native python3 backend/service.py. The default binary path is /usr/local/bin/oscr-snes-native. No system daemon or package installation is included yet.
3. To unlock PHP access, put a PHP password_hash(PASSWORD_DEFAULT) hash as a single line into /etc/retrode3-web-control.auth. Username is admin. Make the file owned by root, readable by the PHP worker, and NOT located within the public web root. Never publish it. Without it the UI returns HTTP 503.
4. The PHP gateway uses HTTP Basic authentication. Passwords traverse HTTP without encryption, so do not expose this prototype to an untrusted LAN, public Wi-Fi, or the Internet. Production needs HTTPS or a stronger pairing and device-local trust model.
5. Backend requires ROM folder write permissions and restricted cartridge device access. WLAN is controlled via existing retrode3-wlan using sudo -n (configurable with RETRODE3_WLAN_SUDO=0). Existing helper/privileged dependencies require separate security review.

Prototype endpoints: GET /api/health, /api/capabilities, /api/settings, /api/wifi/status, /api/wifi/scan, /api/files?path=, /api/files/download?path=, /api/jobs/{id}; POST /api/jobs, /api/jobs/{id}/cancel, /api/files/mkdir, /api/files/move, /api/files/delete, /api/wifi/connect, /api/wifi/disconnect.

Submit a probe with JSON {"system":"snes","command":"probe"}. Submit a dump with {"system":"snes","command":"read_rom","filename":"Terranigma","mapping":"hi","size_bytes":4194304}. Optional mapping/size should only be presented if the native capabilities permit them. Poll the returned job ID. Backend restarts currently lose job history; client cannot rediscover active jobs without an ID.

## Release requirements
- Run Python unit tests, PHP lint, JS checks and native mocked protocol integration tests; verify 3.4/PHP compatibility.
- Run real SNES LoROM and HiROM physical read/progress/cancel tests and check ROM output byte-for-byte.
- Add robust crash/cancel/timeout cleanup and job persistence, fd-based file sandbox against concurrent Samba path swaps, disk quotas and space checks.
- Audit WLAN helper (and whether AP mode/fallback is needed), network security and first-run password setup.
- Resolve USB mass-storage live sharing safely, without simultaneous read/write ownership.
- Package backend as a managed service, install native binary, permissions and sudo rules with least privilege.
- Add reconnection behavior and user-friendly error mapping; ensure other systems are never falsely enabled.
- Make a tested, reviewed switch from old web root to v2 only when feature parity is achieved, then merge into master.

The current v2 branch is a starting implementation, not a production release.



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
It configures an authenticated development UI (username admin), a localhost
backend service and an on-device updater. It does not change the native OSCR
source or the main branch. The previously installed web UI is copied to
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
HTTP Basic credentials are not encrypted over plain HTTP, so **do not expose
this development UI to the public Internet or untrusted networks**. The device
may have Internet access without being publicly reachable, but use a trusted
connection and do not forward its HTTP port.

Diagnostics:

    service retrode3-web-v2 status
    tail -n 80 /var/log/retrode3-web-v2.log
    python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8765/api/health").read())'

Rollback on the device:

    /usr/local/sbin/retrode3-web-v2-rollback

Rollback restores the prior webroot and stops/disables the v2 service; it
leaves the native reader and existing ROM files alone. New versions remain
development builds until tested against real SNES hardware. USB mass storage
still uses an independent FAT image and is not synchronized automatically
with Samba/Web.
