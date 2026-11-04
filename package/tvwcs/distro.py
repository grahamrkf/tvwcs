"""Which family of distributions this computer belongs to, and what differs between them. No GTK dependency.

TVWCS supports three families, all with systemd: Debian (Debian, Ubuntu, Linux Mint, Pop!_OS, Raspberry Pi OS), with
apt; Arch (Arch Linux, EndeavourOS, CachyOS, Manjaro), with pacman; and Fedora (Fedora, Nobara, Ultramarine), with dnf.
Red Hat Enterprise Linux and its rebuilds name fedora in ID_LIKE too, but have no sway of their own: they are not
counted as Fedora. Fedora's Atomic editions (Silverblue, Sway Atomic...) are Fedora too; atomic() tells them apart,
since their system files can only change through rpm-ostree. The package names Settings installs, the commands
it installs them with and how it asks which are installed are kept here; everything else reads them from here.

TVWCS_FAMILY (debian, arch or fedora) overrides what /etc/os-release says: the tests set it, so they give the same answers on
any computer."""
from __future__ import annotations
import os, re, shutil, subprocess

DEBIAN="debian"
ARCH="arch"
FEDORA="fedora"
NAMES={DEBIAN:"Debian",ARCH:"Arch",FEDORA:"Fedora"}
# os-release's ID and ID_LIKE values, for each family
_IDS={"debian":DEBIAN,"ubuntu":DEBIAN,"linuxmint":DEBIAN,"pop":DEBIAN,"raspbian":DEBIAN,
      "arch":ARCH,"archarm":ARCH,"endeavouros":ARCH,"cachyos":ARCH,"manjaro":ARCH,"manjaro-arm":ARCH,"garuda":ARCH,
      "fedora":FEDORA,"nobara":FEDORA,"ultramarine":FEDORA}
_NOT_FEDORA={"rhel","centos","almalinux","rocky","ol"}   # ID_LIKE says fedora, but these are not supported
_TOOLS=((DEBIAN,"apt-get"),(ARCH,"pacman"),(FEDORA,"dnf"))

def parse_os_release(text) -> dict:
    out={}
    for line in (text or "").splitlines():
        key,found,value=line.strip().partition("=")
        if found and key and not key.startswith("#"): out[key]=value.strip().strip("\"'")
    return out

def _os_release():
    for p in ("/etc/os-release","/usr/lib/os-release"):
        try:
            with open(p,encoding="utf-8") as f: return parse_os_release(f.read())
        except OSError: continue
    return {}

def family(release=None, which=shutil.which) -> str:
    """debian, arch, fedora, or "" when it is none of them: from os-release's ID, then ID_LIKE, then the package
    manager there."""
    forced=os.environ.get("TVWCS_FAMILY","")
    if forced in NAMES: return forced
    release=_os_release() if release is None else release
    words=[w.lower() for w in [release.get("ID","")]+release.get("ID_LIKE","").split()]
    if _NOT_FEDORA & set(words): return ""
    for word in words:
        if word in _IDS: return _IDS[word]
    return next((fam for fam,tool in _TOOLS if which(tool)),"")

def is_arch(): return family()==ARCH
def is_fedora(): return family()==FEDORA

def atomic(exists=os.path.exists) -> bool:
    """An image-based system (Fedora Atomic: rpm-ostree): /usr cannot be changed by a package manager while it runs."""
    return exists(os.environ.get("TVWCS_OSTREE","/run/ostree-booted"))

# ---------------------------------------------------------------------- package names
# What each part of TVWCS installs, by family. On Arch, bluetoothctl is in bluez-utils and pactl in libpulse; on
# Fedora, PipeWire's PulseAudio server is pipewire-pulseaudio.
PACKAGES={
    "sound":{DEBIAN:("pipewire","pipewire-pulse","wireplumber","pulseaudio-utils"),ARCH:("pipewire","pipewire-pulse","wireplumber","libpulse"),
             FEDORA:("pipewire","pipewire-pulseaudio","wireplumber","pulseaudio-utils")},
    "bluetooth":{DEBIAN:("bluez",),ARCH:("bluez","bluez-utils"),FEDORA:("bluez",)},
    "ssh":{DEBIAN:("openssh-server",),ARCH:("openssh",),FEDORA:("openssh-server",)},
    "greetd":{DEBIAN:("greetd",),ARCH:("greetd",),FEDORA:("greetd",)},
}
# Services a package leaves off where installing never starts anything: Arch's, and Fedora's (its presets may enable a
# service, but it only starts at the next start-up). Debian's packages start their own.
SERVICES={"bluetooth":{ARCH:("bluetooth.service",),FEDORA:("bluetooth.service",)}}

def packages(need, fam=None) -> tuple:
    fam=family() if fam is None else fam
    names=PACKAGES[need]
    return names.get(fam,names[DEBIAN])

def services(need, fam=None) -> tuple:
    fam=family() if fam is None else fam
    return SERVICES.get(need,{}).get(fam,())

VALID_PACKAGE=re.compile(r"[a-z0-9][a-z0-9+._@-]*")
def _check(names):
    if not names or not all(VALID_PACKAGE.fullmatch(p) for p in names): raise ValueError("Unexpected package name.")

def can_install(fam=None) -> bool:
    fam=family() if fam is None else fam
    return bool(shutil.which(dict(_TOOLS).get(fam,"")))

def install_argv(names, fam=None, enable=()) -> list:
    """The root command that installs `names` (and then starts each unit in `enable` now and at every start-up).
    Arch: pacman -S without -y, since refreshing the package lists alone and installing would be a partial upgrade
    (which Arch does not support); with old lists, it says what to download and fails, and Software updates fixes that."""
    _check(names); fam=family() if fam is None else fam
    then=f" && systemctl enable --now {' '.join(enable)}" if enable else ""
    if fam==ARCH: return ["sh","-c",'pacman -S --needed --noconfirm "$@"'+then,"sh",*names]
    if fam==FEDORA: return ["sh","-c",'dnf install -y "$@"'+then,"sh",*names]
    return ["env","DEBIAN_FRONTEND=noninteractive","sh","-c",'apt-get update -q && apt-get install -y "$@"'+then,"sh",*names]

def remove_argv(names, fam=None) -> list:
    """Remove the packages (their settings stay, as with `apt-get remove`; pacman keeps changed config files as .pacsave)."""
    _check(names); fam=family() if fam is None else fam
    if fam==ARCH: return ["pacman","-R","--noconfirm",*names]
    if fam==FEDORA: return ["dnf","remove","-y",*names]
    return ["env","DEBIAN_FRONTEND=noninteractive","apt-get","remove","-y",*names]

def install_script(fam=None) -> str:
    """A shell line that installs the packages named in $packages (for scripts that go on to do more as root)."""
    fam=family() if fam is None else fam
    if fam==ARCH: return "pacman -S --needed --noconfirm $packages"
    if fam==FEDORA: return "dnf install -y $packages"
    return "apt-get update -q; DEBIAN_FRONTEND=noninteractive apt-get install -y $packages"

def package_states(names, fam=None, run=subprocess.run) -> dict:
    """{package: installed?}, or {} without the family's package tool."""
    fam=family() if fam is None else fam
    if fam==ARCH:
        if not shutil.which("pacman"): return {}
        argv=["pacman","-Q",*names]
    elif fam==FEDORA:
        if not shutil.which("rpm"): return {}
        argv=["rpm","-q","--qf","%{NAME}\\n",*names]
    else:
        if not shutil.which("dpkg-query"): return {}
        argv=["dpkg-query","-W","-f=${Package}\t${db:Status-Abbrev}\n",*names]
    try: out=run(argv,capture_output=True,text=True,timeout=20).stdout
    except (OSError,subprocess.SubprocessError): return {}
    return parse_states(out,names,fam)

def parse_states(out, names, fam):
    """dpkg-query's 'name<TAB>ii ' lines, pacman -Q's 'name version' lines (a package that is not installed is only
    named on stderr), or rpm -q's names ('package bluez is not installed' for one that is not)."""
    states={p:False for p in names}
    for line in (out or "").splitlines():
        if fam==FEDORA:
            if line.strip() in states: states[line.strip()]=True
        elif fam==ARCH:
            parts=line.split()
            if len(parts)==2 and parts[0] in states: states[parts[0]]=True
        else:
            name,_tab,status=line.partition("\t")
            if name in states: states[name]=status.startswith("ii")
    return states

# ---------------------------------------------------------------------- greetd
# (its user, its text login, the console it runs on), as each family's greetd package sets them up
GREETD={DEBIAN:("_greetd","/usr/sbin/agreety",7),ARCH:("greeter","/usr/bin/agreety",1),FEDORA:("greetd","/usr/bin/agreety",1)}
def greetd(fam=None):
    fam=family() if fam is None else fam
    return GREETD.get(fam,GREETD[DEBIAN])
