"""Formatierungs- und Darstellungshilfen."""

import datetime

from .. import config as C

PHASE_TEXT = {
    "unavailable": ("Daemon nicht erreichbar", "hideme-shield-off-symbolic", "unavailable"),
    "disconnected": ("Nicht verbunden", "hideme-shield-off-symbolic", "disconnected"),
    "blocked": ("Internet blockiert", "hideme-shield-alert-symbolic", "blocked"),
    "connecting": ("Verbinde …", "hideme-shield-sync-symbolic", "connecting"),
    "reconnecting": ("Verbinde neu …", "hideme-shield-sync-symbolic", "connecting"),
    "disconnecting": ("Trenne …", "hideme-shield-sync-symbolic", "connecting"),
    "connected": ("Geschützt", "hideme-shield-symbolic", "connected"),
}

# Tags der Serverliste; nicht aufgeführte (no-ping, no-hop-in, no-geo, …) sind intern
TAG_LABELS = {"free": "Kostenlos", "10g": "10 Gbit/s", "non-p2p": "Kein P2P", "upgrade": "Premium"}
VISIBLE_TAGS = [("free", "free"), ("10g", "fast"), ("non-p2p", None)]

CONTINENTS = [("EU", "Europa"), ("NA", "Nordamerika"), ("SA", "Südamerika"), ("AS", "Asien"),
              ("AF", "Afrika"), ("OC", "Ozeanien"), ("AN", "Antarktis")]


def continent_name(code):
    return dict(CONTINENTS).get((code or "").upper(), code or "")


def visible_tags(tags):
    """Liefert (Beschriftung, CSS-Klasse) für die anzuzeigenden Tags."""
    tags = set(tags or [])
    return [(TAG_LABELS[t], css) for t, css in VISIBLE_TAGS if t in tags]


def fmt_number(value, digits=1):
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{fmt_number(n)} {unit}"
        n /= 1000
    return f"{n} B"


def fmt_rate(bps):
    bits = float(bps or 0) * 8
    for unit in ("bit/s", "kbit/s", "Mbit/s", "Gbit/s"):
        if bits < 1000 or unit == "Gbit/s":
            return f"{int(bits)} {unit}" if unit == "bit/s" else f"{fmt_number(bits)} {unit}"
        bits /= 1000
    return f"{bits} bit/s"


def fmt_duration(delta):
    if delta is None:
        return "–"
    total = int(delta.total_seconds()) if isinstance(delta, datetime.timedelta) else int(delta)
    total = max(total, 0)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d} d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def since(dt):
    if not dt:
        return None
    now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
    return now - dt


def flag_emoji(code):
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)


def location_country(loc):
    geo = (loc or {}).get("geo") or {}
    code = geo.get("countryCode") or ""
    if not code:
        flag = (loc or {}).get("flag") or ""
        if len(flag) == 2:
            code = flag
    return code


def server_label(controller, host):
    """Anzeigename + Flagge für einen Server (Kurzname, FQDN oder IP)."""
    if not host:
        return "Kein Server gewählt", "🌐"
    loc = controller.find_server(host)
    if loc:
        name = loc.get("displayName") or C.short_name(host)
        return name, flag_emoji(location_country(loc))
    return C.short_name(host), "🌐"


def ips(values):
    if not values:
        return "–"
    if isinstance(values, (list, tuple)):
        return ", ".join(str(v) for v in values if v)
    return str(values)


def endpoint_text(ep):
    if not isinstance(ep, dict) or not ep.get("IP"):
        return "–"
    ip = ep.get("IP")
    port = ep.get("Port")
    return f"[{ip}]:{port}" if ":" in str(ip) else f"{ip}:{port}"
