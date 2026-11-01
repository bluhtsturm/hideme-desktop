"""hide.me Desktop – grafische Oberfläche für den hide.me CLI VPN-Client."""

APP_ID = "io.github.HideMeDesktop"
APP_NAME = "hide.me VPN"
VERSION = "1.0.0"

# Standardadresse der Steuerschnittstelle des Daemons (siehe data/systemd/hideme-daemon.service)
DEFAULT_SOCKET = "/run/hideme/hide.me.sock"
DAEMON_UNIT = "hideme-daemon.service"
AUTOCONNECT_UNIT = "hideme-autoconnect.service"
DAEMON_GROUP = "hideme"
