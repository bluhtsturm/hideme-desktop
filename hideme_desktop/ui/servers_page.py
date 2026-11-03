"""Seite "Server": Standortliste mit Suche, Favoriten und Filter."""

from gi.repository import Adw, Gtk

from .. import config as C
from . import util as U
from .compat import EntryRow
from .widgets import tag_label


def _norm(text):
    return (text or "").casefold()


class ServersView(Gtk.Box):
    def __init__(self, window, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.ctl = controller
        self.settings = controller.settings
        self._rows = []  # (row, searchable_text, is_free, parent_expander_or_None, host)
        self._expanders = []
        self._current_marks = {}
        self._fav_rows = []

        bar = Gtk.Box(spacing=8, margin_top=10, margin_bottom=6, margin_start=12, margin_end=12)
        clamp_bar = Adw.Clamp(maximum_size=720)
        clamp_bar.set_child(bar)
        self.search = Gtk.SearchEntry(placeholder_text="Land, Stadt oder Servername suchen", hexpand=True)
        self.search.connect("search-changed", lambda *_a: self._apply_filter())
        bar.append(self.search)
        self.free_toggle = Gtk.ToggleButton(label="Nur kostenlose", active=self.settings["free_only"],
                                            tooltip_text="Nur Server anzeigen, die mit einem kostenlosen Konto nutzbar sind")
        self.free_toggle.connect("toggled", self._free_toggled)
        bar.append(self.free_toggle)
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Serverliste neu laden")
        self.refresh_btn.connect("clicked", lambda *_a: self.ctl.refresh_servers())
        bar.append(self.refresh_btn)
        self.append(clamp_bar)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.append(self.stack)

        loading = Adw.StatusPage(title="Serverliste wird geladen …")
        spinner = Gtk.Spinner(width_request=32, height_request=32, halign=Gtk.Align.CENTER)
        spinner.start()
        loading.set_child(spinner)
        self.stack.add_named(loading, "loading")

        self.error_page = Adw.StatusPage(icon_name="network-error-symbolic", title="Serverliste nicht verfügbar")
        retry = Gtk.Button(label="Erneut versuchen", halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.add_css_class("suggested-action")
        retry.connect("clicked", lambda *_a: self.ctl.refresh_servers())
        err_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        err_box.append(retry)
        self.manual_err = EntryRow("Server manuell eingeben (z. B. nl, amsterdam, 1.2.3.4)",
                                   on_apply=self._manual_connect)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        lb.append(self.manual_err.widget)
        clamp_err = Adw.Clamp(maximum_size=480)
        clamp_err.set_child(lb)
        err_box.append(clamp_err)
        self.error_page.set_child(err_box)
        self.stack.add_named(self.error_page, "error")

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=720, margin_top=6, margin_bottom=24, margin_start=12, margin_end=12)
        scroller.set_child(clamp)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(self.list_box)
        self.stack.add_named(scroller, "list")

        self.fav_group = Adw.PreferencesGroup(title="Favoriten")
        self._groups = []
        self.no_match = Adw.PreferencesGroup(description="Keine passenden Standorte gefunden.")
        self.no_match.set_visible(False)
        self.manual_group = Adw.PreferencesGroup(
            title="Eigener Server", description="Hostname, Kurzname (z. B. „nl“) oder IP-Adresse eines hide.me-Servers")
        self.manual = EntryRow("Server", on_apply=self._manual_connect)
        go = Gtk.Button(label="Verbinden", valign=Gtk.Align.CENTER)
        go.add_css_class("flat")
        go.connect("clicked", lambda *_a: self._manual_connect(self.manual.get_text()))
        self.manual.add_suffix(go)
        self.manual_group.add(self.manual.widget)
        self.list_box.append(self.fav_group)
        self.list_box.append(self.no_match)
        self.list_box.append(self.manual_group)

        self.ctl.connect("servers-changed", lambda *_a: self.rebuild())
        self.ctl.connect("changed", lambda *_a: self._update_current())
        self.settings.connect_changed(self._settings_changed)
        self.rebuild()

    # ------------------------------------------------------------------
    def _settings_changed(self, key, _value):
        if key == "favorites":
            self.rebuild()

    def _free_toggled(self, btn):
        self.settings["free_only"] = btn.get_active()
        self._apply_filter()

    def _manual_connect(self, text):
        text = (text or "").strip()
        if not text:
            return
        self.ctl.connect_vpn(text)
        self.window.show_page("status")

    def _connect(self, host):
        self.ctl.connect_vpn(host)
        self.window.show_page("status")

    def _make_row(self, loc, parent_name=None, expander=None):
        host = C.short_name(loc.get("hostname") or "")
        name = loc.get("displayName") or host
        tags = [t for t in (loc.get("tags") or []) if t]
        country = U.location_country(loc)
        row = Adw.ActionRow(title=name, activatable=True)
        geo = loc.get("geo") or {}
        sub = host
        if geo.get("cityName") and geo.get("cityName") not in name:
            sub = f"{geo['cityName']} · {host}"
        row.set_subtitle(sub)
        flag = Gtk.Label(label=U.flag_emoji(country))
        flag.add_css_class("hm-flag")
        row.add_prefix(flag)
        self._add_common_suffixes(row, host, tags)
        row.connect("activated", lambda *_a, h=host: self._connect(h))
        self._rows.append((row, self._search_text(loc, parent_name), "free" in tags, expander, host))
        return row

    @staticmethod
    def _search_text(loc, parent_name=None):
        geo = loc.get("geo") or {}
        tags = loc.get("tags") or []
        parts = [loc.get("displayName"), C.short_name(loc.get("hostname") or ""), parent_name,
                 U.location_country(loc), geo.get("cityName"), U.continent_name(geo.get("continent"))]
        parts += [U.TAG_LABELS.get(t, "") for t in tags]
        return " ".join(_norm(p) for p in parts if p)

    def _add_common_suffixes(self, row, host, tags=()):
        widgets = [tag_label(label, css) for label, css in U.visible_tags(tags)]
        current = Gtk.Image(icon_name="object-select-symbolic", tooltip_text="Aktueller Server")
        current.add_css_class("hm-current")
        current.set_visible(False)
        widgets.append(current)
        self._current_marks.setdefault(host, []).append(current)
        fav = self.settings.is_favorite(host)
        star = Gtk.Button(icon_name="starred-symbolic" if fav else "non-starred-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Favorit entfernen" if fav else "Als Favorit markieren")
        star.add_css_class("flat")
        star.connect("clicked", lambda *_a, h=host: self.settings.toggle_favorite(h))
        widgets.append(star)
        connect = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Verbinden")
        connect.add_css_class("flat")
        connect.connect("clicked", lambda *_a, h=host: self._connect(h))
        widgets.append(connect)
        # Adw.ExpanderRow fügt Suffixe vorne ein, Adw.ActionRow hinten
        for widget in (reversed(widgets) if isinstance(row, Adw.ExpanderRow) else widgets):
            row.add_suffix(widget)

    def _make_expander(self, loc):
        children = loc.get("children") or []
        host = C.short_name(loc.get("hostname") or "")
        tags = [t for t in (loc.get("tags") or []) if t]
        exp = Adw.ExpanderRow(title=loc.get("displayName") or host)
        exp.set_subtitle(f"{host} · {len(children) + 1} Server")
        flag = Gtk.Label(label=U.flag_emoji(U.location_country(loc)))
        flag.add_css_class("hm-flag")
        exp.add_prefix(flag)
        if hasattr(exp, "add_suffix"):
            self._add_common_suffixes(exp, host, tags)
        else:
            exp.add_action(self._connect_button(host))
        self._expanders.append((exp, self._search_text(loc), "free" in tags, host))
        for child in sorted(children, key=self._sort_key):
            exp.add_row(self._make_row(child, exp.get_title(), exp))
        return exp

    @staticmethod
    def _sort_key(loc):
        return _norm(loc.get("displayName") or loc.get("hostname"))

    def rebuild(self):
        self._rows = []
        self._expanders = []
        self._current_marks = {}
        self._fav_rows = []
        for group in [self.fav_group] + [g for g, _m in self._groups]:
            if group.get_parent() is not None:
                self.list_box.remove(group)
        self._groups = []
        self.fav_group = Adw.PreferencesGroup(title="Favoriten")
        self.list_box.prepend(self.fav_group)

        servers = self.ctl.servers or []
        if not servers:
            if self.ctl.servers_loading:
                self.stack.set_visible_child_name("loading")
            else:
                self.error_page.set_description(self.ctl.servers_error or
                                                "Die Serverliste konnte nicht vom Daemon abgerufen werden.")
                self.stack.set_visible_child_name("error")
            return
        self.stack.set_visible_child_name("list")
        self.refresh_btn.set_sensitive(not self.ctl.servers_loading)

        favs = self.settings["favorites"]
        for host in favs:
            loc = self.ctl.find_server(host)
            if loc:
                row = self._make_row(loc)
                self.fav_group.add(row)
                self._fav_rows.append(row)
            else:
                row = Adw.ActionRow(title=host, subtitle="Eigener Server", activatable=True)
                flag = Gtk.Label(label="🌐")
                flag.add_css_class("hm-flag")
                row.add_prefix(flag)
                self._add_common_suffixes(row, host)
                row.connect("activated", lambda *_a, h=host: self._connect(h))
                self._rows.append((row, _norm(host), False, None, host))
                self.fav_group.add(row)
                self._fav_rows.append(row)
        self.fav_group.set_visible(bool(favs))

        # Kostenlose Server zuerst, danach nach Kontinent gruppiert
        buckets = {}
        for loc in servers:
            if "free" in (loc.get("tags") or []):
                key = "free"
            else:
                key = (loc.get("geo") or {}).get("continent") or "other"
            buckets.setdefault(key, []).append(loc)
        order = ["free"] + [code for code, _n in U.CONTINENTS] + sorted(
            k for k in buckets if k not in ("free", "other") and k not in dict(U.CONTINENTS)) + ["other"]
        previous = self.fav_group
        for key in order:
            locs = buckets.get(key)
            if not locs:
                continue
            title = "Kostenlose Server" if key == "free" else \
                U.continent_name(key) if key != "other" else "Weitere Standorte"
            group = Adw.PreferencesGroup(title=title)
            members = []
            for loc in sorted(locs, key=self._sort_key):
                widget = self._make_expander(loc) if loc.get("children") else self._make_row(loc)
                group.add(widget)
                members.append(widget)
            self.list_box.insert_child_after(group, previous)
            previous = group
            self._groups.append((group, members))
        self._apply_filter()
        self._update_current()

    def _connect_button(self, host):
        btn = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Verbinden")
        btn.add_css_class("flat")
        btn.connect("clicked", lambda *_a: self._connect(host))
        return btn

    def _apply_filter(self):
        query = _norm(self.search.get_text()).strip()
        parts = query.split()
        free_only = self.free_toggle.get_active()
        exp_text = {e: t for e, t, _f, _h in self._expanders}
        exp_free = {e: f for e, _t, f, _h in self._expanders}
        visible_children = {}
        for row, text, is_free, expander, _host in self._rows:
            ok = all(p in text for p in parts) and (not free_only or is_free)
            if expander is not None:
                # Kind ist sichtbar, wenn es selbst passt oder der übergeordnete Standort passt
                parent_ok = bool(parts) and all(p in exp_text[expander] for p in parts)
                ok = ok or (parent_ok and (not free_only or is_free))
                visible_children.setdefault(expander, False)
                visible_children[expander] |= ok
            row.set_visible(ok)
        for exp, text, is_free, _host in self._expanders:
            parent_ok = all(p in text for p in parts) and (not free_only or exp_free[exp])
            exp.set_visible(parent_ok or visible_children.get(exp, False))
            exp.set_expanded(bool(parts) and visible_children.get(exp, False))
        self.fav_group.set_visible(any(r.get_visible() for r in self._fav_rows))
        any_visible = False
        for group, members in self._groups:
            shown = any(m.get_visible() for m in members)
            group.set_visible(shown)
            any_visible |= shown
        self.no_match.set_visible(not any_visible)

    def _update_current(self):
        current = C.short_name(self.ctl.current_host)
        for host, marks in self._current_marks.items():
            for mark in marks:
                mark.set_visible(host == current)
        self.refresh_btn.set_sensitive(not self.ctl.servers_loading)
