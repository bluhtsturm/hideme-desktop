"""Hilfsfunktionen rund um die Daemon-Konfiguration (connection.Config).

Die JSON-Feldnamen entsprechen den Go-Strukturen aus hide.client.linux:
``Rest`` (rest.Config), ``WireGuard`` (wireguard.Config), ``DoH`` (doh.Config)
und ``Plain`` (plain.Config). Zeitdauern sind Nanosekunden.
"""

import ipaddress
import re
import shlex

NS = 1_000_000_000

# Standardwerte aus configuration.go (NewConfiguration)
DEFAULTS = {
    "Rest": {
        "Port": 432,
        "CA": "CA.pem",
        "AccessTokenPath": "accessToken.txt",
        "RestTimeout": 90 * NS,
        "ReconnectWait": 30 * NS,
        "AccessTokenUpdateDelay": 2 * NS,
        "Mark": 0,
        "UseDoH": True,
        "Filter": {},
        "PortForward": {},
    },
    "WireGuard": {
        "Name": "vpn",
        "ListenPort": 0,
        "Mark": 0,
        "RPDBPriority": 10,
        "PrivateKey": "",
        "RoutingTable": 55555,
        "LeakProtection": True,
        "ResolvConfBackupFile": "",
        "DpdTimeout": 60 * NS,
        "SplitTunnel": "",
        "IPv4": True,
        "IPv6": True,
    },
    "DoH": {"filename": "resolvers.txt"},
    "Plain": {"Servers": ["209.250.251.37:53", "217.182.206.81:53"]},
}

PG_VALUES = [0, 12, 18, 21]
RISK_LEVELS = [("possible", "Mögliches Risiko"), ("medium", "Mittleres Risiko"), ("high", "Hohes Risiko")]
ILLEGAL_KINDS = [
    ("content", "Illegale Inhalte"),
    ("warez", "Warez / Raubkopien"),
    ("spyware", "Spyware"),
    ("copyright", "Urheberrechtsverletzungen"),
]
FILTER_SWITCHES = [
    ("ads", "Werbung blockieren", "Blendet Werbeanzeigen über DNS-Filterung aus (--noAds)"),
    ("trackers", "Tracker blockieren", "Unterbindet Tracking-Dienste (--noTrackers)"),
    ("malware", "Malware blockieren", "Sperrt Seiten, die Malware verbreiten (--noMalware)"),
    ("malicious", "Schädliche Ziele blockieren", "Sperrt bekannte bösartige Hosts und Domains (--noMalicious)"),
    ("safeSearch", "SafeSearch erzwingen", "Erzwingt SafeSearch bei Google und Bing (--safeSearch)"),
    ("forceDns", "DNS über hide.me erzwingen",
     "Jede DNS-Anfrage im Tunnel wird vom hide.me-Server beantwortet (--forceDns)"),
]

_DNS_NAME_RE = re.compile(r"^([0-9A-Za-z_]|\.|-|\*)+$")


def get(cfg, section, key):
    """Liest einen Wert mit Rückfall auf den Standardwert."""
    sec = (cfg or {}).get(section) or {}
    if key in sec and sec[key] is not None:
        return sec[key]
    return DEFAULTS.get(section, {}).get(key)


def get_filter(cfg):
    f = dict(((cfg or {}).get("Rest") or {}).get("Filter") or {})
    f.setdefault("PG", 0)
    for key in ("risk", "illegal", "whitelist", "blacklist", "categories"):
        f[key] = list(f.get(key) or [])
    for key, _t, _s in FILTER_SWITCHES:
        f[key] = bool(f.get(key, False))
    return f


def filter_active(f):
    if any(f.get(k) for k, _t, _s in FILTER_SWITCHES):
        return True
    if f.get("PG"):
        return True
    return any(f.get(k) for k in ("risk", "illegal", "whitelist", "blacklist", "categories"))


def filter_summary(f):
    parts = []
    names = {"ads": "Werbung", "trackers": "Tracker", "malware": "Malware", "malicious": "Schädliches",
             "safeSearch": "SafeSearch", "forceDns": "DNS erzwungen"}
    for key, label in names.items():
        if f.get(key):
            parts.append(label)
    if f.get("PG"):
        parts.append(f"Jugendschutz {f['PG']}")
    if f.get("categories"):
        parts.append(f"{len(f['categories'])} Kategorien")
    if f.get("risk"):
        parts.append("Risiko")
    if f.get("illegal"):
        parts.append("Illegales")
    if f.get("blacklist"):
        parts.append(f"{len(f['blacklist'])} gesperrte Domains")
    return ", ".join(parts) if parts else "Aus"


def valid_dns_name(name):
    return bool(_DNS_NAME_RE.match(name or ""))


def valid_cidr(text):
    try:
        ipaddress.ip_network(text.strip(), strict=False)
        return "/" in text
    except ValueError:
        return False


def valid_hostport(text):
    text = (text or "").strip()
    if text.startswith("["):
        m = re.match(r"^\[([^\]]+)\]:(\d+)$", text)
        if not m:
            return False
        host, port = m.group(1), m.group(2)
    else:
        if text.count(":") != 1:
            return False
        host, port = text.rsplit(":", 1)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return port.isdigit() and 0 < int(port) < 65536


def is_ip(text):
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def short_name(host):
    """``nl-v4.hideservers.net`` → ``nl`` (wie ``hide.me list`` es anzeigt)."""
    host = (host or "").strip()
    if is_ip(host):
        return host
    for suffix in ("-v4.hideservers.net", ".hideservers.net", ".hide.me"):
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return host


def fqdn(host):
    """Entspricht rest.Config.SetHost(): Kurzname → ``<name>.hideservers.net``."""
    host = (host or "").strip()
    if not host or is_ip(host) or host.endswith(".hideservers.net"):
        return host
    if host.endswith("-v4.hideservers.net"):
        host = host[: -len("-v4.hideservers.net")]
    if host.endswith(".hide.me"):
        host = host[: -len(".hide.me")]
    return host + ".hideservers.net"


def seconds(ns):
    try:
        return int(ns or 0) / NS
    except (TypeError, ValueError):
        return 0


def duration_go(ns):
    """Nanosekunden → Go-Dauerschreibweise (z. B. ``1m30s``)."""
    total = int(round(seconds(ns)))
    if total <= 0:
        return "0s"
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    out = ""
    if h:
        out += f"{h}h"
    if h or m:
        out += f"{m}m"
    out += f"{s}s"
    return out


# Felder, deren Änderung ein Neuaufsetzen des Routings (destroy/route) erfordert
REROUTE_FIELDS = {
    "WireGuard": {"Name", "ListenPort", "Mark", "RPDBPriority", "PrivateKey", "RoutingTable",
                  "LeakProtection", "IPv4", "IPv6"},
    "Rest": {"Mark", "CA", "AccessToken", "AccessTokenPath"},
    "DoH": None,  # alle Felder
}


def patch_needs_reroute(patch):
    for section, fields in REROUTE_FIELDS.items():
        if section not in patch:
            continue
        if fields is None:
            return True
        if any(k in fields for k in (patch.get(section) or {})):
            return True
    return False


def cli_command(cfg, host=None, binary="hide.me"):
    """Erzeugt einen gleichwertigen ``hide.me connect``-Aufruf (ohne Geheimnisse)."""
    args = [binary]
    rest = (cfg or {}).get("Rest") or {}
    wg = (cfg or {}).get("WireGuard") or {}

    def differs(section, key):
        return get(cfg, section, key) != DEFAULTS[section].get(key)

    if differs("Rest", "Port"):
        args += ["-p", str(get(cfg, "Rest", "Port"))]
    if differs("Rest", "CA"):
        args += ["--ca", str(get(cfg, "Rest", "CA"))]
    if differs("Rest", "AccessTokenPath"):
        args += ["-t", str(get(cfg, "Rest", "AccessTokenPath"))]
    if not get(cfg, "Rest", "UseDoH"):
        args += ["--doh=false"]
    if differs("Rest", "RestTimeout"):
        args += ["--rest-timeout", duration_go(get(cfg, "Rest", "RestTimeout"))]
    if (rest.get("PortForward") or {}).get("enabled"):
        args += ["--pf"]
    plain = get(cfg, "Plain", "Servers") or []
    if list(plain) != DEFAULTS["Plain"]["Servers"]:
        args += ["--dns", ",".join(plain)]
    f = get_filter(cfg)
    flag_map = {"forceDns": "--forceDns", "ads": "--noAds", "trackers": "--noTrackers", "malware": "--noMalware",
                "malicious": "--noMalicious", "safeSearch": "--safeSearch"}
    for key, flag in flag_map.items():
        if f.get(key):
            args.append(flag)
    if f.get("PG"):
        args += ["--pg", str(f["PG"])]
    for key, flag in (("risk", "--noRisk"), ("illegal", "--noIllegal"), ("categories", "--noCategories"),
                      ("whitelist", "--whitelist"), ("blacklist", "--blacklist")):
        if f.get(key):
            args += [flag, ",".join(f[key])]
    if differs("WireGuard", "Name"):
        args += ["-i", str(wg.get("Name"))]
    if wg.get("ListenPort"):
        args += ["-l", str(wg.get("ListenPort"))]
    if wg.get("Mark"):
        args += ["-m", str(wg.get("Mark"))]
    if differs("WireGuard", "RoutingTable"):
        args += ["-r", str(wg.get("RoutingTable"))]
    if differs("WireGuard", "RPDBPriority"):
        args += ["-R", str(wg.get("RPDBPriority"))]
    if not get(cfg, "WireGuard", "LeakProtection"):
        args += ["--kill-switch=false"]
    if wg.get("ResolvConfBackupFile"):
        args += ["-b", wg["ResolvConfBackupFile"]]
    if differs("WireGuard", "DpdTimeout"):
        args += ["--dpd", duration_go(get(cfg, "WireGuard", "DpdTimeout"))]
    if wg.get("SplitTunnel"):
        args += ["-s", wg["SplitTunnel"]]
    v4, v6 = get(cfg, "WireGuard", "IPv4"), get(cfg, "WireGuard", "IPv6")
    if v4 and not v6:
        args.append("-4")
    elif v6 and not v4:
        args.append("-6")
    args += ["connect", short_name(host or rest.get("Host") or "SERVER")]
    return " ".join(shlex.quote(a) for a in args)


_ERROR_HINTS = [
    ("no Access-Token", "Kein Zugangstoken vorhanden – bitte zuerst mit deinem hide.me-Konto anmelden."),
    ("bad HTTP status 401", "Anmeldung abgelehnt (HTTP 401) – Benutzername oder Passwort prüfen."),
    ("bad HTTP status 403", "Zugriff verweigert (HTTP 403) – Konto, Abo oder gewählten Server prüfen."),
    ("bad HTTP status 410", "Der Server meldet: Client-Update erforderlich oder Token ungültig (HTTP 410)."),
    ("application update required", "Der hide.me-Server verlangt eine neuere Client-Version."),
    ("missing host", "Kein Server ausgewählt."),
    ("no such host", "Der Servername konnte nicht aufgelöst werden."),
    ("context deadline exceeded", "Zeitüberschreitung – der Server antwortet nicht."),
    ("i/o timeout", "Zeitüberschreitung – der Server antwortet nicht."),
    ("network is unreachable", "Netzwerk nicht erreichbar."),
    ("bad public key PIN", "Zertifikatsprüfung fehlgeschlagen (PIN stimmt nicht) – möglicher Angriff!"),
    ("operation not permitted", "Fehlende Rechte – läuft der Daemon als root?"),
    ("bad state", "Der Daemon befindet sich in einem unpassenden Zustand."),
    ("no username", "Bitte Benutzernamen angeben."),
    ("no password", "Bitte Passwort angeben."),
    ("dpd timeout above 1 minute", "Der DPD-Timeout darf höchstens 60 Sekunden betragen."),
]


def explain_error(message):
    """Ergänzt technische Fehlermeldungen um eine verständliche Erklärung."""
    msg = str(message or "").strip()
    for needle, hint in _ERROR_HINTS:
        if needle.lower() in msg.lower():
            return f"{hint}\n\nDetails: {msg}" if msg and msg.lower() != needle.lower() else hint
    return msg or "Unbekannter Fehler"
