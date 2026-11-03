"""Client für die REST-Steuerschnittstelle von ``hide.me service``.

Die Schnittstelle ist in hide.client.linux/serviceScripts/api.md dokumentiert.
Sie wird über HTTP angesprochen – wahlweise über einen UNIX-Socket (Pfad oder
abstrakter Socket ``@name``), über TCP (``host:port``) oder über TLS
(``https://host:port``).

Dieses Modul hängt nur von der Python-Standardbibliothek ab, damit es auch von
``hidemectl`` (ohne GTK) genutzt werden kann.
"""

import http.client
import json
import socket
import ssl
import threading

# Zustandscodes aus connection/state.go
CLEAN = "clean"
ROUTED = "routed"
CONNECTING = "connecting"
CONNECTED = "connected"
DISCONNECTING = "disconnecting"
DPD_TIMEOUT = "dpd timeout"
# Reine Benachrichtigungen (keine Zustände)
TOKEN_UPDATE = "token update"
TOKEN_UPDATE_DONE = "token update done"
CONFIGURATION_GET = "configuration get"
CONFIGURATION_SET = "configuration set"
LOG_DUMP = "logs dumped"
DNS_LOOKUP = "dns lookup"
EXTERNAL_IPS = "external ips"

STATE_CODES = {CLEAN, ROUTED, CONNECTING, CONNECTED, DISCONNECTING, DPD_TIMEOUT}


class ApiError(Exception):
    """Fehlerantwort des Daemons (JSON-RPC-Fehlerobjekt oder HTTP-Fehler)."""

    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class DaemonUnavailable(ApiError):
    """Der Daemon ist nicht erreichbar (Socket fehlt, keine Berechtigung, …)."""

    def __init__(self, message, reason="unreachable"):
        super().__init__(message)
        self.reason = reason  # "missing", "permission", "refused", "unreachable"


class Busy(ApiError):
    """Der Daemon führt gerade eine andere Operation aus (HTTP 409)."""


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._path)
        except Exception:
            sock.close()
            raise
        self.sock = sock


class ControlClient:
    def __init__(self, address, tls_ca=None, tls_verify=True):
        self.address = (address or "").strip()
        self.tls_ca = tls_ca or None
        self.tls_verify = tls_verify

    # ------------------------------------------------------------------ transport
    def describe(self):
        return self.address

    def _connection(self, timeout):
        addr = self.address
        if addr.startswith("@"):
            return _UnixHTTPConnection("\0" + addr[1:], timeout)
        if addr.startswith("/"):
            return _UnixHTTPConnection(addr, timeout)
        if addr.startswith("https://"):
            hostport = addr[len("https://"):].rstrip("/")
            ctx = ssl.create_default_context(cafile=self.tls_ca) if self.tls_ca else ssl.create_default_context()
            if not self.tls_verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(hostport, timeout=timeout, context=ctx)
        hostport = addr[len("http://"):] if addr.startswith("http://") else addr
        return http.client.HTTPConnection(hostport.rstrip("/"), timeout=timeout)

    def _open(self, method, path, body, timeout):
        conn = self._connection(timeout)
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            return conn, conn.getresponse()
        except FileNotFoundError as e:
            conn.close()
            raise DaemonUnavailable(f"Steuer-Socket {self.address} existiert nicht", "missing") from e
        except PermissionError as e:
            conn.close()
            raise DaemonUnavailable(f"Keine Berechtigung für {self.address}", "permission") from e
        except ConnectionRefusedError as e:
            conn.close()
            raise DaemonUnavailable(f"Verbindung zu {self.address} abgelehnt", "refused") from e
        except (socket.timeout, TimeoutError) as e:
            conn.close()
            raise ApiError("Zeitüberschreitung bei der Kommunikation mit dem Daemon", "timeout") from e
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise DaemonUnavailable(f"Daemon nicht erreichbar: {e}", "unreachable") from e

    def request(self, method, path, body=None, timeout=15.0):
        """Führt eine Anfrage aus und liefert (status, content_type, bytes)."""
        conn, resp = self._open(method, path, body, timeout)
        try:
            payload = resp.read()
            return resp.status, resp.getheader("content-type", ""), payload
        except (socket.timeout, TimeoutError) as e:
            raise ApiError("Zeitüberschreitung beim Lesen der Antwort", "timeout") from e
        except (OSError, http.client.HTTPException) as e:
            raise DaemonUnavailable(f"Verbindung zum Daemon abgebrochen: {e}") from e
        finally:
            conn.close()

    def call(self, method, path, body=None, timeout=15.0):
        """Ruft eine JSON-RPC-artige Methode auf und liefert das ``result``-Feld."""
        status, _ctype, payload = self.request(method, path, body, timeout)
        if status == 409:
            raise Busy("Der Daemon ist gerade beschäftigt", "busy", status)
        text = payload.decode("utf-8", "replace").strip()
        obj = None
        if text:
            try:
                obj = json.loads(text)
            except ValueError:
                obj = None
        if isinstance(obj, dict) and obj.get("error"):
            err = obj["error"]
            raise ApiError(err.get("message") or err.get("code") or "Unbekannter Fehler", err.get("code"), status)
        if status >= 400:
            raise ApiError(text or http.client.responses.get(status, str(status)), None, status)
        if isinstance(obj, dict):
            return obj.get("result")
        return obj if obj is not None else text

    # ------------------------------------------------------------------ methods
    def version(self):
        status, _c, payload = self.request("GET", "/version", timeout=5)
        if status != 200:
            raise ApiError(f"HTTP {status}", status=status)
        return payload.decode("utf-8", "replace").strip().strip('"')

    def state(self):
        return self.call("GET", "/state", timeout=8) or {}

    def get_configuration(self):
        status, _c, payload = self.request("GET", "/configuration", timeout=8)
        if status == 409:
            raise Busy("Der Daemon ist gerade beschäftigt", "busy", status)
        if status != 200:
            raise ApiError(payload.decode("utf-8", "replace").strip() or f"HTTP {status}", status=status)
        return json.loads(payload.decode("utf-8"))

    def set_configuration(self, patch):
        return self.call("POST", "/configuration", patch, timeout=8)

    def route(self):
        return self.call("GET", "/route", timeout=30)

    def connect(self, timeout=150):
        return self.call("GET", "/connect", timeout=timeout)

    def disconnect(self):
        return self.call("GET", "/disconnect", timeout=60)

    def destroy(self):
        return self.call("GET", "/destroy", timeout=60)

    def shutdown(self):
        return self.call("GET", "/shutdown", timeout=30)

    def token(self, timeout=120):
        return self.call("GET", "/token", timeout=timeout)

    def delete_token(self):
        return self.call("DELETE", "/token", timeout=10)

    def request_token(self, host, username, password, timeout=120):
        body = {"Host": host, "Username": username, "Password": password}
        return self.call("POST", "/requestToken", body, timeout=timeout)

    def log(self):
        status, _c, payload = self.request("GET", "/log", timeout=15)
        if status != 200:
            raise ApiError(f"HTTP {status}", status=status)
        return payload.decode("utf-8", "replace")

    # /serverList wird bewusst nicht angeboten: In hide.me 0.9.14 überschreibt der Abruf dauerhaft
    # die REST-Konfiguration des Daemons (siehe netinfo.py). Die Liste kommt direkt von api.hide.me.

    def external_ips(self):
        status, _c, payload = self.request("GET", "/externalIps", timeout=10)
        if status == 409:
            raise Busy("Der Daemon ist gerade beschäftigt", "busy", status)
        if status != 200:
            raise ApiError(payload.decode("utf-8", "replace").strip() or f"HTTP {status}", status=status)

    def watch(self):
        """Öffnet den Ereignisstrom und liefert ein :class:`EventStream`.

        Der Daemon sendet die HTTP-Antwort erst mit dem ersten Ereignis; deshalb wird
        hier nur die Anfrage abgeschickt und erst beim Iterieren auf die Antwort gewartet.
        """
        conn = self._connection(None)
        try:
            conn.request("GET", "/watch", headers={"Accept": "application/json"})
        except FileNotFoundError as e:
            conn.close()
            raise DaemonUnavailable(f"Steuer-Socket {self.address} existiert nicht", "missing") from e
        except PermissionError as e:
            conn.close()
            raise DaemonUnavailable(f"Keine Berechtigung für {self.address}", "permission") from e
        except ConnectionRefusedError as e:
            conn.close()
            raise DaemonUnavailable(f"Verbindung zu {self.address} abgelehnt", "refused") from e
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise DaemonUnavailable(f"Daemon nicht erreichbar: {e}", "unreachable") from e
        return EventStream(conn)


class EventStream:
    """Iterator über die zeilenweise JSON-Ereignisse von ``/watch``."""

    def __init__(self, conn):
        self._conn = conn
        self._lock = threading.Lock()
        self._closed = False

    def __iter__(self):
        try:
            resp = self._conn.getresponse()
        except (OSError, ValueError, http.client.HTTPException, AttributeError):
            return
        if resp.status != 200:
            return
        while True:
            try:
                line = resp.readline()
            except (OSError, ValueError, http.client.HTTPException, AttributeError):
                return
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        sock = getattr(self._conn, "sock", None)
        try:
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._conn.close()
        except Exception:
            pass
