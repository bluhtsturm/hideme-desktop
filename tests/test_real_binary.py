#!/usr/bin/env python3
"""Prüft die App-Anbindung gegen das echte hide.me-Programm (ohne Root-Rechte).

Startet ``hide.me service`` als normaler Benutzer in einem temporären Verzeichnis.
Verbindungsaufbau ist so nicht möglich (fehlende Netzwerkrechte), wohl aber alle
übrigen Schnittstellen. Benötigt Internetzugang (Serverliste, Kategorien, DoH).

    python3 -I tests/test_real_binary.py build/hide.me
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hideme_desktop import api as A  # noqa: E402
from hideme_desktop import cli  # noqa: E402
from hideme_desktop import config as C  # noqa: E402

BIN = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "hide.me"))
os.environ["HIDEME_BIN"] = BIN
work = tempfile.mkdtemp(prefix="hm-real-")
os.environ["XDG_CACHE_HOME"] = os.path.join(work, "cache")
sock = f"/run/user/{os.getuid()}/hm-real.sock"
shutil.copy(os.path.join(ROOT, "hide.client.linux", "CA.pem"), work)
cfg_path = os.path.join(work, "config.json")
with open(cfg_path, "w") as fh:
    fh.write("{}")

failures = []


def check(name, cond, detail=""):
    print(("  OK  " if cond else "  FEHLER ") + name + (f" – {detail}" if detail and not cond else ""), flush=True)
    if not cond:
        failures.append(name)


proc = subprocess.Popen([BIN, "--caddr", sock, "-c", cfg_path, "service"], cwd=work,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(50):
        if os.path.exists(sock):
            break
        time.sleep(0.1)
    c = A.ControlClient(sock)

    check("version", c.version() == "0.9.14", c.version())
    st = c.state()
    check("state: clean", st.get("code") == "clean", json.dumps(st))

    cfg = c.get_configuration()
    check("Konfiguration: Abschnitte Rest/WireGuard/DoH/Plain", all(k in cfg for k in ("Rest", "WireGuard", "DoH", "Plain")),
          ",".join(cfg))
    check("Konfiguration: Feldnamen wie erwartet",
          cfg["WireGuard"]["LeakProtection"] is True and cfg["Rest"]["Port"] == 432 and
          cfg["WireGuard"]["DpdTimeout"] == 60 * C.NS and "Servers" in cfg["Plain"] and "filename" in cfg["DoH"],
          json.dumps(cfg)[:300])
    for section, fields in C.DEFAULTS.items():
        missing = [k for k in fields if k not in cfg[section]]
        check(f"Standardwerte-Felder in {section} vorhanden", not missing, str(missing))

    events = []
    stream = c.watch()
    threading.Thread(target=lambda: [events.append(e) for e in stream], daemon=True).start()
    time.sleep(0.3)

    patch = {"Rest": {"Host": C.fqdn("nl"), "Filter": {"ads": True, "PG": 12, "blacklist": ["ads.example.com"]},
                      "PortForward": {"enabled": True}},
             "WireGuard": {"SplitTunnel": "192.168.0.0/16", "DpdTimeout": 30 * C.NS}}
    check("POST /configuration", c.set_configuration(patch) is True)
    cfg2 = c.get_configuration()
    check("Teilkonfiguration übernommen (Filter, PortForward, SplitTunnel, DPD)",
          cfg2["Rest"]["Filter"].get("ads") is True and cfg2["Rest"]["Filter"].get("PG") == 12 and
          cfg2["Rest"]["PortForward"].get("enabled") is True and cfg2["WireGuard"]["SplitTunnel"] == "192.168.0.0/16"
          and cfg2["WireGuard"]["DpdTimeout"] == 30 * C.NS, json.dumps(cfg2["Rest"]["Filter"]))
    check("Bestehende Felder bleiben erhalten", cfg2["WireGuard"]["LeakProtection"] is True)
    with open(cfg_path) as fh:
        saved = json.load(fh)
    check("Konfiguration in Datei gespeichert (SaveJson)", saved.get("Rest", {}).get("Host") == "nl.hideservers.net",
          json.dumps(saved)[:200])

    c.set_configuration({"Rest": {"Filter": {"ads": False, "PG": 0, "blacklist": []}}})
    f3 = c.get_configuration()["Rest"]["Filter"]
    check("Filter lassen sich wieder ausschalten", not f3.get("ads") and not f3.get("PG") and not f3.get("blacklist"),
          json.dumps(f3))

    try:
        c.connect(timeout=30)
        check("connect ohne Token schlägt fehl", False, "kein Fehler")
    except A.ApiError as e:
        print(f"       (connect-Fehler wie erwartet: {e.message})")
        check("connect ohne Root/Token liefert JSON-Fehler", e.code == "connect", f"{e.code}: {e.message}")
    check("Zustand danach wieder clean", c.state().get("code") == "clean", c.state().get("code"))

    try:
        servers = c.server_list(timeout=60)
        check("Serverliste geladen", isinstance(servers, list) and len(servers) > 5, str(type(servers)))
        sample = servers[0]
        keys = set(sample)
        check("Serverliste: erwartete Felder", {"hostname", "displayName", "tags", "geo"} <= keys, str(keys))
        geo_ok = any((s.get("geo") or {}).get("countryCode") for s in servers)
        check("Serverliste: Ländercodes vorhanden", geo_ok)
        total = sum(1 + len(s.get("children") or []) for s in servers)
        free = [C.short_name(s["hostname"]) for s in servers if "free" in (s.get("tags") or [])]
        print(f"       {len(servers)} Standorte, {total} Einträge, kostenlos: {', '.join(free[:8])}")
        print(f"       Beispiel: {json.dumps(sample)[:260]}")
    except A.ApiError as e:
        check("Serverliste geladen", False, e.message)

    c.external_ips()
    deadline = time.time() + 15
    ext = None
    while time.time() < deadline and not ext:
        ext = next((e for e in events if e.get("code") == A.EXTERNAL_IPS), None)
        time.sleep(0.3)
    check("Öffentliche IP per Ereignis 'external ips'", ext is not None and (ext.get("external_ip") or
                                                                             ext.get("external_ipv6")), str(ext))

    log = c.log()
    check("Log enthält Einträge", "Serv: Configured" in log, log[-200:])
    codes = [e.get("code") for e in events]
    check("Ereignisstrom liefert 'configuration set'", A.CONFIGURATION_SET in codes, str(codes))
    stream.close()

    # Programmaufrufe als Benutzer
    try:
        ips = cli.resolve_doh("nl.hideservers.net")
        check("hide.me resolve (DoH)", len(ips) > 0, str(ips))
    except cli.CliError as e:
        check("hide.me resolve (DoH)", False, str(e))
    try:
        ips = cli.lookup_plain("nl.hideservers.net", C.DEFAULTS["Plain"]["Servers"])
        check("hide.me lookup (klassisch)", len(ips) > 0, str(ips))
    except cli.CliError as e:
        if "operation not permitted" in str(e):
            print(f"       (lookup übersprungen: UDP-DNS wird von diesem Netzwerk blockiert – {e})")
        else:
            check("hide.me lookup (klassisch)", False, str(e))
    try:
        cats = cli.categories("nl")
        check("hide.me categories", len(cats) > 5, str(cats[:3]))
        print(f"       {len(cats)} Kategorien, z. B. {', '.join(n for n, _d in cats[:6])}")
    except cli.CliError as e:
        check("hide.me categories", False, str(e))
    yaml_text = cli.config_to_yaml(cfg2)
    check("Export nach YAML (hide.me conf)", "leakProtection" in yaml_text or "leakprotection" in yaml_text.lower(),
          yaml_text[:200])
    ypath = os.path.join(work, "export.yaml")
    with open(ypath, "w") as fh:
        fh.write(yaml_text)
    back = cli.config_file_to_json(ypath)
    check("Import aus YAML (hide.me jsonconf)", back.get("WireGuard", {}).get("SplitTunnel") == "192.168.0.0/16",
          json.dumps(back)[:200])
    print(f"       CLI-Äquivalent: {C.cli_command(cfg2)}")
finally:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out = ""
    shutil.rmtree(work, ignore_errors=True)

print(f"\n{'Alle Prüfungen bestanden' if not failures else str(len(failures)) + ' Fehler'}")
sys.exit(1 if failures else 0)
