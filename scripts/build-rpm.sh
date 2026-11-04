#!/usr/bin/env bash
# Build TVWCS's Fedora package from the repository, into resources/fedora/:
#   tvwcs-<version>-src.tar.gz    the source (the same tarball as the Arch package's)
#   tvwcs.spec                    from packaging/fedora/tvwcs.spec.in, with the version filled in
#   tvwcs-<version>-1.noarch.rpm  the package, built with rpmbuild (on Fedora: it needs rpm-build and python3)
# The release workflow builds it in a Fedora container and attaches the .rpm to the GitHub release, where install.sh
# and TVWCS's updater download it. Without rpmbuild, only the tarball and the spec are made.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
OUT=$ROOT/resources/fedora
NAME=tvwcs-$VERSION
rm -rf "$OUT"; mkdir -p "$OUT"
( cd "$ROOT" && git ls-files -z --cached --others --exclude-standard -- . ':!assets' ':!resources' |
  tar --null -T - --transform "s,^,$NAME/," --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf - ) |
  gzip -n9 > "$OUT/$NAME-src.tar.gz"
DATE=$(LC_ALL=C date -u -d "@$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)" '+%a %b %d %Y')
sed -e "s/@VERSION@/$VERSION/g" -e "s/@DATE@/$DATE/" "$ROOT/packaging/fedora/tvwcs.spec.in" > "$OUT/tvwcs.spec"
echo "Built resources/fedora/tvwcs.spec and $NAME-src.tar.gz"
if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "rpmbuild is not installed: the .rpm is built on Fedora (sudo dnf install rpm-build python3)." >&2; exit 1
fi
TOP=$(mktemp -d); trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP/SOURCES"; cp "$OUT/$NAME-src.tar.gz" "$TOP/SOURCES/"
rpmbuild --quiet --define "_topdir $TOP" -bb "$OUT/tvwcs.spec"
cp "$TOP"/RPMS/noarch/tvwcs-"$VERSION"-1.noarch.rpm "$OUT/"
echo "Built resources/fedora/tvwcs-$VERSION-1.noarch.rpm"
