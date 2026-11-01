"""Anmeldedialog: fordert mit Benutzername/Passwort ein Zugangstoken an."""

from gi.repository import Adw, Gtk

from .. import api as A
from .. import config as C
from .compat import SwitchRow


class LoginDialog(Adw.Window):
    def __init__(self, parent, controller, on_success=None):
        super().__init__(title="hide.me-Konto", modal=True, transient_for=parent,
                         default_width=460, default_height=-1, resizable=False)
        self.ctl = controller
        self.on_success = on_success

        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Abbrechen")
        cancel.connect("clicked", lambda *_a: self.close())
        header.pack_start(cancel)
        self.login_btn = Gtk.Button(label="Anmelden")
        self.login_btn.add_css_class("suggested-action")
        self.login_btn.connect("clicked", lambda *_a: self._login())
        header.pack_end(self.login_btn)
        self.spinner = Gtk.Spinner()
        header.pack_end(self.spinner)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(header)
        page = Adw.PreferencesPage()
        content.append(page)
        self.set_content(content)

        intro = Adw.PreferencesGroup(
            description="Mit deinen hide.me-Zugangsdaten wird einmalig ein Zugangstoken (Access-Token) "
                        "angefordert. Benutzername und Passwort werden nicht gespeichert.")
        page.add(intro)

        creds = Adw.PreferencesGroup(title="Zugangsdaten")
        self.username = Adw.EntryRow(title="Benutzername")
        self.password = Adw.PasswordEntryRow(title="Passwort") if hasattr(Adw, "PasswordEntryRow") else \
            Adw.EntryRow(title="Passwort")
        self.username.connect("entry-activated", lambda *_a: self.password.grab_focus())
        self.password.connect("entry-activated", lambda *_a: self._login())
        creds.add(self.username)
        creds.add(self.password)
        page.add(creds)

        opts = Adw.PreferencesGroup(title="Optionen")
        self.pf = SwitchRow("Port-Forwarding-Token",
                            "Hängt „@pf“ an den Benutzernamen an – Port-Forwarding ist dann bei jeder "
                            "Verbindung aktiv")
        opts.add(self.pf.widget)
        self.host = Adw.EntryRow(title="Server für die Token-Anfrage")
        self.host.set_text(C.short_name(controller.settings["token_host"] or "free"))
        opts.add(self.host)
        page.add(opts)

        self.error = Gtk.Label(wrap=True, xalign=0, margin_start=12, margin_end=12, visible=False)
        self.error.add_css_class("error")
        err_group = Adw.PreferencesGroup()
        err_group.add(self.error)
        page.add(err_group)

        self.username.grab_focus()

    def _login(self):
        user = self.username.get_text().strip()
        pw = self.password.get_text()
        if not user or not pw:
            self._show_error("Bitte Benutzername und Passwort eingeben.")
            return
        if self.pf.get_active() and not user.endswith("@pf"):
            user += "@pf"
        host = self.host.get_text().strip() or "free"
        self.ctl.settings["token_host"] = C.short_name(host)
        self._set_busy(True)
        self.error.set_visible(False)

        def done():
            self._set_busy(False)
            self.close()
            if self.on_success:
                self.on_success()

        def failed(exc):
            self._set_busy(False)
            msg = exc.message if isinstance(exc, A.ApiError) else str(exc)
            self._show_error(C.explain_error(msg))

        if not self.ctl.login(user, pw, host, done, failed):
            self._set_busy(False)
            self._show_error("Eine andere Aktion läuft noch – bitte gleich erneut versuchen.")

    def _set_busy(self, busy):
        self.login_btn.set_sensitive(not busy)
        for w in (self.username, self.password, self.host, self.pf.widget):
            w.set_sensitive(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

    def _show_error(self, text):
        self.error.set_text(text)
        self.error.set_visible(True)
