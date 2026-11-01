"""Wiederverwendbare Widgets."""

from gi.repository import Adw, Gtk

from .compat import EntryRow


class ListEditor:
    """Bearbeitbare Liste als ausklappbare Zeile (z. B. Split-Tunnel-Netze, DNS-Server)."""

    def __init__(self, title, subtitle="", validator=None, on_change=None, placeholder="",
                 add_title="Eintrag hinzufügen", error_text="Ungültiger Eintrag", empty_text="Keine Einträge"):
        self.validator = validator
        self.on_change = on_change
        self.error_text = error_text
        self.empty_text = empty_text
        self.base_subtitle = subtitle
        self.items = []
        self._rows = []
        self.widget = Adw.ExpanderRow(title=title)
        self.widget.set_subtitle(subtitle)
        self._add = EntryRow(add_title, on_apply=self._on_add, placeholder=placeholder)
        add_btn = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Hinzufügen")
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", lambda *_a: self._on_add(self._add.get_text()))
        self._add.add_suffix(add_btn)
        self.widget.add_row(self._add.widget)
        self._update_subtitle()

    def _update_subtitle(self):
        count = len(self.items)
        summary = f"{count} Einträge" if count != 1 else "1 Eintrag"
        if count == 0:
            summary = self.empty_text
        elif count <= 3:
            summary = ", ".join(self.items)
        self.widget.set_subtitle(f"{self.base_subtitle}\n{summary}" if self.base_subtitle else summary)

    def set_items(self, items):
        items = [i for i in (items or []) if i]
        if items == self.items:
            return
        for row in self._rows:
            self.widget.remove(row)
        self._rows = []
        self.items = []
        for item in items:
            self._append_row(item)
        self._update_subtitle()

    def _append_row(self, item):
        row = Adw.ActionRow(title=item)
        try:
            row.set_title_selectable(True)
        except AttributeError:
            pass
        btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Entfernen")
        btn.add_css_class("flat")
        btn.connect("clicked", lambda *_a, r=row, i=item: self._remove(r, i))
        row.add_suffix(btn)
        self.widget.add_row(row)
        self._rows.append(row)
        self.items.append(item)

    def _remove(self, row, item):
        if row in self._rows:
            self.widget.remove(row)
            self._rows.remove(row)
        if item in self.items:
            self.items.remove(item)
        self._update_subtitle()
        if self.on_change:
            self.on_change(list(self.items))

    def _on_add(self, text):
        value = (text or "").strip()
        if not value:
            return
        if self.validator and not self.validator(value):
            self._add.set_error(True)
            self._add.widget.set_tooltip_text(self.error_text)
            return
        self._add.set_error(False)
        self._add.widget.set_tooltip_text(None)
        if value not in self.items:
            self._append_row(value)
            self._update_subtitle()
            if self.on_change:
                self.on_change(list(self.items))
        self._add.set_text("")


def tag_label(text, css=None):
    label = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    label.add_css_class("hm-tag")
    if css:
        label.add_css_class(css)
    return label
