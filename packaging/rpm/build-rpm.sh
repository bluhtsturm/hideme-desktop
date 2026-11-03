#!/bin/bash
# Baut ein RPM-Paket nach dist/ (Fedora, openSUSE, RHEL-Derivate). Benötigt rpmbuild.
# Liegt bereits ein gebautes build/hide.me vor, wird es verwendet (kein Go nötig);
# sonst baut rpmbuild es aus dem mitgelieferten Quellcode (dann wird golang benötigt).
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
cd "$SRC"
command -v rpmbuild >/dev/null || { echo "rpmbuild fehlt (Fedora: dnf install rpm-build, openSUSE: zypper install rpm-build)" >&2; exit 1; }
VERSION="$(python3 -I -c 'import sys; sys.path.insert(0, "."); from hideme_desktop import VERSION; print(VERSION)')"
TOP="$(mktemp -d)"
trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}

EXCLUDES=(--exclude=./.git --exclude=./dist --exclude='__pycache__')
DEFINES=(--define "_topdir $TOP" --define "app_version $VERSION")
if [ -x build/hide.me ]; then
    echo "Verwende das vorhandene build/hide.me"
    DEFINES+=(--define "_with_prebuilt 1")
else
    EXCLUDES+=(--exclude=./build)
fi
tar "${EXCLUDES[@]}" --transform "s,^\.,hideme-desktop-$VERSION," \
    -czf "$TOP/SOURCES/hideme-desktop-$VERSION.tar.gz" .
rpmbuild "${DEFINES[@]}" -bb packaging/rpm/hideme-desktop.spec
mkdir -p dist
find "$TOP/RPMS" -name '*.rpm' -exec cp {} dist/ \;
ls dist/*.rpm
