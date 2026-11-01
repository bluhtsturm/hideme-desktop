"""Einstellungen der Desktop-App selbst (nicht des Daemons).

Gespeichert als JSON unter ``$XDG_CONFIG_HOME/hideme-desktop/settings.json``.
"""

import json
import os

from . import DEFAULT_SOCKET

DEFAULTS = {
    "control_address": DEFAULT_SOCKET,
    "control_tls_ca": "",
    "control_tls_verify": True,
    "last_server": "",
    "favorites": [],
    "recent": [],
    "autoconnect": False,          # beim Start der App verbinden
    "autoconnect_server": "last",  # "last" oder ein Hostname
    "start_hidden": True,          # bei Autostart nur im Hintergrund/Tray starten
    "run_in_background": True,     # beim Schließen des Fensters weiterlaufen
    "show_tray": True,
    "notifications": True,
    "auto_reconnect": True,        # bei Abbruch selbstständig neu verbinden
    "block_after_disconnect": False,  # Kill-Switch nach manuellem Trennen aktiv lassen
    "free_only": False,
    "token_host": "free.hideservers.net",
    "log_autorefresh": False,
}


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "hideme-desktop")


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "hideme-desktop")


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.data = dict(DEFAULTS)
        self._listeners = []
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            print(f"hideme-desktop: Einstellungen konnten nicht gelesen werden: {e}")

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        try:
            self.save()
        except OSError as e:
            print(f"hideme-desktop: Einstellungen konnten nicht gespeichert werden: {e}")
        for cb in list(self._listeners):
            cb(key, value)

    def connect_changed(self, callback):
        self._listeners.append(callback)

    # Favoriten / zuletzt verwendet ------------------------------------------
    def is_favorite(self, host):
        return host in self["favorites"]

    def toggle_favorite(self, host):
        favs = list(self["favorites"])
        if host in favs:
            favs.remove(host)
        else:
            favs.append(host)
        self["favorites"] = favs
        return host in favs

    def add_recent(self, host):
        recent = [h for h in self["recent"] if h != host]
        recent.insert(0, host)
        self["recent"] = recent[:8]
