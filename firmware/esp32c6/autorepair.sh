#!/bin/sh
# One automatic attempt per bundled firmware, never triggered by WLAN association.
set -eu
FW=/usr/share/retrode3/esp32c6
EXPECTED=NG-1.0.6.0.1
STATE=/var/lib/retrode3/esp-autorepair
FLASHER=/usr/sbin/retrode3-esp-flasher
# Explicit development gate until serial recovery and real flash tests pass.
[ -f /etc/retrode3/esp-autorepair-enabled ] || exit 0
[ -x "$FLASHER" ] && [ -r "$FW/SHA256SUMS" ] || exit 1
[ -c /dev/ttyS1 ] && [ -w /sys/devices/platform/wlan_pwrseq/enable_power ] &&
    [ -w /sys/devices/platform/wlan_pwrseq/enable_flashing ] || exit 1

# Wait for the asynchronous SDIO/ESP startup. Latest explicit version wins.
version_status() {
    dmesg | sed -n \
        -e 's/.*ESP-Hosted Version: \([^ ]*\).*/ok \1/p' \
        -e 's/.*Firmware version: \([^,]*\), Host version: \([^ ]*\).*/mismatch \1 \2/p' |
        tail -n 1
}
n=0
while [ "$n" -lt 20 ]; do
    status="$(version_status)"
    case "$status" in
        "ok $EXPECTED") exit 0 ;;
        mismatch*) break ;;
    esac
    n=$((n+1))
    sleep 1
done
# Never downgrade a newer or unrecognized firmware. For the known old
# driver mismatch we have positive evidence, not merely a missing network.
case "$status" in
    "ok "*) exit 0 ;;
    "mismatch NG-1.0.3.0.1 $EXPECTED") mode=--flash-confirmed ;;
    "") 
        # Unknown boot failure: only a positively verified erased flash
        # may be written. A working interface also rules out this fallback.
        for dev in /sys/class/net/wlan*; do
            [ ! -e "$dev" ] || exit 0
        done
        mode=--flash-if-blank ;;
    *) echo "ESP autorepair: unrecognized firmware state; manual diagnosis required"; exit 0 ;;
esac
# Verify the bundle before reserving the one-shot attempt.
(cd "$FW" && sha256sum -c --strict SHA256SUMS) || exit 1
install -d -o root -g root -m 0755 "$STATE"
[ ! -L "$STATE" ] || exit 1
key="$(sha256sum "$FW/SHA256SUMS" | cut -d ' ' -f 1)"
attempt="$STATE/$key"
if ! mkdir -m 0700 "$attempt" 2>/dev/null; then
    echo "ESP autorepair: attempt already recorded; no repeat"
    exit 0
fi
printf '%s\n' "$mode" > "$attempt/mode"
# Persist the marker before any write so an interrupted flash cannot loop.
sync
if "$FLASHER" "$mode"; then
    echo flashed > "$attempt/result"
    sync
    echo "ESP autorepair: flash verified; WLAN registration still needs checking"
else
    rc=$?
    printf 'exit=%s\n' "$rc" > "$attempt/result"
    sync
    echo "ESP autorepair: no verified update; manual recovery may be required" >&2
    exit "$rc"
fi
