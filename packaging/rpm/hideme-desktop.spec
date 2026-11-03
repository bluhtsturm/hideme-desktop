# Fedora / openSUSE / RHEL-Derivate:  packaging/rpm/build-rpm.sh
%global debug_package %{nil}
%global __brp_strip %{nil}

Name:           hideme-desktop
Version:        1.0.1
Release:        1%{?dist}
Summary:        Inoffizielle GTK-Oberfläche für den hide.me CLI VPN-Client
License:        GPL-2.0-only
URL:            https://github.com/eventure/hide.client.linux
Source0:        %{name}-%{version}.tar.gz
BuildRequires:  golang
BuildRequires:  systemd-rpm-macros
Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       polkit
Requires:       systemd

%description
GTK4/libadwaita-Oberfläche für den hide.me WireGuard-Client mit allen Funktionen
der Kommandozeile: Serverauswahl, Kill-Switch, Split-Tunneling, SmartGuard,
Port-Forwarding, DNS-over-HTTPS und Tray-Symbol. Kein offizielles Produkt der eVenture Ltd.

%prep
%autosetup

%build
./build.sh

%install
./install.sh --package --destdir %{buildroot} --bindir %{_bindir} --datadir %{_datadir} --unitdir %{_unitdir}

%pre
getent group hideme >/dev/null || groupadd --system hideme

%post
%systemd_post hideme-daemon.service
if [ "$1" -eq 1 ] && [ -d /run/systemd/system ]; then systemctl enable --now hideme-daemon.service || :; fi

%preun
%systemd_preun hideme-daemon.service hideme-autoconnect.service

%postun
%systemd_postun_with_restart hideme-daemon.service

%files
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
