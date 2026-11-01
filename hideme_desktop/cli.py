"""Aufrufe des hide.me-Programms, die keine Root-Rechte benötigen.

``categories``, ``resolve``, ``lookup``, ``conf`` und ``jsonconf`` laufen als
normaler Benutzer. Alles, was Routing oder Schnittstellen verändert, erledigt
der Daemon.
"""

import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.request

from .settings import cache_dir

_HERE = os.path.dirname(os.path.abspath(__file__))


class CliError(Exception):
    pass


def find_binary():
    candidates = [
        os.environ.get("HIDEME_BIN"),
        os.path.join(os.path.dirname(_HERE), "bin", "hide.me"),
        "/opt/hideme-desktop/bin/hide.me",
        "/usr/lib/hideme-desktop/hide.me",
        "/usr/bin/hide.me",
        "/opt/hide.me/hide.me",
        shutil.which("hide.me"),
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _run(args, timeout=90):
    binary = find_binary()
    if not binary:
        raise CliError("Das hide.me-Programm wurde nicht gefunden. Ist hide.me Desktop vollständig installiert?")
    workdir = cache_dir()
    os.makedirs(workdir, exist_ok=True)
    try:
        proc = subprocess.run([binary] + list(args), cwd=workdir, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise CliError("Zeitüberschreitung beim Ausführen von hide.me") from e
    except OSError as e:
        raise CliError(f"hide.me konnte nicht gestartet werden: {e}") from e
    return proc.returncode, proc.stdout, proc.stderr


def categories(host):
    """Liefert eine Liste von (Name, Beschreibung) der SmartGuard-Kategorien.

    Zuerst direkt per HTTPS mit regulärer Zertifikatsprüfung: ``hide.me categories``
    0.9.14 pinnt eine veraltete DigiCert-Zwischenstelle und scheitert deshalb mit
    "bad public key PIN". Das Programm dient nur noch als Rückfall.
    """
    try:
        return _categories_https(host)
    except (OSError, ValueError) as e:
        direct_error = e
    try:
        return _categories_cli(host)
    except CliError as e:
        raise CliError(f"{e} (direkter Abruf: {direct_error})") from e


def _categories_https(host):
    from . import config as C
    url = f"https://{C.fqdn(host)}/categorization/categories.json"
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=20, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    cats = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            low = {k.lower(): v for k, v in item.items()}
            if low.get("name"):
                cats.append((str(low["name"]), str(low.get("description") or "")))
    if not cats:
        raise ValueError("leere Kategorienliste")
    return cats


def _categories_cli(host):
    _rc, out, err = _run(["categories", host])
    cats = []
    for line in (err + "\n" + out).splitlines():
        if " | " not in line:
            continue
        name, _sep, desc = line.partition(" | ")
        name, desc = name.strip(), desc.strip()
        if not name or name in ("CATEGORY", "--------"):
            continue
        cats.append((name, desc))
    if not cats:
        last = [l for l in err.splitlines() if l.strip()]
        raise CliError(last[-1] if last else "Die Kategorienliste konnte nicht abgerufen werden")
    return cats


_RESOLVED_RE = re.compile(r"Main: Resolved (\S+) to \[(.*)\]")
_FAILED_RE = re.compile(r"Main: Resolve (\S+) failed: (.*)")


def _parse_resolve(err, out):
    text = err + "\n" + out
    m = _RESOLVED_RE.search(text)
    if m:
        return [ip for ip in m.group(2).split() if ip]
    m = _FAILED_RE.search(text)
    if m:
        raise CliError(m.group(2).strip())
    lines = [l for l in text.splitlines() if l.strip()]
    raise CliError(lines[-1] if lines else "Keine Antwort")


def resolve_doh(name):
    _rc, out, err = _run(["resolve", name], timeout=60)
    return _parse_resolve(err, out)


def lookup_plain(name, dns_servers=None):
    args = []
    if dns_servers:
        args += ["--dns", ",".join(dns_servers)]
    _rc, out, err = _run(args + ["lookup", name], timeout=60)
    return _parse_resolve(err, out)


def _with_temp_config(content, args, suffix):
    fd, path = tempfile.mkstemp(prefix="hideme-", suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        rc, out, err = _run(["-c", path] + args, timeout=30)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if rc != 0 or not out.strip():
        lines = [l for l in err.splitlines() if l.strip()]
        raise CliError(lines[-1] if lines else "hide.me lieferte keine Ausgabe")
    return out


def config_to_yaml(cfg):
    """Daemon-Konfiguration (JSON) → YAML im Format von ``hide.me conf``."""
    return _with_temp_config(json.dumps(cfg), ["conf"], ".json")


def config_file_to_json(path):
    """Liest eine YAML- oder JSON-Konfigurationsdatei wie ``hide.me -c`` und liefert JSON."""
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    if content.lstrip().startswith("{"):
        return json.loads(content)
    out = _with_temp_config(content, ["jsonconf"], ".yaml")
    return json.loads(out)
