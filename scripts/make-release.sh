#!/usr/bin/env bash
# Build a TVWCS release from the repository, into resources/:
#   tvwcs_<version>_all.deb   (scripts/build-debs.sh)
#   tvwcs.tar.gz and TVWCS-<version>.zip: install.sh with the package, to install from without downloading them.
# tvwcs.tar.gz's name never changes, so it can be downloaded from
# https://github.com/grahamrkf/tvwcs/releases/latest/download/tvwcs.tar.gz. The zip is what TVWCS 4.x's
# updater looks for: its install.sh tells it that TVWCS 5 is installed from a terminal. (The zip also holds the Python
# package, which 4.x's updater checks for.)
#   scripts/make-release.sh --beta   names the zip TVWCS-<version>-beta.<n>.zip
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
SUFFIX=""
if [ "${1:-}" = "--beta" ]; then
    N=$(git -C "$ROOT" tag -l "v$VERSION-beta*" 2>/dev/null | wc -l | tr -d ' ')
    SUFFIX="-beta.$((N+1))"
fi
NAME="TVWCS-${VERSION}${SUFFIX}"
"$ROOT/scripts/build-debs.sh"
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
rm -f "$ROOT/resources/$NAME.zip" "$ROOT/resources/tvwcs.tar.gz"   # zip -r would otherwise add to an old archive
mkdir -p "$STAGE/tvwcs"
cp -r "$ROOT/package/tvwcs" "$STAGE/tvwcs/tvwcs"
find "$STAGE/tvwcs/tvwcs" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$ROOT/resources/tvwcs_${VERSION}_all.deb" "$STAGE/tvwcs/"
cp "$ROOT/install.sh" "$ROOT/VERSION" "$ROOT/LICENSE" "$ROOT/README.md" "$ROOT/CHANGELOG.md" "$STAGE/tvwcs/"
if command -v zip >/dev/null 2>&1; then
    (cd "$STAGE" && zip -rq "$ROOT/resources/$NAME.zip" tvwcs)
else
    (cd "$STAGE" && python3 -m zipfile -c "$ROOT/resources/$NAME.zip" tvwcs)
fi
tar -czf "$ROOT/resources/tvwcs.tar.gz" -C "$STAGE" tvwcs
echo "Built resources/$NAME.zip and resources/tvwcs.tar.gz"
