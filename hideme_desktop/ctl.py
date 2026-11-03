"""hidemectl – Steuerung des hide.me-Daemons von der Kommandozeile.

Wird auch von hideme-autoconnect.service beim Systemstart verwendet.
"""

import argparse
import getpass
import json
import sys
import threading
import time

from . import DEFAULT_SOCKET, VERSION
from . import api as A
from . import config as C


def _print_state(st):
    code = st.get("code", "?")
    print(f"Zustand:   {code}")
    if st.get("host"):
        print(f"Server:    {st['host']}")
    if code == A.CONNECTED:
        print(f"Endpunkt:  {(st.get('endpoint') or {}).get('IP', '–')}")
        print(f"Tunnel:    {', '.join(st.get('allowedIps') or [])}")
        print(f"DNS:       {', '.join(st.get('DNS') or [])}")
        print(f"Empfangen: {st.get('rx', 0)} B   Gesendet: {st.get('tx', 0)} B")
    if st.get("external_ip"):
        print(f"IPv4:      {st['external_ip']}")
    if st.get("external_ipv6"):
        print(f"IPv6:      {st['external_ipv6']}")


def cmd_connect(client, args):
    if args.server:
        client.set_configuration({"Rest": {"Host": C.fqdn(args.server)}})
    attempts = max(1, args.retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            st = client.state()
            if st.get("code") == A.CONNECTED and not args.server:
                print("Bereits verbunden.")
                return 0
            if st.get("code") in (A.CONNECTED, A.CONNECTING):
                client.disconnect()
            res = client.connect()
            _print_state(res or {})
            return 0
        except A.ApiError as e:
            msg = e.message
            print(f"Versuch {attempt}/{attempts} fehlgeschlagen: {msg}", file=sys.stderr)
            permanent = ("no Access-Token", "missing host", "401", "403", "application update required")
            if any(p in msg for p in permanent) or attempt == attempts:
                return 1
            time.sleep(min(5 * attempt, 30))
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="hidemectl", description="hide.me-Daemon steuern")
    p.add_argument("--socket", default=DEFAULT_SOCKET, help=f"Steueradresse (Standard: {DEFAULT_SOCKET})")
    p.add_argument("--version", action="version", version=f"hidemectl {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Zustand anzeigen")
    c = sub.add_parser("connect", help="verbinden")
    c.add_argument("server", nargs="?", help="Server (z. B. nl, amsterdam); leer = zuletzt verwendeter")
    c.add_argument("--retries", type=int, default=0, help="Anzahl Wiederholungen bei Fehlern")
    sub.add_parser("disconnect", help="trennen (Kill-Switch bleibt aktiv)")
    sub.add_parser("destroy", help="trennen und Routing entfernen")
    sub.add_parser("route", help="Routing/Kill-Switch einrichten ohne Verbindung")
    sub.add_parser("log", help="Daemon-Protokoll ausgeben")
    s = sub.add_parser("servers", help="Serverliste")
    s.add_argument("--free", action="store_true", help="nur kostenlose Server")
    sub.add_parser("watch", help="Ereignisse live anzeigen")
    sub.add_parser("ip", help="öffentliche IP-Adressen ermitteln")
    lg = sub.add_parser("login", help="Zugangstoken anfordern")
    lg.add_argument("username")
    lg.add_argument("--host", default="free", help="Server für die Token-Anfrage")
    sub.add_parser("logout", help="Zugangstoken entfernen")
    cf = sub.add_parser("config", help="Konfiguration lesen oder setzen")
    cf.add_argument("json", nargs="?", help="JSON-Teilkonfiguration, z. B. '{\"WireGuard\":{\"LeakProtection\":true}}'")
    sub.add_parser("version", help="Daemon-Version")
    args = p.parse_args(argv)

    client = A.ControlClient(args.socket)
    try:
        if args.cmd == "status":
            _print_state(client.state())
        elif args.cmd == "connect":
            return cmd_connect(client, args)
        elif args.cmd == "disconnect":
            _print_state(client.disconnect() or {})
        elif args.cmd == "destroy":
            _print_state(client.destroy() or {})
        elif args.cmd == "route":
            _print_state(client.route() or {})
        elif args.cmd == "log":
            sys.stdout.write(client.log())
        elif args.cmd == "servers":
            def walk(items, depth=0):
                for loc in items:
                    tags = loc.get("tags") or []
                    if not args.free or "free" in tags:
                        print(f"{'  ' * depth}{loc.get('displayName', ''):<30} {C.short_name(loc.get('hostname')):<20} "
                              f"{','.join(tags)}")
                    walk(loc.get("children") or [], depth + 1)
            walk(client.server_list())
        elif args.cmd == "watch":
            for ev in client.watch():
                print(json.dumps(ev), flush=True)
        elif args.cmd == "ip":
            stream = client.watch()
            time.sleep(0.3)  # dem Daemon Zeit geben, den Beobachter zu registrieren
            timer = threading.Timer(20, stream.close)  # nicht ewig auf das Ereignis warten
            timer.start()
            client.external_ips()
            found = False
            for ev in stream:
                if ev.get("code") == A.EXTERNAL_IPS:
                    print(f"IPv4: {ev.get('external_ip') or '–'}")
                    print(f"IPv6: {ev.get('external_ipv6') or '–'}")
                    found = True
                    break
            timer.cancel()
            stream.close()
            if not found:
                print("Fehler: keine Antwort vom Daemon", file=sys.stderr)
                return 1
        elif args.cmd == "login":
            password = getpass.getpass("Passwort: ")
            old = (client.get_configuration().get("Rest") or {}).get("AccessToken") or ""
            if old:
                # Ein vorhandenes Token hätte bei der Anfrage Vorrang vor Benutzername/Passwort
                client.set_configuration({"Rest": {"AccessToken": ""}})
            try:
                token = client.request_token(C.fqdn(args.host), args.username, password)
                if not isinstance(token, str) or not token:
                    raise A.ApiError("Der Server hat kein Token geliefert")
            except A.ApiError:
                if old:
                    client.set_configuration({"Rest": {"AccessToken": old}})  # altes Token behalten
                raise
            client.set_configuration({"Rest": {"AccessToken": token}})
            print("Zugangstoken gespeichert.")
        elif args.cmd == "logout":
            client.set_configuration({"Rest": {"AccessToken": ""}})
            client.delete_token()
            print("Zugangstoken entfernt.")
        elif args.cmd == "config":
            if args.json:
                client.set_configuration(json.loads(args.json))
            cfg = client.get_configuration()
            if (cfg.get("Rest") or {}).get("AccessToken"):
                cfg["Rest"]["AccessToken"] = "<gesetzt>"
            print(json.dumps(cfg, indent=2))
        elif args.cmd == "version":
            print(client.version())
    except A.ApiError as e:
        print(f"Fehler: {C.explain_error(e.message)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
