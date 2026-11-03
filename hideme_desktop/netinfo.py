"""Direkte Netzabfragen der App – ohne den Daemon.

Zwei Funktionen des hide.me-Daemons (CLI 0.9.14) sind dafür ungeeignet:

* ``/serverList`` überschreibt dauerhaft die REST-Konfiguration des Daemons (Host
  ``api.hide.me``, Port 443, leere CA, API-Version ``v1``): Der Daemon erzeugt den
  Abrufer mit der laufenden Konfiguration statt mit einer Kopie (control/methods.go,
  ``rest.New(s.connection.Config.Rest)``), und ``FetchServerList`` ändert diese
  (rest/client.go). Danach scheitern Anmeldung und Verbindungsaufbau.
* ``/externalIps`` fragt bei bestehender Verbindung die fest eingestellten
  hide.me-DNS-Server ab, die durch den Tunnel nicht antworten – die Abfrage liefert dann keine Adressen.

Für Tests lassen sich die Adressen über Umgebungsvariablen umleiten (auch auf file://).
"""

import ipaddress
import json
import os
import ssl
import urllib.request

from . import VERSION

SERVERLIST_URL = os.environ.get("HIDEME_SERVERLIST_URL") or "https://api.hide.me/v1/network/free/en"
# Der IP-Prüfdienst antwortet nur über HTTP (über HTTPS kommt keine Verbindung zustande)
IPCHECK_V4_URL = os.environ.get("HIDEME_IPCHECK_V4") or "http://ipcheck.hideservers.net/"
IPCHECK_V6_URL = os.environ.get("HIDEME_IPCHECK_V6") or "http://ipcheck-v6.hideservers.net/"


def _get(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": f"hideme-desktop/{VERSION}"})
    context = ssl.create_default_context() if url.startswith("https:") else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


def fetch_server_list(timeout=20):
    """Standortliste wie ``hide.me list`` (dieselbe Adresse, reguläre Zertifikatsprüfung)."""
    data = json.loads(_get(SERVERLIST_URL, timeout).decode("utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("unerwartete Antwort von api.hide.me")
    return data


def _public_ip(url, version, timeout):
    try:
        ip = ipaddress.ip_address(_get(url, timeout).decode("ascii", "replace").strip())
    except (OSError, ValueError):
        return None
    return str(ip) if ip.version == version else None


def public_ips(timeout=6):
    """Öffentliche (IPv4, IPv6) über den aktuellen Netzweg – bei bestehender Verbindung also durch den Tunnel."""
    return _public_ip(IPCHECK_V4_URL, 4, timeout), _public_ip(IPCHECK_V6_URL, 6, timeout)
