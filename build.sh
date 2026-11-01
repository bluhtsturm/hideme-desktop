#!/bin/bash
# Baut das hide.me-Programm aus dem mitgelieferten Quellcode (hide.client.linux) nach build/hide.me.
# Benötigt Go >= 1.21 (die passende Toolchain 1.24+ wird bei Bedarf automatisch geladen).
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
OUT="$SRC/build"

if ! command -v go >/dev/null 2>&1; then
    echo "Fehler: Go ist nicht installiert." >&2
    echo "  Debian/Ubuntu: sudo apt install golang-go" >&2
    echo "  Fedora:        sudo dnf install golang" >&2
    echo "  Arch:          sudo pacman -S go" >&2
    echo "  openSUSE:      sudo zypper install go" >&2
    exit 1
fi

mkdir -p "$OUT"
cd "$SRC/hide.client.linux"
echo "Baue hide.me mit $(go version) …"
# GOTOOLCHAIN=auto: ältere Go-Versionen laden die in go.mod verlangte Toolchain selbst nach
GOTOOLCHAIN="${GOTOOLCHAIN:-auto}" CGO_ENABLED=0 GOFLAGS="${GOFLAGS:--mod=readonly}" \
    go build -trimpath -ldflags="-s -w" -o "$OUT/hide.me" .
echo "Fertig: $OUT/hide.me"
"$OUT/hide.me" 2>&1 | head -3 || true
