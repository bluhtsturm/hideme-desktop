#!/bin/bash
# Baut ein .deb-Paket (Debian, Ubuntu, Linux Mint, Pop!_OS, …) nach dist/.
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
cd "$SRC"
VERSION="$(python3 -I -c 'import sys; sys.path.insert(0, "."); from hideme_desktop import VERSION; print(VERSION)')"
ARCH="$(dpkg --print-architecture)"
[ -x build/hide.me ] || ./build.sh
STAGE="$(mktemp -d)"
chmod 0755 "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
./install.sh --package --destdir "$STAGE" --bindir /usr/bin --datadir /usr/share --unitdir /usr/lib/systemd/system
install -d "$STAGE/DEBIAN"
SIZE="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: hideme-desktop
Version: $VERSION
Architecture: $ARCH
Section: net
Priority: optional
Installed-Size: $SIZE
Depends: python3 (>= 3.9), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.2), pkexec | policykit-1, systemd
Maintainer: hide.me Desktop (inoffiziell) <root@localhost>
Homepage: https://github.com/eventure/hide.client.linux
Description: Inoffizielle Desktop-Oberfläche für den hide.me CLI VPN-Client
 GTK4/libadwaita-Oberfläche für den hide.me WireGuard-Client mit allen
 Funktionen der Kommandozeile: Serverauswahl, Kill-Switch, Split-Tunneling,
 SmartGuard-DNS-Filter, Port-Forwarding, DNS-over-HTTPS, Tray-Symbol.
 Kein offizielles Produkt der eVenture Ltd.
CTRL
cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    systemd-sysusers hideme-desktop.conf 2>/dev/null || getent group hideme >/dev/null || groupadd --system hideme
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then usermod -aG hideme "$SUDO_USER" || true; fi
    if [ -d /run/systemd/system ]; then
        systemctl daemon-reload || true
        systemctl enable --now hideme-daemon.service || true
    fi
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
fi
POST
cat > "$STAGE/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
if [ "$1" = remove ] && [ -d /run/systemd/system ]; then
    systemctl disable --now hideme-autoconnect.service hideme-daemon.service 2>/dev/null || true
fi
PRERM
cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = purge ]; then
    rm -rf /var/lib/hideme
    getent group hideme >/dev/null && groupdel hideme || true
fi
[ -d /run/systemd/system ] && systemctl daemon-reload 2>/dev/null || true
POSTRM
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
mkdir -p dist
dpkg-deb --build --root-owner-group "$STAGE" "dist/hideme-desktop_${VERSION}_${ARCH}.deb"
echo "Paket: dist/hideme-desktop_${VERSION}_${ARCH}.deb"
echo "Installieren: sudo apt install ./dist/hideme-desktop_${VERSION}_${ARCH}.deb"
