# hide.me Desktop

Inoffizielle grafische Oberfläche für den quelloffenen
[hide.me CLI VPN-Client](https://github.com/eventure/hide.client.linux) (WireGuard) –
für alle gängigen Linux-Desktops: GNOME, KDE Plasma, Xfce, Cinnamon, MATE, Budgie, LXQt.

> Kein offizielles Produkt der eVenture Ltd. Der VPN-Client selbst ist der unveränderte
> hide.me-CLI-Quellcode (Version 0.9.14) im Ordner `hide.client.linux/`.

## So funktioniert es

```
┌──────────────────────────┐   HTTP über UNIX-Socket    ┌───────────────────────────────┐
│ hide.me VPN (GTK4-App)   │ ─────────────────────────▶ │ hideme-daemon.service (root)  │
│ läuft als dein Benutzer  │  /run/hideme/hide.me.sock  │ = hide.me CLI im Service-Modus│
│ + Tray-Symbol, hidemectl │ ◀───────────────────────── │   WireGuard, Routing, DNS     │
└──────────────────────────┘     Ereignisstrom /watch   └───────────────────────────────┘
```

- Der hide.me-Client braucht Root-Rechte (WireGuard-Schnittstelle, Routing, `/etc/resolv.conf`).
  Er läuft deshalb als systemd-Dienst im **Service-Modus** und wird über dessen REST-Schnittstelle
  gesteuert (`serviceScripts/api.md`).
- Die App selbst läuft **ohne Root-Rechte**. Den Steuer-Socket dürfen nur Mitglieder der Gruppe
  `hideme` benutzen (Rechte `root:hideme 0770`).
- Die VPN-Verbindung hält der Daemon – das Fenster oder sogar die ganze App kann geschlossen
  werden, ohne dass die Verbindung abbricht.

## Installation

Fertige Dateien gibt es unter [Releases](https://github.com/bluhtsturm/hideme-desktop/releases/latest):

- `hideme-desktop_<Version>_amd64.deb` – Paket für Debian, Ubuntu, Linux Mint, Pop!_OS & Co.
- `hideme-desktop-<Version>-1.x86_64.rpm` – Paket für Fedora, openSUSE und RHEL-Derivate
- `hide.me-0.9.14-linux-amd64` – das hide.me-Programm (statisch gelinkt, aus dem mitgelieferten Quellcode gebaut)

Debian/Ubuntu-basierte Systeme:

```bash
sudo apt install ./hideme-desktop_*_amd64.deb
```

Fedora bzw. openSUSE:

```bash
sudo dnf install ./hideme-desktop-*.x86_64.rpm
```

```bash
sudo zypper install ./hideme-desktop-*.x86_64.rpm
```

Danach einmal ab- und wieder anmelden (oder `sudo usermod -aG hideme $USER`, falls die Paketinstallation
den Benutzer nicht erkennen konnte), damit die App den Daemon steuern darf.

Alle anderen Distributionen (oder ohne Paket):

```bash
git clone https://github.com/bluhtsturm/hideme-desktop.git
cd hideme-desktop
sudo ./install.sh
```

Wer Go nicht installieren möchte, legt das hide.me-Programm aus dem Release vorher als `build/hide.me`
ab (`mkdir -p build && cp hide.me-0.9.14-linux-amd64 build/hide.me && chmod +x build/hide.me`).

Das Skript

1. prüft die Abhängigkeiten (Python 3, PyGObject, GTK 4, libadwaita ≥ 1.2, polkit) und installiert
   fehlende Pakete nach Rückfrage über `apt`, `dnf`, `zypper` oder `pacman`,
2. baut `hide.me` aus dem mitgelieferten Quellcode (installiert Go bei Bedarf nach Rückfrage),
3. installiert alles nach `/opt/hideme-desktop`, legt Menüeintrag, Icons und polkit-Regel an,
4. legt die Gruppe `hideme` an und fügt dich hinzu,
5. übernimmt ein vorhandenes Zugangstoken einer bisherigen CLI-Installation (`/opt/hide.me/accessToken.txt`),
6. startet `hideme-daemon.service`.

Danach **„hide.me VPN“** im Anwendungsmenü starten. Beim ersten Start meldest du dich mit deinem
hide.me-Konto an – Benutzername und Passwort werden nur zum Abrufen des Zugangstokens verwendet und
nicht gespeichert.

Die Gruppenmitgliedschaft gilt erst nach dem nächsten Anmelden; bis dahin startet sich die App
automatisch über `sg hideme` mit den passenden Rechten.

**Tray-Symbol unter GNOME:** benötigt die Erweiterung
*AppIndicator and KStatusNotifierItem Support* (bei Ubuntu vorinstalliert). Alle anderen Desktops
unterstützen das Tray-Protokoll direkt.

### Pakete statt install.sh

| Distribution | Befehl | Ergebnis |
|---|---|---|
| Debian, Ubuntu, Mint, Pop!_OS | `packaging/debian/build-deb.sh` | `dist/hideme-desktop_<Version>_amd64.deb` |
| Fedora, openSUSE | `packaging/rpm/build-rpm.sh` | `dist/hideme-desktop-<Version>-1.*.rpm` |
| Arch, Manjaro, EndeavourOS | `cd packaging/arch && makepkg -si` | Paket wird direkt installiert |

Nur das Programm bauen: `./build.sh` (Go ≥ 1.21; die in `go.mod` verlangte Toolchain 1.24 wird
automatisch nachgeladen).

### Deinstallation

```bash
sudo ./uninstall.sh            # Konfiguration und Token bleiben in /var/lib/hideme
sudo ./uninstall.sh --purge    # entfernt auch Token, Konfiguration und die Gruppe
```

## Funktionen

Alle Befehle und Optionen der hide.me-CLI sind in der App erreichbar:

| hide.me CLI | in der App |
|---|---|
| `token` | Anmelden (Menü › Konto) – auch Token erneuern und Abmelden; `@pf`-Token per Schalter |
| `connect HOST` | Status › Verbinden, Server-Liste, Favoriten, Tray-Menü, eigener Server (Name, Kurzname, IP) |
| `list [free]` | Seite **Server**: Suche, Favoriten, Filter „Nur kostenlose“, 10-Gbit/s-Kennzeichnung |
| `categories` | **SmartGuard › Kategorien** (Liste wird vom hide.me-Server geladen) |
| `conf` / `jsonconf` / `-c` | Werkzeuge › Konfiguration exportieren (YAML/JSON) und importieren |
| `updateDoh` | Einstellungen › DNS › DoH-Serverliste aktualisieren |
| `resolve` / `lookup` | Werkzeuge › DNS-Test (DoH und klassisch) |
| `service` | läuft als `hideme-daemon.service` |
| `-k, --kill-switch` | Status › Schutz und Einstellungen › Verbindung |
| `-s, --split-tunnel` | Einstellungen › Verbindung › Split-Tunneling (Netzliste mit Prüfung) |
| `-4` / `-6` | Einstellungen › Verbindung › IP-Protokolle |
| `--pf` | Status › Schutz › Port-Forwarding |
| `--dpd`, `--rest-timeout`, `ReconnectWait` | Einstellungen › Verbindung › Verbindungsüberwachung |
| `--doh`, `--dns` | Einstellungen › DNS |
| `-b, --resolv-conf-bak` | Einstellungen › DNS › System-DNS |
| `--noAds --noTrackers --noMalware --noMalicious --safeSearch --forceDns` | Seite **SmartGuard** |
| `--pg`, `--noRisk`, `--noIllegal`, `--noCategories` | Seite **SmartGuard** |
| `--whitelist`, `--blacklist` | Seite **SmartGuard** › Eigene Listen |
| `-i -l -m -r -R`, `PrivateKey` | Einstellungen › Erweitert › WireGuard und Routing |
| `-p`, `--ca`, `-t`, `AccessTokenUpdateDelay` | Einstellungen › Erweitert / Konto |
| `--caddr`, `--ccert`, `--ckey` | Einstellungen › Erweitert › Verbindung zum Daemon (Socket, `@abstrakt`, `host:port`, `https://`) |
| systemd `hide.me@SERVER` | Einstellungen › Allgemein › Beim Systemstart verbinden |

Dazu kommt, was die REST-Schnittstelle zusätzlich bietet: Live-Status mit Datenrate und
Verbindungsdauer, öffentliche IPv4/IPv6, Ereignisprotokoll, Daemon-Log, `route`/`destroy`/`shutdown`.

Weitere Komfortfunktionen: Tray-Symbol mit Menü (Verbinden/Trennen, Server wechseln, Kill-Switch),
Benachrichtigungen, Autostart, automatische Verbindung beim Start, automatische Neuverbindung mit
Backoff, Option „Nach dem Trennen weiter blockieren“, Hinweis bei Änderungen, die erst nach einer
Neuverbindung wirken, Tastenkürzel (Strg+Eingabe verbinden/trennen, Alt+1…4 Seiten, Strg+F Serversuche).

### Kommandozeile

```bash
hideme-desktop --connect=nl      # verbinden (leer = letzter Server), --disconnect, --toggle, --background
hidemectl status                 # Zustand ohne Oberfläche
hidemectl connect amsterdam
hidemectl servers --free
hidemectl config '{"WireGuard":{"LeakProtection":true}}'
```

### Bekannte Fehler der CLI 0.9.14 und wie die App damit umgeht

- **`/serverList` beschädigt die Daemon-Konfiguration:** Der Abruf überschreibt dauerhaft Host, Port, CA und
  API-Version der hide.me-Schnittstelle; danach scheitern Anmeldung und Verbindung mit
  „tls: no application protocol“. Die App lädt die Serverliste deshalb direkt von api.hide.me und repariert eine
  so beschädigte Konfiguration automatisch.
- **IP-Abfrage bei bestehender Verbindung:** Der Daemon fragt dafür fest eingestellte DNS-Server, die durch den Tunnel nicht
  antworten (außerhalb des Tunnels schon). Die App ermittelt die öffentliche IP bei bestehender Verbindung selbst durch den Tunnel.
- **`hide.me categories` scheitert mit „bad public key PIN“:** Der hide.me-Server verwendet inzwischen ein
  Zertifikat der Zwischenstelle *DigiCert Global G2 TLS RSA SHA256 2020 CA1*, die CLI pinnt noch die
  ältere *DigiCert TLS RSA SHA256 2020 CA1*. Die App lädt die Kategorienliste deshalb direkt per HTTPS
  mit regulärer Zertifikatsprüfung (`*.hideservers.net`, eVenture Limited) und nutzt die CLI nur als
  Rückfall. Verbindungsaufbau und Token-Anfragen sind nicht betroffen – sie laufen über Port 432 mit
  der eigenen hide.me-CA (`CA.pem`).

## Sicherheit

- Zugangstoken und Konfiguration liegen in `/var/lib/hideme/config.json` (nur root lesbar, 0600).
- Den Daemon steuern darf nur, wer in der Gruppe `hideme` ist. Achtung: Wer den Socket benutzen darf,
  kann auch das Token auslesen – nimm nur vertrauenswürdige Benutzer in die Gruppe auf.
- Die systemd-Unit übernimmt die Härtung der Original-Unit (`ProtectSystem=strict`, `ProtectHome`,
  `NoNewPrivileges`, Systemaufruf-Filter …).
- Root-Aktionen der App laufen ausschließlich über polkit (`systemctl` bzw. `pkexec hideme-helper`
  mit festen Befehlen).

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| „Daemon nicht erreichbar“ | `systemctl status hideme-daemon` · `journalctl -u hideme-daemon -e` |
| „Keine Berechtigung“ | `sudo usermod -aG hideme $USER`, danach ab- und wieder anmelden |
| Internet nach dem Trennen gesperrt | Der Kill-Switch blockiert absichtlich. „Blockierung aufheben“ klicken oder `hidemectl destroy` |
| Kein Tray-Symbol unter GNOME | Erweiterung „AppIndicator and KStatusNotifierItem Support“ aktivieren |
| Alte CLI-Verbindung läuft noch | `sudo systemctl disable --now 'hide.me@*'` (nutzt dieselbe Schnittstelle `vpn`) |

## Entwicklung

```bash
python3 -I tests/test_api.py                    # API-Client und Hilfsfunktionen gegen einen simulierten Daemon
tests/run_ui_test.sh                            # Oberflächentest (unsichtbare Broadway-Anzeige, ca. 1 Minute)
python3 -I tests/test_real_binary.py build/hide.me   # gegen das echte hide.me-Programm, ohne Root
python3 tests/mock_daemon.py /run/user/$UID/hm-mock.sock   # simulierter Daemon zum Ausprobieren
```

Struktur: `hideme_desktop/api.py` (REST-Client), `controller.py` (Zustand, Aktionen, Ereignisse),
`tray.py` (StatusNotifierItem + DBusMenu), `ui/` (Seiten und Dialoge), `ctl.py` (`hidemectl`),
`libexec/hideme-helper` (Root-Helfer), `data/` (Units, Desktop-Datei, Icons, polkit).

Lizenz: GPL-2.0 (siehe `LICENSE`) – wie der enthaltene hide.me-Client (`hide.client.linux/`).
