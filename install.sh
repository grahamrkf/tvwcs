#!/bin/sh
# TVWCS's installer. It installs, upgrades or removes TVWCS: its Debian package, on Fedora its .rpm, or on Arch the
# package it builds from the release's PKGBUILD. Run it in a terminal:
#
#     wget -qO- https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash
#
# (it then downloads the release you choose), or from an unpacked release (./install.sh; it then offers to install the
# .deb next to it, or to download another release). It asks every question first and changes nothing (downloads
# nothing either) until you agree to the list of what it will do:
#   - with TVWCS installed: upgrade, install a different version (the prerelease, or one of the two releases before
#     the latest) or remove TVWCS;
#   - logging in automatically into TVWCS's session. Without a login screen, the first text console logs in and starts
#     it (typing tvwcs there starts it too);
#   - adding TVWCS to your usual sway session (one include line in its config), where it runs in desktop mode;
#   - on Ubuntu, removing Snap, cloud-init and the Ubuntu Pro client, each asked.
# apt (or pacman, or dnf) installs the packages TVWCS needs with it. Supported, with systemd: Debian and its family
# (apt), Fedora (dnf; from TVWCS 5.15.0; not its Atomic editions, see docs/INSTALL-FEDORA.md), and Arch and its family
# (pacman; run it as your own user, since makepkg will not build as root; it needs fakeroot, from base-devel, and
# offers to install it).
#
# Options: --remove removes TVWCS. --help shows this text.
# Environment: TVWCS_VERSION=package|latest|<x.y.z> answers which version (default: asked).
# The tests use TVWCS_ETC, TVWCS_RUN, TVWCS_SHARE, TVWCS_LIB, TVWCS_UNITS, TVWCS_GITHUB, TVWCS_API and TVWCS_PACKAGES (the packages
# to treat as installed) to stand in for the system.
set -eu

REPO=grahamrkf/tvwcs
GITHUB=${TVWCS_GITHUB:-https://github.com}
API=${TVWCS_API:-https://api.github.com}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
ETC=${TVWCS_ETC:-/etc}
SHARE=${TVWCS_SHARE:-/usr/share}
LIB=${TVWCS_LIB:-/usr/lib/tvwcs}
TVCONF=$CONFIG_HOME/tvwcs
FIRST_ARCH=5.11.0                      # the first release with a PKGBUILD
FIRST_FEDORA=5.15.0                    # the first release with an .rpm
INCLUDE="include /usr/share/tvwcs/tvwcs.conf"

# ====================================================================== talking to the person installing
# Questions are read from the terminal. Run as `wget ... | bash`, the script itself comes in on standard input, so
# they are read from /dev/tty instead.
TTY=""
find_tty() {
    if [ -t 0 ]; then TTY=/dev/stdin; return; fi
    if [ -p /dev/stdin ] && [ -r /dev/tty ] && ( : </dev/tty ) 2>/dev/null; then TTY=/dev/tty; fi
}
say() { printf '%s\n' "$*"; }
heading() { printf '\n== %s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
read_answer() {   # read_answer -> ANSWER
    ANSWER=""
    IFS= read -r ANSWER < "$TTY" || { ANSWER=""; return 1; }
    return 0
}
ask_yes() {   # ask_yes "question" -> yes (Enter) or no
    printf '%s [Y/n] ' "$1"; read_answer || return 1
    case "$ANSWER" in [Nn]*) return 1 ;; *) return 0 ;; esac
}
ask_no() {   # ask_no "question" -> no (Enter) or yes
    printf '%s [y/N] ' "$1"; read_answer || return 1
    case "$ANSWER" in [Yy]*) return 0 ;; *) return 1 ;; esac
}
# choose <default number> <choice 1> <choice 2> ... -> CHOICE (the number chosen). Asked again until it is one of them.
choose() {
    DEFAULT=$1; shift; N=0
    for C in "$@"; do N=$((N+1)); printf '  %s) %s\n' "$N" "$C"; done
    while :; do
        printf 'Choose 1-%s [%s]: ' "$N" "$DEFAULT"; read_answer || { CHOICE=$DEFAULT; return 0; }
        case "$ANSWER" in "") CHOICE=$DEFAULT; return 0 ;; *[!0-9]*) ;; *) [ "$ANSWER" -ge 1 ] && [ "$ANSWER" -le "$N" ] && { CHOICE=$ANSWER; return 0; } ;; esac
        say "Type a number from 1 to $N."
    done
}
fail() { warn ""; warn "The installation failed: $*"; exit 1; }

# ====================================================================== this computer
distro() {   # debian (Debian and its family), arch (Arch and its family), fedora or unknown (Red Hat Enterprise Linux and its rebuilds too)
    ( if [ -r "$ETC/os-release" ]; then . "$ETC/os-release"; elif [ "$ETC" = /etc ] && [ -r /usr/lib/os-release ]; then . /usr/lib/os-release; fi
      for D in ${ID:-} ${ID_LIKE:-}; do case "$D" in rhel|centos|almalinux|rocky|ol) echo unknown; exit ;; esac; done
      for D in ${ID:-} ${ID_LIKE:-}; do case "$D" in
          debian|ubuntu|linuxmint|pop|raspbian) echo debian; exit ;;
          fedora|nobara|ultramarine) echo fedora; exit ;;
          arch|archarm|endeavouros|cachyos|manjaro|manjaro-arm|garuda) echo arch; exit ;; esac; done; echo unknown )
}
os_is() {   # os_is <id>: this system is <id> or built on it (os-release's ID or ID_LIKE)
    ( if [ -r "$ETC/os-release" ]; then . "$ETC/os-release"; elif [ "$ETC" = /etc ] && [ -r /usr/lib/os-release ]; then . /usr/lib/os-release; fi
      for D in ${ID:-} ${ID_LIKE:-}; do [ "$D" = "$1" ] && exit 0; done; exit 1 )
}
have() { command -v "$1" >/dev/null 2>&1; }
# Run as root, asking for the password on the terminal (sudo reads it from the terminal itself, never from the script's
# input, which may be the script itself).
as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif have sudo; then sudo "$@" </dev/null
    elif have doas; then doas "$@" </dev/null
    else warn "Neither sudo nor doas is installed, so the system cannot be changed."; return 1; fi
}
pkg_installed() {   # pkg_installed <package>
    if [ -n "${TVWCS_PACKAGES+set}" ]; then case " $TVWCS_PACKAGES " in *" $1 "*) return 0 ;; *) return 1 ;; esac; fi
    if [ "$OS" = arch ]; then pacman -Q "$1" >/dev/null 2>&1; return; fi
    if [ "$OS" = fedora ]; then rpm -q "$1" >/dev/null 2>&1; return; fi
    dpkg-query -W -f='${db:Status-Abbrev}' "$1" 2>/dev/null | grep -q '^ii'
}
pkg_known() {   # pkg_known <package>: installed, or removed with its settings left ("rc"), so that a purge does something
    pkg_installed "$1" && return 0
    [ -z "${TVWCS_PACKAGES+set}" ] && [ "$OS" = debian ] || return 1
    dpkg-query -W -f='${db:Status-Abbrev}' "$1" 2>/dev/null | grep -q '^rc'
}
installed_version() { [ ! -f "$LIB/VERSION" ] || cat "$LIB/VERSION"; }

# ---- login screens
DISPLAY_MANAGERS="gdm3 gdm sddm lightdm lxdm xdm slim ly greetd emptty nodm entrance lemurs"
login_screen() {   # the login screen that runs at start-up (lightdm, gdm3, greetd...), or "" for none
    N=""
    if [ -L "$ETC/systemd/system/display-manager.service" ]; then N=$(readlink "$ETC/systemd/system/display-manager.service"); N=${N##*/}; N=${N%.service}
    # under systemd the link is the whole answer: disabling a login screen leaves default-display-manager behind
    elif [ "$ETC" = /etc ] && [ -d /run/systemd/system ]; then :
    elif [ -s "$ETC/X11/default-display-manager" ]; then N=$(sed -n 1p "$ETC/X11/default-display-manager"); N=${N##*/}; fi
    echo "$N"
}
login_screen_name() {
    case "$1" in
        gdm|gdm3) echo "GNOME's login screen (GDM)" ;; sddm) echo SDDM ;; lightdm) echo LightDM ;; greetd) echo greetd ;;
        "") echo "no login screen" ;; *) echo "$1" ;;
    esac
}
autologin_user() {   # who greetd logs in automatically now
    sed -n '/^\[initial_session\]/,/^\[/p' "$ETC/greetd/config.toml" 2>/dev/null | sed -n 's/^user *= *"\(.*\)"$/\1/p'
}

# ---- the usual sway config (desktop mode)
sway_config() { for C in "$CONFIG_HOME/sway/config" "$HOME/.sway/config"; do [ -f "$C" ] && { echo "$C"; return; }; done; echo ""; }
has_include() { grep -q '^[[:space:]]*include[[:space:]].*/usr/share/tvwcs/tvwcs\.conf' "$1" 2>/dev/null; }
backup() { [ -f "$1.tvwcs-backup" ] || cp "$1" "$1.tvwcs-backup"; }

# ====================================================================== releases
fetch() {   # fetch <url> <file>
    if have wget; then wget -qO "$2" "$1"
    elif have curl; then curl -fsSL -o "$2" "$1"
    else warn "Neither wget nor curl is installed, so nothing can be downloaded."; return 1; fi
}
# The release list, one line per release: "<version> <latest|prerelease|release>", newest first. GitHub's answer is
# read with grep and awk: each release's tag_name comes before its draft and prerelease fields; quotes inside text are
# escaped, so a release's notes cannot be mistaken for them. Releases before 5.0 have no .deb and are left out.
RELEASES=""; LATEST=""; OS=""
read_releases() {
    [ -z "$RELEASES" ] || return 0
    T=$WORK/releases.json; L=$WORK/latest.json
    fetch "$API/repos/$REPO/releases?per_page=30" "$T" 2>/dev/null || return 1
    fetch "$API/repos/$REPO/releases/latest" "$L" 2>/dev/null || :
    LATEST=$(grep -o '"tag_name": *"[^"]*"' "$L" 2>/dev/null | sed -n '1s/.*"v\{0,1\}\([^"]*\)"$/\1/p')
    FIRST=""; [ "$OS" != arch ] || FIRST=$FIRST_ARCH   # releases before it have no PKGBUILD
    [ "$OS" != fedora ] || FIRST=$FIRST_FEDORA          # or no .rpm
    RELEASES=$(grep -o '"tag_name": *"[^"]*"\|"draft": *[a-z]*\|"prerelease": *[a-z]*' "$T" | awk -v latest="$LATEST" -v first="$FIRST" '
        /"tag_name"/ { if (tag != "" && draft != "true") out(); tag = $0; sub(/.*: *"v?/, "", tag); sub(/"$/, "", tag); draft = ""; pre = "" }
        /"draft"/ { draft = $0; sub(/.*: */, "", draft) }
        /"prerelease"/ { pre = $0; sub(/.*: */, "", pre) }
        function out() { if (tag ~ /^[0-9]+(\.[0-9]+)*$/ && tag + 0 >= 5 && !(first != "" && older(tag, first))) print tag, (tag == latest ? "latest" : pre == "true" ? "prerelease" : "release") }
        function older(a, b,   x, y, i) { split(a, x, "."); split(b, y, "."); for (i = 1; i <= 3; i++) if (x[i] + 0 != y[i] + 0) return x[i] + 0 < y[i] + 0; return 0 }
        END { if (tag != "" && draft != "true") out() }' | sort -t. -k1,1nr -k2,2nr -k3,3nr)
    case " $(echo "$RELEASES" | cut -d' ' -f1 | tr '\n' ' ') " in *" $LATEST "*) ;; *) LATEST=$(echo "$RELEASES" | awk '$2 == "release" { print $1; exit }') ;; esac
    [ -n "$RELEASES" ]
}
version_lt() {   # version_lt a b: a is older than b
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | sed -n 1p)" = "$1" ]
}
other_versions() {   # the prerelease newer than the latest (when there is one), then the two releases before the latest
    echo "$RELEASES" | awk -v latest="$LATEST" '
        function lt(a, b,   x, y, i, n) { n = split(a, x, "."); split(b, y, "."); for (i = 1; i <= 3; i++) if (x[i] + 0 != y[i] + 0) return x[i] + 0 < y[i] + 0; return 0 }
        latest == "" || $2 == "prerelease" && pre == "" && lt(latest, $1) { pre = $1; print $1, "prerelease" }
        $2 == "release" && lt($1, latest) && n < 2 { n++; print $1, "release" }'
}
download_pkgbuild() {   # download_pkgbuild <version>: the release's PKGBUILD and tvwcs.install into $WORK/arch
    V=$1; D=$WORK/arch; rm -rf "$D"; mkdir -p "$D"
    say "Downloading TVWCS $V's PKGBUILD..."
    for F in PKGBUILD tvwcs.install; do
        fetch "$GITHUB/$REPO/releases/download/v$V/$F" "$D/$F" 2>/dev/null || { warn "Could not download $F for TVWCS $V from GitHub."; return 1; }
    done
}
download_rpm() {   # download_rpm <version>: into $WORK/rpm
    V=$1; D=$WORK/rpm; rm -rf "$D"; mkdir -p "$D"; chmod 755 "$WORK" "$D"
    say "Downloading TVWCS $V..."
    F=tvwcs-$V-1.noarch.rpm
    fetch "$GITHUB/$REPO/releases/download/v$V/$F" "$D/$F" 2>/dev/null || { warn "Could not download TVWCS $V's .rpm from GitHub."; return 1; }
    chmod 644 "$D/$F"
}
download_debs() {   # download_debs <version> <packages...>: into $WORK/debs
    V=$1; shift; D=$WORK/debs; rm -rf "$D"; mkdir -p "$D"; chmod 755 "$WORK" "$D"
    say "Downloading TVWCS $V..."
    for P in "$@"; do
        fetch "$GITHUB/$REPO/releases/download/v$V/${P}_${V}_all.deb" "$D/${P}_${V}_all.deb" 2>/dev/null || { warn "Could not download $P $V from GitHub."; return 1; }
        chmod 644 "$D/${P}_${V}_all.deb"
    done
}

# ====================================================================== where TVWCS comes from
# An unpacked release has its .deb files (or the .rpm) next to this script.
PACKAGED=""; PKG_VERSION=""
find_package() {
    [ "$OS" != arch ] || return 0
    case "$0" in */*) D=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || return 0 ;; *) return 0 ;; esac   # piped to bash: $0 is "bash"
    if [ "$OS" = fedora ]; then
        for F in "$D"/tvwcs-*-1.noarch.rpm; do
            [ -f "$F" ] || continue
            PACKAGED=$D; PKG_VERSION=${F##*/tvwcs-}; PKG_VERSION=${PKG_VERSION%-1.noarch.rpm}; return 0
        done
        return 0
    fi
    for F in "$D"/tvwcs_*_all.deb; do
        [ -f "$F" ] || continue
        PACKAGED=$D; PKG_VERSION=${F##*/tvwcs_}; PKG_VERSION=${PKG_VERSION%_all.deb}; return 0
    done
}

# ====================================================================== the questions
choose_version() {   # -> WANT (a version, or "package" for the .deb files next to this script)
    case "${TVWCS_VERSION:-}" in
        package) [ -n "$PACKAGED" ] || fail "There are no TVWCS packages next to this script."; WANT=package; return ;;
        latest) read_releases || fail "Could not read TVWCS's releases from GitHub."; WANT=$LATEST; [ -n "$WANT" ] || fail "There is no TVWCS 5 release yet."; return ;;
        [0-9]*) WANT=$TVWCS_VERSION; return ;;
    esac
    read_releases || RELEASES=""
    set --; DEF=1
    if [ -n "$PACKAGED" ]; then set -- "$@" "TVWCS $PKG_VERSION (the package next to this script)"; fi
    [ -z "$LATEST" ] || set -- "$@" "TVWCS $LATEST, the latest release"
    OTHERS=$(other_versions | awk -v p="$PKG_VERSION" '$1 != p')   # not twice: the package here is already offered
    for V in $(echo "$OTHERS" | cut -d' ' -f1); do
        case "$(echo "$OTHERS" | awk -v v="$V" '$1 == v { print $2 }')" in prerelease) set -- "$@" "TVWCS $V, a prerelease (not tested on a TV yet)" ;; *) set -- "$@" "TVWCS $V, an older release" ;; esac
    done
    [ $# -gt 0 ] || fail "Could not read TVWCS's releases from GitHub, and there are no packages next to this script."
    if [ $# -gt 1 ]; then heading "Which version?"; choose "$DEF" "$@"; else CHOICE=1; fi
    N=$CHOICE
    if [ -n "$PACKAGED" ]; then [ "$N" = 1 ] && { WANT=package; return; }; N=$((N-1)); fi
    if [ -n "$LATEST" ]; then [ "$N" = 1 ] && { WANT=$LATEST; return; }; N=$((N-1)); fi
    WANT=$(echo "$OTHERS" | sed -n "${N}p" | cut -d' ' -f1)
}

ask_questions() {
    LS=$(login_screen); ME=$(id -un); AUTO=""; DESKTOP=""; FAKEROOT=""
    [ "$OS" != arch ] || have fakeroot || FAKEROOT=1

    heading "Logging in"
    if [ -z "$LS" ]; then
        say "There is no login screen here: log in at the text console and type tvwcs to start TVWCS."
        ask_yes "Log $ME in automatically into TVWCS at startup, on the first text console?" && AUTO=$ME || :
    else
        WHO=""; [ "$LS" != greetd ] || WHO=$(autologin_user)
        case "$LS" in greetd|lightdm|sddm)
            if [ -n "$WHO" ]; then say "$WHO is still logged in automatically into TVWCS."; AUTO=$WHO
            else ask_no "Log $ME in automatically into TVWCS at startup, skipping the login screen?" && AUTO=$ME || :; fi ;;
        *) say "$(login_screen_name "$LS") is the login screen: choose \"TVWCS\" there. (TVWCS cannot set its automatic login.)" ;; esac
    fi

    CFG=$(sway_config)
    if [ -n "$CFG" ] && ! has_include "$CFG"; then
        heading "Your usual sway session"
        say "TVWCS has a \"TVWCS\" session of its own at the login screen, which runs it in TV mode."
        ask_no "Also add TVWCS to your usual sway session ($CFG), where it runs in desktop mode?" && DESKTOP=$CFG || :
    fi
}

# Ubuntu's own extras, offered for removal (purge) one by one: "key|name|packages|what it is". The same lists are in
# tvwcs/settings/ubuntu.py, which removes them (Settings > Software updates offers them too). Nothing is pinned, so a
# package that needs snapd brings it back.
UBUNTU_EXTRAS="snap|Snap (snapd)|snapd|Ubuntu's second app store. Every Snap app goes with it.
cloud-init|cloud-init|cloud-init cloud-init-base cloud-initramfs-copymods cloud-initramfs-dyn-netconf|Sets up cloud servers on their first start; at home it only slows start-up.
pro|Ubuntu Pro client|ubuntu-pro-client ubuntu-pro-client-l10n ubuntu-advantage-tools ubuntu-pro-auto-attach|Ubuntu Pro's subscription tool and its adverts in apt; security updates keep coming without it. update-notifier-common and update-manager-core go with it (do-release-upgrade stays)."
snap_apps() { have snap || return 0; snap list 2>/dev/null | awk 'NR > 1 && $NF != "base" && $NF != "snapd" && $1 !~ /^(core[0-9]*|snapd|bare|gnome-|gtk-|mesa-|kf[56]-)/ { printf "%s ", $1 }' | sed 's/ $//'; }
PURGE=""; PURGE_NAMES=""
choose_ubuntu_extras() {
    PURGE=""; PURGE_NAMES=""
    os_is ubuntu || return 0
    FOUND=$(printf '%s\n' "$UBUNTU_EXTRAS" | while IFS='|' read -r KEY NAME PKGS WHAT; do
        for P in $PKGS; do if pkg_installed "$P"; then printf '%s|%s|%s\n' "$KEY" "$NAME" "$WHAT"; break; fi; done; done)
    [ -n "$FOUND" ] || return 0
    heading "Ubuntu extras"
    say "Ubuntu comes with these, which a TV computer does without. Each can be removed now (or later in Settings > Software updates)."
    OLD_IFS=$IFS; IFS='
'
    for LINE in $FOUND; do   # not read from a here-document: the answers come from the terminal
        IFS=$OLD_IFS; KEY=${LINE%%|*}; NAME=${LINE#*|}; WHAT=${NAME#*|}; NAME=${NAME%%|*}
        say; say "$NAME: $WHAT"
        [ "$KEY" != snap ] || { A=$(snap_apps); [ -z "$A" ] || say "Snap apps installed: $A"; }
        if ask_no "Remove $NAME?"; then PURGE="$PURGE $KEY"; PURGE_NAMES="$PURGE_NAMES, $NAME"; fi
    done
    IFS=$OLD_IFS
    PURGE=${PURGE# }; PURGE_NAMES=${PURGE_NAMES#, }
}
purge_ubuntu_extras() {   # after the install: a failure only warns
    [ -n "$PURGE" ] || return 0
    say "Removing $PURGE_NAMES..."
    # shellcheck disable=SC2086
    as_root env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$LIB" python3 -m "$(tvwcs_module settings.ubuntu control_ubuntu)" purge $PURGE ||
        warn "$PURGE_NAMES could not be removed. Settings > Software updates can try again."
}

summary() {
    heading "TVWCS will now"
    if [ "$OS" = arch ]; then
        [ -z "$FAKEROOT" ] || say "  install fakeroot with pacman, which makepkg needs to build the package"
        say "  download TVWCS $WANT's PKGBUILD, build the package with makepkg (as $ME; it only copies files into place)"
        say "  install it with pacman, with the packages TVWCS needs (asks for your password)"
    elif [ "$OS" = fedora ]; then
        if [ "$WANT" = package ]; then say "  install the TVWCS $PKG_VERSION package from $PACKAGED"; else say "  download and install TVWCS $WANT"; fi
        say "  install the packages TVWCS needs with dnf (asks for your password)"
    else
        if [ "$WANT" = package ]; then say "  install the TVWCS $PKG_VERSION packages from $PACKAGED"; else say "  download and install TVWCS $WANT"; fi
        say "  install the packages TVWCS needs with apt (asks for your password)"
        ! pkg_installed tvwcs-boot-logo || say "  remove the TVWCS logo at startup (TVWCS no longer has one)"
    fi
    [ -z "$AUTO" ] || say "  log $AUTO in automatically into TVWCS at startup$([ -n "$LS" ] || echo ", on the first text console")"
    [ -z "$DESKTOP" ] || say "  add TVWCS to $DESKTOP (backup: $DESKTOP.tvwcs-backup)"
    [ -z "$PURGE" ] || say "  remove $PURGE_NAMES"
}

# ====================================================================== doing it
# tvwcs_module <new> <old>: a module's name in the installed TVWCS. From 5.22.0 the modules are in folders
# (tvwcs.system.loginscreen); an older release chosen to install has them at the top (tvwcs.loginscreen).
tvwcs_module() { if [ -f "$LIB/tvwcs/$(echo "$1" | tr . /).py" ]; then echo "tvwcs.$1"; else echo "tvwcs.$2"; fi; }
loginscreen_root() { as_root env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$LIB" python3 -m "$(tvwcs_module system.loginscreen loginscreen)" "$@"; }

# Without a login screen: the shell profile starts TVWCS's session at a login on the first console (as this user)
console_profile() { env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$LIB" python3 -m "$(tvwcs_module system.loginscreen loginscreen)" profile "$1"; }

install_arch() {
    if [ -n "$FAKEROOT" ]; then as_root pacman -S --needed --noconfirm fakeroot || fail "pacman could not install fakeroot."; fi
    download_pkgbuild "$WANT" || fail "the download did not work."
    say "Building the package..."
    ( cd "$WORK/arch" && makepkg -f --nodeps --noconfirm ) || fail "makepkg could not build the package."
    set -- "$WORK"/arch/tvwcs-"$WANT"-*.pkg.tar.*
    [ -f "$1" ] || fail "makepkg made no package."
    say "Installing it (pacman installs what TVWCS needs; sudo may ask for your password)..."
    as_root pacman -U --needed --noconfirm "$1" ||
        fail "pacman could not install TVWCS. If it could not find a package TVWCS needs, update the system first (sudo pacman -Syu), then run this again."
    V=$WANT
}
install_fedora() {
    if [ "$WANT" = package ]; then D=$WORK/rpm; mkdir -p "$D"; chmod 755 "$WORK" "$D"; V=$PKG_VERSION
        cp "$PACKAGED/tvwcs-$V-1.noarch.rpm" "$D/"; chmod 644 "$D"/*.rpm
    else download_rpm "$WANT" || fail "the download did not work."; V=$WANT; fi
    # dnf only installs an older version, or the same one again, when told to
    VERB=install; CUR=$(installed_version)
    if [ -n "$CUR" ] && pkg_installed tvwcs; then
        if [ "$CUR" = "$V" ]; then VERB=reinstall; elif version_lt "$V" "$CUR"; then VERB=downgrade; fi
    fi
    say "Installing it (dnf installs what TVWCS needs; sudo may ask for your password)..."
    as_root dnf "$VERB" -y "$WORK/rpm/tvwcs-$V-1.noarch.rpm" || fail "dnf could not install TVWCS."
}
install_all() {
    if [ "$OS" = arch ]; then install_arch
    elif [ "$OS" = fedora ]; then install_fedora
    elif [ "$WANT" = package ]; then D=$WORK/debs; mkdir -p "$D"; chmod 755 "$WORK" "$D"
        cp "$PACKAGED/tvwcs_${PKG_VERSION}_all.deb" "$D/"
        chmod 644 "$D"/*.deb; V=$PKG_VERSION
    else download_debs "$WANT" tvwcs || fail "the download did not work."; V=$WANT; fi
    if [ "$OS" = debian ]; then
    set -- "$WORK/debs/tvwcs_${V}_all.deb"
    say "Installing the packages (apt asks for nothing; sudo may ask for your password)..."
    as_root apt-get update -q || warn "apt-get update did not finish; installing with the package lists there are."
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades "$@" || fail "apt-get could not install TVWCS."
    if pkg_known tvwcs-boot-logo; then   # 5.0.x's: the tvwcs package conflicts with it, so apt removed it; purged, nothing of it stays
        as_root env DEBIAN_FRONTEND=noninteractive apt-get purge -y tvwcs-boot-logo || warn "The TVWCS logo at startup could not be removed."; fi
    fi
    if [ -n "$AUTO" ] && [ -z "$LS" ]; then
        if console_profile on && loginscreen_root autologin "$AUTO"; then :; else console_profile off || :; warn "The automatic login could not be set."; fi
    elif [ -n "$AUTO" ]; then loginscreen_root autologin "$AUTO" || warn "The automatic login could not be set."; fi
    if [ -n "$DESKTOP" ]; then backup "$DESKTOP"
        { echo; echo "# TVWCS (desktop mode): its hotkeys, window rules and autostart. Added by TVWCS's install.sh."; echo "$INCLUDE"; } >> "$DESKTOP"; fi
    purge_ubuntu_extras
    heading "TVWCS $V is installed"
    if [ -n "${SWAYSOCK:-}" ] && have swaymsg; then swaymsg reload >/dev/null 2>&1 || :; say "sway has reloaded its config."
    elif [ -z "$LS" ]; then say "Type tvwcs at the text console to start TVWCS$( [ -n "$AUTO" ] && echo ", or restart: it logs in by itself")."
    else say "Choose \"TVWCS\" at the login screen$( [ -n "$AUTO" ] && echo ", or restart: it logs in by itself")."; fi
}

remove_all() {
    heading "Remove TVWCS?"
    say "This removes the tvwcs package$(CFG=$(sway_config); [ -n "$CFG" ] && has_include "$CFG" && echo " and TVWCS's include line in $CFG")."
    say "Your settings in $TVCONF are kept unless you choose to delete them."
    ask_no "Remove TVWCS now?" || { say "Nothing was changed."; exit 0; }
    KEEP=1; ask_no "Also delete your TVWCS settings ($TVCONF)?" && KEEP="" || :
    if [ "$OS" = debian ] && [ "$(login_screen)" = greetd ] && grep -q tvwcs-session "$ETC/greetd/config.toml" 2>/dev/null; then   # (Arch's and Fedora's packages do this themselves)
        say "greetd starts TVWCS's session: that goes from its config, and the rest of it stays."
        # as the package's prerm does: [initial_session] goes, and agreety starts a shell instead of TVWCS
        as_root sh -c 'awk -v greeter="/usr/sbin/agreety --cmd /bin/sh" '"'"'
            function flush() { if (held != "" && held !~ /tvwcs-session/) printf "%s", held; held = "" }
            /^[ \t]*\[/ { flush(); s = $0; gsub(/[ \t]/, "", s); sub(/^\[/, "", s); sub(/\].*/, "", s) }
            s == "initial_session" { held = held $0 "\n"; next }
            s == "default_session" && /^[ \t]*command[ \t]*=/ && /tvwcs-session/ { print "command = \"" greeter "\""; next }
            { print }
            END { flush() }'"'"' "$1" > "$1.tvwcs-new" && cat "$1.tvwcs-new" > "$1" && rm -f "$1.tvwcs-new"' sh "$ETC/greetd/config.toml"
    fi
    for F in "$ETC/lightdm/lightdm.conf.d/50-tvwcs-autologin.conf" "$ETC/sddm.conf.d/50-tvwcs-autologin.conf" "$ETC/systemd/system/getty@tty1.service.d/tvwcs-autologin.conf" "$ETC/tvwcs/server-mode" "$ETC/polkit-1/rules.d/50-tvwcs-server-mode.rules"; do [ ! -f "$F" ] || as_root rm -f "$F"; done
    console_profile off || :
    if [ "$OS" = arch ]; then as_root pacman -R --noconfirm tvwcs || fail "pacman could not remove TVWCS."
    elif [ "$OS" = fedora ]; then as_root dnf remove -y tvwcs || fail "dnf could not remove TVWCS."
    else
        # shellcheck disable=SC2046
        as_root env DEBIAN_FRONTEND=noninteractive apt-get purge -y tvwcs $(pkg_known tvwcs-boot-logo && echo tvwcs-boot-logo) || fail "apt-get could not remove TVWCS."
    fi
    CFG=$(sway_config)
    if [ -n "$CFG" ] && has_include "$CFG"; then backup "$CFG"
        sed -i -e '/^# TVWCS (desktop mode): its hotkeys/d' -e '/^[[:space:]]*include[[:space:]].*\/usr\/share\/tvwcs\/tvwcs\.conf/d' "$CFG"; fi
    [ -n "$KEEP" ] || rm -rf "$TVCONF"
    say "TVWCS is removed."
}

usage() { sed -n '2,/^set -eu/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }

main() {
    case "${1:-}" in
        --help|-h) usage; exit 0 ;;
        --remove|"") ;;
        *) warn "Unknown option $1. See --help."; exit 2 ;;
    esac
    find_tty
    if [ -z "$TTY" ]; then
        warn "Installing TVWCS needs your password. Run its installer in a terminal:"
        warn "    wget -qO- https://github.com/$REPO/releases/latest/download/install.sh | bash"
        exit 1
    fi
    OS=$(distro)
    [ "$OS" != unknown ] || fail "TVWCS supports Debian and its family (apt), Fedora (dnf), and Arch and its family (pacman)."
    if [ "$OS" = fedora ] && [ -e "${TVWCS_RUN:-/run}/ostree-booted" ]; then
        fail "this is one of Fedora's Atomic editions, whose system only changes through rpm-ostree. Download the release's .rpm and layer it: sudo rpm-ostree install ./tvwcs-<version>-1.noarch.rpm, then restart. See https://github.com/$REPO/blob/main/docs/INSTALL-FEDORA.md"
    fi
    if [ "$OS" = arch ] && [ "${1:-}" != --remove ]; then
        [ "$(id -u)" != 0 ] || fail "On Arch, run this as your own user, not as root: makepkg will not build packages as root. It asks for your password when it installs."
        have makepkg || fail "makepkg is not installed (it comes with pacman)."
    fi
    [ -d "${TVWCS_RUN:-/run}/systemd/system" ] || fail "TVWCS needs systemd."
    have python3 || fail "python3 is not installed."
    WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
    if [ "${1:-}" = --remove ]; then remove_all; return; fi
    find_package
    CUR=$(installed_version)
    heading "TVWCS"
    if [ -n "$CUR" ]; then say "TVWCS $CUR is installed."; else say "This installs TVWCS, a launcher and settings for sway made for a TV and a remote."; fi
    choose_version
    ask_questions
    choose_ubuntu_extras
    summary
    echo; ask_yes "Go ahead?" || { say "Nothing was changed."; exit 0; }
    install_all
}

main "$@"
