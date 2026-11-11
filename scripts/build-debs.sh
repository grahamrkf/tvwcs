#!/usr/bin/env bash
# Build TVWCS's Debian package from the repository, into resources/:
#   tvwcs_<version>_all.deb   the program, its sway session and the Settings app
# It is a plain dpkg-deb build: architecture independent, no compiling. The release workflow attaches it to the
# GitHub release, where install.sh and TVWCS's updater download it.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
OUT=$ROOT/resources; mkdir -p "$OUT"
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT

control() {   # control <package> <staged tree>: DEBIAN/control with the version and size filled in
    mkdir -p "$2/DEBIAN"
    SIZE=$(du -sk --exclude=DEBIAN "$2" | cut -f1)
    sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" "$ROOT/packaging/$1/control" > "$2/DEBIAN/control"
}
build() {   # build <staged tree>: owned by root, standard permissions
    find "$1" -type d -exec chmod 755 {} +
    dpkg-deb --root-owner-group -Zxz --build "$1" "$OUT/$(basename "$1")_${VERSION}_all.deb" >/dev/null
    echo "Built resources/$(basename "$1")_${VERSION}_all.deb"
}

# ---------------------------------------------------------------------- tvwcs
P=$STAGE/tvwcs
install -d "$P/usr/lib/tvwcs/tvwcs" "$P/usr/bin" "$P/usr/share/tvwcs" "$P/usr/share/wayland-sessions" "$P/usr/share/applications" \
    "$P/usr/share/icons/hicolor/scalable/apps" "$P/usr/share/doc/tvwcs" "$P/usr/share/slick-greeter/badges"
install -m 644 "$ROOT"/package/tvwcs/*.py "$P/usr/lib/tvwcs/tvwcs/"
install -d "$P/usr/lib/tvwcs/tvwcs/retro/icons/hicolor/scalable/actions"   # the Retro theme's fonts, icons and TV static (scripts/make-retro-assets.py)
install -m 644 "$ROOT"/package/tvwcs/retro/*.ttf "$ROOT"/package/tvwcs/retro/*.png "$P/usr/lib/tvwcs/tvwcs/retro/"
install -m 644 "$ROOT"/package/tvwcs/retro/icons/hicolor/scalable/actions/*.svg "$P/usr/lib/tvwcs/tvwcs/retro/icons/hicolor/scalable/actions/"
install -m 644 "$ROOT/VERSION" "$P/usr/lib/tvwcs/VERSION"
# TVWCS's own updates from its GitHub releases (vendor.py). A vendor building its own package leaves it out with
# TVWCS_NO_UPDATER=1, so its repository delivers TVWCS (or ships a vendor.json, which wins anyway)
[ -n "${TVWCS_NO_UPDATER:-}" ] || install -m 644 "$ROOT/packaging/common/updates.json" "$P/usr/lib/tvwcs/updates.json"
install -m 755 "$ROOT/package/bin/tvwcs" "$P/usr/bin/tvwcs"
install -m 755 "$ROOT/data/tvwcs-session" "$P/usr/bin/tvwcs-session"
install -m 644 "$ROOT/data/tvwcs.conf" "$P/usr/share/tvwcs/tvwcs.conf"
install -D -m 644 "$ROOT/data/70-tvwcs-cec.rules" "$P/usr/lib/udev/rules.d/70-tvwcs-cec.rules"   # the TV remote over HDMI-CEC (cec.py)
install -D -m 644 "$ROOT/data/tvwcs-uinput.conf" "$P/usr/lib/modules-load.d/tvwcs-uinput.conf"
install -m 644 "$ROOT/data/tvwcs-sway.desktop" "$P/usr/share/wayland-sessions/tvwcs-sway.desktop"
# slick-greeter (Linux Mint's login screen) shows badges/<session file name>.svg next to a session, else a blank disc
install -m 644 "$ROOT/data/tvwcs-sway-badge.svg" "$P/usr/share/slick-greeter/badges/tvwcs-sway.svg"
install -m 644 "$ROOT/data/com.tvwcs.ControlPanel.desktop" "$P/usr/share/applications/"
install -m 644 "$ROOT/data/tvwcs.svg" "$ROOT/data/tvwcs-settings.svg" "$P/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$ROOT/README.md" "$ROOT/CHANGELOG.md" "$P/usr/share/doc/tvwcs/"
install -m 644 "$ROOT/LICENSE" "$P/usr/share/doc/tvwcs/copyright"
cat "$ROOT/scripts/retro/FONTS.txt" >> "$P/usr/share/doc/tvwcs/copyright"   # the Retro theme's fonts come from these
control tvwcs "$P"
install -m 755 "$ROOT/packaging/tvwcs/postinst" "$ROOT/packaging/tvwcs/prerm" "$P/DEBIAN/"
build "$P"

