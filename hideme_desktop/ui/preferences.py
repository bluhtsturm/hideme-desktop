"""Einstellungsdialog: App-Verhalten und sämtliche Optionen des hide.me-Clients."""

from gi.repository import Adw, GLib, Gtk

from .. import AUTOCONNECT_UNIT, system
from .. import config as C
from .compat import (ComboRow, EntryRow, SpinRow, SwitchRow, alert, button_row, info_row,
                     preferences_container, toast)
from .widgets import ListEditor

NS = C.NS


class Preferences:
    def __init__(self, window, controller):
        self.window = window
        self.ctl = controller
        self.settings = controller.settings
        self._binders = []
        self.dialog = preferences_container(window, "Einstellungen")
        self.pages = {}

        self._page_general()
        self._page_connection()
        self._page_dns()
        self._page_account()
        self._page_advanced()

        self._h1 = controller.connect("config-changed", lambda *_a: self._load())
        self._h2 = controller.connect("changed", lambda *_a: self._update_account())
        self.dialog.connect("closed" if hasattr(Adw, "PreferencesDialog") else "destroy", self._on_destroy)
        self._load()

    def _on_destroy(self, *_a):
        for h in (self._h1, self._h2):
            try:
                self.ctl.disconnect(h)
            except TypeError:
                pass

    def present(self, page=None):
        if page and page in self.pages:
            self.dialog.set_visible_page(self.pages[page])
        if hasattr(Adw, "PreferencesDialog") and isinstance(self.dialog, Adw.PreferencesDialog):
            self.dialog.present(self.window)
        else:
            self.dialog.present()

    def _toast(self, text):
        toast(self.dialog, text)

    def _add_page(self, key, title, icon):
        page = Adw.PreferencesPage(title=title, icon_name=icon)
        self.dialog.add(page)
        self.pages[key] = page
        return page

    def _bind(self, func):
        self._binders.append(func)

    def _load(self):
        cfg = self.ctl.config
        for func in self._binders:
            func(cfg)
        self._update_account()

    def _set(self, section, key, value):
        patch = {section: {key: value}}
        if section == "WireGuard" and key == "Mark":
            patch["Rest"] = {"Mark": value}
        self.ctl.update_config(patch)

    # Hilfen für an die Daemon-Konfiguration gebundene Zeilen ------------------------
    def _switch(self, group, title, subtitle, section, key, confirm_off=None):
        sw = SwitchRow(title, subtitle)

        def toggled(value):
            if confirm_off and not value:
                def resp(rid):
                    if rid == "ok":
                        self._set(section, key, False)
                    else:
                        sw.set_active(True)
                alert(self.dialog if hasattr(Adw, "AlertDialog") else self.window, confirm_off[0], confirm_off[1],
                      [("cancel", "Abbrechen"), ("ok", "Trotzdem deaktivieren")], resp, default="cancel",
                      destructive="ok")
                return
            self._set(section, key, value)
        sw.on_toggle = toggled
        group.add(sw.widget)
        self._bind(lambda cfg: sw.set_active(C.get(cfg, section, key)))
        self._bind(lambda cfg: sw.set_sensitive(cfg is not None))
        return sw

    def _spin(self, group, title, subtitle, section, key, lower, upper, scale=1, step=1):
        spin = SpinRow(title, subtitle, lower, upper, step, lower,
                       on_change=lambda v: self._set(section, key, int(v * scale)))
        group.add(spin.widget)
        self._bind(lambda cfg: spin.set_value((C.get(cfg, section, key) or 0) / scale))
        self._bind(lambda cfg: spin.widget.set_sensitive(cfg is not None))
        return spin

    def _entry(self, group, title, section, key, password=False, placeholder=""):
        entry = EntryRow(title, password=password, placeholder=placeholder,
                         on_apply=lambda t: self._set(section, key, t.strip()))
        group.add(entry.widget)
        self._bind(lambda cfg: entry.set_text(str(C.get(cfg, section, key) or "")))
        self._bind(lambda cfg: entry.widget.set_sensitive(cfg is not None))
        return entry

    def _app_switch(self, group, title, subtitle, key, on_toggle=None):
        def toggled(value):
            self.settings[key] = value
            if on_toggle:
                on_toggle(value)
        sw = SwitchRow(title, subtitle, active=self.settings[key], on_toggle=toggled)
        group.add(sw.widget)
        return sw

    # ------------------------------------------------------------------ Allgemein
    def _page_general(self):
        page = self._add_page("general", "Allgemein", "preferences-system-symbolic")

        start = Adw.PreferencesGroup(title="Start")
        self.sw_autostart = SwitchRow("Bei der Anmeldung starten", "Startet die App mit der Desktop-Sitzung",
                                      active=system.autostart_enabled(), on_toggle=self._toggle_autostart)
        start.add(self.sw_autostart.widget)
        self._app_switch(start, "Im Hintergrund starten",
                         "Beim Autostart nur das Tray-Symbol zeigen, kein Fenster", "start_hidden")
        self._app_switch(start, "Beim Start automatisch verbinden", "Verbindet, sobald die App gestartet wurde",
                         "autoconnect")
        options = [("last", "Zuletzt verwendeter Server")] + [(h, h) for h in self.settings["favorites"]]
        if self.settings["autoconnect_server"] not in [o[0] for o in options]:
            options.append((self.settings["autoconnect_server"], self.settings["autoconnect_server"]))
        self.autoconnect_server = ComboRow("Server für automatische Verbindung", options,
                                           on_select=lambda v: self.settings.__setitem__("autoconnect_server", v))
        self.autoconnect_server.set_value(self.settings["autoconnect_server"])
        start.add(self.autoconnect_server.widget)
        page.add(start)

        boot = Adw.PreferencesGroup(
            title="Systemstart",
            description="Verbindet bereits beim Hochfahren – auch bevor sich jemand anmeldet. Verwendet den "
                        "zuletzt eingestellten Server des Daemons. Das Ändern erfordert Administratorrechte.")
        self.sw_boot = SwitchRow("Beim Systemstart verbinden", f"systemd-Unit {AUTOCONNECT_UNIT}",
                                 on_toggle=self._toggle_boot)
        self.sw_boot.set_sensitive(False)
        boot.add(self.sw_boot.widget)
        page.add(boot)
        self.ctl.run_bg(system.boot_autoconnect_enabled, self._boot_state, lambda e: None)

        behaviour = Adw.PreferencesGroup(title="Verhalten")
        self._app_switch(behaviour, "Im Hintergrund weiterlaufen",
                         "Beim Schließen des Fensters läuft die App im Tray weiter. Die VPN-Verbindung bleibt "
                         "in jedem Fall bestehen, da sie vom Daemon gehalten wird.", "run_in_background")
        self._app_switch(behaviour, "Tray-Symbol anzeigen",
                         "Benötigt unter GNOME die Erweiterung „AppIndicator and KStatusNotifierItem Support“",
                         "show_tray")
        self._app_switch(behaviour, "Benachrichtigungen", "Bei Verbindungsaufbau, -abbruch und Fehlern",
                         "notifications")
        self._app_switch(behaviour, "Automatisch neu verbinden",
                         "Nach einem Verbindungsabbruch selbstständig erneut verbinden", "auto_reconnect")
        page.add(behaviour)

    def _toggle_autostart(self, value):
        try:
            system.set_autostart(value)
        except OSError as e:
            self._toast(f"Autostart konnte nicht geändert werden: {e}")
            self.sw_autostart.set_active(not value)

    def _boot_state(self, enabled):
        self.sw_boot.set_active(enabled)
        self.sw_boot.set_sensitive(True)

    def _toggle_boot(self, value):
        self.sw_boot.set_sensitive(False)
        if value and self.ctl.current_host:
            self.ctl.update_config({"Rest": {"Host": C.fqdn(self.ctl.current_host)}}, quiet=True)

        def done(_r):
            self._toast("Verbindung beim Systemstart " + ("aktiviert" if value else "deaktiviert"))
            self.ctl.run_bg(system.boot_autoconnect_enabled, self._boot_state, lambda e: None)

        def failed(exc):
            self._toast(f"Fehlgeschlagen: {exc}")
            self.ctl.run_bg(system.boot_autoconnect_enabled, self._boot_state, lambda e: None)
        self.ctl.run_bg(lambda: system.set_boot_autoconnect(value), done, failed)

    # ------------------------------------------------------------------ Verbindung
    def _page_connection(self):
        page = self._add_page("connection", "Verbindung", "network-vpn-symbolic")

        sec = Adw.PreferencesGroup(title="Sicherheit")
        self._switch(sec, "Kill-Switch (Leckschutz)",
                     "Leitet sämtlichen Verkehr über eine eigene Routing-Tabelle und verwirft ihn, solange kein "
                     "Tunnel besteht (--kill-switch)", "WireGuard", "LeakProtection",
                     confirm_off=("Kill-Switch deaktivieren?",
                                  "Bei Verbindungsabbrüchen kann ungeschützter Verkehr dein Gerät verlassen."))
        self._app_switch(sec, "Nach dem Trennen weiter blockieren",
                         "Beim manuellen Trennen bleibt der Kill-Switch aktiv – das Internet ist dann gesperrt, "
                         "bis du erneut verbindest oder die Blockierung aufhebst", "block_after_disconnect")

        self.ip_mode = ComboRow("IP-Protokolle", [("both", "IPv4 und IPv6 (empfohlen)"), ("v4", "Nur IPv4 (-4)"),
                                                  ("v6", "Nur IPv6 (-6)")],
                                subtitle="Bei „nur IPv4/IPv6“ bleibt das jeweils andere Protokoll ungeschützt",
                                on_select=self._set_ip_mode)
        sec.add(self.ip_mode.widget)

        def load_ip(cfg):
            v4, v6 = C.get(cfg, "WireGuard", "IPv4"), C.get(cfg, "WireGuard", "IPv6")
            self.ip_mode.set_value("v4" if v4 and not v6 else "v6" if v6 and not v4 else "both")
            self.ip_mode.widget.set_sensitive(cfg is not None)
        self._bind(load_ip)
        page.add(sec)

        split = Adw.PreferencesGroup(
            title="Split-Tunneling",
            description="Netze (CIDR), deren Verkehr am VPN vorbei direkt geleitet wird – z. B. das lokale Netz "
                        "192.168.0.0/16 (--split-tunnel)")
        self.split = ListEditor("Netze ausnehmen", "", validator=C.valid_cidr, placeholder="192.168.0.0/16",
                                error_text="Bitte ein Netz in CIDR-Schreibweise angeben, z. B. 10.0.0.0/8",
                                add_title="Netz hinzufügen", empty_text="Keine – sämtlicher Verkehr läuft durch den Tunnel",
                                on_change=lambda items: self._set("WireGuard", "SplitTunnel", ",".join(items)))
        split.add(self.split.widget)
        self._bind(lambda cfg: self.split.set_items(
            [s for s in (C.get(cfg, "WireGuard", "SplitTunnel") or "").split(",") if s]))
        page.add(split)

        pf = Adw.PreferencesGroup(title="Port-Forwarding",
                                  description="Alternativ kann ein Token mit „@pf“-Benutzernamen angefordert werden; "
                                              "dann diese Option nicht zusätzlich aktivieren.")
        pf_sw = SwitchRow("Dynamisches Port-Forwarding", "UPnP und NAT-PMP über den VPN-Server (--pf)",
                          on_toggle=lambda v: self.ctl.update_config({"Rest": {"PortForward": {"enabled": v}}}))
        pf.add(pf_sw.widget)
        self._bind(lambda cfg: pf_sw.set_active(bool((C.get(cfg, "Rest", "PortForward") or {}).get("enabled"))))
        page.add(pf)

        mon = Adw.PreferencesGroup(title="Verbindungsüberwachung")
        self._spin(mon, "DPD-Timeout (Sekunden)",
                   "Intervall der Dead-Peer-Erkennung, höchstens 60 s (--dpd)", "WireGuard", "DpdTimeout",
                   1, 60, scale=NS)
        self._spin(mon, "Wartezeit vor Neuverbindung (Sekunden)",
                   "Nach einem Verbindungsverlust (nur per Konfigurationsdatei: ReconnectWait)",
                   "Rest", "ReconnectWait", 1, 3600, scale=NS)
        self._spin(mon, "REST-Timeout (Sekunden)", "Zeitlimit für Token- und Verbindungsanfragen (--rest-timeout)",
                   "Rest", "RestTimeout", 5, 600, scale=NS)
        page.add(mon)

    def _set_ip_mode(self, mode):
        v4, v6 = {"both": (True, True), "v4": (True, False), "v6": (False, True)}[mode]
        self.ctl.update_config({"WireGuard": {"IPv4": v4, "IPv6": v6}})

    # ------------------------------------------------------------------ DNS
    def _page_dns(self):
        page = self._add_page("dns", "DNS", "network-server-symbolic")

        res = Adw.PreferencesGroup(
            title="Namensauflösung der VPN-Server",
            description="Wie der Client die Adressen der hide.me-Server ermittelt. Im Tunnel verwendet das "
                        "System die DNS-Server des VPN.")
        self._switch(res, "DNS-over-HTTPS verwenden", "Auflösung verschlüsselt über DoH, mit Rückfall auf "
                     "klassisches DNS (--doh)", "Rest", "UseDoH")
        self.plain = ListEditor("Klassische DNS-Server", "Rückfall-Server im Format IP:Port (--dns)",
                                validator=C.valid_hostport, placeholder="209.250.251.37:53",
                                error_text="Format: IP:Port, z. B. 1.1.1.1:53 oder [2606:4700::1111]:53",
                                add_title="DNS-Server hinzufügen",
                                on_change=lambda items: self._set("Plain", "Servers", items))
        res.add(self.plain.widget)
        self._bind(lambda cfg: self.plain.set_items(C.get(cfg, "Plain", "Servers") or []))
        page.add(res)

        doh = Adw.PreferencesGroup(title="DNS-over-HTTPS-Server")
        upd = button_row("DoH-Serverliste aktualisieren",
                         "Lädt über 100 öffentliche DoH-Server in die Datei resolvers.txt (updateDoh). "
                         "Erfordert Administratorrechte.", "Aktualisieren", self._update_doh)
        self.doh_btn = upd.button
        doh.add(upd)
        self.doh_servers = ListEditor("Zusätzliche DoH-Server", "DNS-Stamps (sdns://…)",
                                      validator=lambda s: s.startswith("sdns://"), placeholder="sdns://…",
                                      error_text="DNS-Stamps beginnen mit sdns://", add_title="DNS-Stamp hinzufügen",
                                      empty_text="Eingebaute Standardserver (Quad9)",
                                      on_change=lambda items: self._set("DoH", "servers", items))
        doh.add(self.doh_servers.widget)
        self._bind(lambda cfg: self.doh_servers.set_items(((cfg or {}).get("DoH") or {}).get("servers") or []))
        self.doh_urls = ListEditor("Update-Quellen", "Listen, aus denen updateDoh Server bezieht",
                                   validator=lambda s: s.startswith("https://"), placeholder="https://…",
                                   error_text="Bitte eine https://-Adresse angeben", add_title="Quelle hinzufügen",
                                   on_change=lambda items: self._set("DoH", "updateURLs", items))
        doh.add(self.doh_urls.widget)
        self._bind(lambda cfg: self.doh_urls.set_items(((cfg or {}).get("DoH") or {}).get("updateURLs") or []))
        self._entry(doh, "Datei mit DoH-Servern (relativ zum Daemon-Verzeichnis)", "DoH", "filename")
        page.add(doh)

        sysdns = Adw.PreferencesGroup(
            title="System-DNS",
            description="Während der Verbindung schreibt der Client die DNS-Server des VPN nach /etc/resolv.conf "
                        "und stellt die alte Datei danach wieder her.")
        self._entry(sysdns, "Zusätzliche Sicherung von resolv.conf (Dateipfad, -b)", "WireGuard",
                    "ResolvConfBackupFile", placeholder="leer = nur im Speicher")
        page.add(sysdns)

    def _update_doh(self):
        self.doh_btn.set_sensitive(False)

        def done(out):
            self.doh_btn.set_sensitive(True)
            self._toast("DoH-Serverliste aktualisiert")
            self.ctl._dirty = True

        def failed(exc):
            self.doh_btn.set_sensitive(True)
            self._toast(f"Aktualisierung fehlgeschlagen: {exc}")
        self.ctl.run_bg(lambda: system.run_helper("update-doh"), done, failed)

    # ------------------------------------------------------------------ Konto
    def _page_account(self):
        page = self._add_page("account", "Konto", "avatar-default-symbolic")
        acc = Adw.PreferencesGroup(title="hide.me-Konto")
        self.acc_status = Adw.ActionRow(title="Status")
        self.acc_icon = Gtk.Image(icon_name="dialog-question-symbolic")
        self.acc_status.add_prefix(self.acc_icon)
        acc.add(self.acc_status)
        self.login_row = button_row("Anmelden", "Zugangstoken mit Benutzername und Passwort anfordern",
                                    "Anmelden …", lambda: self.window.show_login(), "suggested-action")
        acc.add(self.login_row)
        self.refresh_row = button_row("Token erneuern", "Fordert mit dem vorhandenen Token ein neues an (token)",
                                      "Erneuern", lambda: self.ctl.refresh_token())
        acc.add(self.refresh_row)
        self.logout_row = button_row("Abmelden", "Entfernt das gespeicherte Zugangstoken vom System",
                                     "Abmelden", self._logout, "destructive-action")
        acc.add(self.logout_row)
        page.add(acc)

        tok = Adw.PreferencesGroup(title="Token-Speicherung")
        self._entry(tok, "Token-Datei (relativ zum Daemon-Verzeichnis, -t)", "Rest", "AccessTokenPath")
        self._spin(tok, "Verzögerung der Token-Erneuerung (Sekunden)",
                   "Wartezeit, bevor ein veraltetes Token erneuert wird (AccessTokenUpdateDelay)",
                   "Rest", "AccessTokenUpdateDelay", 0, 600, scale=NS)
        page.add(tok)

    def _logout(self):
        def resp(rid):
            if rid == "logout":
                self.ctl.logout()
        alert(self.dialog if hasattr(Adw, "AlertDialog") else self.window, "Abmelden?",
              "Das Zugangstoken wird gelöscht. Für neue Verbindungen musst du dich erneut anmelden.",
              [("cancel", "Abbrechen"), ("logout", "Abmelden")], resp, default="cancel", destructive="logout")

    def _update_account(self):
        has = self.ctl.has_token
        if has is None:
            self.acc_status.set_subtitle("Unbekannt – Daemon nicht erreichbar")
            self.acc_icon.set_from_icon_name("dialog-question-symbolic")
        elif has:
            self.acc_status.set_subtitle("Angemeldet – Zugangstoken ist gespeichert")
            self.acc_icon.set_from_icon_name("emblem-ok-symbolic")
        else:
            self.acc_status.set_subtitle("Kein Token in der Konfiguration. Falls eine Token-Datei existiert, "
                                         "wird diese verwendet.")
            self.acc_icon.set_from_icon_name("dialog-warning-symbolic")
        avail = self.ctl.available and self.ctl.busy is None
        for row in (self.login_row, self.refresh_row, self.logout_row):
            row.button.set_sensitive(avail)

    # ------------------------------------------------------------------ Erweitert
    def _page_advanced(self):
        page = self._add_page("advanced", "Erweitert", "applications-engineering-symbolic")

        wg = Adw.PreferencesGroup(
            title="WireGuard und Routing",
            description="Änderungen werden beim nächsten Verbindungsaufbau angewendet (Routing wird neu eingerichtet).")
        self._entry(wg, "Name der Netzwerkschnittstelle (-i)", "WireGuard", "Name")
        self._spin(wg, "WireGuard-Port", "Lokaler UDP-Port, 0 = automatisch (-l)", "WireGuard", "ListenPort", 0, 65535)
        self._spin(wg, "Firewall-Markierung", "Markierung für WireGuard- und Client-Verkehr, 0 = aus (-m)",
                   "WireGuard", "Mark", 0, 2147483647)
        self._spin(wg, "Routing-Tabelle", "Tabelle für Tunnel- und Leckschutz-Routen (-r)", "WireGuard",
                   "RoutingTable", 1, 2147483647)
        self._spin(wg, "Priorität der Routing-Regeln", "RPDB-Regelpriorität (-R)", "WireGuard", "RPDBPriority",
                   0, 32765)
        self._entry(wg, "Privater WireGuard-Schlüssel (Base64, leer = automatisch)", "WireGuard", "PrivateKey",
                    password=True)
        page.add(wg)

        rest = Adw.PreferencesGroup(title="REST-Schnittstelle der hide.me-Server")
        self._spin(rest, "Port", "Port der Schlüsselaustausch-Schnittstelle (-p)", "Rest", "Port", 1, 65535)
        self._entry(rest, "CA-Zertifikat (relativ zum Daemon-Verzeichnis, --ca)", "Rest", "CA")
        page.add(rest)

        ctrl = Adw.PreferencesGroup(
            title="Verbindung zum Daemon",
            description="Adresse der Steuerschnittstelle: Socket-Pfad, abstrakter Socket (@name), host:port oder "
                        "https://host:port (--caddr).")
        self.ctrl_addr = EntryRow("Adresse", text=self.settings["control_address"], on_apply=self._apply_control)
        ctrl.add(self.ctrl_addr.widget)
        self.ctrl_ca = EntryRow("CA-Zertifikat für https (optional)", text=self.settings["control_tls_ca"],
                                on_apply=lambda _t: self._apply_control(self.ctrl_addr.get_text()))
        ctrl.add(self.ctrl_ca.widget)
        self.ctrl_verify = SwitchRow("TLS-Zertifikat prüfen", active=self.settings["control_tls_verify"],
                                     on_toggle=lambda _v: self._apply_control(self.ctrl_addr.get_text()))
        ctrl.add(self.ctrl_verify.widget)
        self.ver_row = info_row("Daemon-Version")
        ctrl.add(self.ver_row)
        self._bind(lambda cfg: self.ver_row.value_label.set_text(self.ctl.daemon_version or "–"))
        ctrl.add(button_row("Daemon neu starten", "Trennt eine bestehende Verbindung", "Neu starten",
                            self._restart_daemon))
        page.add(ctrl)

        reset = Adw.PreferencesGroup()
        reset.add(button_row("Standardwerte wiederherstellen",
                             "Setzt alle Client-Optionen zurück. Anmeldung, Server und SmartGuard bleiben erhalten.",
                             "Zurücksetzen", self._reset_defaults, "destructive-action"))
        page.add(reset)

    def _apply_control(self, address):
        address = (address or "").strip()
        if not address:
            return
        self.ctl.set_control_address(address, self.ctrl_ca.get_text().strip(), self.ctrl_verify.get_active())
        self._toast("Steueradresse übernommen")

    def _restart_daemon(self):
        def done(_r):
            self._toast("Daemon wird neu gestartet …")
            GLib.timeout_add_seconds(2, lambda: (self.ctl.poll_now(), False)[1])

        def failed(exc):
            self._toast(f"Neustart fehlgeschlagen: {exc}")
        self.ctl.run_bg(system.restart_daemon, done, failed)

    def _reset_defaults(self):
        def resp(rid):
            if rid != "reset":
                return
            rest = {k: v for k, v in C.DEFAULTS["Rest"].items() if k not in ("Filter",)}
            rest["PortForward"] = {"enabled": False}
            patch = {"Rest": rest, "WireGuard": dict(C.DEFAULTS["WireGuard"]),
                     "Plain": dict(C.DEFAULTS["Plain"])}
            self.ctl.update_config(patch)
            self._toast("Standardwerte wiederhergestellt")
        alert(self.dialog if hasattr(Adw, "AlertDialog") else self.window, "Standardwerte wiederherstellen?",
              "Alle Client-Optionen werden auf die Voreinstellungen von hide.me zurückgesetzt.",
              [("cancel", "Abbrechen"), ("reset", "Zurücksetzen")], resp, default="cancel", destructive="reset")
