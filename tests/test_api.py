#!/usr/bin/env python3
"""Testet den API-Client gegen den Mock-Daemon (ohne GTK)."""
import json
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
    # Wie hide.me 0.9.14: /serverList beschädigt die REST-Konfiguration – die Reparatur muss das erkennen
    assert C.repair_patch(c.get_configuration(), "amsterdam") is None
    c.request("GET", "/serverList")
    fix = C.repair_patch(c.get_configuration(), "amsterdam")
    assert fix == {"Rest": {"Port": 432, "APIVersion": "v1.0.0", "CA": "CA.pem",
                            "Host": "amsterdam.hideservers.net"}}, fix
    c.set_configuration(fix)
    assert C.repair_patch(c.get_configuration()) is None
    assert C.repair_patch({"Rest": {"Host": "nl.hideservers.net", "Port": 432, "CA": "CA.pem",
                                    "APIVersion": "v1"}}) == {"Rest": {"Port": 432, "APIVersion": "v1.0.0"}}
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
    # Direkte Abfragen (Serverliste, IP) über umgeleitete Adressen
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "servers.json"), "w") as fh:
        json.dump([{"hostname": "nl-v4.hideservers.net", "displayName": "Netherlands", "tags": []}], fh)
    with open(os.path.join(tmp, "ip4"), "w") as fh:
        fh.write("185.212.170.10\n")
    with open(os.path.join(tmp, "ip6"), "w") as fh:
        fh.write("kein-ip-text")
    os.environ["HIDEME_SERVERLIST_URL"] = "file://" + os.path.join(tmp, "servers.json")
    os.environ["HIDEME_IPCHECK_V4"] = "file://" + os.path.join(tmp, "ip4")
    os.environ["HIDEME_IPCHECK_V6"] = "file://" + os.path.join(tmp, "ip6")
    from hideme_desktop import netinfo
    assert netinfo.fetch_server_list()[0]["hostname"] == "nl-v4.hideservers.net"
    assert netinfo.public_ips() == ("185.212.170.10", None), netinfo.public_ips()
    assert C.patch_needs_reconnect({"Rest": {"Filter": {"ads": True}}})
    assert not C.patch_needs_reconnect({"WireGuard": {"DpdTimeout": 1}, "Rest": {"ReconnectWait": 1}})
    try:
        from hideme_desktop.controller import parse_go_time
    except ImportError:  # ohne PyGObject
        parse_go_time = None
    if parse_go_time:
        for stamp in ("2026-11-01T17:01:02.5+01:00", "2026-11-01T17:01:02.123456789+01:00",
                      "2026-11-01T16:01:02Z", "2026-11-01T17:01:02.1234+01:00"):
            assert parse_go_time(stamp) is not None, stamp
        assert parse_go_time("0001-01-01T00:00:00Z") is None
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
