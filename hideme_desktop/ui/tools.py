"""Fenster "Werkzeuge": DNS-Test, öffentliche IP, Konfigurations-Export/-Import, Daemon."""

import copy
import json

from gi.repository import Adw, Gtk

from .. import cli
from .. import config as C
from .compat import (EntryRow, SwitchRow, alert, button_row, info_row, open_file, save_file, toast)


def _strip_secrets(cfg):
    cfg = copy.deepcopy(cfg or {})
    rest = cfg.get("Rest") or {}
    for key in ("AccessToken", "Password", "Username"):
        if key in rest:
            rest[key] = ""
    wg = cfg.get("WireGuard") or {}
    if "PrivateKey" in wg:
        wg["PrivateKey"] = ""
    return cfg


class ToolsWindow(Adw.Window):
    def __init__(self, parent, controller):
        super().__init__(title="Werkzeuge", transient_for=parent, default_width=640, default_height=720)
        self.ctl = controller
        self.parent_window = parent

        self.toasts = Adw.ToastOverlay()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        box.append(page)
        self.toasts.set_child(box)
        self.set_content(self.toasts)

        # DNS-Test --------------------------------------------------------------
        dns = Adw.PreferencesGroup(
            title="DNS-Test",
            description="Vergleicht die Auflösung per DNS-over-HTTPS (resolve) mit klassischem DNS über die "
                        "konfigurierten Server (lookup).")
        self.dns_host = EntryRow("Hostname", text="nl.hideservers.net", on_apply=lambda _t: self._resolve(True))
        dns.add(self.dns_host.widget)
        btns = Adw.ActionRow(title="Auflösen")
        b1 = Gtk.Button(label="DoH", valign=Gtk.Align.CENTER, tooltip_text="hide.me resolve")
        b1.connect("clicked", lambda *_a: self._resolve(True))
        b2 = Gtk.Button(label="Klassisch", valign=Gtk.Align.CENTER, tooltip_text="hide.me lookup")
        b2.connect("clicked", lambda *_a: self._resolve(False))
        self.dns_spinner = Gtk.Spinner()
        btns.add_suffix(self.dns_spinner)
        btns.add_suffix(b1)
        btns.add_suffix(b2)
        dns.add(btns)
        self.dns_doh = info_row("Ergebnis DoH", copyable=True)
        self.dns_plain = info_row("Ergebnis klassisch", copyable=True)
        dns.add(self.dns_doh)
        dns.add(self.dns_plain)
        page.add(dns)

        # Öffentliche IP -----------------------------------------------------------
        ipg = Adw.PreferencesGroup(title="Öffentliche IP-Adressen",
                                   description="Abfrage über ipcheck.hideservers.net durch den Daemon")
        self.ip4 = info_row("IPv4", copyable=True)
        self.ip6 = info_row("IPv6", copyable=True)
        ipg.add(self.ip4)
        ipg.add(self.ip6)
        ipg.add(button_row("Jetzt prüfen", "", "Prüfen", lambda: self.ctl.check_external_ip()))
        page.add(ipg)

        # Konfiguration --------------------------------------------------------------
        conf = Adw.PreferencesGroup(
            title="Konfiguration",
            description="Exportierte Dateien sind mit „hide.me -c DATEI connect SERVER“ direkt nutzbar.")
        self.strip = SwitchRow("Geheimnisse entfernen", "Zugangstoken und privaten Schlüssel nicht exportieren",
                               active=True)
        conf.add(self.strip.widget)
        conf.add(button_row("Als YAML exportieren", "Format von „hide.me conf“", "Exportieren …",
                            lambda: self._export("yaml")))
        conf.add(button_row("Als JSON exportieren", "Format von „hide.me jsonconf“", "Exportieren …",
                            lambda: self._export("json")))
        conf.add(button_row("Importieren", "YAML- oder JSON-Konfiguration übernehmen", "Importieren …",
                            self._import))
        self.cmd_row = Adw.ActionRow(title="Entsprechender CLI-Aufruf")
        self.cmd_label = Gtk.Label(wrap=True, selectable=True, xalign=0, margin_top=6, margin_bottom=6)
        self.cmd_label.add_css_class("monospace")
        self.cmd_row.set_subtitle("")
        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Kopieren")
        copy_btn.add_css_class("flat")
        copy_btn.connect("clicked", lambda *_a: (self.get_clipboard().set(self.cmd_label.get_text()),
                                                  toast(self.toasts, "Kopiert")))
        self.cmd_row.add_suffix(copy_btn)
        conf.add(self.cmd_row)
        cmd_box = Gtk.ListBoxRow(activatable=False, selectable=False)
        cmd_box.set_child(self.cmd_label)
        self.cmd_label.set_margin_start(12)
        self.cmd_label.set_margin_end(12)
        conf.add(cmd_box)
        page.add(conf)

        # Daemon ---------------------------------------------------------------
        dmn = Adw.PreferencesGroup(title="Daemon")
        self.d_addr = info_row("Steueradresse")
        self.d_ver = info_row("Version")
        self.d_state = info_row("Zustand")
        for r in (self.d_addr, self.d_ver, self.d_state):
            dmn.add(r)
        dmn.add(button_row("Kill-Switch-Blockade einrichten",
                           "Richtet Routing und Leckschutz ein, ohne zu verbinden (route)", "Blockieren",
                           self.ctl.block))
        dmn.add(button_row("Routing entfernen", "Trennt und entfernt Schnittstelle, Regeln und Routen (destroy)",
                           "Entfernen", self.ctl.destroy))
        dmn.add(button_row("Routing herunterfahren", "Entfernt das Routing im getrennten Zustand (shutdown)",
                           "Herunterfahren", self.ctl.shutdown_routing))
        page.add(dmn)

        self._h = [controller.connect("changed", lambda *_a: self.refresh()),
                   controller.connect("config-changed", lambda *_a: self.refresh())]
        self.connect("close-request", self._on_close)
        self.refresh()

    def _on_close(self, *_a):
        for h in self._h:
            self.ctl.disconnect(h)
        return False

    def refresh(self):
        ctl = self.ctl
        self.ip4.value_label.set_text(ctl.ext_ip4 or ("wird ermittelt …" if ctl.ext_ip_checking else "–"))
        self.ip6.value_label.set_text(ctl.ext_ip6 or ("wird ermittelt …" if ctl.ext_ip_checking else "–"))
        self.d_addr.value_label.set_text(ctl.api.describe())
        self.d_ver.value_label.set_text(ctl.daemon_version or "–")
        self.d_state.value_label.set_text(ctl.code if ctl.available else ctl.unavailable_reason)
        self.cmd_label.set_text(C.cli_command(ctl.config, ctl.current_host) if ctl.config else "–")

    def _resolve(self, doh):
        name = self.dns_host.get_text().strip()
        if not name:
            return
        target = self.dns_doh if doh else self.dns_plain
        target.value_label.set_text("…")
        self.dns_spinner.start()
        servers = C.get(self.ctl.config, "Plain", "Servers")

        def done(ips):
            self.dns_spinner.stop()
            target.value_label.set_text(", ".join(ips) if ips else "keine Adressen")

        def failed(exc):
            self.dns_spinner.stop()
            target.value_label.set_text(f"Fehler: {exc}")
        func = (lambda: cli.resolve_doh(name)) if doh else (lambda: cli.lookup_plain(name, servers))
        self.ctl.run_bg(func, done, failed)

    def _export(self, fmt):
        if not self.ctl.config:
            toast(self.toasts, "Keine Konfiguration verfügbar – Daemon nicht erreichbar")
            return
        cfg = _strip_secrets(self.ctl.config) if self.strip.get_active() else copy.deepcopy(self.ctl.config)
        if cfg.get("Rest"):
            cfg["Rest"].pop("APIVersion", None)

        def write(path, text):
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                toast(self.toasts, f"Gespeichert: {path}")
            except OSError as e:
                toast(self.toasts, f"Speichern fehlgeschlagen: {e}")

        if fmt == "json":
            text = json.dumps(cfg, indent="\t") + "\n"
            save_file(self, "Konfiguration exportieren", "hide.me.json", lambda p: write(p, text))
        else:
            def done(yaml_text):
                save_file(self, "Konfiguration exportieren", "hide.me.yaml", lambda p: write(p, yaml_text))

            def failed(exc):
                toast(self.toasts, f"YAML-Export fehlgeschlagen: {exc}")
            self.ctl.run_bg(lambda: cli.config_to_yaml(cfg), done, failed)

    def _import(self):
        def chosen(path):
            def done(data):
                patch = {k: data[k] for k in ("Rest", "WireGuard", "DoH", "Plain") if isinstance(data.get(k), dict)}
                if "Rest" in patch:
                    # Benutzername/Passwort nicht übernehmen: Verbindungen nutzen nur das Zugangstoken,
                    # und das Passwort landete sonst im Klartext in der Daemon-Konfiguration.
                    patch["Rest"] = {k: v for k, v in patch["Rest"].items()
                                     if k not in ("APIVersion", "Domain", "Username", "Password")}
                    if not patch["Rest"].get("AccessToken"):
                        patch["Rest"].pop("AccessToken", None)
                if not patch:
                    toast(self.toasts, "Die Datei enthält keine verwertbare Konfiguration")
                    return

                def resp(rid):
                    if rid == "import":
                        self.ctl.update_config(patch)
                        toast(self.toasts, "Konfiguration übernommen")
                alert(self, "Konfiguration übernehmen?",
                      f"Die Einstellungen aus „{path}“ ersetzen die aktuellen Werte "
                      f"({', '.join(patch)}).", [("cancel", "Abbrechen"), ("import", "Übernehmen")], resp,
                      default="import")

            def failed(exc):
                toast(self.toasts, f"Import fehlgeschlagen: {exc}")
            self.ctl.run_bg(lambda: cli.config_file_to_json(path), done, failed)
        open_file(self, "Konfiguration importieren", chosen)
