# Änderungen

## 1.0.1

Fehlerbehebungen nach einer vollständigen Durchsicht.

**Verbindung**
- Schlägt ein manueller Verbindungsversuch fehl, blieb der Daemon mit aktivem Kill-Switch im Zustand
  „routed“ zurück – das Internet war gesperrt. Jetzt wird der Ausgangszustand wiederhergestellt
  (außer bei „Nach dem Trennen weiter blockieren“).
- Trennt ein anderes Programm (z. B. `hidemectl disconnect`) die Verbindung, verbindet die App nicht mehr
  eigenmächtig neu.
- „Abbrechen“ während des Verbindungsaufbaus funktioniert: Die Verbindung wird direkt nach dem Aufbau getrennt.
- Aktionen scheitern nicht mehr mit „Daemon beschäftigt“, während der Daemon z. B. die Serverliste lädt –
  sie werden kurz wiederholt.
- „Routing entfernen“, „Routing herunterfahren“ und „Blockieren“ in den Werkzeugen lösten danach eine
  automatische Neuverbindung aus.
- Ohne Zugangstoken erscheinen nicht mehr Fehlermeldung und Anmeldedialog gleichzeitig.

**Daemon / System**
- systemd-Unit: Schreibrecht für `/run/NetworkManager` und `/run/resolvconf`. Ist `/etc/resolv.conf` dorthin
  verlinkt, scheiterte bisher jeder Verbindungsaufbau beim Setzen des DNS.
- `install.sh` startet den Daemon bei einer Aktualisierung neu und entfernt Reste älterer Versionen;
  das .deb startet ihn bei Aktualisierungen ebenfalls neu.
- `build.sh` erkennt zu alte Go-Versionen (< 1.21) und nennt die Alternative (fertiges Programm aus dem Release).

**Oberfläche**
- Kein falsches „VPN verbunden“ mehr bei jedem Start der App, keine doppelte Meldung bei Verbindungsabbruch.
- Fensterklasse unter X11 entspricht der App-ID – Xfce, MATE, Cinnamon und KDE (X11) zeigen das richtige
  Symbol in der Taskleiste.
- Das Fenster lässt sich wieder auf 360 px verkleinern (die Werkzeugleiste des Protokolls war zu breit).
- Noch nicht übernommene Eingaben in den Einstellungen werden nicht mehr von anderen Änderungen überschrieben.
- Nur noch ein Einstellungsdialog gleichzeitig; „Token erneuern“ nur mit vorhandenem Token.
- Ein weiterer Aufruf mit `--background` öffnet kein Fenster mehr.
- Beim Beenden wartet die App nicht mehr auf laufende Netzwerkaufrufe.
- Uhrzeiten mit wenigen Nachkommastellen werden auch unter Python 3.9/3.10 gelesen („Verbunden seit“).
- Eigene Abfragen verdrängen keine echten Ereignisse mehr aus dem Ereignisprotokoll.
- Die Serverliste wird beim Start aktualisiert, wenn sie älter als sechs Stunden ist.
- „Öffentliche IP“ bleibt nicht mehr dauerhaft auf „wird ermittelt …“ stehen.
- Konfigurationsimport übernimmt keine Benutzernamen/Passwörter mehr in die Daemon-Konfiguration.
- Doppelte Ausführung beim Bestätigen von Eingabefeldern verhindert.

**Entwicklung**
- `tests/run_ui_test.sh` startet den Oberflächentest mit eigener, unsichtbarer Testanzeige; der Test deckt jetzt
  auch Fehlversuche, fremdes Trennen, Abbrechen, Live-Einstellungen und die Mindestbreite des Fensters ab.

**hidemectl**
- `login`: Bei falschem Passwort bleibt das bisherige Token erhalten.
- `connect`: keine minutenlangen Wiederholungen, wenn kein Server eingestellt ist.
- `ip`: bricht nach 20 s ab statt endlos zu warten.

## 1.0.0

Erste Version.
