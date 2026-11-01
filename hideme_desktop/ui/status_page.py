"""Seite "Verbindung": Status, Verbinden/Trennen, Verbindungsdetails."""

from gi.repository import Adw, GLib, Gtk

from .. import api as A
from .. import config as C
from . import util as U
from .compat import SwitchRow, info_row


class StatusView(Gtk.ScrolledWindow):
    def __init__(self, window, controller):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.ctl = controller

        clamp = Adw.Clamp(maximum_size=560, margin_top=28, margin_bottom=28, margin_start=16, margin_end=16)
        self.set_child(clamp)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)

        # Statusanzeige ---------------------------------------------------------
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        self.badge = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, margin_top=18, margin_bottom=22)
        self.badge.add_css_class("hm-badge")
        self.badge_icon = Gtk.Image(icon_name="hideme-shield-off-symbolic", pixel_size=72,
                                    halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True)
        self.badge.append(self.badge_icon)
        hero.append(self.badge)
        self.title = Gtk.Label(label="Nicht verbunden", justify=Gtk.Justification.CENTER)
        self.title.add_css_class("hm-status-title")
        hero.append(self.title)
        self.subtitle = Gtk.Label(label="", wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=50)
        self.subtitle.add_css_class("dim-label")
        hero.append(self.subtitle)
        box.append(hero)

        # Hauptknopf ------------------------------------------------------------
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER, margin_top=6)
        self.main_button = Gtk.Button()
        self.main_button.add_css_class("pill")
        self.main_button.add_css_class("hm-main-button")
        btn_box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.main_spinner = Gtk.Spinner()
        self.main_label = Gtk.Label(label="Verbinden")
        btn_box.append(self.main_spinner)
        btn_box.append(self.main_label)
        self.main_button.set_child(btn_box)
        self.main_button.connect("clicked", self._on_main)
        buttons.append(self.main_button)
        self.unblock_button = Gtk.Button(label="Blockierung aufheben")
        self.unblock_button.add_css_class("flat")
        self.unblock_button.connect("clicked", lambda *_a: self.ctl.unblock())
        buttons.append(self.unblock_button)
        box.append(buttons)

        # Konto-Hinweis ---------------------------------------------------------
        self.login_group = Adw.PreferencesGroup()
        login_row = Adw.ActionRow(title="Nicht angemeldet",
                                  subtitle="Für eine Verbindung wird ein Zugangstoken deines hide.me-Kontos benötigt.")
        login_row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
        login_btn = Gtk.Button(label="Anmelden", valign=Gtk.Align.CENTER)
        login_btn.add_css_class("suggested-action")
        login_btn.connect("clicked", lambda *_a: self.window.show_login())
        login_row.add_suffix(login_btn)
        self.login_group.add(login_row)
        box.append(self.login_group)

        # Server ------------------------------------------------------------------
        server_group = Adw.PreferencesGroup(title="Server")
        self.server_row = Adw.ActionRow(title="–", activatable=True)
        self.server_flag = Gtk.Label(label="🌐")
        self.server_flag.add_css_class("hm-flag")
        self.server_row.add_prefix(self.server_flag)
        change = Gtk.Button(label="Ändern", valign=Gtk.Align.CENTER)
        change.add_css_class("flat")
        change.connect("clicked", lambda *_a: self.window.show_page("servers"))
        self.server_row.add_suffix(change)
        self.server_row.connect("activated", lambda *_a: self.window.show_page("servers"))
        server_group.add(self.server_row)

        self.fav_row = Adw.ActionRow(title="Favoriten")
        self.fav_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                                   column_spacing=6, row_spacing=6, margin_top=8, margin_bottom=8,
                                   valign=Gtk.Align.CENTER, hexpand=True)
        self.fav_row.add_suffix(self.fav_box)
        server_group.add(self.fav_row)
        box.append(server_group)

        # Verbindungsdetails --------------------------------------------------------
        self.details = Adw.PreferencesGroup(title="Verbindung")
        self.row_ip4 = info_row("Öffentliche IPv4", copyable=True)
        self.row_ip6 = info_row("Öffentliche IPv6", copyable=True)
        self.row_since = info_row("Verbunden seit")
        self.row_down = info_row("Empfangen")
        self.row_up = info_row("Gesendet")
        self.row_tunnel = info_row("Tunnel-Adressen", copyable=True)
        self.row_dns = info_row("DNS-Server")
        self.row_endpoint = info_row("Server-Endpunkt", copyable=True)
        for row in (self.row_ip4, self.row_ip6, self.row_since, self.row_down, self.row_up, self.row_tunnel,
                    self.row_dns, self.row_endpoint):
            self.details.add(row)
        box.append(self.details)

        self.ip_group = Adw.PreferencesGroup(title="Deine Verbindung ohne VPN")
        self.row_real_ip = info_row("Öffentliche IP-Adresse", copyable=True)
        check = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Prüfen")
        check.add_css_class("flat")
        check.connect("clicked", lambda *_a: self.ctl.check_external_ip())
        self.row_real_ip.add_suffix(check)
        self.ip_group.add(self.row_real_ip)
        box.append(self.ip_group)

        # Schutz ------------------------------------------------------------------
        protect = Adw.PreferencesGroup(title="Schutz")
        self.sw_killswitch = SwitchRow("Kill-Switch", "Blockiert Datenverkehr außerhalb des Tunnels (Leckschutz)",
                                       on_toggle=self._toggle_killswitch)
        protect.add(self.sw_killswitch.widget)
        self.sw_pf = SwitchRow("Port-Forwarding", "Dynamische Portweiterleitung per UPnP und NAT-PMP",
                               on_toggle=lambda v: self.ctl.update_config({"Rest": {"PortForward": {"enabled": v}}}))
        protect.add(self.sw_pf.widget)
        self.sg_row = Adw.ActionRow(title="SmartGuard", subtitle="Aus", activatable=True)
        self.sg_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.sg_row.connect("activated", lambda *_a: self.window.show_page("smartguard"))
        protect.add(self.sg_row)
        self.split_row = Adw.ActionRow(title="Split-Tunneling", subtitle="Aus", activatable=True)
        self.split_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.split_row.connect("activated", lambda *_a: self.window.show_preferences("connection"))
        protect.add(self.split_row)
        box.append(protect)

        self.ctl.connect("changed", lambda *_a: self.refresh())
        self.ctl.connect("config-changed", lambda *_a: self.refresh_config())
        self.ctl.connect("servers-changed", lambda *_a: self.refresh())
        self.ctl.settings.connect_changed(self._settings_changed)
        GLib.timeout_add_seconds(1, self._tick)
        self._fav_signature = None
        self.refresh_config()
        self.refresh()

    # ------------------------------------------------------------------
    def _settings_changed(self, key, _value):
        if key in ("favorites", "last_server"):
            self.refresh()

    def _toggle_killswitch(self, value):
        if not value:
            def resp(rid):
                if rid == "off":
                    self.ctl.update_config({"WireGuard": {"LeakProtection": False}})
                else:
                    self.sw_killswitch.set_active(True)
            from .compat import alert
            alert(self.window, "Kill-Switch deaktivieren?",
                  "Ohne Kill-Switch kann bei einem Verbindungsabbruch ungeschützter Datenverkehr dein "
                  "Gerät verlassen.", [("cancel", "Abbrechen"), ("off", "Deaktivieren")], resp,
                  default="cancel", destructive="off")
        else:
            self.ctl.update_config({"WireGuard": {"LeakProtection": True}})

    def _on_main(self, *_a):
        phase = self.ctl.phase()
        if phase in ("connected", "reconnecting") or (phase == "connecting" and self.ctl.busy is None):
            self.ctl.disconnect_vpn()
        elif phase == "unavailable":
            self.ctl.poll_now()
        else:
            if self.ctl.has_token is False:
                self.window.show_login(connect_after=True)
                return
            if not self.ctl.current_host:
                self.window.show_page("servers")
                self.window.toast("Bitte wähle einen Server aus.")
                return
            self.ctl.connect_vpn()

    def _tick(self):
        if self.ctl.code == A.CONNECTED and self.get_mapped():
            self._update_live()
        elif self.ctl.phase() == "reconnecting" and self.get_mapped():
            self.refresh()
        return True

    def _update_live(self):
        st = self.ctl.state
        self.row_since.value_label.set_text(U.fmt_duration(U.since(self.ctl.connected_since)))
        self.row_down.value_label.set_text(f"{U.fmt_bytes(st.get('rx'))}  ·  {U.fmt_rate(self.ctl.rx_rate)}")
        self.row_up.value_label.set_text(f"{U.fmt_bytes(st.get('tx'))}  ·  {U.fmt_rate(self.ctl.tx_rate)}")
        name, _flag = U.server_label(self.ctl, self.ctl.current_host)
        self.subtitle.set_text(f"Verbunden mit {name} · {U.fmt_duration(U.since(self.ctl.connected_since))}")

    def refresh_config(self):
        cfg = self.ctl.config
        self.sw_killswitch.set_active(C.get(cfg, "WireGuard", "LeakProtection"))
        self.sw_pf.set_active(bool(((C.get(cfg, "Rest", "PortForward")) or {}).get("enabled")))
        f = C.get_filter(cfg)
        self.sg_row.set_subtitle(C.filter_summary(f))
        split = [s for s in (C.get(cfg, "WireGuard", "SplitTunnel") or "").split(",") if s]
        self.split_row.set_subtitle(", ".join(split) if split else "Aus – sämtlicher Verkehr läuft durch den Tunnel")
        for w in (self.sw_killswitch, self.sw_pf):
            w.set_sensitive(cfg is not None)

    def refresh(self):
        ctl = self.ctl
        phase = ctl.phase()
        title, icon, css = U.PHASE_TEXT.get(phase, U.PHASE_TEXT["disconnected"])
        for c in ("connected", "disconnected", "blocked", "connecting", "unavailable"):
            self.badge.remove_css_class(c)
            self.title.remove_css_class(c)
        self.badge.add_css_class(css)
        self.title.add_css_class(css)
        self.badge_icon.set_from_icon_name(icon)
        self.title.set_text(title)

        host = ctl.current_host
        name, flag = U.server_label(ctl, host)
        self.server_row.set_title(name)
        self.server_row.set_subtitle(C.short_name(host) if host else "Tippe auf „Ändern“, um einen Server zu wählen")
        self.server_flag.set_text(flag)

        sub = ""
        if phase == "connected":
            sub = f"Verbunden mit {name}"
        elif phase == "connecting":
            sub = f"Verbindung zu {name} wird aufgebaut …"
            if ctl.code == A.ROUTED and ctl.busy:
                sub = f"Bereite Verbindung zu {name} vor …"
        elif phase == "reconnecting":
            secs = ctl.reconnect_in()
            sub = "Verbindung unterbrochen – Kill-Switch schützt dich." if ctl.leak_protection else \
                "Verbindung unterbrochen."
            if secs:
                sub += f" Neuer Versuch in {secs} s."
        elif phase == "disconnecting":
            sub = "Verbindung wird getrennt …"
        elif phase == "blocked":
            sub = "Der Kill-Switch ist aktiv, aber es besteht keine VPN-Verbindung. " \
                  "Ungeschützter Datenverkehr wird blockiert."
        elif phase == "disconnected":
            sub = "Dein Datenverkehr ist nicht geschützt."
            if ctl.last_error and not ctl.want_connected:
                sub += f"\nLetzter Fehler: {ctl.last_error}"
        elif phase == "unavailable":
            sub = ctl.unavailable_reason
        self.subtitle.set_text(sub)

        busy = phase in ("connecting", "disconnecting") and ctl.busy is not None
        self.main_spinner.set_visible(busy)
        if busy:
            self.main_spinner.start()
        else:
            self.main_spinner.stop()
        for c in ("suggested-action", "destructive-action"):
            self.main_button.remove_css_class(c)
        if phase in ("connected", "reconnecting"):
            self.main_label.set_text("Trennen")
            self.main_button.add_css_class("destructive-action")
            self.main_button.set_sensitive(True)
        elif phase == "connecting":
            self.main_label.set_text("Verbinde …" if ctl.busy else "Abbrechen")
            self.main_button.set_sensitive(ctl.busy is None)
        elif phase == "disconnecting":
            self.main_label.set_text("Trenne …")
            self.main_button.set_sensitive(False)
        else:
            self.main_label.set_text("Verbinden")
            self.main_button.add_css_class("suggested-action")
            self.main_button.set_sensitive(phase != "unavailable" and ctl.busy is None)
        self.unblock_button.set_visible(phase == "blocked" and ctl.busy is None)
        self.login_group.set_visible(ctl.available and ctl.has_token is False)

        connected = phase == "connected"
        self.details.set_visible(connected)
        self.ip_group.set_visible(not connected and ctl.available)
        if connected:
            st = ctl.state
            self.row_ip4.value_label.set_text(ctl.ext_ip4 or ("wird ermittelt …" if ctl.ext_ip_checking else "–"))
            self.row_ip6.value_label.set_text(ctl.ext_ip6 or ("wird ermittelt …" if ctl.ext_ip_checking else "–"))
            self.row_tunnel.value_label.set_text(U.ips(st.get("allowedIps")))
            self.row_dns.value_label.set_text(U.ips(st.get("DNS")))
            self.row_endpoint.value_label.set_text(U.endpoint_text(st.get("endpoint")))
            self._update_live()
        else:
            ips = ", ".join(x for x in (ctl.ext_ip4, ctl.ext_ip6) if x)
            self.row_real_ip.value_label.set_text(
                ips or ("wird ermittelt …" if ctl.ext_ip_checking else "Zum Prüfen auf ↻ klicken"))
        self._refresh_favorites()

    def _refresh_favorites(self):
        favs = list(self.ctl.settings["favorites"])
        signature = (tuple(favs), len(self.ctl.servers))
        if signature == self._fav_signature:
            return
        self._fav_signature = signature
        child = self.fav_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.fav_box.remove(child)
            child = nxt
        self.fav_row.set_visible(bool(favs))
        for host in favs[:12]:
            name, flag = U.server_label(self.ctl, host)
            btn = Gtk.Button(label=f"{flag}  {name}", tooltip_text=f"Mit {name} verbinden")
            btn.add_css_class("hm-fav-chip")
            btn.connect("clicked", lambda *_a, h=host: self.ctl.connect_vpn(h))
            self.fav_box.append(btn)
