# Fedora / openSUSE / RHEL-Derivate – gebaut mit packaging/rpm/build-rpm.sh
#
# Die Skripte verwenden bewusst keine distributionsspezifischen Makros (%systemd_post gibt es nur
# bei Fedora, openSUSE nutzt %service_add_post), damit dasselbe Paket überall funktioniert.
%global debug_package %{nil}
%global __brp_strip %{nil}
%global __brp_strip_comment_note %{nil}
%{!?app_version:%global app_version 1.0.1}
%{!?_unitdir:%global _unitdir /usr/lib/systemd/system}
# Dokumentation wie bei Fedora/openSUSE unter /usr/share/doc/hideme-desktop (ohne Versionsnummer)
%global _docdir_fmt %{name}

Name:           hideme-desktop
Version:        %{app_version}
Release:        1%{?dist}
Summary:        Inoffizielle GTK-Oberfläche für den hide.me CLI VPN-Client
License:        GPL-2.0-only
URL:            https://github.com/bluhtsturm/hideme-desktop
Source0:        %{name}-%{version}.tar.gz
# Mit --define "_with_prebuilt 1" wird das bereits gebaute build/hide.me verwendet
%if 0%{!?_with_prebuilt:1}
BuildRequires:  golang
%endif
Requires:       python3
Requires:       python3-gobject
# Paketnamen von Fedora bzw. openSUSE
Requires:       (gtk4 or typelib-1_0-Gtk-4_0)
Requires:       (libadwaita or typelib-1_0-Adw-1)
Requires:       polkit
Requires:       systemd

%description
GTK4/libadwaita-Oberfläche für den hide.me WireGuard-Client mit allen Funktionen
der Kommandozeile: Serverauswahl, Kill-Switch, Split-Tunneling, SmartGuard,
Port-Forwarding, DNS-over-HTTPS und Tray-Symbol. Kein offizielles Produkt der
eVenture Ltd.

%prep
%setup -q

%build
%if 0%{!?_with_prebuilt:1}
./build.sh
%endif
test -x build/hide.me

%install
./install.sh --package --destdir %{buildroot} --bindir %{_bindir} --datadir %{_datadir} --unitdir %{_unitdir}

%pre
getent group hideme >/dev/null || groupadd -r hideme || :

%post
systemctl daemon-reload >/dev/null 2>&1 || :
if [ -d /run/systemd/system ]; then
    if [ "$1" -eq 1 ]; then
        systemctl enable --now hideme-daemon.service >/dev/null 2>&1 || :
    else
        # Aktualisierung: neue Programmversion laden
        systemctl try-restart hideme-daemon.service >/dev/null 2>&1 || :
    fi
fi
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    usermod -aG hideme "$SUDO_USER" >/dev/null 2>&1 || :
fi
gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor >/dev/null 2>&1 || :

%preun
if [ "$1" -eq 0 ] && [ -d /run/systemd/system ]; then
    systemctl disable --now hideme-autoconnect.service hideme-daemon.service >/dev/null 2>&1 || :
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || :
if [ "$1" -eq 0 ]; then
    gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc README.md CHANGELOG.md
/opt/hideme-desktop
%{_bindir}/hideme-desktop
%{_bindir}/hidemectl
%{_unitdir}/hideme-daemon.service
%{_unitdir}/hideme-autoconnect.service
%{_datadir}/applications/io.github.HideMeDesktop.desktop
%{_datadir}/metainfo/io.github.HideMeDesktop.metainfo.xml
%{_datadir}/icons/hicolor/*/*/io.github.HideMeDesktop*.svg
%{_datadir}/icons/hicolor/symbolic/apps/hideme-*-symbolic.svg
%{_datadir}/polkit-1/actions/io.github.HideMeDesktop.policy
/usr/lib/sysusers.d/hideme-desktop.conf

%changelog
* Tue Nov 03 2026 hide.me Desktop (inoffiziell) <root@localhost> - 1.0.1-1
- Fehlerbehebungen nach vollständiger Durchsicht, siehe CHANGELOG.md
* Sun Nov 01 2026 hide.me Desktop (inoffiziell) <root@localhost> - 1.0.0-1
- Erste Version
