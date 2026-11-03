#!/bin/bash
# hide.me Desktop – Installation
#
#   sudo ./install.sh            Abhängigkeiten prüfen/installieren, hide.me bauen, alles einrichten
#   sudo ./install.sh -y         ohne Rückfragen
#   ./install.sh --package --destdir DIR [--bindir /usr/bin --datadir /usr/share --unitdir /usr/lib/systemd/system]
#                                nur Dateien ablegen (für den Paketbau), keine Systemänderungen
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PREFIX=/opt/hideme-desktop
BINDIR=/usr/local/bin
DATADIR=/usr/local/share
UNITDIR=/etc/systemd/system
POLKITDIR=/usr/share/polkit-1/actions
SYSUSERSDIR=/usr/lib/sysusers.d
DESTDIR=""
PACKAGE=0
ASSUME_YES=0
NO_DEPS=0
GROUP=hideme
APP_ID=io.github.HideMeDesktop

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift ;;
        --bindir) BINDIR="$2"; shift ;;
        --datadir) DATADIR="$2"; shift ;;
        --unitdir) UNITDIR="$2"; shift ;;
        --destdir) DESTDIR="$2"; shift ;;
        --package) PACKAGE=1 ;;
        --no-deps) NO_DEPS=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) usage ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWarnung:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }
confirm() {
    [ "$ASSUME_YES" = 1 ] && return 0
    local answer
    read -r -p "$1 [J/n] " answer || return 1
    case "${answer,,}" in ""|j|ja|y|yes) return 0 ;; *) return 1 ;; esac
}

if [ "$PACKAGE" = 0 ] && [ "$(id -u)" != 0 ]; then
    die "Bitte mit Administratorrechten ausführen: sudo $0"
fi

INVOKING_USER="${SUDO_USER:-}"
if [ -z "$INVOKING_USER" ] && [ -n "${PKEXEC_UID:-}" ]; then
    INVOKING_USER="$(getent passwd "$PKEXEC_UID" | cut -d: -f1)"
fi
[ "$INVOKING_USER" = root ] && INVOKING_USER=""

# --------------------------------------------------------------------------- Paketverwaltung
PM=""
for candidate in apt-get dnf zypper pacman; do
    if command -v "$candidate" >/dev/null 2>&1; then PM="$candidate"; break; fi
done

pm_install() {
    case "$PM" in
        apt-get) DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
        dnf) dnf install -y "$@" ;;
        zypper) zypper --non-interactive install "$@" ;;
        pacman) pacman -S --needed --noconfirm "$@" ;;
        *) return 1 ;;
    esac
}

runtime_packages() {
    case "$PM" in
        apt-get)
            local pk=pkexec
            apt-cache show pkexec >/dev/null 2>&1 || pk=policykit-1
            echo "python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 $pk" ;;
        dnf) echo "python3 python3-gobject gtk4 libadwaita polkit" ;;
        zypper) echo "python3 python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 polkit" ;;
        pacman) echo "python python-gobject gtk4 libadwaita polkit" ;;
    esac
}

go_package() {
    case "$PM" in
        apt-get) echo golang-go ;;
        dnf) echo golang ;;
        zypper) echo go ;;
        pacman) echo go ;;
    esac
}

check_runtime() {
    python3 - <<'EOF' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 2)
EOF
}

if [ "$PACKAGE" = 0 ] && [ "$NO_DEPS" = 0 ]; then
    if ! check_runtime || ! command -v pkexec >/dev/null 2>&1; then
        pkgs="$(runtime_packages || true)"
        if [ -n "$pkgs" ]; then
            info "Fehlende Laufzeitabhängigkeiten: $pkgs"
            if confirm "Jetzt mit $PM installieren?"; then
                pm_install $pkgs || die "Installation der Abhängigkeiten fehlgeschlagen"
            fi
        fi
        check_runtime || die "Python 3 mit GTK 4 und libadwaita (>= 1.2) wird benötigt."
    fi
fi

# --------------------------------------------------------------------------- hide.me bauen
BIN="$SRC/build/hide.me"
if [ ! -x "$BIN" ]; then
    if ! command -v go >/dev/null 2>&1; then
        [ "$PACKAGE" = 1 ] && die "build/hide.me fehlt – zuerst ./build.sh ausführen"
        pkg="$(go_package || true)"
        [ -n "$pkg" ] || die "Go ist nicht installiert und es wurde keine bekannte Paketverwaltung gefunden."
        info "Zum Bauen von hide.me wird Go benötigt (Paket: $pkg)."
        confirm "Go jetzt installieren?" || die "Abgebrochen – ohne Go kann hide.me nicht gebaut werden."
        pm_install "$pkg" || die "Installation von Go fehlgeschlagen"
    fi
    info "Baue hide.me aus dem mitgelieferten Quellcode …"
    if [ -n "$INVOKING_USER" ] && [ "$PACKAGE" = 0 ]; then
        # Als normaler Benutzer bauen, damit Go-Cache und Module nicht root gehören
        mkdir -p "$SRC/build" && chown "$INVOKING_USER" "$SRC/build"
        sudo -u "$INVOKING_USER" -H "$SRC/build.sh"
    else
        "$SRC/build.sh"
    fi
fi
[ -x "$BIN" ] || die "build/hide.me wurde nicht erzeugt"

# --------------------------------------------------------------------------- Dateien
D="$DESTDIR"
info "Installiere nach $D$PREFIX"
rm -rf "$D$PREFIX/hideme_desktop"  # Reste älterer Versionen entfernen
install -d -m 0755 "$D$PREFIX"/{bin,libexec,share,hideme_desktop/ui,data}
install -m 0644 "$SRC"/hideme_desktop/*.py "$D$PREFIX/hideme_desktop/"
install -m 0644 "$SRC"/hideme_desktop/ui/*.py "$SRC/hideme_desktop/ui/style.css" "$D$PREFIX/hideme_desktop/ui/"
install -m 0755 "$SRC/bin/hideme-desktop" "$SRC/bin/hidemectl" "$BIN" "$D$PREFIX/bin/"
install -m 0755 "$SRC/libexec/hideme-helper" "$D$PREFIX/libexec/"
install -m 0644 "$SRC/hide.client.linux/CA.pem" "$D$PREFIX/share/CA.pem"
install -m 0644 "$SRC/hide.client.linux/LICENSE.md" "$D$PREFIX/share/LICENSE-hide.client.linux.md"
rm -rf "$D$PREFIX/data/icons"
cp -r "$SRC/data/icons" "$D$PREFIX/data/icons"
find "$D$PREFIX/data/icons" -type d -exec chmod 0755 {} + ; find "$D$PREFIX/data/icons" -type f -exec chmod 0644 {} +

install -d -m 0755 "$D$BINDIR"
ln -sf "$PREFIX/bin/hideme-desktop" "$D$BINDIR/hideme-desktop"
ln -sf "$PREFIX/bin/hidemectl" "$D$BINDIR/hidemectl"

install -d -m 0755 "$D$DATADIR/applications" "$D$DATADIR/metainfo"
sed "s|@BINDIR@|$BINDIR|g" "$SRC/data/$APP_ID.desktop" > "$D$DATADIR/applications/$APP_ID.desktop"
chmod 0644 "$D$DATADIR/applications/$APP_ID.desktop"
install -m 0644 "$SRC/data/$APP_ID.metainfo.xml" "$D$DATADIR/metainfo/"
(cd "$SRC/data/icons" && find hicolor -type f -name '*.svg') | while read -r icon; do
    install -D -m 0644 "$SRC/data/icons/$icon" "$D$DATADIR/icons/$icon"
done

install -d -m 0755 "$D$POLKITDIR" "$D$UNITDIR" "$D$SYSUSERSDIR"
sed "s|@PREFIX@|$PREFIX|g" "$SRC/data/$APP_ID.policy" > "$D$POLKITDIR/$APP_ID.policy"
for unit in hideme-daemon.service hideme-autoconnect.service; do
    sed "s|@PREFIX@|$PREFIX|g" "$SRC/data/systemd/$unit" > "$D$UNITDIR/$unit"
done
chmod 0644 "$D$POLKITDIR/$APP_ID.policy" "$D$UNITDIR"/hideme-*.service
echo "g $GROUP - -" > "$D$SYSUSERSDIR/hideme-desktop.conf"
chmod 0644 "$D$SYSUSERSDIR/hideme-desktop.conf"

if [ "$PACKAGE" = 1 ]; then
    info "Dateien für den Paketbau unter $DESTDIR abgelegt."
    exit 0
fi

# --------------------------------------------------------------------------- System einrichten
if ! getent group "$GROUP" >/dev/null; then
    info "Lege Systemgruppe '$GROUP' an"
    groupadd --system "$GROUP"
fi
if [ -n "$INVOKING_USER" ]; then
    if ! id -nG "$INVOKING_USER" | tr ' ' '\n' | grep -qx "$GROUP"; then
        info "Füge $INVOKING_USER der Gruppe '$GROUP' hinzu (Steuerung des VPN ohne Root-Rechte)"
        usermod -aG "$GROUP" "$INVOKING_USER"
    fi
else
    warn "Füge Benutzer, die das VPN steuern dürfen, der Gruppe '$GROUP' hinzu: usermod -aG $GROUP BENUTZER"
fi

# Vorhandenes Zugangstoken einer bisherigen hide.me-CLI-Installation übernehmen
install -d -m 0700 /var/lib/hideme
if [ ! -e /var/lib/hideme/config.json ]; then
    for tok in /opt/hide.me/accessToken.txt /etc/hide.me/accessToken.txt; do
        if [ -s "$tok" ]; then
            info "Übernehme vorhandenes Zugangstoken aus $tok"
            (umask 077
             python3 -c 'import json,sys; print(json.dumps({"Rest": {"AccessToken": open(sys.argv[1]).read().strip()}}))' \
                 "$tok" > /var/lib/hideme/config.json)
            break
        fi
    done
fi

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    running="$(systemctl list-units --plain --no-legend --state=active 'hide.me@*' 2>/dev/null | awk '{print $1}')"
    if [ -n "$running" ]; then
        warn "Es laufen bereits Verbindungen der hide.me-CLI: $running"
        warn "Diese nutzen dieselbe Schnittstelle 'vpn'. Bitte beenden: systemctl disable --now $running"
    fi
    systemctl daemon-reload
    systemctl enable hideme-daemon.service
    if systemctl is-active --quiet hideme-daemon.service; then
        # Aktualisierung: neue Programmversion laden. Eine bestehende VPN-Verbindung wird dabei
        # getrennt; die App verbindet automatisch neu, wenn sie verbunden war.
        info "Starte den hide.me-Daemon neu (hideme-daemon.service)"
        systemctl restart hideme-daemon.service || warn "Neustart fehlgeschlagen: journalctl -u hideme-daemon"
    else
        info "Starte den hide.me-Daemon (hideme-daemon.service)"
        systemctl start hideme-daemon.service || warn "Der Daemon konnte nicht gestartet werden: journalctl -u hideme-daemon"
    fi
else
    warn "systemd wurde nicht gefunden. Den Daemon bitte selbst als root starten:"
    warn "  cd /var/lib/hideme && $PREFIX/bin/hide.me --caddr /run/hideme/hide.me.sock -c /var/lib/hideme/config.json service"
fi

command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "$DATADIR/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATADIR/applications" 2>/dev/null || true

echo
info "hide.me Desktop ist installiert."
echo "    Starten:   „hide.me VPN“ im Anwendungsmenü oder 'hideme-desktop'"
echo "    Kommandozeile: hidemectl status | connect nl | disconnect"
if [ -n "$INVOKING_USER" ]; then
    echo "    Hinweis: Die Gruppenmitgliedschaft gilt nach dem nächsten Anmelden; bis dahin startet"
    echo "    hideme-desktop sich automatisch mit den passenden Rechten (über 'sg')."
fi
# sudo setzt XDG_CURRENT_DESKTOP meist zurück – daher auf installierte GNOME Shell prüfen
if command -v gnome-shell >/dev/null 2>&1; then
    echo "    GNOME: Für das Tray-Symbol wird die Erweiterung „AppIndicator and KStatusNotifierItem Support“ benötigt."
fi
