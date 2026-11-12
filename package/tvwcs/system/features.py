"""The software each part of TVWCS needs beyond a basic install. No GTK dependency.

The installer installs what the Quick Menu, the applications list and Settings need. Each entry below needs packages
of its own; a Settings page whose software is missing offers to install it (Sound installs PipeWire, Bluetooth installs
BlueZ), and its Quick Menu icon is not shown until then. There is no on/off switch: what
is installed is used. (Before 4.0 there was a Features page with one.)"""

from __future__ import annotations
import shutil, subprocess
from dataclasses import dataclass

from tvwcs.system import distro


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    what: str  # what it gives, one sentence
    packages: tuple  # Debian packages (distro.PACKAGES has each family's: packages_for)
    probes: tuple  # ("cmd", name) | ("gi", namespace, version): all must pass
    pages: tuple = ()  # the Settings pages it brings


FEATURES = (
    Feature(
        "sound",
        "Sound",
        "Volume, and the speakers, headphones and microphones to use (the Sound page and the Quick Menu's volume).",
        ("pipewire", "pipewire-pulse", "wireplumber", "pulseaudio-utils"),
        (("cmd", "pactl"),),
        ("sound",),
    ),
    Feature(
        "bluetooth",
        "Bluetooth",
        "Pairing and connecting Bluetooth remotes, headphones and game controllers.",
        ("bluez",),
        (("cmd", "bluetoothctl"),),
        ("bluetooth",),
    ),
)
BY_KEY = {f.key: f for f in FEATURES}
PAGE_FEATURE = {p: f.key for f in FEATURES for p in f.pages}


def packages_for(feature, fam=None) -> tuple:
    """Its packages on this computer's family of distributions."""
    return distro.packages(feature.key, fam)


# ---------------------------------------------------------------------- what is installed
def _probe(p, which=shutil.which):
    if p[0] == "cmd":
        return bool(which(p[1]))
    try:
        import gi

        if p[0] == "gi":
            gi.require_version(p[1], p[2])
            __import__("gi.repository." + p[1])
            return True
    except (ImportError, ValueError, AttributeError):
        return False
    return False


def installed(feature, which=shutil.which):
    """Its software is there (what it runs, not the package names: another distribution's packages count too)."""
    return all(_probe(p, which) for p in feature.probes)


def package_states(packages, run=subprocess.run):
    """{package: installed?} from dpkg or pacman; {} without them."""
    return distro.package_states(packages, run=run)


def missing_packages(feature, run=subprocess.run):
    wanted = packages_for(feature)
    states = package_states(wanted, run)
    return [p for p in wanted if not states.get(p, False)] if states else list(wanted)


VALID_PACKAGE = distro.VALID_PACKAGE


def install_argv(packages, feature=None):
    """Install the packages as root; on Arch, also start the services the feature needs (Bluetooth's), which Debian's
    packages start by themselves."""
    return distro.install_argv(packages, enable=distro.services(feature.key) if feature else ())


def remove_argv(packages):
    return distro.remove_argv(packages)
