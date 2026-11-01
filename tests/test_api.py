#!/usr/bin/env python3
"""Testet den API-Client gegen den Mock-Daemon (ohne GTK)."""
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hideme_desktop import api as A  # noqa: E402
from hideme_desktop import config as C  # noqa: E402

sock = os.path.join(tempfile.mkdtemp(), "mock.sock")
proc = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "tests", "mock_daemon.py"), sock])
try:
    for _ in range(50):
        if os.path.exists(sock):
            break
        time.sleep(0.1)
    c = A.ControlClient(sock)
    assert c.version() == "0.9.14", c.version()
    assert c.state()["code"] == "clean"
    events = []
    stream = c.watch()
    t = threading.Thread(target=lambda: [events.append(e["code"]) for e in stream], daemon=True)
    t.start()
    time.sleep(0.2)
    try:
        c.connect()
        raise SystemExit("connect ohne Token hätte fehlschlagen müssen")
    except A.ApiError as e:
        assert "no Access-Token" in e.message, e.message
    try:
        c.request_token("free.hideservers.net", "user", "falsch")
        raise SystemExit("falsches Passwort hätte fehlschlagen müssen")
    except A.ApiError as e:
        assert "401" in e.message
    tok = c.request_token("free.hideservers.net", "user", "geheim")
    assert tok.startswith("dG9r")
    assert c.set_configuration({"Rest": {"AccessToken": tok, "Host": C.fqdn("amsterdam")}}) is True
    cfg = c.get_configuration()
    assert cfg["Rest"]["Host"] == "amsterdam.hideservers.net"
    res = c.connect()
    assert res["code"] == "connected", res
    st = c.state()
    assert st["rx"] > 0
    c.external_ips()
    time.sleep(1.2)
    assert c.server_list()[0]["hostname"] == "nl-v4.hideservers.net"
    assert "Conn: Connected" in c.log()
    c.destroy()
    assert c.state()["code"] == "clean"
    time.sleep(0.3)
    stream.close()
    print("Ereignisse:", events)
    for needed in ("connecting", "dns lookup", "connected", "external ips", "disconnecting", "clean"):
        assert needed in events, needed
    # Hilfsfunktionen
    assert C.fqdn("nl") == "nl.hideservers.net"
    assert C.fqdn("nl.hide.me") == "nl.hideservers.net"
    assert C.fqdn("1.2.3.4") == "1.2.3.4"
    assert C.short_name("amsterdam-v4.hideservers.net") == "amsterdam"
    assert C.valid_cidr("192.168.0.0/16") and not C.valid_cidr("192.168.0.1")
    assert C.valid_hostport("1.1.1.1:53") and C.valid_hostport("[2606:4700::1111]:53")
    assert not C.valid_hostport("dns.google:53")
    assert C.valid_dns_name("*.example.com") and not C.valid_dns_name("bad name")
    assert C.duration_go(90 * C.NS) == "1m30s"
    assert C.patch_needs_reroute({"WireGuard": {"LeakProtection": False}})
    assert not C.patch_needs_reroute({"Rest": {"Filter": {"ads": True}}})
    print(C.cli_command(cfg, "amsterdam"))
    # nicht erreichbar
    try:
        A.ControlClient("/nonexistent/x.sock").state()
    except A.DaemonUnavailable as e:
        assert e.reason == "missing"
    print("OK – alle API-Tests bestanden")
finally:
    proc.terminate()
    proc.wait()
