#!/usr/bin/env python3
"""Simulierter ``hide.me service`` für Tests ohne Root-Rechte.

Bildet die REST-Steuerschnittstelle (serviceScripts/api.md) nach: Zustände,
Ereignisstrom (/watch, chunked), Konfiguration, Token, Serverliste, Log.

    python3 tests/mock_daemon.py /tmp/hideme-test.sock
"""

import copy
import datetime
import http.server
import json
import os
import queue
import random
import socketserver
import sys
import threading
import time

NS = 1_000_000_000

CONFIG = {
    "Rest": {"APIVersion": "v1.0.0", "Host": "", "Port": 432, "Domain": "hide.me", "AccessTokenPath": "accessToken.txt",
             "AccessToken": "", "Username": "", "Password": "", "RestTimeout": 90 * NS, "ReconnectWait": 30 * NS,
             "AccessTokenUpdateDelay": 2 * NS, "CA": "CA.pem", "Mark": 0, "Filter": {}, "PortForward": {},
             "UseDoH": True},
    "WireGuard": {"Name": "vpn", "ListenPort": 0, "Mark": 0, "RPDBPriority": 10, "PrivateKey": "",
                  "RoutingTable": 55555, "LeakProtection": True, "ResolvConfBackupFile": "", "DpdTimeout": 60 * NS,
                  "SplitTunnel": "", "IPv4": True, "IPv6": True},
    "DoH": {"servers": ["sdns://AgYAAAAAAAAADjE0OS4xMTIuMTEyLjEw"], "updateURLs": [
        "https://raw.githubusercontent.com/DNSCrypt/dnscrypt-resolvers/master/v3/public-resolvers.md"],
        "filename": "resolvers.txt"},
    "Plain": {"Servers": ["209.250.251.37:53", "217.182.206.81:53"]},
}


def loc(i, host, name, cc, city, continent, tags=None, children=None):
    """Aufbau wie die echte Liste von api.hide.me/v1/network/free/en."""
    entry = {"id": i, "hostname": host, "flag": cc.lower(), "displayName": name, "tags": tags or [],
             "geo": {"lat": 0, "lon": 0, "cityName": city, "countryCode": cc, "continent": continent}}
    if children:
        entry["children"] = children
    return entry


PREMIUM = ["upgrade", "no-ping"]
SERVERS = [
    loc(1, "nl-v4.hideservers.net", "Netherlands", "NL", "", "EU", PREMIUM + ["10g"], [
        loc(11, "amsterdam-v4.hideservers.net", "Amsterdam", "NL", "Amsterdam", "EU", PREMIUM + ["10g"]),
        loc(12, "rotterdam-v4.hideservers.net", "Rotterdam", "NL", "Rotterdam", "EU", PREMIUM)]),
    loc(2, "de-v4.hideservers.net", "Germany", "DE", "", "EU", PREMIUM + ["10g"], [
        loc(21, "frankfurt-v4.hideservers.net", "Frankfurt", "DE", "Frankfurt", "EU", PREMIUM + ["10g"]),
        loc(22, "berlin-v4.hideservers.net", "Berlin", "DE", "Berlin", "EU", PREMIUM),
        loc(23, "munich-v4.hideservers.net", "Munich", "DE", "Munich", "EU", PREMIUM + ["non-p2p"])]),
    loc(3, "ch-v4.hideservers.net", "Switzerland", "CH", "Zurich", "EU", PREMIUM + ["10g"]),
    loc(4, "us-v4.hideservers.net", "United States", "US", "", "NA", PREMIUM + ["10g"], [
        loc(41, "newyork-v4.hideservers.net", "New York", "US", "New York", "NA", PREMIUM + ["10g"]),
        loc(42, "losangeles-v4.hideservers.net", "Los Angeles", "US", "Los Angeles", "NA", PREMIUM),
        loc(43, "dallas-v4.hideservers.net", "Dallas", "US", "Dallas", "NA", PREMIUM)]),
    loc(5, "jp-v4.hideservers.net", "Japan", "JP", "Tokyo", "AS", PREMIUM + ["10g"]),
    loc(6, "br-v4.hideservers.net", "Brazil", "BR", "Sao Paulo", "SA", PREMIUM + ["non-p2p"]),
    loc(7, "free-de-v4.hideservers.net", "Germany - Free", "DE", "Frankfurt", "EU", ["free", "no-geo", "no-best"]),
    loc(8, "free-nl-v4.hideservers.net", "Netherlands - Free", "NL", "Amsterdam", "EU", ["free", "no-geo", "no-best"]),
    loc(9, "free-us-v4.hideservers.net", "USA - Free", "US", "New York", "NA", ["free", "no-geo", "no-best"]),
]


def now_go():
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


class Daemon:
    def __init__(self):
        self.config = copy.deepcopy(CONFIG)
        self.state = {"code": "clean", "timestamp": "0001-01-01T00:00:00Z"}
        self.ops = threading.Lock()
        self.lock = threading.RLock()
        self.watchers = []
        self.log_lines = []
        self.rx = 0
        self.tx = 0
        self.log("Init: Starting HTTP server on mock socket")

    def log(self, line):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
        self.log_lines.append(f"{stamp} {line}")
        del self.log_lines[:-2000]

    def notify(self, state):
        data = json.dumps(state).encode() + b"\n"
        for q in list(self.watchers):
            q.put(data)

    def set_code(self, code, notify=True, **extra):
        with self.lock:
            self.state = {"code": code, "timestamp": now_go(), "host": self.config["Rest"]["Host"]}
            self.state.update(extra)
            st = dict(self.state)
        if notify:
            self.notify(st)

    def merge(self, target, patch):
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(target.get(k), dict):
                self.merge(target[k], v)
            else:
                target[k] = v

    def connect(self):
        host = self.config["Rest"]["Host"]
        if not self.config["Rest"]["AccessToken"]:
            raise RuntimeError("no Access-Token")
        self.log(f"Conn: Connecting in 0s")
        self.set_code("connecting")
        self.notify({"code": "dns lookup", "timestamp": now_go()})
        time.sleep(0.6)
        if not host:
            raise RuntimeError("missing host")
        if "fail" in host:
            self.set_code("disconnecting")
            self.set_code("routed")
            raise RuntimeError(f"lookup {host} on 127.0.0.53:53: no such host")
        self.set_code("connecting")
        time.sleep(1.2)
        self.rx, self.tx = 0, 0
        resp = {"publicKey": "DV4UWlB7PJa3j6uvtpRLObilcMY0gqrePtfSOsJIlzc=",
                "endpoint": {"IP": "185.%d.%d.%d" % tuple(random.randint(1, 254) for _ in range(3)), "Port": 432,
                             "Zone": ""},
                "presharedKey": "ZpJf9/OwzaXzjNvK6R1sz2LkNoamAfmKBCNSfI/gwXw=", "persistentKeepalive": 20 * NS,
                "allowedIps": ["10.140.242.229", "fd00:6968:6564:679::a8c:f2e5"],
                "DNS": ["10.140.242.1", "fd00:6968:6564:679::1"],
                "gateway": ["10.140.242.1", "fd00:6968:6564:679::1"], "sessionToken": "c2Vzc2lvbg=="}
        self.log(f"Conn: Connected to {host}")
        f = self.config["Rest"].get("Filter") or {}
        if any(f.values()):
            self.log(f"Fltr: Filters ( {', '.join(k for k, v in f.items() if v)} ) applied")
        self.set_code("connected", **resp)
        return dict(self.state)

    def disconnect(self):
        if self.state["code"] in ("connected", "connecting", "dpd timeout"):
            self.set_code("disconnecting")
            time.sleep(0.3)
            self.log("Conn: Disconnected")
            self.set_code("routed")

    def destroy(self):
        self.disconnect()
        if self.state["code"] == "routed":
            self.log("Init: Shutdown done")
            self.set_code("clean")

    def external_ips(self):
        def run():
            time.sleep(0.8)
            connected = self.state["code"] == "connected"
            ip4 = "185.212.170.%d" % random.randint(2, 250) if connected else "93.184.216.34"
            ip6 = "2a00:1234:5678::%x" % random.randint(1, 4000) if connected else None
            with self.lock:
                self.state["external_ip"] = ip4
                if ip6:
                    self.state["external_ipv6"] = ip6
                st = dict(self.state)
            st["code"] = "external ips"
            self.log(f"ExIP: Retrieved {ip4}")
            self.notify(st)
        threading.Thread(target=run, daemon=True).start()

    def simulate_dpd(self):
        """Simuliert einen Verbindungsabbruch mit anschließender Neuverbindung des Daemons."""
        if self.state["code"] != "connected":
            return
        self.set_code("dpd timeout")
        self.set_code("disconnecting")
        with self.lock:
            self.state["code"] = "routed"

        def later():
            time.sleep(3)
            try:
                self.connect()
            except RuntimeError:
                pass
        threading.Thread(target=later, daemon=True).start()


D = Daemon()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def address_string(self):
        return "mock-client"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _result(self, result=None, error=None):
        obj = {}
        if result is not None:
            obj["result"] = result
        if error:
            obj["error"] = {"code": error[0], "message": error[1]}
        self._send(200, json.dumps(obj))

    def _lock(self):
        if not D.ops.acquire(timeout=1):
            self._send(409, "Conflict\n", "text/plain")
            return False
        return True

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/watch":
            q = queue.Queue()
            D.watchers.append(q)
            headers_sent = False
            try:
                while True:
                    data = q.get()
                    if not headers_sent:
                        # Wie der echte Daemon: Antwortkopf erst mit dem ersten Ereignis
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Transfer-Encoding", "chunked")
                        self.end_headers()
                        headers_sent = True
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                D.watchers.remove(q)
            self.close_connection = True
            return
        if path == "/version":
            return self._send(200, "0.9.14")
        if path == "/log":
            D.notify({"code": "logs dumped", "timestamp": "0001-01-01T00:00:00Z"})
            return self._send(200, "\n".join(D.log_lines) + "\n", "text/plain")
        if path == "/dpd":  # nur im Mock: Verbindungsabbruch simulieren
            D.simulate_dpd()
            return self._result(True)
        if not self._lock():
            return
        try:
            if path == "/configuration":
                D.notify({"code": "configuration get", "timestamp": now_go()})
                return self._send(200, json.dumps(D.config) + "\n")
            if path == "/state":
                with D.lock:
                    if D.state["code"] == "connected":
                        D.rx += random.randint(20_000, 900_000)
                        D.tx += random.randint(5_000, 120_000)
                        D.state["rx"], D.state["tx"] = D.rx, D.tx
                    st = dict(D.state)
                return self._result(st)
            if path == "/route":
                if D.state["code"] != "clean":
                    return self._result(error=("route", "bad state: " + D.state["code"]))
                D.set_code("routed", notify=False)
                return self._result(dict(D.state))
            if path == "/connect":
                if D.state["code"] not in ("clean", "routed"):
                    return self._result(error=("connect", "bad state: " + D.state["code"]))
                try:
                    return self._result(D.connect())
                except RuntimeError as e:
                    if D.state["code"] != "routed":
                        D.set_code("routed")
                    D.log(f"Conn: [ERR] {e}")
                    return self._result(error=("connect", str(e)))
            if path == "/disconnect":
                D.disconnect()
                return self._result(dict(D.state))
            if path in ("/destroy", "/shutdown"):
                D.destroy() if path == "/destroy" else (D.state["code"] == "routed" and D.set_code("clean"))
                return self._result(dict(D.state))
            if path == "/token":
                if not D.config["Rest"]["AccessToken"]:
                    return self._result(error=("token", "no username"))
                D.notify({"code": "token update", "timestamp": now_go()})
                D.notify({"code": "token update done", "timestamp": now_go()})
                return self._result("bmV1ZXNUb2tlbg==")
            if path == "/serverList":
                time.sleep(0.4)
                return self._send(200, json.dumps(SERVERS))
            if path == "/externalIps":
                D.external_ips()
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(404, "404 page not found\n", "text/plain")
        finally:
            D.ops.release()

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if not self._lock():
            return
        try:
            data = json.loads(body or b"{}")
            if path == "/configuration":
                D.merge(D.config, data)
                D.log(f"Serv: Configured from mock-client with {body.decode()[:200]}")
                D.notify({"code": "configuration set", "timestamp": now_go()})
                return self._send(200, json.dumps({"result": True}))
            if path == "/requestToken":
                time.sleep(0.8)
                if not data.get("Username"):
                    return self._result(error=("token", "no username"))
                if data.get("Password") == "falsch":
                    return self._result(error=("token", "bad HTTP status 401"))
                D.notify({"code": "token update", "timestamp": now_go()})
                D.notify({"code": "token update done", "timestamp": now_go()})
                return self._result("dG9rZW4tZnVlci0" + data["Username"].encode().hex())
            self._send(404, "404 page not found\n", "text/plain")
        finally:
            D.ops.release()

    def do_DELETE(self):
        if self.path == "/token":
            return self._result(None)
        self._send(404, "404 page not found\n", "text/plain")


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hideme-mock.sock"
    if len(sys.argv) > 2 and sys.argv[2] == "--logged-in":
        D.config["Rest"]["AccessToken"] = "dG9rZW4="
        D.config["Rest"]["Host"] = "amsterdam.hideservers.net"
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = Server(path, Handler)
    print(f"Mock-Daemon lauscht auf {path}", flush=True)
    try:
        srv.serve_forever()
    finally:
        os.unlink(path)


if __name__ == "__main__":
    main()
