#!/bin/sh
# Development install on the Retrode. Backup and rollback included.
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=/opt/retrode3-web-v2
WWW=/var/www/html
BACKUP_ROOT=/var/backups/retrode3-web-v2
AUTH=/etc/retrode3-web-control.auth
fail() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[ "$(id -u)" = 0 ] || fail "Run as root."
[ -f "$BASE/backend/service.py" ] || fail "Missing backend/service.py"
[ -f "$BASE/web/index.php" ] || fail "Missing web/index.php"
[ -f "$BASE/service/retrode3-web-v2.init" ] || fail "Missing init script"
[ -f "$BASE/rollback-on-retrode.sh" ] || fail "Missing rollback script"
[ -f "$BASE/manage-auth-on-retrode.sh" ] || fail "Missing authentication manager"
[ -d "$WWW" ] || fail "Webroot $WWW not found."
[ -d /usr/local/games ] || fail "Games share /usr/local/games missing."
id www-data >/dev/null 2>&1 || fail "Account www-data missing."
command -v python3 >/dev/null 2>&1 || fail "Python3 missing."
command -v php >/dev/null 2>&1 || fail "PHP CLI missing."
command -v start-stop-daemon >/dev/null 2>&1 || fail "start-stop-daemon missing."
php -r 'if (!function_exists("password_hash") || !function_exists("password_verify") || !function_exists("hash_equals")) exit(1);' ||
    fail "PHP >= 5.6 required."
python3 -c 'import sys; assert sys.version_info >= (3,4)' || fail "Python >= 3.4 required."
python3 -m py_compile "$BASE/backend/service.py" || fail "Backend syntax error."
for f in "$BASE"/web/*.php; do php -l "$f" >/dev/null || fail "PHP syntax error $f"; done
info "Preflight checks passed."

# Avoid orphaning a native child while the web backend is replaced.
if [ -f /etc/init.d/retrode3-web-v2 ]; then
    if python3 -c '
import json, sys, http.client
try:
    conn = http.client.HTTPConnection("127.0.0.1", 8765, timeout=3)
    conn.request("GET", "/api/jobs/active")
    response = conn.getresponse()
    if response.status != 200:
        sys.exit(2)
    state = json.loads(response.read().decode("utf-8")).get("status", "unknown")
    conn.close()
except Exception:
    sys.exit(2)
if state in ("queued", "running", "cancelling"):
    sys.exit(1)
sys.exit(0 if state in ("idle", "done", "failed", "cancelled") else 2)
'; then
        :
    else
        CODE=$?
        [ "$CODE" -eq 1 ] && fail "A cartridge job is running; finish or cancel it before installing."
        fail "Cannot verify backend is idle; not restarting it."
    fi
fi


# The shared core registry/operation host is built in retrode3-oscr,
# not installed by the older native SNES/MD acceptance-reader setup.
# Copy the built host to a root-owned fixed path. Never replace an existing
# system-installed CLI or follow an unexpected destination symlink.
CLI_BUILD=/usr/local/src/retrode3-oscr/build/migration/retrode3-cli
CLI_INSTALL=/usr/local/bin/retrode3-cli
if [ ! -e "$CLI_INSTALL" ] && [ ! -L "$CLI_INSTALL" ]; then
    if [ -f "$CLI_BUILD" ] && [ -x "$CLI_BUILD" ]; then
        install -o root -g root -m 0755 "$CLI_BUILD" "$CLI_INSTALL"
        info "Installed central Retrode3 CLI for web core discovery."
    else
        info "WARNING: central CLI is not built at $CLI_BUILD."
        info "Build it in retrode3-oscr with: make -f Makefile.migration native-core-registry"
    fi
elif [ -x "$CLI_INSTALL" ]; then
    info "Using existing central CLI at $CLI_INSTALL (not replacing it)."
else
    info "WARNING: $CLI_INSTALL exists but cannot be executed; inspect it manually."
fi

if [ ! -e /usr/local/bin/oscr-snes-native ]; then
    if [ -x /usr/local/src/retrode3-oscr/build/migration/oscr-snes-native ]; then
        ln -s /usr/local/src/retrode3-oscr/build/migration/oscr-snes-native /usr/local/bin/oscr-snes-native
        info "Linked existing native SNES executable."
    else
        info "WARNING: native SNES executable not found, ROM reading remains disabled."
    fi
fi

# Link the read-only MegaDrive stage-1 binary if it was built locally.
# The Web UI only enables it after a separate compatible NDJSON handshake.
if [ ! -e /usr/local/bin/oscr-md-native ] &&
   [ -x /usr/local/src/retrode3-oscr/build/migration/oscr-md-native ]; then
    ln -s /usr/local/src/retrode3-oscr/build/migration/oscr-md-native /usr/local/bin/oscr-md-native
    info "Linked native MegaDrive CLI (NDJSON web support still required)."
fi

if [ -e "$AUTH" ]; then
    info "Optional web password file is present. Authentication remains enabled."
else
    info "Web access without password (default). Configure optional protection later if desired."
fi

if [ ! -e /usr/local/games/ROMs ]; then
    mkdir -m 0755 /usr/local/games/ROMs
fi
[ -d /usr/local/games/ROMs ] && [ ! -L /usr/local/games/ROMs ] ||
    fail "ROMs must be a real directory, not a symlink."
chown www-data:www-data /usr/local/games/ROMs
chmod 0755 /usr/local/games/ROMs

# The shared CLI uses the same cartridge devices and an exclusive flock.
# Grant ONLY the dedicated reader group access; no world-writable lock/device.
getent group retrode3-reader >/dev/null 2>&1 || groupadd -r retrode3-reader
usermod -a -G retrode3-reader www-data
for SLOT in snes md; do
    DEVICE="/dev/slot-$SLOT"
    if [ -c "$DEVICE" ]; then
        chgrp retrode3-reader "$DEVICE"
        chmod g+rw "$DEVICE"
        info "Granted device-group access to $DEVICE (until reboot)."
    else
        info "WARNING: $DEVICE not present; $SLOT reads may be unavailable."
    fi
done

# The CLI creates /run/lock/retrode3/bus.lock with O_RDWR|O_CREAT.
# A previous root-run hardware test may already have left root:root/0640
# there. The web service needs group write to acquire the same flock.
LOCK_DIR=/run/lock/retrode3
[ ! -L "$LOCK_DIR" ] || fail "Unsafe symlink in $LOCK_DIR"
if [ -e "$LOCK_DIR" ]; then
    [ -d "$LOCK_DIR" ] || fail "Invalid bus lock directory."
fi
install -d -o root -g retrode3-reader -m 2770 "$LOCK_DIR"
if [ -e "$LOCK_DIR/bus.lock" ] || [ -L "$LOCK_DIR/bus.lock" ]; then
    [ -f "$LOCK_DIR/bus.lock" ] && [ ! -L "$LOCK_DIR/bus.lock" ] ||
        fail "Unsafe bus lock file."
    chgrp retrode3-reader "$LOCK_DIR/bus.lock"
    chmod 0660 "$LOCK_DIR/bus.lock"
fi
info "Configured shared CLI cartridge bus lock for retrode3-reader group."

mkdir -p "$ROOT/backend" "$BACKUP_ROOT"
cp "$BASE/backend/service.py" "$ROOT/backend/service.py"
chown root:root "$ROOT/backend/service.py"
chmod 0644 "$ROOT/backend/service.py"
cat > "$ROOT/start.sh" <<'EOF'
#!/bin/sh
umask 022
exec /usr/bin/python3 /opt/retrode3-web-v2/backend/service.py >>/var/log/retrode3-web-v2.log 2>&1
EOF
chown root:root "$ROOT/start.sh"
chmod 0755 "$ROOT/start.sh"
if [ -f /etc/init.d/retrode3-web-v2 ]; then
    cp -a /etc/init.d/retrode3-web-v2 /etc/init.d/retrode3-web-v2.prev
    service retrode3-web-v2 stop || true
fi
cp "$BASE/service/retrode3-web-v2.init" /etc/init.d/retrode3-web-v2
chmod 0755 /etc/init.d/retrode3-web-v2
touch /var/log/retrode3-web-v2.log
chown www-data:www-data /var/log/retrode3-web-v2.log
chmod 0640 /var/log/retrode3-web-v2.log
service retrode3-web-v2 start || fail "Backend start failed, old website remains."

info "Checking backend health..."
OK=0
COUNT=0
while [ "$COUNT" -lt 12 ]; do
    if python3 -c 'import json,http.client; c=http.client.HTTPConnection("127.0.0.1",8765,timeout=2); c.request("GET","/api/health"); r=c.getresponse(); assert r.status == 200; assert json.loads(r.read().decode("utf-8")).get("ok") is True; c.close()' >/dev/null 2>&1; then
        OK=1
        break
    fi
    COUNT=$((COUNT + 1))
    sleep 1
done
if [ "$OK" != 1 ]; then
    tail -n 30 /var/log/retrode3-web-v2.log || true
    fail "Backend health check failed; old website NOT replaced."
fi

# Discovery is read-only and must work as the unprivileged backend account.
# Report a useful warning rather than silently treating a missing CLI as no cores.
info "Checking CLI core discovery through the running web backend..."
python3 -c '
import json, http.client
try:
    c = http.client.HTTPConnection("127.0.0.1", 8765, timeout=6)
    c.request("GET", "/api/cores")
    r = c.getresponse()
    body = json.loads(r.read().decode("utf-8"))
    c.close()
    if r.status != 200:
        print("WARNING: /api/cores returned HTTP %s: %s" % (r.status, body.get("error", "unknown")))
    elif not body.get("available"):
        print("WARNING: CLI discovery unavailable: %s" % body.get("reason", "unknown"))
    else:
        print("Core discovery working: %d installed cores" % len(body.get("cores", [])))
except Exception as e:
    print("WARNING: CLI discovery check failed: %s" % e)
' || true

STAGE="/var/www/html-retrode3-v2-staging-$"
[ ! -e "$STAGE" ] || fail "Staging path exists."
mkdir "$STAGE"
cp -a "$BASE/web/." "$STAGE/"
cat > "$STAGE/index.html" <<'EOF'
<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=index.php"></head><body><a href="index.php">Retrode3</a></body></html>
EOF
chown -R root:root "$STAGE"
find "$STAGE" -type d -exec chmod 0755 {} \;
find "$STAGE" -type f -exec chmod 0644 {} \;

STAMP=$(date '+%Y%m%d-%H%M%S')
BACKUP="$BACKUP_ROOT/$STAMP"
[ ! -e "$BACKUP" ] || fail "Backup location already exists."
mkdir "$BACKUP"
info "Backing up $WWW to $BACKUP"
cp -a "$WWW" "$BACKUP/previous-webroot"
[ -f "$BACKUP/previous-webroot/index.php" ] || fail "Legacy backup check failed."
mv "$WWW" "$BACKUP/old-active-webroot"
if ! mv "$STAGE" "$WWW"; then
    mv "$BACKUP/old-active-webroot" "$WWW" || true
    fail "Could not replace webroot; old website restored."
fi
printf '%s\n' "$BACKUP" > "$BACKUP_ROOT/latest"
cp "$BASE/rollback-on-retrode.sh" /usr/local/sbin/retrode3-web-v2-rollback
chmod 0755 /usr/local/sbin/retrode3-web-v2-rollback
if command -v update-rc.d >/dev/null 2>&1; then
    update-rc.d retrode3-web-v2 defaults >/dev/null || true
fi

info "SUCCESS: New frontend is installed at http://192.168.0.202/"
info "Check service: service retrode3-web-v2 status"
info "Read logs: tail -n 50 /var/log/retrode3-web-v2.log"
info "Rollback: /usr/local/sbin/retrode3-web-v2-rollback"
info "Login: no password by default. Optional password: retrode3-web-v2-auth enable."

# Only a private checkout is pulled. Do not expose a .git directory to HTTP.
if command -v git >/dev/null 2>&1; then
    SRC=$(git -C "$BASE" rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$SRC" ] && [ -f "$SRC/retrode3-web-control/v2/update-on-retrode.sh" ]; then
        ( umask 077; printf '%s\n' "$SRC" > /etc/retrode3-web-v2-source )
        cat > /usr/local/sbin/retrode3-web-v2-update <<'EOF'
#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
IFS= read -r SOURCE < /etc/retrode3-web-v2-source
exec /bin/sh "$SOURCE/retrode3-web-control/v2/update-on-retrode.sh"
EOF
        chmod 0755 /usr/local/sbin/retrode3-web-v2-update
        chown root:root /usr/local/sbin/retrode3-web-v2-update
        info "Next updates: retrode3-web-v2-update (Git pull + deploy + backup)"
    fi
fi

# Install optional authentication manager. The site works without this step.
cp "$BASE/manage-auth-on-retrode.sh" /usr/local/sbin/retrode3-web-v2-auth
chown root:root /usr/local/sbin/retrode3-web-v2-auth
chmod 0755 /usr/local/sbin/retrode3-web-v2-auth
