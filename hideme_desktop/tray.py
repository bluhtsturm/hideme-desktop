"""Tray-Symbol über das StatusNotifierItem-Protokoll (D-Bus).

Funktioniert unter KDE Plasma, Xfce, Cinnamon, MATE, Budgie, LXQt sowie unter
GNOME mit der Erweiterung "AppIndicator and KStatusNotifierItem Support".
Implementiert ``org.kde.StatusNotifierItem`` und ``com.canonical.dbusmenu``
direkt mit Gio – ohne zusätzliche Bibliotheken.
"""

import os

from gi.repository import Gio, GLib

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>
</node>
"""


class MenuItem:
    def __init__(self, label="", callback=None, enabled=True, separator=False, children=None,
                 toggle=None, icon=None):
        self.label = label
        self.callback = callback
        self.enabled = enabled
        self.separator = separator
        self.children = children or []
        self.toggle = toggle  # None, True oder False (Häkchen)
        self.icon = icon
        self.id = 0

    def props(self):
        p = {}
        if self.separator:
            p["type"] = GLib.Variant("s", "separator")
            return p
        p["label"] = GLib.Variant("s", self.label.replace("_", "__"))
        p["enabled"] = GLib.Variant("b", bool(self.enabled))
        p["visible"] = GLib.Variant("b", True)
        if self.icon:
            p["icon-name"] = GLib.Variant("s", self.icon)
        if self.toggle is not None:
            p["toggle-type"] = GLib.Variant("s", "checkmark")
            p["toggle-state"] = GLib.Variant("i", 1 if self.toggle else 0)
        if self.children:
            p["children-display"] = GLib.Variant("s", "submenu")
        return p


class TrayIcon:
    """Verwaltet das Tray-Symbol. ``available`` ist True, solange ein Host existiert."""

    def __init__(self, app_id, title, icon_theme_path, on_activate, on_availability=None):
        self.app_id = app_id
        self.title = title
        self.icon_theme_path = icon_theme_path or ""
        self.on_activate = on_activate
        self.on_availability = on_availability
        self.icon_name = app_id
        self.status = "Active"
        self.tooltip_title = title
        self.tooltip_body = ""
        self.available = False
        self._bus = None
        self._ids = []
        self._name_id = 0
        self._watch_id = 0
        self._service = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._revision = 1
        self._items = {}
        self._root = MenuItem(children=[])
        self._enabled = False

    # ---------------------------------------------------------------- lifecycle
    def enable(self):
        if self._enabled:
            return
        self._enabled = True
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            print(f"hideme-desktop: Kein Session-Bus für das Tray-Symbol: {e.message}")
            self._enabled = False
            return
        sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._ids.append(self._bus.register_object(ITEM_PATH, sni_info, self._sni_call, self._sni_get, None))
        self._ids.append(self._bus.register_object(MENU_PATH, menu_info, self._menu_call, self._menu_get, None))
        self._name_id = Gio.bus_own_name_on_connection(self._bus, self._service, Gio.BusNameOwnerFlags.NONE,
                                                       None, None)
        self._watch_id = Gio.bus_watch_name_on_connection(self._bus, WATCHER_NAME, Gio.BusNameWatcherFlags.NONE,
                                                          self._watcher_appeared, self._watcher_vanished)

    def disable(self):
        if not self._enabled:
            return
        self._enabled = False
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._name_id:
            Gio.bus_unown_name(self._name_id)
            self._name_id = 0
        for reg in self._ids:
            self._bus.unregister_object(reg)
        self._ids = []
        self._set_available(False)

    def _watcher_appeared(self, conn, _name, _owner):
        conn.call(WATCHER_NAME, "/StatusNotifierWatcher", WATCHER_NAME, "RegisterStatusNotifierItem",
                  GLib.Variant("(s)", (self._service,)), None, Gio.DBusCallFlags.NONE, 5000, None,
                  self._registered)

    def _registered(self, conn, result):
        try:
            conn.call_finish(result)
            self._set_available(True)
        except GLib.Error as e:
            print(f"hideme-desktop: Tray-Registrierung fehlgeschlagen: {e.message}")
            self._set_available(False)

    def _watcher_vanished(self, _conn, _name):
        self._set_available(False)

    def _set_available(self, value):
        if value != self.available:
            self.available = value
            if self.on_availability:
                self.on_availability(value)

    # ---------------------------------------------------------------- updates
    def _emit(self, path, iface, signal, params=None):
        if not self._bus or not self._enabled:
            return
        try:
            self._bus.emit_signal(None, path, iface, signal, params)
        except GLib.Error:
            pass

    def set_icon(self, icon_name):
        if icon_name != self.icon_name:
            self.icon_name = icon_name
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewIcon")

    def set_tooltip(self, title, body):
        if (title, body) != (self.tooltip_title, self.tooltip_body):
            self.tooltip_title, self.tooltip_body = title, body
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip")
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewTitle")

    def set_menu(self, items):
        self._root = MenuItem(children=items)
        self._items = {0: self._root}
        counter = [1]

        def assign(item):
            for child in item.children:
                child.id = counter[0]
                counter[0] += 1
                self._items[child.id] = child
                assign(child)
        assign(self._root)
        self._revision += 1
        self._emit(MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                   GLib.Variant("(ui)", (self._revision, 0)))

    # ---------------------------------------------------------------- SNI
    def _sni_get(self, _conn, _sender, _path, _iface, prop):
        if prop == "Category":
            return GLib.Variant("s", "Communications")
        if prop == "Id":
            return GLib.Variant("s", self.app_id)
        if prop == "Title":
            return GLib.Variant("s", self.tooltip_title or self.title)
        if prop == "Status":
            return GLib.Variant("s", self.status)
        if prop == "WindowId":
            return GLib.Variant("i", 0)
        if prop == "IconName":
            return GLib.Variant("s", self.icon_name)
        if prop == "IconThemePath":
            return GLib.Variant("s", self.icon_theme_path)
        if prop == "IconPixmap":
            return GLib.Variant("a(iiay)", [])
        if prop in ("OverlayIconName", "AttentionIconName"):
            return GLib.Variant("s", "")
        if prop == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", (self.icon_name, [], self.tooltip_title, self.tooltip_body))
        if prop == "ItemIsMenu":
            return GLib.Variant("b", False)
        if prop == "Menu":
            return GLib.Variant("o", MENU_PATH)
        return None

    def _sni_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(lambda: (self.on_activate(), False)[1])
        invocation.return_value(None)

    # ---------------------------------------------------------------- dbusmenu
    def _menu_get(self, _conn, _sender, _path, _iface, prop):
        if prop == "Version":
            return GLib.Variant("u", 3)
        if prop == "TextDirection":
            return GLib.Variant("s", "ltr")
        if prop == "Status":
            return GLib.Variant("s", "normal")
        if prop == "IconThemePath":
            return GLib.Variant("as", [self.icon_theme_path] if self.icon_theme_path else [])
        return None

    def _layout(self, item, depth):
        children = []
        if depth != 0:
            for child in item.children:
                children.append(GLib.Variant("(ia{sv}av)", self._layout(child, depth - 1)))
        props = item.props()
        if item is self._root:
            props = {"children-display": GLib.Variant("s", "submenu")}
        return (item.id, props, children)

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent_id, depth, _names = args
            item = self._items.get(parent_id, self._root)
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._revision, self._layout(item, depth))))
        elif method == "GetGroupProperties":
            ids, _names = args
            result = []
            for item_id in ids or list(self._items):
                item = self._items.get(item_id)
                if item is not None:
                    result.append((item_id, item.props()))
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item_id, name = args
            item = self._items.get(item_id)
            value = (item.props().get(name) if item else None) or GLib.Variant("s", "")
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event_id, _data, _ts = args
            self._dispatch(item_id, event_id)
            invocation.return_value(None)
        elif method == "EventGroup":
            errors = []
            for item_id, event_id, _data, _ts in args[0]:
                if item_id not in self._items:
                    errors.append(item_id)
                self._dispatch(item_id, event_id)
            invocation.return_value(GLib.Variant("(ai)", (errors,)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _dispatch(self, item_id, event_id):
        if event_id != "clicked":
            return
        item = self._items.get(item_id)
        if item and item.callback and item.enabled:
            GLib.idle_add(lambda: (item.callback(), False)[1])
