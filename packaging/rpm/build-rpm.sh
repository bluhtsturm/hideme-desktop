#!/bin/bash
# Baut ein RPM-Paket nach dist/ (benötigt rpmbuild und golang).
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
cd "$SRC"
VERSION="$(python3 -I -c 'import sys; sys.path.insert(0, "."); from hideme_desktop import VERSION; print(VERSION)')"
TOP="$(mktemp -d)"
trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}
tar --exclude=./dist --exclude=./build --exclude='__pycache__' --transform "s,^\.,hideme-desktop-$VERSION," \
    -czf "$TOP/SOURCES/hideme-desktop-$VERSION.tar.gz" .
rpmbuild --define "_topdir $TOP" -ba packaging/rpm/hideme-desktop.spec
mkdir -p dist
find "$TOP/RPMS" -name '*.rpm' -exec cp {} dist/ \;
ls dist/*.rpm
