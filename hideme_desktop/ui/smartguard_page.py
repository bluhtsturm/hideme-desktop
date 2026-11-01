"""Seite "SmartGuard": DNS-basierte Filter des hide.me-Servers."""

import json
import os

from gi.repository import Adw, GLib, Gtk

from .. import cli
from .. import config as C
from ..settings import cache_dir
from .compat import ComboRow, SwitchRow
from .widgets import ListEditor


class SmartGuardView(Gtk.ScrolledWindow):
    def __init__(self, window, controller):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.ctl = controller
        self.filter = C.get_filter(controller.config)
        self._post_timer = 0
        self._categories = []
        self._cat_rows = {}

        page = Adw.PreferencesPage()
        self.set_child(page)

        intro = Adw.PreferencesGroup(
            title="SmartGuard",
            description="DNS-basierter Filter, der auf dem hide.me-Server läuft. Änderungen werden beim "
                        "nächsten Verbindungsaufbau aktiv.")
        self.enabled_row = Adw.ActionRow(title="Status", subtitle="Aus")
        self.enabled_row.add_prefix(Gtk.Image(icon_name="hideme-filter-symbolic"))
        self.reset_btn = Gtk.Button(label="Alle Filter aus", valign=Gtk.Align.CENTER)
        self.reset_btn.add_css_class("flat")
        self.reset_btn.connect("clicked", lambda *_a: self._reset())
        self.enabled_row.add_suffix(self.reset_btn)
        intro.add(self.enabled_row)
        page.add(intro)

        protect = Adw.PreferencesGroup(title="Schutz")
        self.switches = {}
        for key, title, subtitle in C.FILTER_SWITCHES:
            sw = SwitchRow(title, subtitle, on_toggle=lambda v, k=key: self._set(k, v))
            self.switches[key] = sw
            protect.add(sw.widget)
        page.add(protect)

        family = Adw.PreferencesGroup(title="Jugendschutz")
        self.pg = ComboRow("Altersfreigabe", [(0, "Aus"), (12, "Ab 12 Jahren"), (18, "Ab 18 Jahren"),
                                              (21, "Ab 21 Jahren")],
                           subtitle="Filtert ungeeignete Inhalte nach Altersgrenze (--pg)",
                           on_select=lambda v: self._set("PG", v))
        family.add(self.pg.widget)
        page.add(family)

        risk = Adw.PreferencesGroup(title="Risikostufen",
                                    description="Inhalte nach eingeschätztem Risiko filtern (--noRisk)")
        self.risk_switches = {}
        for key, label in C.RISK_LEVELS:
            sw = SwitchRow(label, on_toggle=lambda v, k=key: self._set_list("risk", k, v))
            self.risk_switches[key] = sw
            risk.add(sw.widget)
        page.add(risk)

        illegal = Adw.PreferencesGroup(title="Illegale Inhalte", description="Grobe Filterung (--noIllegal)")
        self.illegal_switches = {}
        for key, label in C.ILLEGAL_KINDS:
            sw = SwitchRow(label, on_toggle=lambda v, k=key: self._set_list("illegal", k, v))
            self.illegal_switches[key] = sw
            illegal.add(sw.widget)
        page.add(illegal)

        cats = Adw.PreferencesGroup(title="Kategorien",
                                    description="Feingranulare Filterung nach Inhaltskategorien (--noCategories)")
        self.cat_expander = Adw.ExpanderRow(title="Gesperrte Kategorien", subtitle="Keine")
        self.cat_spinner = Gtk.Spinner()
        load = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Kategorienliste vom hide.me-Server laden")
        load.add_css_class("flat")
        load.connect("clicked", lambda *_a: self._load_categories(force=True))
        if hasattr(self.cat_expander, "add_suffix"):
            self.cat_expander.add_suffix(self.cat_spinner)
            self.cat_expander.add_suffix(load)
        else:
            self.cat_expander.add_action(load)
        self.cat_expander.connect("notify::expanded", self._cat_expanded)
        self.cat_search_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        self.cat_search = Gtk.SearchEntry(placeholder_text="Kategorien durchsuchen", hexpand=True,
                                          valign=Gtk.Align.CENTER, margin_top=8, margin_bottom=8,
                                          margin_start=12, margin_end=12)
        self.cat_search.connect("search-changed", lambda *_a: self._filter_categories())
        self.cat_search_row.set_child(self.cat_search)
        self.cat_expander.add_row(self.cat_search_row)
        cats.add(self.cat_expander)
        page.add(cats)

        lists = Adw.PreferencesGroup(title="Eigene Listen",
                                     description="Domain-Namen, Platzhalter „*“ sind erlaubt (z. B. *.example.com)")
        self.whitelist = ListEditor("Immer erlauben", "Umgehen jeden Filter (--whitelist)",
                                    validator=C.valid_dns_name, error_text="Ungültiger DNS-Name",
                                    on_change=lambda items: self._set("whitelist", items),
                                    placeholder="example.com", add_title="Domain hinzufügen")
        self.blacklist = ListEditor("Immer sperren", "Werden immer gefiltert (--blacklist)",
                                    validator=C.valid_dns_name, error_text="Ungültiger DNS-Name",
                                    on_change=lambda items: self._set("blacklist", items),
                                    placeholder="ads.example.com", add_title="Domain hinzufügen")
        lists.add(self.whitelist.widget)
        lists.add(self.blacklist.widget)
        page.add(lists)

        self.ctl.connect("config-changed", lambda *_a: self.load_from_config())
        self.ctl.connect("changed", lambda *_a: self.set_sensitive(self.ctl.config is not None))
        self._load_cached_categories()
        self.load_from_config()

    # ------------------------------------------------------------------
    def load_from_config(self):
        if self._post_timer:
            return  # lokale Änderung wartet noch auf Übertragung
        self.filter = C.get_filter(self.ctl.config)
        f = self.filter
        for key, sw in self.switches.items():
            sw.set_active(f.get(key))
        self.pg.set_value(f.get("PG") or 0)
        for key, sw in self.risk_switches.items():
            sw.set_active(key in f["risk"])
        for key, sw in self.illegal_switches.items():
            sw.set_active(key in f["illegal"])
        self.whitelist.set_items(f["whitelist"])
        self.blacklist.set_items(f["blacklist"])
        self._sync_categories()
        self._update_summary()
        self.set_sensitive(self.ctl.config is not None)

    def _update_summary(self):
        active = C.filter_active(self.filter)
        self.enabled_row.set_subtitle(C.filter_summary(self.filter) if active else "Aus – keine Filter aktiv")
        self.reset_btn.set_sensitive(active)
        cats = self.filter["categories"]
        self.cat_expander.set_subtitle(", ".join(cats[:4]) + (" …" if len(cats) > 4 else "") if cats else "Keine")

    def _set(self, key, value):
        self.filter[key] = value
        self._schedule_post()

    def _set_list(self, key, item, enabled):
        items = [i for i in self.filter[key] if i != item]
        if enabled:
            items.append(item)
        self.filter[key] = items
        self._schedule_post()

    def _reset(self):
        self.filter = C.get_filter({})
        self._schedule_post(0)

    def _schedule_post(self, delay=400):
        self._update_summary()
        if self._post_timer:
            GLib.source_remove(self._post_timer)
        self._post_timer = GLib.timeout_add(delay, self._post)

    def _post(self):
        self._post_timer = 0
        f = dict(self.filter)
        payload = {
            "forceDns": bool(f.get("forceDns")), "ads": bool(f.get("ads")), "trackers": bool(f.get("trackers")),
            "malware": bool(f.get("malware")), "safeSearch": bool(f.get("safeSearch")),
            "malicious": bool(f.get("malicious")), "PG": int(f.get("PG") or 0),
            "risk": list(f["risk"]), "illegal": list(f["illegal"]), "whitelist": list(f["whitelist"]),
            "blacklist": list(f["blacklist"]), "categories": list(f["categories"]),
        }
        self.ctl.update_config({"Rest": {"Filter": payload}})
        return False

    # Kategorien ---------------------------------------------------------------
    def _cache_file(self):
        return os.path.join(cache_dir(), "categories.json")

    def _load_cached_categories(self):
        try:
            with open(self._cache_file(), encoding="utf-8") as fh:
                data = json.load(fh)
            self._categories = [tuple(x) for x in data if isinstance(x, list) and len(x) == 2]
        except (OSError, ValueError):
            self._categories = []
        self._build_category_rows()

    def _cat_expanded(self, *_a):
        if self.cat_expander.get_expanded() and not self._categories:
            self._load_categories()

    def _load_categories(self, force=False):
        if self.cat_spinner.get_spinning():
            return
        host = self.ctl.current_host or "free"
        self.cat_spinner.start()

        def done(cats):
            self.cat_spinner.stop()
            self._categories = cats
            try:
                os.makedirs(cache_dir(), exist_ok=True)
                with open(self._cache_file(), "w", encoding="utf-8") as fh:
                    json.dump([list(c) for c in cats], fh)
            except OSError:
                pass
            self._build_category_rows()

        def failed(exc):
            self.cat_spinner.stop()
            self.window.toast(f"Kategorien konnten nicht geladen werden: {exc}")
        self.ctl.run_bg(lambda: cli.categories(C.short_name(host)), done, failed)

    def _build_category_rows(self):
        for row in list(self._cat_rows.values()):
            self.cat_expander.remove(row.widget)
        self._cat_rows = {}
        names = [n for n, _d in self._categories]
        extra = [c for c in self.filter["categories"] if c not in names]
        for name, desc in list(self._categories) + [(c, "Manuell gesetzt") for c in extra]:
            sw = SwitchRow(name, desc, active=name in self.filter["categories"],
                           on_toggle=lambda v, n=name: self._set_list("categories", n, v))
            self._cat_rows[name] = sw
            self.cat_expander.add_row(sw.widget)
        self._filter_categories()

    def _sync_categories(self):
        names = set(self._cat_rows)
        if any(c not in names for c in self.filter["categories"]):
            self._build_category_rows()
            return
        for name, sw in self._cat_rows.items():
            sw.set_active(name in self.filter["categories"])

    def _filter_categories(self):
        query = self.cat_search.get_text().casefold().strip()
        for name, sw in self._cat_rows.items():
            text = (name + " " + (sw.widget.get_subtitle() or "")).casefold()
            sw.widget.set_visible(not query or query in text)
