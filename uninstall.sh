#!/bin/bash
# hide.me Desktop – Deinstallation
#   sudo ./uninstall.sh           entfernt Programm, Dienste und Menüeintrag (Konfiguration bleibt erhalten)
#   sudo ./uninstall.sh --purge   entfernt zusätzlich /var/lib/hideme (Zugangstoken!) und die Gruppe "hideme"
set -euo pipefail
PREFIX=/opt/hideme-desktop
BINDIR=/usr/local/bin
DATADIR=/usr/local/share
UNITDIR=/etc/systemd/system
APP_ID=io.github.HideMeDesktop
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1
[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo ausführen: sudo $0" >&2; exit 1; }

if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now hideme-autoconnect.service 2>/dev/null || true
    systemctl disable --now hideme-daemon.service 2>/dev/null || true
fi
rm -f "$UNITDIR/hideme-daemon.service" "$UNITDIR/hideme-autoconnect.service"
command -v systemctl >/dev/null 2>&1 && systemctl daemon-reload 2>/dev/null || true

rm -f "$BINDIR/hideme-desktop" "$BINDIR/hidemectl"
rm -f "$DATADIR/applications/$APP_ID.desktop" "$DATADIR/metainfo/$APP_ID.metainfo.xml"
find "$DATADIR/icons/hicolor" \( -name "$APP_ID*.svg" -o -name 'hideme-*-symbolic.svg' \) -delete 2>/dev/null || true
rm -f "/usr/share/polkit-1/actions/$APP_ID.policy" /usr/lib/sysusers.d/hideme-desktop.conf
rm -rf "$PREFIX"
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "$DATADIR/icons/hicolor" 2>/dev/null || true

if [ "$PURGE" = 1 ]; then
    rm -rf /var/lib/hideme
    getent group hideme >/dev/null && groupdel hideme || true
    echo "Konfiguration, Zugangstoken und Gruppe entfernt."
else
    echo "Konfiguration und Zugangstoken bleiben in /var/lib/hideme erhalten (entfernen mit --purge)."
fi
echo "Eigene Einstellungen der App liegen unter ~/.config/hideme-desktop und können gelöscht werden."
echo "hide.me Desktop wurde entfernt."
