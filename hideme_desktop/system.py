"""Integration ins System: Autostart, systemd-Units, Root-Helfer, Gruppenrechte."""

import grp
import os
import shutil
import subprocess

from . import APP_ID, AUTOCONNECT_UNIT, DAEMON_GROUP, DAEMON_UNIT

_HERE = os.path.dirname(os.path.abspath(__file__))


def _autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", f"{APP_ID}.desktop")


def launcher_command():
    for candidate in (os.path.join(os.path.dirname(_HERE), "bin", "hideme-desktop"),
                      shutil.which("hideme-desktop")):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    return "hideme-desktop"


def autostart_enabled():
    return os.path.exists(_autostart_path())


def set_autostart(enabled):
    path = _autostart_path()
    if not enabled:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=hide.me VPN\n"
            "Comment=hide.me VPN im Hintergrund starten\n"
            f"Exec={launcher_command()} --background\n"
            f"Icon={APP_ID}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-GNOME-Autostart-Delay=3\n"
            "X-KDE-autostart-after=panel\n"
            "X-MATE-Autostart-Delay=3\n"
        )


def _systemctl(*args, timeout=120):
    if not shutil.which("systemctl"):
        return 127, "", "systemctl nicht gefunden"
    try:
        proc = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def unit_state(unit=DAEMON_UNIT):
    """Liefert (is_active, is_enabled, unit_exists)."""
    rc_a, out_a, _ = _systemctl("is-active", unit, timeout=10)
    rc_e, out_e, _ = _systemctl("is-enabled", unit, timeout=10)
    exists = out_e not in ("", "not-found") and "No such file" not in out_e
    return out_a == "active", out_e == "enabled", exists


def boot_autoconnect_enabled():
    _rc, out, _ = _systemctl("is-enabled", AUTOCONNECT_UNIT, timeout=10)
    return out == "enabled"


def set_boot_autoconnect(enabled):
    """(De)aktiviert die Verbindung beim Systemstart. systemd fragt per polkit nach Rechten."""
    rc, _out, err = _systemctl("enable" if enabled else "disable", AUTOCONNECT_UNIT)
    if rc != 0:
        raise RuntimeError(err or "systemctl ist fehlgeschlagen")


def restart_daemon():
    rc, _out, err = _systemctl("restart", DAEMON_UNIT)
    if rc != 0:
        raise RuntimeError(err or "systemctl restart ist fehlgeschlagen")


def start_daemon():
    rc, _out, err = _systemctl("enable", "--now", DAEMON_UNIT)
    if rc != 0:
        raise RuntimeError(err or "systemctl ist fehlgeschlagen")


def helper_path():
    for candidate in (os.path.join(os.path.dirname(_HERE), "libexec", "hideme-helper"),
                      "/opt/hideme-desktop/libexec/hideme-helper",
                      "/usr/lib/hideme-desktop/hideme-helper"):
        if os.path.isfile(candidate):
            return candidate
    return None


def run_helper(*args, timeout=300):
    """Führt den Root-Helfer über pkexec aus (Passwortabfrage über polkit)."""
    helper = helper_path()
    if not helper:
        raise RuntimeError("Der Root-Helfer (hideme-helper) wurde nicht gefunden.")
    if not shutil.which("pkexec"):
        raise RuntimeError("pkexec (polkit) ist nicht installiert.")
    try:
        proc = subprocess.run(["pkexec", helper, *args], capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Zeitüberschreitung") from e
    if proc.returncode in (126, 127):
        raise RuntimeError("Authentifizierung abgebrochen oder abgelehnt.")
    if proc.returncode != 0:
        lines = [l for l in (proc.stderr + "\n" + proc.stdout).splitlines() if l.strip()]
        raise RuntimeError(lines[-1] if lines else f"Fehlercode {proc.returncode}")
    return (proc.stdout + proc.stderr).strip()


def group_status():
    """Liefert (gruppe_existiert, benutzer_ist_mitglied, in_aktueller_sitzung_aktiv)."""
    try:
        group = grp.getgrnam(DAEMON_GROUP)
    except KeyError:
        return False, False, False
    user = os.environ.get("USER") or ""
    try:
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
        primary = pwd.getpwuid(os.getuid()).pw_gid
    except (KeyError, ImportError):
        primary = -1
    member = user in group.gr_mem or primary == group.gr_gid
    active = group.gr_gid in os.getgroups() or os.getgid() == group.gr_gid
    return True, member, active
