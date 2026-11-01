"""Zentrale Steuerlogik: Zustand des Daemons, Aktionen, Ereignisse.

Alle Netzwerkaufrufe laufen in Hintergrund-Threads; Ergebnisse werden per
``GLib.idle_add`` in den GTK-Hauptthread zurückgereicht. Die Oberfläche hört
nur auf die Signale dieses Objekts.
"""

import concurrent.futures
import datetime
import json
import os
import re
import threading
import time

from gi.repository import GLib, GObject

from . import api as A
from . import config as C
from .settings import cache_dir

POLL_INTERVAL_MS = 1500
MAX_EVENTS = 500

AUTH_ERRORS = ("no Access-Token", "bad HTTP status 401", "bad HTTP status 403", "no username", "no password",
               "application update required")


def parse_go_time(text):
    """Go-Zeitstempel (RFC 3339 mit Nanosekunden) → datetime oder None."""
    if not text or text.startswith("0001-01-01"):
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    text = text.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


class Controller(GObject.Object):
    __gsignals__ = {
        # Zustand, Erreichbarkeit oder laufende Aktion haben sich geändert
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Daemon-Konfiguration neu geladen
        "config-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Ereignis aus /watch: (code, payload)
        "event": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        # Fehler, der dem Benutzer angezeigt werden soll: (titel, text)
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        # Kurzer Hinweis (Toast)
        "notice": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # Desktop-Benachrichtigung: (id, titel, text)
        "notify-user": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
        # Serverliste aktualisiert
        "servers-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Anmeldung erforderlich (kein Token)
        "login-required": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.api = self._make_api()

        self.available = False
        self.unavailable_reason = "Verbinde mit dem Daemon …"
        self.unavailable_kind = "unknown"
        self.daemon_version = ""
        self.state = {"code": A.CLEAN}
        self.code = A.CLEAN
        self.config = None
        self.busy = None
        self.want_connected = False
        self.user_disconnected = False
        self.reconnect_at = None
        self.reconnect_attempt = 0
        self.daemon_reconnect_until = 0.0
        self.pending_changes = False
        self._dirty = False
        self.rx_rate = 0.0
        self.tx_rate = 0.0
        self._last_counters = None
        self.ext_ip4 = None
        self.ext_ip6 = None
        self.ext_ip_checking = False
        self.events = []
        self.servers = []
        self.servers_error = None
        self.servers_loading = False
        self.last_error = None
        self._autoconnect_pending = False

        self._ops = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hideme-op")
        self._poller = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hideme-poll")
        self._bg = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="hideme-bg")
        self._poll_inflight = False
        self._config_fetch_inflight = False
        self._watch_stop = threading.Event()
        self._watch_thread = None
        self._watch_stream = None
        self._watch_lock = threading.Lock()
        self._timer = None
        self._closing = False

        self._load_cached_servers()

    # ------------------------------------------------------------------ setup
    def _make_api(self):
        return A.ControlClient(self.settings["control_address"], self.settings["control_tls_ca"] or None,
                               self.settings["control_tls_verify"])

    def start(self, autoconnect=False):
        self._autoconnect_pending = autoconnect
        self._timer = GLib.timeout_add(POLL_INTERVAL_MS, self._tick)
        self.poll_now()

    def shutdown(self):
        self._closing = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        self._stop_watch()
        for ex in (self._ops, self._poller, self._bg):
            ex.shutdown(wait=False, cancel_futures=True)

    def set_control_address(self, address, tls_ca="", tls_verify=True):
        self.settings["control_address"] = address
        self.settings["control_tls_ca"] = tls_ca
        self.settings["control_tls_verify"] = tls_verify
        self._stop_watch()
        self.api = self._make_api()
        self._set_unavailable("Verbinde mit dem Daemon …", "unknown")
        self.poll_now()

    # ------------------------------------------------------------------ helpers
    def _idle(self, func, *args):
        def run():
            if not self._closing:
                func(*args)
            return False
        GLib.idle_add(run)

    def run_bg(self, func, on_done=None, on_error=None):
        """Führt ``func`` im Hintergrund aus und ruft die Callbacks im Hauptthread auf."""
        def done(fut):
            exc = fut.exception()
            if exc is not None:
                if on_error:
                    self._idle(on_error, exc)
                else:
                    self._idle(self._report_error, "Fehler", exc)
            elif on_done:
                self._idle(on_done, fut.result())
        try:
            self._bg.submit(func).add_done_callback(done)
        except RuntimeError:
            pass

    def _report_error(self, title, exc):
        msg = exc.message if isinstance(exc, A.ApiError) else str(exc)
        self.last_error = msg
        self.emit("error", title, C.explain_error(msg))

    def _run_op(self, label, func, on_done=None, on_error=None):
        if self.busy:
            self.emit("notice", "Bitte warten – eine andere Aktion läuft noch.")
            return False
        self.busy = label
        self.emit("changed")

        def finished(fut):
            self._idle(self._op_finished, fut, on_done, on_error)
        try:
            self._ops.submit(func).add_done_callback(finished)
        except RuntimeError:
            self.busy = None
            return False
        return True

    def _op_finished(self, fut, on_done, on_error):
        self.busy = None
        exc = fut.exception()
        if exc is not None:
            if isinstance(exc, A.DaemonUnavailable):
                self._set_unavailable(exc.message, exc.reason)
            if on_error:
                on_error(exc)
            else:
                self._report_error("Aktion fehlgeschlagen", exc)
        elif on_done:
            on_done(fut.result())
        self.emit("changed")
        self.poll_now()
        self._maybe_schedule_reconnect()

    # ------------------------------------------------------------------ derived state
    @property
    def leak_protection(self):
        return bool(C.get(self.config, "WireGuard", "LeakProtection")) if self.config else True

    @property
    def current_host(self):
        host = self.state.get("host") or ""
        if not host and self.config:
            host = (self.config.get("Rest") or {}).get("Host") or ""
        return host or self.settings["last_server"] or ""

    @property
    def has_token(self):
        if not self.config:
            return None
        return bool((self.config.get("Rest") or {}).get("AccessToken"))

    @property
    def connected_since(self):
        if self.code != A.CONNECTED:
            return None
        return parse_go_time(self.state.get("timestamp"))

    def phase(self):
        if not self.available:
            return "unavailable"
        code = self.code
        if self.busy in ("connect", "reconnect"):
            return "connecting"
        if self.busy == "disconnect" or code == A.DISCONNECTING:
            return "disconnecting"
        if code == A.CONNECTED:
            return "connected"
        if code == A.CONNECTING:
            return "connecting"
        if code == A.DPD_TIMEOUT:
            return "reconnecting"
        if self.want_connected and (self.reconnect_at or self.daemon_reconnect_until > time.monotonic()):
            return "reconnecting"
        if code == A.ROUTED and self.leak_protection:
            return "blocked"
        return "disconnected"

    def reconnect_in(self):
        """Sekunden bis zum nächsten Verbindungsversuch (eigener oder des Daemons), sonst None."""
        now = time.monotonic()
        if self.reconnect_at:
            return max(0, int(self.reconnect_at - now))
        if self.daemon_reconnect_until > now:
            # daemon_reconnect_until = Abbruch + ReconnectWait + 20 s Puffer
            return max(0, int(self.daemon_reconnect_until - 20 - now))
        return None

    # ------------------------------------------------------------------ polling
    def _tick(self):
        if self._closing:
            return False
        now = time.monotonic()
        if self.reconnect_at and now >= self.reconnect_at and not self.busy:
            self.reconnect_at = None
            if self.want_connected and self.available and self.code in (A.ROUTED, A.CLEAN):
                self.reconnect_attempt += 1
                self._connect(self.current_host, auto=True)
        self.poll_now()
        return True

    def poll_now(self):
        if self._poll_inflight or self._closing:
            return
        self._poll_inflight = True
        api = self.api

        def work():
            try:
                return "ok", api.state()
            except A.Busy:
                return "busy", None
            except A.DaemonUnavailable as e:
                return "down", e
            except A.ApiError as e:
                return "error", e

        def done(fut):
            self._idle(self._poll_done, api, fut.result())
        try:
            self._poller.submit(work).add_done_callback(done)
        except RuntimeError:
            self._poll_inflight = False

    def _poll_done(self, api, result):
        self._poll_inflight = False
        if api is not self.api:
            return
        kind, value = result
        if kind == "down":
            self._set_unavailable(value.message, value.reason)
            return
        if kind == "error":
            # Antwort erhalten, aber unerwartet – Daemon läuft trotzdem
            value = None
        if not self.available:
            self._daemon_up()
        if kind == "ok" and isinstance(value, dict):
            self._apply_state(value)

    def _set_unavailable(self, reason, kind):
        changed = self.available or reason != self.unavailable_reason
        self.available = False
        self.unavailable_reason = reason
        self.unavailable_kind = kind
        self._stop_watch()
        if changed:
            self.emit("changed")

    def _daemon_up(self):
        self.available = True
        self.unavailable_reason = ""
        self._start_watch()
        self.refresh_config()
        api = self.api

        def ver():
            return api.version()

        def got_version(v):
            self.daemon_version = v
            self.emit("changed")
        self.run_bg(ver, got_version, lambda e: None)
        if not self.servers:
            self.refresh_servers()
        self.emit("changed")

    def _apply_state(self, st):
        old_code = self.code
        code = st.get("code") or A.CLEAN
        self.state = st
        self.code = code
        now = time.monotonic()
        if code == A.CONNECTED:
            rx, tx = int(st.get("rx") or 0), int(st.get("tx") or 0)
            if self._last_counters and rx >= self._last_counters[1] and tx >= self._last_counters[2]:
                dt = now - self._last_counters[0]
                if dt > 0.2:
                    self.rx_rate = (rx - self._last_counters[1]) / dt
                    self.tx_rate = (tx - self._last_counters[2]) / dt
            self._last_counters = (now, rx, tx)
            if st.get("external_ip"):
                self.ext_ip4 = st.get("external_ip")
            if st.get("external_ipv6"):
                self.ext_ip6 = st.get("external_ipv6")
        else:
            self._last_counters = None
            self.rx_rate = self.tx_rate = 0.0

        if code != old_code:
            self._on_transition(old_code, code)
        if self._autoconnect_pending and self.available:
            self._autoconnect_pending = False
            if code != A.CONNECTED and code != A.CONNECTING:
                host = self.settings["autoconnect_server"]
                if host in ("", "last"):
                    host = self.settings["last_server"]
                if host:
                    self.connect_vpn(host)
        if code == A.CONNECTED and old_code != A.CONNECTED and not self.want_connected:
            # Verbindung besteht bereits (z. B. nach Neustart der App)
            self.want_connected = True
        self.emit("changed")
        self._maybe_schedule_reconnect()

    def _on_transition(self, old, new):
        if new == A.CONNECTED:
            self.reconnect_attempt = 0
            self.reconnect_at = None
            self.daemon_reconnect_until = 0.0
            self.user_disconnected = False
            host = C.short_name(self.state.get("host") or self.current_host)
            self.emit("notify-user", "vpn-state", "VPN verbunden", f"Verbunden mit {host}")
        elif old == A.CONNECTED:
            self.ext_ip4 = self.ext_ip6 = None
            if not self.user_disconnected and self.busy not in ("connect", "reconnect", "disconnect"):
                body = "Die Verbindung wurde unterbrochen."
                if self.leak_protection:
                    body += " Der Kill-Switch blockiert ungeschützten Verkehr."
                if self.want_connected and self.settings["auto_reconnect"]:
                    body += " Es wird automatisch neu verbunden."
                self.emit("notify-user", "vpn-state", "VPN getrennt", body)
        if new == A.CONNECTING and self.daemon_reconnect_until:
            # Der Daemon versucht selbst die Neuverbindung
            self.daemon_reconnect_until = 0.0

    def _maybe_schedule_reconnect(self):
        if not (self.want_connected and self.settings["auto_reconnect"] and self.available):
            return
        if self.busy or self.reconnect_at or self.code not in (A.ROUTED, A.CLEAN):
            return
        if self.daemon_reconnect_until > time.monotonic():
            return
        delay = min(5 * (2 ** min(self.reconnect_attempt, 5)), 120)
        self.reconnect_at = time.monotonic() + delay
        self.emit("changed")

    # ------------------------------------------------------------------ watch stream
    def _start_watch(self):
        if self._watch_thread and self._watch_thread.is_alive():
            return
        self._watch_stop = threading.Event()
        stop = self._watch_stop
        api = self.api

        def run():
            while not stop.is_set():
                try:
                    stream = api.watch()
                except A.ApiError:
                    if stop.wait(3):
                        break
                    continue
                with self._watch_lock:
                    self._watch_stream = stream
                try:
                    for event in stream:
                        if stop.is_set():
                            break
                        self._idle(self._on_event, event)
                finally:
                    stream.close()
                    with self._watch_lock:
                        self._watch_stream = None
                if stop.wait(1):
                    break
                self._idle(self.poll_now)

        self._watch_thread = threading.Thread(target=run, name="hideme-watch", daemon=True)
        self._watch_thread.start()

    def _stop_watch(self):
        self._watch_stop.set()
        with self._watch_lock:
            stream = self._watch_stream
        if stream:
            stream.close()

    def _on_event(self, ev):
        if not isinstance(ev, dict):
            return
        code = ev.get("code") or ""
        entry = {"time": datetime.datetime.now(), "code": code, "data": ev}
        self.events.append(entry)
        del self.events[:-MAX_EVENTS]
        self.emit("event", code, ev)

        if code == A.DPD_TIMEOUT:
            wait = C.seconds(C.get(self.config, "Rest", "ReconnectWait"))
            self.daemon_reconnect_until = time.monotonic() + wait + 20
            self.emit("notify-user", "vpn-state", "Verbindung verloren",
                      f"Keine Antwort vom Server. Neuer Versuch in {int(wait)} s.")
        if code in A.STATE_CODES:
            merged = dict(self.state)
            merged.update(ev)
            if code != A.CONNECTED:
                for key in ("publicKey", "endpoint", "allowedIps", "DNS", "gateway", "rx", "tx"):
                    merged.pop(key, None)
            self._apply_state(merged)
            self.poll_now()
        elif code == A.EXTERNAL_IPS:
            self.ext_ip_checking = False
            self.ext_ip4 = ev.get("external_ip") or None
            self.ext_ip6 = ev.get("external_ipv6") or None
            self.emit("changed")
        elif code == A.CONFIGURATION_SET:
            self.refresh_config()
        elif code == A.TOKEN_UPDATE_DONE and self.busy != "login":
            # Erneuertes Token dauerhaft in der Konfigurationsdatei sichern
            self.update_config({}, quiet=True)
        elif code == A.DNS_LOOKUP:
            self.emit("changed")

    # ------------------------------------------------------------------ configuration
    def refresh_config(self):
        if self._config_fetch_inflight:
            return
        self._config_fetch_inflight = True
        api = self.api

        def done(cfg):
            self._config_fetch_inflight = False
            if api is self.api and isinstance(cfg, dict):
                self.config = cfg
                self.emit("config-changed")
                self.emit("changed")

        def failed(_exc):
            self._config_fetch_inflight = False
            GLib.timeout_add_seconds(2, lambda: (self.refresh_config(), False)[1])

        self.run_bg(api.get_configuration, done, failed)

    def update_config(self, patch, quiet=False, on_done=None):
        """Sendet eine (Teil-)Konfiguration an den Daemon und speichert sie dort."""
        api = self.api
        reroute = C.patch_needs_reroute(patch)

        def work():
            for attempt in range(6):
                try:
                    return api.set_configuration(patch)
                except A.Busy:
                    if attempt == 5:
                        raise
                    time.sleep(1.0)

        def done(_res):
            if patch:
                if reroute:
                    self._dirty = True
                if self.code in (A.CONNECTED, A.CONNECTING) and not quiet:
                    self.pending_changes = True
                elif reroute and self.code == A.ROUTED and not self.busy and not self.want_connected:
                    self._reroute_idle()
            self.refresh_config()
            if on_done:
                on_done()
            self.emit("changed")

        def failed(exc):
            self._report_error("Einstellung konnte nicht übernommen werden", exc)
            self.refresh_config()

        def finished(fut):
            exc = fut.exception()
            if exc is not None:
                self._idle(failed, exc)
            else:
                self._idle(done, fut.result())
        try:
            self._ops.submit(work).add_done_callback(finished)
        except RuntimeError:
            pass

    def _reroute_idle(self):
        """Wendet geänderte Routing-Einstellungen im Ruhezustand an."""
        keep_blocked = self.settings["block_after_disconnect"]
        api = self.api

        def work():
            api.destroy()
            cfg = api.get_configuration()
            if keep_blocked and C.get(cfg, "WireGuard", "LeakProtection"):
                api.route()

        def done(_r):
            self._dirty = False
        self._run_op("config", work, done)

    # ------------------------------------------------------------------ actions
    def connect_vpn(self, host=None):
        host = C.fqdn(host or self.current_host)
        if not host:
            self.emit("error", "Kein Server ausgewählt", "Bitte wähle zuerst einen Server aus der Liste.")
            return
        self.want_connected = True
        self.user_disconnected = False
        self.reconnect_attempt = 0
        self.reconnect_at = None
        self._connect(host, auto=False)

    def _connect(self, host, auto):
        host = C.fqdn(host)
        self.settings["last_server"] = C.short_name(host)
        self.settings.add_recent(C.short_name(host))
        dirty = self._dirty
        self._dirty = False
        api = self.api
        timeout = C.seconds(C.get(self.config, "Rest", "RestTimeout")) + 60

        def work():
            st = api.state()
            code = st.get("code")
            if code in (A.CONNECTED, A.CONNECTING, A.DPD_TIMEOUT):
                api.disconnect()
                code = A.ROUTED
            api.set_configuration({"Rest": {"Host": host}})
            if dirty and code == A.ROUTED:
                api.destroy()
            result = api.connect(timeout=timeout)
            try:
                api.external_ips()
            except A.ApiError:
                pass
            return result

        def done(result):
            self.pending_changes = False
            self.ext_ip_checking = True
            if isinstance(result, dict):
                self._apply_state(result)

        def failed(exc):
            self._dirty = self._dirty or dirty
            msg = exc.message if isinstance(exc, A.ApiError) else str(exc)
            self.last_error = msg
            if any(s.lower() in msg.lower() for s in AUTH_ERRORS):
                self.want_connected = False
                self.reconnect_at = None
                if "no Access-Token" in msg or self.has_token is False:
                    self.emit("login-required")
                self.emit("error", "Verbindung fehlgeschlagen", C.explain_error(msg))
            elif auto:
                self.emit("notice", f"Neuverbindung fehlgeschlagen: {msg}")
            else:
                self.want_connected = False
                self.emit("error", "Verbindung fehlgeschlagen", C.explain_error(msg))
                self.emit("notify-user", "vpn-error", "VPN-Verbindung fehlgeschlagen", C.explain_error(msg))

        self._run_op("reconnect" if auto else "connect", work, done, failed)

    def disconnect_vpn(self):
        self.want_connected = False
        self.user_disconnected = True
        self.reconnect_at = None
        self.daemon_reconnect_until = 0.0
        self.pending_changes = False
        block = self.settings["block_after_disconnect"] and self.leak_protection
        api = self.api
        dirty = self._dirty

        def work():
            if block:
                api.disconnect()
                if dirty:
                    api.destroy()
                    api.route()
            else:
                api.destroy()

        def done(_r):
            self._dirty = False
            if not block:
                self.check_external_ip(quiet=True)

        self._run_op("disconnect", work, done)

    def toggle(self):
        if self.phase() in ("connected", "connecting", "reconnecting"):
            self.disconnect_vpn()
        else:
            self.connect_vpn()

    def reconnect(self):
        """Neu verbinden, z. B. um geänderte Einstellungen anzuwenden."""
        self.connect_vpn(self.current_host)

    def unblock(self):
        """Hebt die Kill-Switch-Blockade auf (Routing entfernen)."""
        self.want_connected = False
        self.reconnect_at = None
        api = self.api
        self._run_op("disconnect", api.destroy, lambda _r: self.check_external_ip(quiet=True))

    def block(self):
        """Aktiviert die Blockade ohne Verbindung (Routing + Kill-Switch)."""
        self._run_op("config", self.api.route)

    def destroy(self):
        self._run_op("disconnect", self.api.destroy)

    def shutdown_routing(self):
        self._run_op("disconnect", self.api.shutdown)

    def check_external_ip(self, quiet=False):
        api = self.api
        self.ext_ip_checking = True
        self.ext_ip4 = self.ext_ip6 = None
        self.emit("changed")

        def failed(exc):
            self.ext_ip_checking = False
            self.emit("changed")
            if not quiet:
                self._report_error("Öffentliche IP konnte nicht ermittelt werden", exc)

        def done(_r):
            # Ergebnis kommt asynchron als Ereignis "external ips"
            GLib.timeout_add_seconds(15, self._ext_ip_timeout)
        self.run_bg(api.external_ips, done, failed)

    def _ext_ip_timeout(self):
        if self.ext_ip_checking:
            self.ext_ip_checking = False
            self.emit("changed")
        return False

    # Anmeldung -------------------------------------------------------------
    def login(self, username, password, host, on_done=None, on_error=None):
        api = self.api
        host = C.fqdn(host or self.settings["token_host"] or "free")

        def work():
            cfg = api.get_configuration()
            old = (cfg.get("Rest") or {}).get("AccessToken") or ""
            if old:
                api.set_configuration({"Rest": {"AccessToken": ""}})
            try:
                token = api.request_token(host, username, password)
            except Exception:
                if old:
                    api.set_configuration({"Rest": {"AccessToken": old}})
                raise
            if not isinstance(token, str) or not token:
                if old:
                    api.set_configuration({"Rest": {"AccessToken": old}})
                raise A.ApiError("Der Server hat kein Token geliefert")
            api.set_configuration({"Rest": {"AccessToken": token}})
            return True

        def done(_r):
            self._dirty = True
            if self.code == A.CONNECTED:
                self.pending_changes = True
            self.refresh_config()
            self.emit("notice", "Anmeldung erfolgreich – Zugangstoken gespeichert.")
            if on_done:
                on_done()

        def failed(exc):
            self.refresh_config()
            if on_error:
                on_error(exc)
            else:
                self._report_error("Anmeldung fehlgeschlagen", exc)

        return self._run_op("login", work, done, failed)

    def refresh_token(self, on_done=None):
        """Fordert mit dem vorhandenen Token ein neues an (wie ``hide.me token``)."""
        api = self.api
        host = C.fqdn(self.settings["token_host"] or "free")

        def work():
            cur = api.get_configuration().get("Rest") or {}
            if not cur.get("Host"):
                api.set_configuration({"Rest": {"Host": host}})
            token = api.token()
            api.set_configuration({"Rest": {"AccessToken": token}})

        def done(_r):
            self.refresh_config()
            self.emit("notice", "Zugangstoken erneuert.")
            if on_done:
                on_done()
        self._run_op("login", work, done)

    def logout(self):
        api = self.api

        def work():
            api.set_configuration({"Rest": {"AccessToken": ""}})
            try:
                api.delete_token()
            except A.ApiError:
                pass

        def done(_r):
            self._dirty = True
            self.refresh_config()
            self.emit("notice", "Abgemeldet – Zugangstoken entfernt.")
        self._run_op("login", work, done)

    # Serverliste -----------------------------------------------------------
    def _servers_cache_path(self):
        return os.path.join(cache_dir(), "serverlist.json")

    def _load_cached_servers(self):
        try:
            with open(self._servers_cache_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                self.servers = data
        except (OSError, ValueError):
            pass

    def refresh_servers(self):
        if self.servers_loading:
            return
        self.servers_loading = True
        self.servers_error = None
        self.emit("servers-changed")
        api = self.api

        def work():
            for attempt in range(10):
                try:
                    return api.server_list()
                except A.Busy:
                    if attempt == 9:
                        raise
                    time.sleep(2)

        def done(data):
            self.servers_loading = False
            if isinstance(data, list) and data:
                self.servers = data
                try:
                    os.makedirs(cache_dir(), exist_ok=True)
                    with open(self._servers_cache_path(), "w", encoding="utf-8") as fh:
                        json.dump(data, fh)
                except OSError:
                    pass
            self.emit("servers-changed")

        def failed(exc):
            self.servers_loading = False
            self.servers_error = exc.message if isinstance(exc, A.ApiError) else str(exc)
            self.emit("servers-changed")
        self.run_bg(work, done, failed)

    def find_server(self, host):
        """Sucht einen Eintrag der Serverliste anhand des (Kurz-)Namens."""
        short = C.short_name(host)

        def walk(items):
            for loc in items or []:
                if C.short_name(loc.get("hostname", "")) == short:
                    return loc
                found = walk(loc.get("children"))
                if found:
                    return found
            return None
        return walk(self.servers)

    # Protokoll ---------------------------------------------------------------
    def fetch_log(self, on_done, on_error=None):
        self.run_bg(self.api.log, on_done, on_error)
