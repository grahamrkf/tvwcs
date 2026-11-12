"""Ubuntu's own extras that a TV computer does without: Snap (snapd), cloud-init and the Ubuntu Pro client. No GTK
dependency.

Settings > Software updates and install.sh offer to remove (purge) each of them, only on Ubuntu and its family and only while it is
installed. Nothing is pinned: a package that needs snapd (Ubuntu's firefox and chromium-browser packages are only
there to install the Snap) brings it back.

    python3 -m tvwcs.control_ubuntu purge <snap|cloud-init|pro>...   (as root: what install.sh runs)"""

from __future__ import annotations
import re, subprocess, sys
from dataclasses import dataclass

from tvwcs.control_cmd import have, run


@dataclass(frozen=True)
class Extra:
    key: str
    name: str
    packages: tuple  # every package that belongs to it; only the installed ones are purged
    what: str


EXTRAS = (
    Extra(
        "snap",
        "Snap (snapd)",
        ("snapd",),
        "Ubuntu's second app store and the service that runs its apps. Removing it removes every Snap app with it.",
    ),
    Extra(
        "cloud-init",
        "cloud-init",
        ("cloud-init", "cloud-init-base", "cloud-initramfs-copymods", "cloud-initramfs-dyn-netconf"),
        "Sets up cloud servers and virtual machines when they first start. A computer at home does not need it; "
        "it only adds to the start-up time. The network settings it wrote in /etc/netplan are kept.",
    ),
    Extra(
        "pro",
        "Ubuntu Pro client",
        ("ubuntu-pro-client", "ubuntu-pro-client-l10n", "ubuntu-advantage-tools", "ubuntu-pro-auto-attach"),
        "Ubuntu's subscription tool (the pro command) and its adverts for Ubuntu Pro in apt and at log-in. Ubuntu's "
        "security updates keep coming without it; only Ubuntu Pro's extra ones (ESM) need it. "
        "Ubuntu's update notices (update-notifier-common, update-manager-core) go with it; do-release-upgrade stays.",
    ),
)
BY_KEY = {e.key: e for e in EXTRAS}


def is_ubuntu(os_release=None):
    """Ubuntu, or a system built on it (its ID or ID_LIKE says ubuntu)."""
    if os_release is None:
        os_release = ""
        for path in ("/etc/os-release", "/usr/lib/os-release"):
            try:
                with open(path, encoding="utf-8") as f:
                    os_release = f.read()
                    break
            except OSError:
                continue
    for line in os_release.splitlines():
        key, _eq, value = line.partition("=")
        if key in ("ID", "ID_LIKE") and "ubuntu" in value.strip().strip("\"'").split():
            return True
    return False


def installed_packages(packages, run=run):
    """The ones of `packages` dpkg has installed."""
    if not have("dpkg-query"):
        return []
    r = run(["dpkg-query", "-W", "-f=${Package}\t${db:Status-Abbrev}\n", *packages], timeout=20)
    found = {n for n, _t, s in (l.partition("\t") for l in r.out.splitlines()) if s.startswith("ii")}
    return [p for p in packages if p in found]


def installed_extras(run=run):
    """[(Extra, its installed packages)] for the extras still installed; [] off Ubuntu."""
    if not is_ubuntu():
        return []
    out = []
    for e in EXTRAS:
        pkgs = installed_packages(e.packages, run)
        if pkgs:
            out.append((e, pkgs))
    return out


def parse_removals(simulation):
    """The packages `apt-get -s purge` would remove ("Purg name [version]" / "Remv name ...")."""
    return [m.group(2) for m in re.finditer(r"^(Purg|Remv) (\S+)", simulation, re.M)]


def would_remove(packages, run=run):
    """Everything apt would remove along with `packages` (other packages that need them), without changing anything."""
    r = run(["apt-get", "-s", "purge", *packages], timeout=60)
    return [p for p in parse_removals(r.out) if p not in packages]


SNAP_BASES = {"core", "core18", "core20", "core22", "core24", "core26", "snapd", "bare"}


def parse_snap_list(text):
    """The apps in `snap list` (its bases, snapd and theme/support snaps left out)."""
    names = []
    for line in text.splitlines()[1:]:
        f = line.split()
        if (
            not f
            or f[0] in SNAP_BASES
            or f[0].startswith(("gnome-", "gtk-", "kf5-", "kf6-", "mesa-"))
            or "base" in f[-1:]
        ):
            continue
        names.append(f[0])
    return names


def snap_apps(run=run):
    if not have("snap"):
        return []
    r = run(["snap", "list"], timeout=20)
    return parse_snap_list(r.out) if r.ok else []


# Run as root with the packages to purge. A metapackage that needs one of them (ubuntu-server, ubuntu-desktop...)
# goes too; what it brought in is marked as installed by hand first, so a later `apt autoremove` keeps it.
PURGE_SCRIPT = r"""set -u
pkgs=""
for p in "$@"; do dpkg-query -W -f='${db:Status-Abbrev}' "$p" 2>/dev/null | grep -q '^ii' && pkgs="$pkgs $p"; done
[ -n "$pkgs" ] || { echo "Nothing left to remove."; exit 0; }
others=$(LC_ALL=C apt-get -s purge $pkgs | sed -nE 's/^(Purg|Remv) ([^ ]+).*/\2/p')
for m in $others; do
  case " $pkgs " in *" $m "*) continue ;; esac
  deps=$(LC_ALL=C apt-cache depends --installed --no-pre-depends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances "$m" 2>/dev/null |
         sed -nE 's/^ *[|]?(Depends|Recommends): ([^< ]+).*/\2/p' | sed 's/:any$//' | sort -u)
  [ -z "$deps" ] || apt-mark manual $deps >/dev/null 2>&1 || true
done
echo "Removing:$pkgs"
DEBIAN_FRONTEND=noninteractive apt-get purge -y $pkgs
"""


def purge_argv(keys):
    """The root command that purges the extras named by `keys` (snap, cloud-init, pro)."""
    packages = [p for k in keys for p in BY_KEY[k].packages]
    return ["sh", "-c", PURGE_SCRIPT, "sh", *packages]


def main(argv):
    if len(argv) >= 2 and argv[0] == "purge" and all(k in BY_KEY for k in argv[1:]):
        return subprocess.call(purge_argv(argv[1:]))
    print("usage: python3 -m tvwcs.control_ubuntu purge <snap|cloud-init|pro>...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
