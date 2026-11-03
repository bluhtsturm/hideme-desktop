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

# Ab Go 1.21 lädt "go" die in go.mod verlangte Version (1.24) selbst nach; ältere können das nicht
GOVER="$(go env GOVERSION 2>/dev/null || go version | awk '{print $3}')"
GOMINOR="$(sed -E 's/^go1\.([0-9]+).*/\1/' <<<"$GOVER")"
if ! [[ "$GOMINOR" =~ ^[0-9]+$ ]] || [ "$GOMINOR" -lt 21 ]; then
    echo "Fehler: $GOVER ist zu alt (benötigt wird Go 1.21 oder neuer)." >&2
    echo "  Alternative ohne Go: das fertige Programm hide.me-0.9.14-linux-amd64 von" >&2
    echo "  https://github.com/bluhtsturm/hideme-desktop/releases als build/hide.me ablegen." >&2
    exit 1
fi

mkdir -p "$OUT"
cd "$SRC/hide.client.linux"
echo "Baue hide.me mit $GOVER …"
# GOTOOLCHAIN=auto: ältere Go-Versionen laden die in go.mod verlangte Toolchain selbst nach
GOTOOLCHAIN="${GOTOOLCHAIN:-auto}" CGO_ENABLED=0 GOFLAGS="${GOFLAGS:--mod=readonly}" \
    go build -trimpath -ldflags="-s -w" -o "$OUT/hide.me" .
"$OUT/hide.me" conf >/dev/null  # Kurztest: gibt die Standardkonfiguration aus
echo "Fertig: $OUT/hide.me"
