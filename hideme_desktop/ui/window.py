"""Hauptfenster."""

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_NAME, DAEMON_GROUP, system
from .compat import Banner, alert, toast
from .log_page import LogView
from .login_dialog import LoginDialog
from .preferences import Preferences
from .servers_page import ServersView
from .smartguard_page import SmartGuardView
from .status_page import StatusView
from .tools import ToolsWindow


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, controller):
        super().__init__(application=app, title=APP_NAME, default_width=760, default_height=840)
        self.set_size_request(360, 500)
        self.app = app
        self.ctl = controller
        self._tools = None
        self._login = None

        self.toasts = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toasts.set_child(root)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack(vexpand=True)
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Einstellungen", "app.preferences")
        section.append("Konto", "app.account")
        section.append("Werkzeuge", "app.tools")
        menu.append_section(None, section)
        section2 = Gio.Menu()
        section2.append("Tastenkürzel", "win.show-help-overlay")
        section2.append(f"Über {APP_NAME}", "app.about")
        section2.append("Beenden", "app.quit")
        menu.append_section(None, section2)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Hauptmenü",
                                  primary=True)
        header.pack_end(menu_btn)
        self.busy_spinner = Gtk.Spinner(tooltip_text="Aktion läuft …")
        header.pack_start(self.busy_spinner)
        root.append(header)

        self.banner = Banner("Einige Einstellungen werden erst nach einer Neuverbindung wirksam.",
                             "Neu verbinden", lambda: self.ctl.reconnect())
        root.append(self.banner.widget)

        self.outer = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        root.append(self.outer)
        self.outer.add_named(self.view_stack, "main")
        self.unavailable = self._build_unavailable()
        self.outer.add_named(self.unavailable, "unavailable")

        self.status_view = StatusView(self, controller)
        self.servers_view = ServersView(self, controller)
        self.smartguard_view = SmartGuardView(self, controller)
        self.log_view = LogView(self, controller)
        self._add_page(self.status_view, "status", "Status", "hideme-shield-symbolic")
        self._add_page(self.servers_view, "servers", "Server", "mark-location-symbolic")
        self._add_page(self.smartguard_view, "smartguard", "SmartGuard", "hideme-filter-symbolic")
        self._add_page(self.log_view, "log", "Protokoll", "utilities-terminal-symbolic")
        self.view_stack.connect("notify::visible-child-name", self._page_changed)

        bottom = Adw.ViewSwitcherBar(stack=self.view_stack)
        root.append(bottom)
        if hasattr(Adw, "Breakpoint"):
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 660sp"))
            bp.add_setter(bottom, "reveal", True)
            bp.add_setter(header, "title-widget", Gtk.Label(label=APP_NAME, css_classes=["title"]))
            self.add_breakpoint(bp)

        self._install_shortcuts()
        controller.connect("changed", lambda *_a: self.refresh())
        controller.connect("error", self._on_error)
        controller.connect("notice", lambda _c, text: self.toast(text))
        controller.connect("login-required", lambda *_a: self.show_login(connect_after=True))
        self.refresh()

    def _add_page(self, widget, name, title, icon):
        page = self.view_stack.add_titled(widget, name, title)
        page.set_icon_name(icon)

    def _install_shortcuts(self):
        ctrl = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        for i, name in enumerate(("status", "servers", "smartguard", "log"), start=1):
            ctrl.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(f"<Alt>{i}"),
                                           action=Gtk.CallbackAction.new(lambda *_a, n=name: self.show_page(n)
                                                                         or True)))
        ctrl.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>f"),
                                       action=Gtk.CallbackAction.new(self._focus_search)))
        self.add_controller(ctrl)
        try:
            builder = Gtk.Builder.new_from_string(_SHORTCUTS_UI, -1)
            self.set_help_overlay(builder.get_object("help_overlay"))
        except (GLib.Error, AttributeError, TypeError):
            pass

    def _focus_search(self, *_a):
        self.show_page("servers")
        self.servers_view.search.grab_focus()
        return True

    def _page_changed(self, *_a):
        if self.view_stack.get_visible_child_name() == "log":
            self.log_view.on_shown()

    def _build_unavailable(self):
        page = Adw.StatusPage(icon_name="network-offline-symbolic", title="Daemon nicht erreichbar")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self.unavail_start = Gtk.Button(label="Daemon starten")
        self.unavail_start.add_css_class("pill")
        self.unavail_start.add_css_class("suggested-action")
        self.unavail_start.connect("clicked", lambda *_a: self._start_daemon())
        box.append(self.unavail_start)
        self.unavail_relaunch = Gtk.Button(label="App mit Gruppenrechten neu starten")
        self.unavail_relaunch.add_css_class("pill")
        self.unavail_relaunch.connect("clicked", lambda *_a: self._relaunch())
        box.append(self.unavail_relaunch)
        retry = Gtk.Button(label="Erneut versuchen")
        retry.add_css_class("pill")
        retry.connect("clicked", lambda *_a: self.ctl.poll_now())
        box.append(retry)
        settings = Gtk.Button(label="Steueradresse ändern …")
        settings.add_css_class("flat")
        settings.connect("clicked", lambda *_a: self.show_preferences("advanced"))
        box.append(settings)
        page.set_child(box)
        return page

    def _start_daemon(self):
        self.unavail_start.set_sensitive(False)

        def done(_r):
            self.unavail_start.set_sensitive(True)
            GLib.timeout_add_seconds(1, lambda: (self.ctl.poll_now(), False)[1])

        def failed(exc):
            self.unavail_start.set_sensitive(True)
            self.toast(f"Start fehlgeschlagen: {exc}")
        self.ctl.run_bg(system.start_daemon, done, failed)

    def _relaunch(self):
        self.app.relaunch_with_group()

    def _unavailable_text(self):
        ctl = self.ctl
        exists, member, active = system.group_status()
        kind = ctl.unavailable_kind
        lines = [ctl.unavailable_reason]
        show_start = False
        show_relaunch = False
        if kind == "permission":
            if exists and member and not active:
                lines.append(f"Du bist Mitglied der Gruppe „{DAEMON_GROUP}“, die aktuelle Sitzung kennt die "
                             "Mitgliedschaft aber noch nicht. Melde dich einmal ab und wieder an – oder starte die "
                             "App mit Gruppenrechten neu.")
                show_relaunch = True
            elif exists and not member:
                lines.append(f"Dein Benutzer muss Mitglied der Gruppe „{DAEMON_GROUP}“ sein:\n"
                             f"sudo usermod -aG {DAEMON_GROUP} $USER")
            else:
                lines.append("Fehlende Berechtigung für den Steuer-Socket.")
        elif kind in ("missing", "refused"):
            lines.append("Der hide.me-Daemon läuft nicht. Er wird mit dem Installationsskript eingerichtet "
                         "(sudo ./install.sh) und als systemd-Dienst gestartet.")
            show_start = True
        return "\n\n".join(l for l in lines if l), show_start, show_relaunch

    def refresh(self):
        ctl = self.ctl
        if ctl.available or ctl.unavailable_kind == "unknown":
            # "unknown": erster Verbindungsversuch läuft noch – keine Fehlerseite aufblitzen lassen
            self.outer.set_visible_child_name("main")
        else:
            text, show_start, show_relaunch = self._unavailable_text()
            self.unavailable.set_description(text)
            self.unavail_start.set_visible(show_start)
            self.unavail_relaunch.set_visible(show_relaunch)
            self.outer.set_visible_child_name("unavailable")
        self.banner.set_revealed(ctl.available and ctl.pending_changes and ctl.code == "connected")
        if ctl.busy:
            self.busy_spinner.start()
            self.busy_spinner.set_visible(True)
        else:
            self.busy_spinner.stop()
            self.busy_spinner.set_visible(False)

    # ------------------------------------------------------------------ öffentlich
    def toast(self, text):
        toast(self.toasts, text)

    def show_page(self, name):
        self.view_stack.set_visible_child_name(name)

    def show_preferences(self, page=None):
        prefs = Preferences(self, self.ctl)
        prefs.present(page)

    def show_tools(self):
        if self._tools is None or not self._tools.get_visible():
            self._tools = ToolsWindow(self, self.ctl)
        self._tools.present()

    def show_login(self, connect_after=False):
        if not self.ctl.available:
            self.toast("Der Daemon ist nicht erreichbar.")
            return
        if self._login is not None and self._login.get_visible():
            self._login.present()
            return

        def success():
            if connect_after and self.ctl.current_host:
                self.ctl.connect_vpn()
        self._login = LoginDialog(self, self.ctl, success)
        self._login.present()

    def _on_error(self, _ctl, title, message):
        if self.get_visible() and self.is_active():
            alert(self, title, message)
        else:
            self.toast(f"{title}: {message.splitlines()[0]}")


_SHORTCUTS_UI = """
<interface>
  <object class="GtkShortcutsWindow" id="help_overlay">
    <property name="modal">True</property>
    <child>
      <object class="GtkShortcutsSection">
        <property name="section-name">shortcuts</property>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">Allgemein</property>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Verbinden / Trennen</property>
              <property name="accelerator">&lt;Control&gt;Return</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Server suchen</property>
              <property name="accelerator">&lt;Control&gt;f</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Einstellungen</property>
              <property name="accelerator">&lt;Control&gt;comma</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Fenster schließen</property>
              <property name="accelerator">&lt;Control&gt;w</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Beenden</property>
              <property name="accelerator">&lt;Control&gt;q</property>
            </object></child>
          </object>
        </child>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">Seiten</property>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Status</property>
              <property name="accelerator">&lt;Alt&gt;1</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Server</property>
              <property name="accelerator">&lt;Alt&gt;2</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">SmartGuard</property>
              <property name="accelerator">&lt;Alt&gt;3</property>
            </object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Protokoll</property>
              <property name="accelerator">&lt;Alt&gt;4</property>
            </object></child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>
"""
