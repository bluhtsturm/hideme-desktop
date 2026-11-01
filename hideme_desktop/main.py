"""Einstiegspunkt der Desktop-App."""

import os
import shlex
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, DAEMON_GROUP, VERSION  # noqa: E402
from . import config as C  # noqa: E402
from .controller import Controller  # noqa: E402
from .settings import Settings  # noqa: E402
from .tray import MenuItem, TrayIcon  # noqa: E402
from .ui import util as U  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """Verzeichnis mit Icons (Entwicklungsbaum oder Installation)."""
    for candidate in (os.path.join(os.path.dirname(HERE), "data"),
                      "/opt/hideme-desktop/data", "/usr/share/hideme-desktop"):
        if os.path.isdir(os.path.join(candidate, "icons")):
            return candidate
    return None


TRAY_ICONS = {
    "connected": f"{APP_ID}-connected",
    "connecting": f"{APP_ID}-connecting",
    "reconnecting": f"{APP_ID}-connecting",
    "disconnecting": f"{APP_ID}-connecting",
    "blocked": f"{APP_ID}-blocked",
    "disconnected": f"{APP_ID}-disconnected",
    "unavailable": f"{APP_ID}-disconnected",
}


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("background", ord("b"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Im Hintergrund starten (nur Tray-Symbol)", None)
        self.add_main_option("connect", ord("c"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Mit SERVER verbinden (leer = zuletzt verwendeter Server)", "SERVER")
        self.add_main_option("disconnect", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "VPN-Verbindung trennen", None)
        self.add_main_option("toggle", ord("t"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Verbinden bzw. trennen", None)
        self.add_main_option("quit", ord("q"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Laufende App beenden (die VPN-Verbindung bleibt bestehen)", None)
        self.add_main_option("version", ord("v"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Version anzeigen", None)
        self.settings = None
        self.controller = None
        self.window = None
        self.tray = None
        self._started = False
        self._tray_signature = None
        self._bg_hint_shown = False

    # ------------------------------------------------------------------ Start
    def do_handle_local_options(self, options):
        if options.contains("version"):
            print(f"{APP_NAME} (hide.me Desktop) {VERSION}")
            return 0
        return -1

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.settings = Settings()
        style = Adw.StyleManager.get_default()
        style.set_color_scheme(Adw.ColorScheme.DEFAULT)

        display = Gdk.Display.get_default()
        dd = data_dir()
        if display and dd:
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(dd, "icons"))
        css = Gtk.CssProvider()
        css_path = os.path.join(HERE, "ui", "style.css")
        try:
            css.load_from_path(css_path)
            if display:
                Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except GLib.Error as e:
            print(f"hideme-desktop: CSS konnte nicht geladen werden: {e.message}")

        self.controller = Controller(self.settings)
        self.controller.connect("changed", lambda *_a: self._update_tray())
        self.controller.connect("servers-changed", lambda *_a: self._update_tray())
        self.controller.connect("notify-user", self._notify)
        self.settings.connect_changed(self._settings_changed)

        self._add_action("preferences", lambda *_a: self._show_window() or self.window.show_preferences(),
                         ["<Control>comma"])
        self._add_action("account", lambda *_a: self._show_window() or self.window.show_preferences("account"))
        self._add_action("tools", lambda *_a: self._show_window() or self.window.show_tools())
        self._add_action("about", lambda *_a: self._about())
        self._add_action("quit", lambda *_a: self.quit_app(), ["<Control>q"])
        self._add_action("toggle", lambda *_a: self.controller.toggle(), ["<Control>Return"])
        self._add_action("show", lambda *_a: self._show_window())
        self.set_accels_for_action("window.close", ["<Control>w"])

        # Die App bleibt aktiv, auch wenn kein Fenster offen ist (Tray-Betrieb)
        self.hold()

    def _add_action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        first = not self._started
        if first:
            self._started = True
            self.controller.start(autoconnect=self.settings["autoconnect"] and "connect" not in options
                                  and "disconnect" not in options)
            if self.settings["show_tray"]:
                self._enable_tray()

        if options.get("quit"):
            self.quit_app()
            return 0
        if "connect" in options:
            target = options.get("connect") or None
            self._when_available(lambda: self.controller.connect_vpn(target))
        if options.get("disconnect"):
            self._when_available(self.controller.disconnect_vpn)
        if options.get("toggle"):
            self._when_available(self.controller.toggle)

        background = options.get("background") and self.settings["start_hidden"]
        action_only = any(k in options for k in ("connect", "disconnect", "toggle"))
        if first and (background or action_only):
            return 0  # unsichtbar starten – ein erneuter Aufruf öffnet das Fenster
        if not action_only:
            self._show_window()
        return 0

    def do_activate(self):
        self._show_window()

    def _when_available(self, func, tries=40):
        if self.controller.available and self.controller.config is not None:
            func()
            return
        if tries <= 0:
            func()
            return
        GLib.timeout_add(250, lambda: (self._when_available(func, tries - 1), False)[1])

    # ------------------------------------------------------------------ Fenster
    def _show_window(self):
        if self.window is None:
            from .ui.window import MainWindow
            self.window = MainWindow(self, self.controller)
            self.window.connect("close-request", self._on_close_request)
        self.window.set_visible(True)
        self.window.present()

    def _on_close_request(self, window):
        if not self.settings["run_in_background"]:
            self.quit_app()
            return True
        window.set_visible(False)
        if not (self.tray and self.tray.available) and not self._bg_hint_shown:
            self._bg_hint_shown = True
            self._send_notification("background", "hide.me VPN läuft weiter",
                                    "Die App läuft im Hintergrund. Starte sie erneut, um das Fenster zu öffnen.")
        return True

    def quit_app(self):
        if self.tray:
            self.tray.disable()
        if self.controller:
            self.controller.shutdown()
        if self.window:
            self.window.destroy()
        self.release()
        self.quit()

    def relaunch_with_group(self):
        """Startet die App mit der Gruppe hideme neu (ohne Ab-/Anmelden)."""
        launcher = os.environ.get("HIDEME_LAUNCHER") or "hideme-desktop"
        try:
            # kurz warten, bis diese Instanz beendet ist und den D-Bus-Namen freigegeben hat
            GLib.spawn_async(["sg", DAEMON_GROUP, "-c", f"sleep 1; exec {shlex.quote(launcher)}"],
                             flags=GLib.SpawnFlags.SEARCH_PATH)
        except GLib.Error as e:
            if self.window:
                self.window.toast(f"Neustart fehlgeschlagen: {e.message}")
            return
        GLib.timeout_add(100, lambda: (self.quit_app(), False)[1])

    def _about(self):
        self._show_window()
        kwargs = dict(application_name=APP_NAME, application_icon=APP_ID, version=VERSION,
                      developer_name="hide.me Desktop (inoffiziell)",
                      comments="Grafische Oberfläche für den quelloffenen hide.me CLI VPN-Client (WireGuard). "
                               "Kein offizielles Produkt der eVenture Ltd.",
                      website="https://github.com/eventure/hide.client.linux",
                      license_type=Gtk.License.GPL_2_0,
                      issue_url="https://github.com/eventure/hide.client.linux/issues")
        if hasattr(Adw, "AboutDialog"):
            dlg = Adw.AboutDialog(**kwargs)
            dlg.add_credit_section("hide.me CLI", ["eVenture Ltd. (hide.client.linux)"])
            dlg.present(self.window)
        else:
            dlg = Adw.AboutWindow(transient_for=self.window, **kwargs)
            dlg.present()

    # ------------------------------------------------------------------ Benachrichtigungen
    def _notify(self, _ctl, nid, title, body):
        if not self.settings["notifications"]:
            return
        if self.window and self.window.get_visible() and self.window.is_active():
            return  # Fenster im Vordergrund zeigt den Zustand ohnehin
        self._send_notification(nid, title, body)

    def _send_notification(self, nid, title, body):
        n = Gio.Notification.new(title)
        n.set_body(body)
        n.set_icon(Gio.ThemedIcon.new(APP_ID))
        n.set_default_action("app.show")
        self.send_notification(nid, n)

    # ------------------------------------------------------------------ Tray
    def _settings_changed(self, key, value):
        if key == "show_tray":
            if value:
                self._enable_tray()
            elif self.tray:
                self.tray.disable()
        if key in ("favorites", "recent", "show_tray"):
            self._tray_signature = None
            self._update_tray()

    def _enable_tray(self):
        if self.tray is None:
            dd = data_dir()
            theme_path = os.path.join(dd, "icons") if dd else ""
            self.tray = TrayIcon(APP_ID, APP_NAME, theme_path, self._tray_activate,
                                 lambda _avail: self._tray_avail())
        self.tray.enable()
        self._tray_signature = None
        self._update_tray()

    def _tray_avail(self):
        self._tray_signature = None
        self._update_tray()

    def _tray_activate(self):
        if self.window and self.window.get_visible() and self.window.is_active():
            self.window.set_visible(False)
        else:
            self._show_window()

    def _update_tray(self):
        if not self.tray:
            return
        ctl = self.controller
        phase = ctl.phase()
        host = ctl.current_host
        name, flag = U.server_label(ctl, host)
        title = U.PHASE_TEXT.get(phase, U.PHASE_TEXT["disconnected"])[0]
        status_line = f"{title} – {name}" if phase in ("connected", "connecting", "reconnecting") else title
        favs = list(self.settings["favorites"])
        recent = [h for h in self.settings["recent"] if h not in favs][:5]
        signature = (phase, host, name, tuple(favs), tuple(recent), ctl.leak_protection, ctl.busy is None,
                     len(ctl.servers))
        self.tray.set_icon(TRAY_ICONS.get(phase, TRAY_ICONS["disconnected"]))
        tip = status_line
        if phase == "connected" and ctl.ext_ip4:
            tip += f"\nIP: {ctl.ext_ip4}"
        self.tray.set_tooltip(APP_NAME, tip)
        if signature == self._tray_signature:
            return
        self._tray_signature = signature

        current = C.short_name(host)
        items = [MenuItem(f"{flag}  {status_line}" if phase != "unavailable" else status_line, enabled=False),
                 MenuItem(separator=True)]
        if phase in ("connected", "connecting", "reconnecting"):
            items.append(MenuItem("Trennen", self.controller.disconnect_vpn, enabled=ctl.busy is None))
        else:
            items.append(MenuItem(f"Verbinden ({name})" if host else "Verbinden", self.controller.connect_vpn,
                                  enabled=ctl.available and ctl.busy is None and bool(host)))
        if phase == "blocked":
            items.append(MenuItem("Blockierung aufheben", self.controller.unblock, enabled=ctl.busy is None))

        server_items = []
        for h in favs:
            n, f = U.server_label(ctl, h)
            server_items.append(MenuItem(f"{f}  {n}", lambda h=h: self.controller.connect_vpn(h),
                                         toggle=(C.short_name(h) == current), enabled=ctl.available))
        if favs and recent:
            server_items.append(MenuItem(separator=True))
        for h in recent:
            n, f = U.server_label(ctl, h)
            server_items.append(MenuItem(f"{f}  {n}", lambda h=h: self.controller.connect_vpn(h),
                                         toggle=(C.short_name(h) == current), enabled=ctl.available))
        if server_items:
            server_items.append(MenuItem(separator=True))
        server_items.append(MenuItem("Alle Server …", self._show_servers))
        items.append(MenuItem("Server wechseln", children=server_items))
        items.append(MenuItem(separator=True))
        items.append(MenuItem("Kill-Switch", self._toggle_killswitch, toggle=ctl.leak_protection,
                              enabled=ctl.available and ctl.config is not None))
        items.append(MenuItem(separator=True))
        items.append(MenuItem("Fenster anzeigen", self._show_window))
        items.append(MenuItem("Einstellungen", lambda: self.activate_action("preferences", None)))
        items.append(MenuItem("Beenden", self.quit_app))
        self.tray.set_menu(items)

    def _show_servers(self):
        self._show_window()
        self.window.show_page("servers")

    def _toggle_killswitch(self):
        self.controller.update_config({"WireGuard": {"LeakProtection": not self.controller.leak_protection}})


def main(argv=None):
    app = Application()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
