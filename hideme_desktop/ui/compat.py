"""Bausteine, die mit libadwaita ab 1.2 funktionieren.

Neuere Widgets (SwitchRow, SpinRow, AlertDialog, PreferencesDialog, …) werden
genutzt, wenn vorhanden – sonst wird ein gleichwertiger Ersatz zusammengesetzt.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

ADW_VERSION = (Adw.get_major_version(), Adw.get_minor_version())


def adw_at_least(minor):
    return ADW_VERSION >= (1, minor)


class _Silent:
    """Unterdrückt Rückrufe, während Werte programmatisch gesetzt werden."""

    def __init__(self):
        self.silent = False

    def __enter__(self):
        self.silent = True

    def __exit__(self, *exc):
        self.silent = False


class SwitchRow:
    def __init__(self, title, subtitle="", active=False, on_toggle=None):
        self._quiet = _Silent()
        self.on_toggle = on_toggle
        if hasattr(Adw, "SwitchRow"):
            self.widget = Adw.SwitchRow(title=title)
            self._switch = None
            self.widget.set_active(active)
            self.widget.connect("notify::active", self._changed)
        else:
            self.widget = Adw.ActionRow(title=title)
            self._switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=active)
            self.widget.add_suffix(self._switch)
            self.widget.set_activatable_widget(self._switch)
            self._switch.connect("notify::active", self._changed)
        if subtitle:
            self.widget.set_subtitle(subtitle)

    def _changed(self, *_a):
        if not self._quiet.silent and self.on_toggle:
            self.on_toggle(self.get_active())

    def get_active(self):
        return (self._switch or self.widget).get_active()

    def set_active(self, value):
        with self._quiet:
            (self._switch or self.widget).set_active(bool(value))

    def set_sensitive(self, value):
        self.widget.set_sensitive(value)

    def set_subtitle(self, text):
        self.widget.set_subtitle(text)


class SpinRow:
    def __init__(self, title, subtitle="", lower=0, upper=100, step=1, value=0, digits=0, on_change=None):
        self._quiet = _Silent()
        self.on_change = on_change
        adj = Gtk.Adjustment(lower=lower, upper=upper, step_increment=step, page_increment=step * 10, value=value)
        if hasattr(Adw, "SpinRow"):
            self.widget = Adw.SpinRow(title=title, adjustment=adj, digits=digits)
            self._spin = self.widget
        else:
            self.widget = Adw.ActionRow(title=title)
            self._spin = Gtk.SpinButton(adjustment=adj, digits=digits, valign=Gtk.Align.CENTER)
            self.widget.add_suffix(self._spin)
        if subtitle:
            self.widget.set_subtitle(subtitle)
        self._timeout = 0
        self._spin.connect("notify::value", self._changed)

    def _changed(self, *_a):
        if self._quiet.silent or not self.on_change:
            return
        if self._timeout:
            GLib.source_remove(self._timeout)
        self._timeout = GLib.timeout_add(700, self._fire)

    def _fire(self):
        self._timeout = 0
        self.on_change(self.get_value())
        return False

    def get_value(self):
        return self._spin.get_value()

    def set_value(self, value):
        with self._quiet:
            self._spin.set_value(value)


class EntryRow:
    """Eingabezeile mit Übernehmen-Knopf; ``on_apply`` erhält den Text."""

    def __init__(self, title, text="", on_apply=None, password=False, placeholder=""):
        self._quiet = _Silent()
        self.on_apply = on_apply
        if hasattr(Adw, "EntryRow"):
            cls = Adw.PasswordEntryRow if password and hasattr(Adw, "PasswordEntryRow") else Adw.EntryRow
            self.widget = cls(title=title)
            if hasattr(self.widget, "set_show_apply_button"):
                self.widget.set_show_apply_button(True)
                self.widget.connect("apply", lambda *_a: self._apply())
            self.widget.connect("entry-activated", lambda *_a: self._apply())
            self._entry = self.widget
        else:
            self.widget = Adw.ActionRow(title=title)
            self._entry = Gtk.PasswordEntry(show_peek_icon=True) if password else Gtk.Entry()
            self._entry.set_valign(Gtk.Align.CENTER)
            self._entry.set_hexpand(True)
            self._entry.connect("activate", lambda *_a: self._apply())
            self.widget.add_suffix(self._entry)
            btn = Gtk.Button(icon_name="object-select-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Übernehmen")
            btn.add_css_class("flat")
            btn.connect("clicked", lambda *_a: self._apply())
            self.widget.add_suffix(btn)
        if placeholder and hasattr(self._entry, "set_placeholder_text"):
            try:
                self._entry.set_placeholder_text(placeholder)
            except (AttributeError, TypeError):
                pass
        self.set_text(text)

    def _apply(self):
        if not self._quiet.silent and self.on_apply:
            self.on_apply(self.get_text())

    def get_text(self):
        return self._entry.get_text()

    def set_text(self, text):
        with self._quiet:
            self._entry.set_text(text or "")

    def add_suffix(self, widget):
        self.widget.add_suffix(widget)

    def set_error(self, error):
        if error:
            self.widget.add_css_class("error")
        else:
            self.widget.remove_css_class("error")


class ComboRow:
    def __init__(self, title, options, subtitle="", selected=0, on_select=None):
        """``options`` ist eine Liste von (wert, beschriftung)."""
        self._quiet = _Silent()
        self.on_select = on_select
        self.values = [v for v, _l in options]
        self.widget = Adw.ComboRow(title=title, model=Gtk.StringList.new([l for _v, l in options]))
        if subtitle:
            self.widget.set_subtitle(subtitle)
        self.widget.set_selected(selected)
        self.widget.connect("notify::selected", self._changed)

    def _changed(self, *_a):
        if not self._quiet.silent and self.on_select:
            idx = self.widget.get_selected()
            if 0 <= idx < len(self.values):
                self.on_select(self.values[idx])

    def set_value(self, value):
        with self._quiet:
            if value in self.values:
                self.widget.set_selected(self.values.index(value))

    def get_value(self):
        idx = self.widget.get_selected()
        return self.values[idx] if 0 <= idx < len(self.values) else None


def button_row(title, subtitle, label, callback, style=None):
    row = Adw.ActionRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    btn = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if style:
        btn.add_css_class(style)
    btn.connect("clicked", lambda *_a: callback())
    row.add_suffix(btn)
    row.button = btn
    return row


class _RowValue:
    """Wert einer Eigenschaftszeile (als Untertitel dargestellt)."""

    def __init__(self, row):
        self.row = row
        self.text = ""

    def set_text(self, text):
        self.text = text or "–"
        self.row.set_subtitle(GLib.markup_escape_text(self.text))

    def get_text(self):
        return self.text


def info_row(title, value="", copyable=False):
    """Zeile im Stil „Bezeichnung / Wert“ (libadwaita-Klasse ``property`` ab 1.3)."""
    row = Adw.ActionRow(title=title)
    if adw_at_least(3):
        row.add_css_class("property")
        row.set_subtitle_selectable(True)
    row.value_label = _RowValue(row)
    row.value_label.set_text(value)
    if copyable:
        btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Kopieren")
        btn.add_css_class("flat")
        btn.connect("clicked", lambda *_a: copy_text(row, row.value_label.get_text()))
        row.add_suffix(btn)
    return row


def copy_text(widget, text):
    widget.get_clipboard().set(text)


class Banner:
    def __init__(self, title="", button_label="", on_click=None):
        self.on_click = on_click
        if hasattr(Adw, "Banner"):
            self.widget = Adw.Banner(title=title)
            if button_label:
                self.widget.set_button_label(button_label)
            self.widget.connect("button-clicked", lambda *_a: self.on_click and self.on_click())
            self._native = True
        else:
            self._native = False
            self.widget = Gtk.Revealer()
            box = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
            box.add_css_class("hm-banner")
            self._label = Gtk.Label(label=title, hexpand=True, wrap=True, xalign=0)
            box.append(self._label)
            self._button = Gtk.Button(label=button_label or "OK")
            self._button.connect("clicked", lambda *_a: self.on_click and self.on_click())
            self._button.set_visible(bool(button_label))
            box.append(self._button)
            self.widget.set_child(box)

    def set_title(self, title):
        if self._native:
            self.widget.set_title(title)
        else:
            self._label.set_text(title)

    def set_button_label(self, label):
        if self._native:
            self.widget.set_button_label(label or None)
        else:
            self._button.set_label(label or "")
            self._button.set_visible(bool(label))

    def set_revealed(self, revealed):
        if self._native:
            self.widget.set_revealed(revealed)
        else:
            self.widget.set_reveal_child(revealed)


def alert(parent, heading, body, responses=None, callback=None, default=None, destructive=None,
          extra_child=None):
    """Zeigt einen Dialog. ``responses`` ist eine Liste von (id, beschriftung)."""
    responses = responses or [("ok", "OK")]
    if hasattr(Adw, "AlertDialog"):
        dlg = Adw.AlertDialog(heading=heading, body=body)
    else:
        dlg = Adw.MessageDialog(transient_for=parent, modal=True, heading=heading, body=body)
    for rid, label in responses:
        dlg.add_response(rid, label)
    if default:
        dlg.set_default_response(default)
    if destructive:
        dlg.set_response_appearance(destructive, Adw.ResponseAppearance.DESTRUCTIVE)
    elif default and default != "cancel":
        dlg.set_response_appearance(default, Adw.ResponseAppearance.SUGGESTED)
    dlg.set_close_response("cancel" if any(r == "cancel" for r, _l in responses) else responses[0][0])
    if extra_child is not None:
        dlg.set_extra_child(extra_child)
    if callback:
        dlg.connect("response", lambda _d, rid: callback(rid))
    if hasattr(Adw, "AlertDialog"):
        dlg.present(parent)
    else:
        dlg.present()
    return dlg


def toast(target, text, timeout=3):
    t = Adw.Toast(title=GLib.markup_escape_text(text))
    t.set_timeout(timeout)
    target.add_toast(t)


def save_file(parent, title, suggested_name, callback):
    """Öffnet einen Speichern-Dialog; ``callback`` erhält den Pfad."""
    if hasattr(Gtk, "FileDialog"):
        dlg = Gtk.FileDialog(title=title, initial_name=suggested_name)

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            if f:
                callback(f.get_path())
        dlg.save(parent, None, done)
    else:
        dlg = Gtk.FileChooserNative(title=title, transient_for=parent, action=Gtk.FileChooserAction.SAVE)
        dlg.set_current_name(suggested_name)

        def resp(d, r):
            if r == Gtk.ResponseType.ACCEPT:
                callback(d.get_file().get_path())
            d.destroy()
        dlg.connect("response", resp)
        dlg.show()
        parent._hm_chooser = dlg


def open_file(parent, title, callback):
    if hasattr(Gtk, "FileDialog"):
        dlg = Gtk.FileDialog(title=title)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if f:
                callback(f.get_path())
        dlg.open(parent, None, done)
    else:
        dlg = Gtk.FileChooserNative(title=title, transient_for=parent, action=Gtk.FileChooserAction.OPEN)

        def resp(d, r):
            if r == Gtk.ResponseType.ACCEPT:
                callback(d.get_file().get_path())
            d.destroy()
        dlg.connect("response", resp)
        dlg.show()
        parent._hm_chooser = dlg


def present_dialog(dialog, parent):
    """Zeigt Adw.Dialog (1.5+) bzw. ein Fenster an."""
    if hasattr(Adw, "Dialog") and isinstance(dialog, Adw.Dialog):
        dialog.present(parent)
    else:
        dialog.set_transient_for(parent)
        dialog.present()


def preferences_container(parent, title):
    if hasattr(Adw, "PreferencesDialog"):
        dlg = Adw.PreferencesDialog(title=title)
        dlg.set_search_enabled(True)
        return dlg
    win = Adw.PreferencesWindow(title=title, transient_for=parent, modal=False)
    win.set_search_enabled(True)
    win.set_default_size(720, 680)
    return win


def open_uri(parent, uri):
    try:
        Gtk.show_uri(parent, uri, 0)
    except Exception:
        Gio.AppInfo.launch_default_for_uri(uri, None)
