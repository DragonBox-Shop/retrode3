#!/bin/sh
# Optional web password management; run as root on the Retrode.
# The development UI deliberately works without a password by default.
set -eu

AUTH=/etc/retrode3-web-control.auth
[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }

case "${1:-status}" in
    status)
        if [ -e "$AUTH" ]; then
            echo "Password protection is enabled (username: admin)."
        else
            echo "Password protection is disabled (default)."
        fi
        ;;
    disable)
        rm -f "$AUTH"
        echo "Password protection disabled. No web-service restart required."
        ;;
    enable)
        [ -c /dev/tty ] || { echo "An interactive terminal is required." >&2; exit 1; }
        command -v php >/dev/null 2>&1 || { echo "PHP CLI is required." >&2; exit 1; }
        id www-data >/dev/null 2>&1 || { echo "www-data account missing." >&2; exit 1; }
        printf "New optional web password (no minimum length): " >/dev/tty
        stty -echo </dev/tty
        trap 'stty echo </dev/tty' 0 1 2 3 15
        IFS= read -r SECRET </dev/tty || exit 1
        stty echo </dev/tty
        trap - 0 1 2 3 15
        printf "\n" >/dev/tty
        [ -n "$SECRET" ] || { echo "Password cannot be empty. Use disable for no password." >&2; exit 1; }
        HASH=$(printf '%s' "$SECRET" | php -r 'echo password_hash(stream_get_contents(STDIN), PASSWORD_DEFAULT);')
        unset SECRET
        [ -n "$HASH" ] || { echo "Could not hash password." >&2; exit 1; }
        umask 077
        TEMP=$(mktemp /etc/retrode3-web-control.auth.XXXXXX)
        trap 'rm -f "$TEMP"' 0 1 2 3 15
        printf '%s\n' "$HASH" > "$TEMP"
        chown root:www-data "$TEMP"
        chmod 0640 "$TEMP"
        mv -f "$TEMP" "$AUTH"
        trap - 0 1 2 3 15
        echo "Password protection enabled (username: admin)."
        ;;
    *)
        echo "Usage: $0 {status|enable|disable}" >&2
        exit 2
        ;;
esac
