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
[ -f "$BASE/service/retrode3-flashctl.py" ] || fail "Missing Flash bridge"
[ -f "$BASE/service/retrode3-flashctl.sudoers" ] || fail "Missing Flash sudoers policy"
[ -f "$BASE/rollback-on-retrode.sh" ] || fail "Missing rollback script"
[ -f "$BASE/manage-auth-on-retrode.sh" ] || fail "Missing authentication manager"
[ -d "$WWW" ] || fail "Webroot $WWW not found."
[ -d /usr/local/games ] || fail "Games share /usr/local/games missing."
id www-data >/dev/null 2>&1 || fail "Account www-data missing."
command -v python3 >/dev/null 2>&1 || fail "Python3 missing."
command -v sudo >/dev/null 2>&1 || fail "sudo required for Flash test bridge."
command -v visudo >/dev/null 2>&1 || fail "visudo required for Flash test bridge."
command -v php >/dev/null 2>&1 || fail "PHP CLI missing."
command -v start-stop-daemon >/dev/null 2>&1 || fail "start-stop-daemon missing."
php -r 'if (!function_exists("password_hash") || !function_exists("password_verify") || !function_exists("hash_equals")) exit(1);' ||
    fail "PHP >= 5.6 required."
python3 -c 'import sys; assert sys.version_info >= (3,4)' || fail "Python >= 3.4 required."
python3 -m py_compile "$BASE/backend/service.py" || fail "Backend syntax error."
python3 -m py_compile "$BASE/service/retrode3-flashctl.py" || fail "Flash bridge syntax error."
visudo -c -f "$BASE/service/retrode3-flashctl.sudoers" >/dev/null ||
    fail "Invalid Flash sudoers policy."
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


# CLI and core modules are installed by the OS, never by the web installer.
CLI=/usr/bin/retrode3-cli
CORECTL=/usr/sbin/retrode3-corectl
[ -x "$CLI" ] && [ ! -L "$CLI" ] || fail "Shared CLI not installed at $CLI"
[ -x "$CORECTL" ] && [ ! -L "$CORECTL" ] || fail "Core helper not installed at $CORECTL"
"$CLI" --list-cores --protocol ndjson-v1 | python3 -c '
import json,sys
value=json.load(sys.stdin)
assert value.get("protocol") == "retrode3-ndjson"
assert value.get("version") == 1 and value.get("event") == "cores"
assert isinstance(value.get("cores"),list)
' || fail "Shared CLI core registry unavailable."

# OS SysV init prepares the lock before the Web backend starts.
# Adopt the tested OS init script from develop without replacing an existing
# installation. Do not remove or recreate a live bus.lock inode.
CORE_INIT=/etc/init.d/retrode3-core-runtime
CORE_SOURCE="$BASE/../../retrode3-core-runtime/etc/init.d/retrode3-core-runtime"
[ ! -L "$CORE_INIT" ] || fail "Unsafe core runtime init symlink"
if [ ! -e "$CORE_INIT" ]; then
    [ -f "$CORE_SOURCE" ] || fail "Missing OS SysV init source: $CORE_SOURCE"
    install -o root -g root -m 0755 "$CORE_SOURCE" "$CORE_INIT"
fi
[ -x "$CORE_INIT" ] || fail "OS core runtime service unavailable"
command -v update-rc.d >/dev/null 2>&1 || fail "SysV init registration unavailable"
update-rc.d retrode3-core-runtime defaults >/dev/null ||
    fail "Cannot register core runtime on boot"
service retrode3-core-runtime start || fail "OS bus lock initialization failed"
service retrode3-core-runtime status >/dev/null 2>&1 ||
    fail "OS bus lock not ready"
info "Using the installed CLI, helper and OS-managed bus lock."

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
SLOT_COUNT=0
for DEVICE in /dev/slot-*; do
    [ -c "$DEVICE" ] || continue
    [ ! -L "$DEVICE" ] || fail "Unexpected symlink for cartridge device $DEVICE"
    chgrp retrode3-reader "$DEVICE"
    chmod g+rw "$DEVICE"
    SLOT_COUNT=$((SLOT_COUNT + 1))
    info "Granted device-group access to $DEVICE (until reboot)."
done
[ "$SLOT_COUNT" -gt 0 ] ||
    info "WARNING: No /dev/slot-* character devices found."

# The OS init script owns the lock directory and file permissions.
[ -d /run/lock/retrode3 ] && [ ! -L /run/lock/retrode3 ] ||
    fail "OS bus lock directory unavailable"
[ -f /run/lock/retrode3/bus.lock ] && [ ! -L /run/lock/retrode3/bus.lock ] ||
    fail "OS bus lock file unavailable"

# Install only a fixed root-owned Flash action validator, never allow sudo
# access to the generic CLI itself. The bridge can operate immediately
# on an experimental Flash-enabled .so, without a prior hardware-test gate.
mkdir -p /etc/sudoers.d
[ ! -L /usr/sbin/retrode3-flashctl ] || fail "Unsafe Flash helper symlink"
[ ! -L /etc/sudoers.d/retrode3-flashctl ] || fail "Unsafe sudoers symlink"
if [ -e /usr/sbin/retrode3-flashctl ]; then
    cp -a /usr/sbin/retrode3-flashctl /usr/sbin/retrode3-flashctl.prev
fi
if [ -e /etc/sudoers.d/retrode3-flashctl ]; then
    cp -a /etc/sudoers.d/retrode3-flashctl /etc/sudoers.d/retrode3-flashctl.prev
fi
install -o root -g root -m 0755 "$BASE/service/retrode3-flashctl.py" /usr/sbin/retrode3-flashctl
install -o root -g root -m 0440 "$BASE/service/retrode3-flashctl.sudoers" /etc/sudoers.d/retrode3-flashctl
visudo -c -f /etc/sudoers.d/retrode3-flashctl >/dev/null ||
    fail "Installed Flash sudoers policy invalid"
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

# Keep the stock Apache MPM config package-owned. Install a separate
# site-specific override only once; preserve future local admin edits.
APACHE_SOURCE="$BASE/../../packaging/assets/retrode3-prefork.conf"
APACHE_CONF=/etc/apache2/conf-available/retrode3-prefork.conf
if [ -f "$APACHE_SOURCE" ] && [ -d /etc/apache2/conf-available ] &&
   command -v a2enconf >/dev/null 2>&1 &&
   command -v apache2ctl >/dev/null 2>&1; then
    CREATED_APACHE_CONF=0
    if [ -L "$APACHE_CONF" ]; then
        info "WARNING: refusing to overwrite symlink $APACHE_CONF"
    else
        if [ ! -e "$APACHE_CONF" ]; then
            install -o root -g root -m 0644 "$APACHE_SOURCE" "$APACHE_CONF"
            CREATED_APACHE_CONF=1
        else
            info "Preserving existing Apache prefork override $APACHE_CONF"
        fi
        ENABLED_APACHE_CONF=0
        [ -L /etc/apache2/conf-enabled/retrode3-prefork.conf ] &&
            ENABLED_APACHE_CONF=1
        a2enconf retrode3-prefork
        if apache2ctl configtest; then
            if [ -x /etc/init.d/apache2 ] &&
               /etc/init.d/apache2 status >/dev/null 2>&1; then
                service apache2 reload ||
                    info "WARNING: Apache reload failed; check service apache2 status"
            fi
            info "Low-memory Apache prefork limits configured."
        else
            info "WARNING: Apache syntax check failed, reverting the new enablement."
            if [ "$ENABLED_APACHE_CONF" -eq 0 ]; then
                a2disconf retrode3-prefork || true
            fi
            if [ "$CREATED_APACHE_CONF" -eq 1 ]; then
                rm -f "$APACHE_CONF"
            fi
        fi
    fi
fi

info "SUCCESS: New frontend is installed at http://172.31.255.1/"
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
