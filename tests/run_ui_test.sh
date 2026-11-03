#!/bin/bash
# Führt den automatischen Oberflächentest aus – mit eigener Broadway-Anzeige (unsichtbar,
# stört die laufende Sitzung nicht), eigenem Mock-Daemon und privater D-Bus-Sitzung.
#
#   tests/run_ui_test.sh [Ausgabeverzeichnis]
#
# Benötigt gtk4-broadwayd (Debian/Ubuntu: libgtk-4-bin) und dbus-run-session.
set -uo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
mkdir -p "$OUT"
RUNTIME="${XDG_RUNTIME_DIR:-/tmp}"
DISPLAY_NR=$(( 40 + RANDOM % 50 ))
SOCK="$RUNTIME/hm-test-$$.sock"
MOCK=""
BWAY=""

cleanup() {
    [ -n "$MOCK" ] && kill "$MOCK" 2>/dev/null
    [ -n "$BWAY" ] && kill "$BWAY" 2>/dev/null
    rm -f "$SOCK"
}
trap cleanup EXIT

for tool in gtk4-broadwayd dbus-run-session; do
    command -v "$tool" >/dev/null || { echo "$tool fehlt" >&2; exit 2; }
done

gtk4-broadwayd ":$DISPLAY_NR" > "$OUT/broadway.log" 2>&1 &
BWAY=$!
python3 -I "$ROOT/tests/mock_daemon.py" "$SOCK" > "$OUT/mock.log" 2>&1 &
MOCK=$!
for _ in $(seq 1 50); do
    [ -S "$SOCK" ] && [ -S "$RUNTIME/broadway$((DISPLAY_NR + 1)).socket" ] && break
    sleep 0.1
done
[ -S "$SOCK" ] || { echo "Mock-Daemon startet nicht:" >&2; cat "$OUT/mock.log" >&2; exit 2; }

GDK_BACKEND=broadway BROADWAY_DISPLAY=":$DISPLAY_NR" HIDEME_NO_SG=1 \
    timeout 300 dbus-run-session -- python3 -I "$ROOT/tests/ui_smoke.py" "$SOCK" "$OUT/run" 2>&1 \
    | grep -v -e 'dbus-daemon' -e 'portal' -e 'fusermount' -e 'Non-compatible' -e 'cannot open display' \
              -e '^$' -e 'discover_other' -e 'exceeds' -e 'frame_timings' -e "connection to the bus can't be made"
exit "${PIPESTATUS[0]}"
