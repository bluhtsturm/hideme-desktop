"""Seite "Protokoll": Daemon-Log (Ringpuffer) und Live-Ereignisse."""

from gi.repository import Adw, GLib, Gtk

from .. import api as A
from . import util as U
from .compat import save_file

NOISE = {A.CONFIGURATION_GET, A.LOG_DUMP}

EVENT_TEXT = {
    A.CLEAN: "Bereinigt (kein Routing aktiv)",
    A.ROUTED: "Routing aktiv, nicht verbunden",
    A.CONNECTING: "Verbinde",
    A.CONNECTED: "Verbunden",
    A.DISCONNECTING: "Trenne",
    A.DPD_TIMEOUT: "Keine Antwort vom Server (DPD-Timeout)",
    A.TOKEN_UPDATE: "Zugangstoken wird erneuert",
    A.TOKEN_UPDATE_DONE: "Zugangstoken erneuert",
    A.CONFIGURATION_SET: "Konfiguration geändert",
    A.CONFIGURATION_GET: "Konfiguration gelesen",
    A.LOG_DUMP: "Protokoll gelesen",
    A.DNS_LOOKUP: "DNS-Auflösung des Servers",
    A.EXTERNAL_IPS: "Öffentliche IP-Adressen ermittelt",
}


class LogView(Gtk.Box):
    def __init__(self, window, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.ctl = controller
        self._raw_log = ""
        self._auto_timer = 0

        bar = Gtk.Box(spacing=8, margin_top=10, margin_bottom=8, margin_start=12, margin_end=12)
        self.stack = Gtk.Stack(vexpand=True)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        bar.append(switcher)
        self.search = Gtk.SearchEntry(placeholder_text="Filtern", hexpand=True)
        self.search.connect("search-changed", lambda *_a: self._render())
        bar.append(self.search)
        self.only_errors = Gtk.ToggleButton(icon_name="dialog-warning-symbolic",
                                            tooltip_text="Nur Warnungen und Fehler anzeigen")
        self.only_errors.connect("toggled", lambda *_a: self._render())
        bar.append(self.only_errors)
        self.auto = Gtk.ToggleButton(icon_name="media-playlist-repeat-symbolic",
                                     tooltip_text="Automatisch aktualisieren",
                                     active=controller.settings["log_autorefresh"])
        self.auto.connect("toggled", self._auto_toggled)
        bar.append(self.auto)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Neu laden")
        refresh.connect("clicked", lambda *_a: self.load())
        bar.append(refresh)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="In die Zwischenablage kopieren")
        copy.connect("clicked", lambda *_a: self._copy())
        bar.append(copy)
        save = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Als Datei speichern …")
        save.connect("clicked", lambda *_a: self._save())
        bar.append(save)
        self.append(bar)
        self.append(self.stack)

        self.log_view, log_scroller = self._make_textview()
        self.stack.add_titled(log_scroller, "log", "Daemon")
        self.event_view, event_scroller = self._make_textview()
        self.stack.add_titled(event_scroller, "events", "Ereignisse")
        self.stack.connect("notify::visible-child-name", lambda *_a: self._render())

        self.ctl.connect("event", self._on_event)
        self._auto_toggled(self.auto)

    def _make_textview(self):
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            left_margin=12, right_margin=12, top_margin=8, bottom_margin=8, cursor_visible=False)
        view.add_css_class("hm-log")
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(view)
        return view, scroller

    def _auto_toggled(self, btn):
        self.ctl.settings["log_autorefresh"] = btn.get_active()
        if self._auto_timer:
            GLib.source_remove(self._auto_timer)
            self._auto_timer = 0
        if btn.get_active():
            self._auto_timer = GLib.timeout_add_seconds(3, self._auto_tick)

    def _auto_tick(self):
        if self.get_mapped() and self.stack.get_visible_child_name() == "log":
            self.load()
        return True

    def load(self):
        def done(text):
            self._raw_log = text
            self._render()

        def failed(exc):
            self._raw_log = f"Protokoll konnte nicht geladen werden: {exc}"
            self._render()
        self.ctl.fetch_log(done, failed)

    def on_shown(self):
        self.load()

    def _filter_lines(self, lines):
        query = self.search.get_text().casefold().strip()
        only = self.only_errors.get_active()
        out = []
        for line in lines:
            if query and query not in line.casefold():
                continue
            if only and not any(x in line for x in ("[ERR]", "[WARN]", "ERR", "failed", "Fehl")):
                continue
            out.append(line)
        return out

    def _event_lines(self):
        lines = []
        for ev in self.ctl.events:
            if ev["code"] in NOISE:
                continue
            data = ev["data"]
            text = EVENT_TEXT.get(ev["code"], ev["code"])
            details = []
            if data.get("host"):
                details.append(data["host"])
            if data.get("external_ip"):
                details.append(f"IPv4 {data['external_ip']}")
            if data.get("external_ipv6"):
                details.append(f"IPv6 {data['external_ipv6']}")
            if ev["code"] == A.CONNECTED and data.get("endpoint"):
                details.append(f"Endpunkt {U.endpoint_text(data.get('endpoint'))}")
            stamp = ev["time"].strftime("%H:%M:%S")
            lines.append(f"{stamp}  {text}" + (f"  ({', '.join(details)})" if details else ""))
        return lines

    def _render(self):
        name = self.stack.get_visible_child_name()
        if name == "events":
            lines = self._filter_lines(self._event_lines())
            view = self.event_view
            if not lines:
                lines = ["Noch keine Ereignisse empfangen."]
        else:
            lines = self._filter_lines(self._raw_log.splitlines())
            view = self.log_view
            if not lines:
                lines = ["Das Protokoll ist leer." if not self._raw_log else "Keine passenden Zeilen."]
        buf = view.get_buffer()
        scroller = view.get_parent()
        adj = scroller.get_vadjustment()
        at_end = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 40
        buf.set_text("\n".join(lines))
        if at_end:
            GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])

    def _on_event(self, _ctl, code, _data):
        if code not in NOISE and self.stack.get_visible_child_name() == "events" and self.get_mapped():
            self._render()

    def _current_text(self):
        view = self.event_view if self.stack.get_visible_child_name() == "events" else self.log_view
        buf = view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _copy(self):
        self.get_clipboard().set(self._current_text())
        self.window.toast("In die Zwischenablage kopiert")

    def _save(self):
        name = "hideme-ereignisse.txt" if self.stack.get_visible_child_name() == "events" else "hideme-daemon.log"
        text = self._current_text()

        def write(path):
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
                self.window.toast(f"Gespeichert: {path}")
            except OSError as e:
                self.window.toast(f"Speichern fehlgeschlagen: {e}")
        save_file(self.window, "Protokoll speichern", name, write)
