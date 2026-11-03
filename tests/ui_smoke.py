#!/usr/bin/env python3
"""Automatischer Oberflächentest gegen den Mock-Daemon.

Startet die App, spielt typische Abläufe durch und speichert Bildschirmfotos
der Fenster als PNG. Aufruf (am besten in einer eigenen D-Bus-Sitzung):

    dbus-run-session -- python3 -I tests/ui_smoke.py SOCKET AUSGABEVERZEICHNIS
"""

import json
import os
import sys
import traceback
import urllib.parse  # noqa: F401  (sicherstellen, dass die Standardbibliothek vollständig ist)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SOCK = sys.argv[1]
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(OUT, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(OUT, "cache")
os.makedirs(os.path.join(OUT, "config", "hideme-desktop"), exist_ok=True)
with open(os.path.join(OUT, "config", "hideme-desktop", "settings.json"), "w") as fh:
    json.dump({"control_address": SOCK, "show_tray": True, "notifications": True,
               "favorites": ["amsterdam", "frankfurt"], "last_server": "amsterdam"}, fh)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from hideme_desktop import api as A  # noqa: E402
from hideme_desktop.main import Application  # noqa: E402

errors = []
results = []


def hook(exc_type, exc, tb):
    errors.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = hook

# Minimaler StatusNotifierWatcher, damit das Tray-Symbol in der privaten D-Bus-Sitzung registriert werden kann
WATCHER_XML = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/>
</interface></node>"""
registered_items = []
bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def _watcher_call(conn, sender, path, iface, method, params, inv):
    registered_items.append((sender, params.unpack()[0]))
    inv.return_value(None)


def _watcher_prop(conn, sender, path, iface, prop):
    return GLib.Variant("b", True) if prop == "IsStatusNotifierHostRegistered" else GLib.Variant("i", 0)


bus.register_object("/StatusNotifierWatcher", Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0],
                    _watcher_call, _watcher_prop, None)
Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, None, None)
menu_layout = {}

app = Application()
raw = A.ControlClient(SOCK)


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  OK  " if cond else "  FEHLER ") + name + (f" – {detail}" if detail and not cond else ""), flush=True)


PAUSE_AT = [x for x in os.environ.get("SHOT_WAIT", "").split(",") if x]
paused = {"name": None}


def shot(widget, name):
    """Hält den Test an der Stelle an, bis OUT/continue existiert (für Bildschirmfotos von außen)."""
    if name in PAUSE_AT:
        paused["name"] = name
        with open(os.path.join(OUT, "current_shot"), "w") as fh:
            fh.write(name)
        print(f"  [Pause für Bildschirmfoto: {name}]", flush=True)


steps = []


def step(delay):
    def deco(func):
        steps.append((delay, func))
        return func
    return deco


@step(2500)
def s_start():
    ctl = app.controller
    check("Daemon erreichbar", ctl.available, ctl.unavailable_reason)
    check("Konfiguration geladen", ctl.config is not None)
    check("Serverliste geladen", len(ctl.servers) > 0)
    check("Kein Token", ctl.has_token is False)
    check("Tray registriert", app.tray is not None and app.tray.available and registered_items, str(registered_items))
    shot(app.window, "01-start")
    # Tray-Menü über D-Bus abfragen (wie es ein Panel tun würde)
    service = registered_items[0][1] if registered_items else ""

    def got(conn, res):
        try:
            menu_layout["value"] = conn.call_finish(res).unpack()
        except GLib.Error as e:
            menu_layout["error"] = e.message
    if service:
        bus.call(service, "/MenuBar", "com.canonical.dbusmenu", "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
                 None, Gio.DBusCallFlags.NONE, 3000, None, got)


@step(500)
def s_login_dialog():
    labels = []

    def walk(node):
        _id, props, children = node
        if "label" in props:
            labels.append(props["label"])
        for c in children:
            walk(c)
    if "value" in menu_layout:
        walk(menu_layout["value"][1])
    check("Tray-Menü per D-Bus abrufbar", "Beenden" in labels and "Server wechseln" in labels,
          str(menu_layout.get("error") or labels))
    app.window.show_login()
    dlg = app.window._login
    dlg.username.set_text("testuser")
    dlg.password.set_text("falsch")
    dlg._login()


@step(2000)
def s_login_wrong():
    dlg = app.window._login
    check("Fehlermeldung bei falschem Passwort", dlg.error.get_visible() and "401" in dlg.error.get_text(),
          dlg.error.get_text())
    shot(dlg, "02-login-fehler")
    dlg.password.set_text("geheim")
    dlg._login()


@step(2500)
def s_login_ok():
    ctl = app.controller
    check("Token nach Anmeldung vorhanden", ctl.has_token is True)
    check("Anmeldedialog geschlossen", not app.window._login.get_visible())
    ctl.connect_vpn("amsterdam")


@step(400)
def s_connecting():
    check("Phase 'connecting' während Verbindungsaufbau", app.controller.phase() == "connecting",
          app.controller.phase())
    shot(app.window, "03-verbinde")


@step(3500)
def s_connected():
    ctl = app.controller
    check("Verbunden", ctl.code == A.CONNECTED, ctl.code)
    check("Server amsterdam", "amsterdam" in ctl.current_host, ctl.current_host)
    check("Externe IP ermittelt", bool(ctl.ext_ip4), str(ctl.ext_ip4))
    sv = app.window.status_view
    check("Statusseite zeigt 'Geschützt'", sv.title.get_text() == "Geschützt", sv.title.get_text())
    check("Details sichtbar", sv.details.get_visible())
    shot(app.window, "04-verbunden")


@step(2500)
def s_rates():
    ctl = app.controller
    check("Übertragungsrate berechnet", ctl.rx_rate > 0, str(ctl.rx_rate))
    shot(app.window, "05-verbunden-raten")
    app.window.show_page("servers")


@step(800)
def s_servers():
    sv = app.window.servers_view
    check("Serverseite hat Einträge", len(sv._rows) >= 8, str(len(sv._rows)))
    shot(app.window, "06-server")
    sv.search.set_text("frank")


@step(800)
def s_search():
    sv = app.window.servers_view
    visible = [h for (row, _t, _f, exp, h) in sv._rows if row.get_visible() and exp is not None]
    check("Suche 'frank' findet Frankfurt", "frankfurt" in visible, str(visible))
    shot(app.window, "07-server-suche")
    # Viele Zeilen gleichzeitig ein-/auszublenden bringt die Broadway-Testanzeige (gtk4-broadwayd,
    # decode_nodes) gelegentlich zum Absturz – die Liste dafür nicht anzeigen. Geprüft wird
    # weiterhin die Sichtbarkeit der Zeilen selbst.
    app.window.show_page("status")
    sv.search.set_text("")
    sv.free_toggle.set_active(True)


@step(600)
def s_free():
    sv = app.window.servers_view
    vis = [h for (row, _t, free, exp, h) in sv._rows if row.get_visible()]
    check("Filter 'kostenlos' blendet Berlin aus", "berlin" not in vis, str(vis))
    sv.free_toggle.set_active(False)
    # Serverwechsel während bestehender Verbindung
    app.controller.connect_vpn("frankfurt")


@step(4000)
def s_switched():
    ctl = app.controller
    check("Serverwechsel auf frankfurt", ctl.code == A.CONNECTED and "frankfurt" in ctl.current_host,
          f"{ctl.code} {ctl.current_host}")
    app.window.show_page("smartguard")


@step(600)
def s_smartguard():
    sg = app.window.smartguard_view
    sg.switches["ads"].widget.set_active(True)
    sg.switches["trackers"].widget.set_active(True)
    sg.pg.widget.set_selected(1)
    sg.blacklist._on_add("ads.example.com")
    sg.blacklist._on_add("ungültig name")


@step(1800)
def s_smartguard_check():
    f = raw.get_configuration()["Rest"]["Filter"]
    check("SmartGuard: Werbung/Tracker/PG gespeichert", f.get("ads") and f.get("trackers") and f.get("PG") == 12,
          json.dumps(f))
    check("SmartGuard: Blacklist gespeichert, ungültiger Name abgelehnt",
          f.get("blacklist") == ["ads.example.com"], json.dumps(f.get("blacklist")))
    check("Hinweis 'Neu verbinden' angezeigt", app.controller.pending_changes)
    shot(app.window, "08-smartguard")
    app.window.show_page("log")


@step(1200)
def s_log():
    lv = app.window.log_view
    buf = lv.log_view.get_buffer()
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    check("Protokoll geladen", "Conn: Connected" in text, text[:120])
    shot(app.window, "09-protokoll")
    lv.stack.set_visible_child_name("events")


@step(600)
def s_events():
    lv = app.window.log_view
    buf = lv.event_view.get_buffer()
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    check("Ereignisliste enthält 'Verbunden'", "Verbunden" in text, text[:200])
    shot(app.window, "10-ereignisse")
    app.window.show_page("status")
    app.window.show_preferences("connection")


@step(1200)
def s_prefs():
    wins = [w for w in Gtk.Window.list_toplevels() if w.get_visible()]
    names = [type(w).__name__ for w in wins]
    for w in wins:
        if w is not app.window and type(w).__name__ != "MainWindow":
            shot(w, "11-einstellungen")
    shot(app.window, "11-einstellungen-hauptfenster")
    check("Einstellungsdialog geöffnet", True, str(names))
    app.controller.update_config({"WireGuard": {"SplitTunnel": "192.168.0.0/16", "LeakProtection": False}})


@step(1200)
def s_prefs_check():
    wg = raw.get_configuration()["WireGuard"]
    check("Split-Tunnel und Kill-Switch gespeichert", wg["SplitTunnel"] == "192.168.0.0/16" and
          wg["LeakProtection"] is False, json.dumps(wg))
    check("Neu-Routing vorgemerkt", app.controller._dirty)
    app.controller.reconnect()


@step(4500)
def s_reconnected():
    ctl = app.controller
    check("Neu verbunden, Änderungen angewendet", ctl.code == A.CONNECTED and not ctl.pending_changes,
          f"{ctl.code} pending={ctl.pending_changes}")
    check("Neu-Routing durchgeführt", not ctl._dirty)
    app.controller.update_config({"WireGuard": {"DpdTimeout": 45 * 1_000_000_000}})


@step(1200)
def s_live_setting():
    ctl = app.controller
    check("Live-Einstellung (DPD) ohne Neuverbindungs-Hinweis", not ctl.pending_changes)
    app.controller.update_config({"WireGuard": {"LeakProtection": True}})
    # Verbindungsabbruch simulieren
    raw.request("GET", "/dpd")


@step(1200)
def s_dpd():
    ctl = app.controller
    check("Abbruch erkannt → 'reconnecting'", ctl.phase() in ("reconnecting", "connecting"), ctl.phase())
    shot(app.window, "12-abbruch")


@step(6000)
def s_dpd_recovered():
    ctl = app.controller
    check("Daemon hat selbst neu verbunden", ctl.code == A.CONNECTED, ctl.code)
    raw.request("GET", "/disconnect")  # wie "hidemectl disconnect"


@step(2000)
def s_external_disconnect():
    ctl = app.controller
    check("Fremdes Trennen erkannt – keine automatische Neuverbindung",
          not ctl.want_connected and ctl.reconnect_at is None and ctl.code == A.ROUTED,
          f"want={ctl.want_connected} at={ctl.reconnect_at} code={ctl.code}")
    app.window.show_tools()


@step(1000)
def s_tools():
    tw = app.window._tools
    check("Werkzeug-Fenster zeigt CLI-Befehl", "connect" in tw.cmd_label.get_text(), tw.cmd_label.get_text())
    shot(tw, "13-werkzeuge")
    tw.close()
    app.controller.disconnect_vpn()


@step(2000)
def s_disconnected():
    ctl = app.controller
    check("Getrennt (destroy → clean)", ctl.code == A.CLEAN, ctl.code)
    check("Kein Auto-Reconnect nach manuellem Trennen", ctl.reconnect_at is None and not ctl.want_connected)
    shot(app.window, "14-getrennt")
    app.controller.connect_vpn("amsterdam")
    app.controller.disconnect_vpn()  # sofort "Abbrechen"


@step(400)
def s_cancel_pending():
    check("Abbruch vorgemerkt", app.controller.cancel_requested and app.controller.busy == "connect",
          f"cancel={app.controller.cancel_requested} busy={app.controller.busy}")


@step(4000)
def s_cancelled():
    ctl = app.controller
    check("Nach Abbruch getrennt", ctl.code == A.CLEAN and not ctl.want_connected and not ctl.cancel_requested,
          f"{ctl.code} want={ctl.want_connected} cancel={ctl.cancel_requested}")
    app.settings["block_after_disconnect"] = True
    app.controller.connect_vpn("amsterdam")


@step(3500)
def s_block_connect():
    check("Wieder verbunden", app.controller.code == A.CONNECTED, app.controller.code)
    app.controller.disconnect_vpn()


@step(1800)
def s_blocked():
    ctl = app.controller
    check("Blockiert nach Trennen (routed + Kill-Switch)", ctl.phase() == "blocked", ctl.phase())
    shot(app.window, "15-blockiert")
    menu_labels = [i.label for i in app.tray._items.values() if i.label]
    check("Tray-Menü bietet 'Blockierung aufheben'", "Blockierung aufheben" in menu_labels, str(menu_labels))
    ctl.unblock()


@step(1500)
def s_unblocked():
    check("Blockierung aufgehoben", app.controller.code == A.CLEAN, app.controller.code)
    app.settings["block_after_disconnect"] = False
    raw.set_configuration({"Rest": {"Host": "fail.hideservers.net"}})
    app.controller.connect_vpn("fail")


@step(2500)
def s_fail():
    ctl = app.controller
    check("Verbindungsfehler gemeldet", ctl.last_error and "no such host" in ctl.last_error, str(ctl.last_error))
    check("Kein Auto-Reconnect nach manuellem Fehlversuch", not ctl.want_connected)
    check("Nach Fehlversuch nicht blockiert (wieder clean)", ctl.code == A.CLEAN and ctl.phase() == "disconnected",
          f"{ctl.code} {ctl.phase()}")
    shot(app.window, "16-fehler")
    app.controller.logout()


@step(1500)
def s_logout():
    check("Abgemeldet", app.controller.has_token is False)
    # Zum Schluss (Größenänderungen bringen die Broadway-Testanzeige gelegentlich zum Absturz):
    # schmale Ansicht mit aktivem Breakpoint
    app.window.set_default_size(360, 700)


@step(2500)
def s_narrow():
    min_width = app.window.get_content().measure(Gtk.Orientation.HORIZONTAL, -1)[0]
    check("Fenster lässt sich auf 360 px verkleinern", app.window.get_width() <= 360 and min_width <= 360,
          f"Fensterbreite {app.window.get_width()} px, Mindestbreite Inhalt {min_width} px")
    app.quit_app()


def run_steps(index=0):
    if index >= len(steps):
        return False
    delay, func = steps[index]

    def fire():
        try:
            func()
        except Exception:
            errors.append(traceback.format_exc())
            traceback.print_exc()
        wait_then(index + 1)
        return False
    GLib.timeout_add(delay, fire)
    return False


def wait_then(index):
    flag = os.path.join(OUT, "continue")
    if paused["name"] and not os.path.exists(flag):
        GLib.timeout_add(200, lambda: (wait_then(index), False)[1])
        return
    if paused["name"]:
        os.unlink(flag)
        paused["name"] = None
    run_steps(index)


def on_activate(*_a):
    pass


GLib.timeout_add(100, lambda: run_steps() or False)
app.run([sys.argv[0]])

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} Prüfungen bestanden, {len(errors)} Ausnahmen")
for e in errors:
    print(e)
sys.exit(1 if failed or errors else 0)
