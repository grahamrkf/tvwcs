"""SSH for Settings: whether the SSH server runs, whether it takes passwords or only keys, and how to reach
this computer from another one (its local name, addresses and user). No GTK dependency.

Changing anything needs root, so this module only builds the commands; the panel runs them through sudo or doas.
Password sign-in is switched with one drop-in file, /etc/ssh/sshd_config.d/00-tvwcs.conf: sshd keeps the first value
it reads for a setting, and the drop-ins are read in name order where sshd_config includes them (at its top on
Debian, Ubuntu and Arch). Keys only is refused while the user has no key, so it cannot lock everyone out."""

from __future__ import annotations
import getpass, glob, os, shlex, shutil, socket
from dataclasses import dataclass, field
from pathlib import Path

from tvwcs.system import distro
from tvwcs.settings.cmd import have, run
from tvwcs.settings.network import parse_ip_json

SSH_DIR = Path("/etc/ssh")
DROPIN_NAME = "00-tvwcs.conf"
KEY_TYPES = ("ssh-", "ecdsa-", "sk-ssh-", "sk-ecdsa-")


@dataclass
class SshState:
    installed: bool = False
    unit: str = ""  # the systemd unit: ssh (Debian, Ubuntu) or sshd (Arch); "" when there is none
    enabled: bool = False  # starts with the computer
    active: bool = False  # running now
    passwords: bool = True  # password sign-in is allowed
    dropins: bool = False  # sshd_config reads sshd_config.d, so the panel can switch passwords
    keys: int = 0  # keys in the user's authorized_keys
    user: str = ""
    hostname: str = ""
    mdns: bool = False  # avahi-daemon runs, so <hostname>.local reaches this computer
    addresses: list = field(default_factory=list)  # [(interface, IPv4 address)]

    @property
    def local_name(self):
        return f"{self.hostname}.local" if self.hostname else ""

    @property
    def address(self):
        """What another computer connects to: the local name when it is announced, else the first address."""
        return (
            self.local_name
            if self.mdns and self.local_name
            else (self.addresses[0][1] if self.addresses else self.hostname)
        )


# ---------------------------------------------------------------------- reading
def parse_unit(text):
    """`systemctl show -p LoadState -p UnitFileState -p ActiveState <unit>` -> (exists, enabled, active)."""
    v = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return (
        v.get("LoadState") == "loaded",
        v.get("UnitFileState") in ("enabled", "enabled-runtime", "alias"),
        v.get("ActiveState") in ("active", "reloading"),
    )


def _config_lines(path, base, seen):
    """sshd_config's lines in the order sshd reads them, with each Include expanded where it stands."""
    path = Path(path)
    if path in seen:
        return
    seen.add(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _sep, value = line.replace("=", " ", 1).partition(" ")
        if key.lower() == "include":
            patterns = [p if os.path.isabs(p) else str(base / p) for p in shlex.split(value)]
            yield ("include", " ".join(patterns))  # before what it includes: where it stands decides what it overrides
            for pattern in patterns:
                for match in sorted(glob.glob(pattern)):
                    yield from _config_lines(match, base, seen)
            continue
        yield (key.lower(), value.strip())


def read_auth(ssh_dir=SSH_DIR):
    """(passwords allowed, drop-ins read first): sshd keeps the first value of each setting, up to the first Match block.
    Password sign-in counts as allowed when PasswordAuthentication or keyboard-interactive (PAM) is on."""
    first = {}
    dropins = False
    dropin_dir = str(Path(ssh_dir) / "sshd_config.d")
    for key, value in _config_lines(Path(ssh_dir) / "sshd_config", Path(ssh_dir), set()):
        if key == "include":  # the drop-ins only win when they are read before sshd_config sets these itself
            if dropin_dir in value and not {"passwordauthentication", "kbdinteractiveauthentication"} & set(first):
                dropins = True
            continue
        if key == "match":
            break
        first.setdefault(key, value.split()[0].lower() if value else "")
    kbd = first.get("kbdinteractiveauthentication", first.get("challengeresponseauthentication", "yes"))
    return first.get("passwordauthentication", "yes") != "no" or kbd != "no", dropins


def count_keys(home=None):
    """How many keys ~/.ssh/authorized_keys holds (options before a key are allowed, as sshd allows them)."""
    home = Path(home or Path.home())
    n = 0
    for name in ("authorized_keys", "authorized_keys2"):
        try:
            lines = (home / ".ssh" / name).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        n += sum(
            1
            for l in lines
            if l.strip() and not l.lstrip().startswith("#") and any(f" {t}" in f" {l.strip()}" for t in KEY_TYPES)
        )
    return n


def avahi_running():
    if have("systemctl") and run(["systemctl", "is-active", "--quiet", "avahi-daemon"], timeout=5).ok:
        return True
    return os.path.exists("/run/avahi-daemon/pid")


def parse_addresses(ip_json, physical=None):
    """`ip -j -4 addr` -> [(interface, address)] of the network cards (no loopback, bridges or containers)."""
    ifaces = parse_ip_json(ip_json, "[]") if physical is None else parse_ip_json(ip_json, "[]", physical)
    return [(i.device, a.split("/")[0]) for i in ifaces for a in i.addresses]


def addresses():
    r = run(["ip", "-j", "-4", "addr", "show"], timeout=5) if have("ip") else None
    return parse_addresses(r.out if r and r.ok else "")


def sshd_path():
    return shutil.which("sshd") or next(
        (p for p in ("/usr/sbin/sshd", "/usr/bin/sshd", "/sbin/sshd") if os.path.exists(p)), ""
    )


def read_state():
    s = SshState(installed=bool(sshd_path()), user=getpass.getuser(), hostname=socket.gethostname().split(".")[0])
    if have("systemctl"):
        for unit in ("ssh", "sshd"):
            exists, enabled, active = parse_unit(
                run(
                    [
                        "systemctl",
                        "show",
                        "-p",
                        "LoadState",
                        "-p",
                        "UnitFileState",
                        "-p",
                        "ActiveState",
                        f"{unit}.service",
                    ],
                    timeout=5,
                ).out
            )
            if exists:
                s.unit, s.enabled, s.active = unit, enabled, active
                break
        if s.unit == "ssh" and not s.active:  # Debian can start it per connection through ssh.socket instead
            _e, senabled, sactive = parse_unit(
                run(
                    ["systemctl", "show", "-p", "LoadState", "-p", "UnitFileState", "-p", "ActiveState", "ssh.socket"],
                    timeout=5,
                ).out
            )
            s.enabled = s.enabled or senabled
            s.active = sactive
    s.passwords, s.dropins = read_auth()
    s.keys = count_keys()
    s.mdns = avahi_running()
    s.addresses = addresses()
    return s


# ---------------------------------------------------------------------- changing (each returns argv to run as root)
def install_argv():
    """Install the SSH server (it is started with the switch on the page). None without apt or pacman."""
    return distro.install_argv(distro.packages("ssh")) if distro.can_install() else None


def service_argv(s, on):
    """Start the SSH server now and at every start-up, or stop it for good. None without systemd."""
    if not s.unit:
        return None
    units = [f"{s.unit}.service"] + (["ssh.socket"] if s.unit == "ssh" and not on else [])
    return ["systemctl", "enable" if on else "disable", "--now", *units]


def key_only_problem(s):
    """Why keys only must not be switched on now, or ""."""
    if not s.dropins:
        return (
            f"This computer's {SSH_DIR}/sshd_config does not read {SSH_DIR}/sshd_config.d, so Settings cannot change "
            "how SSH signs in. Set PasswordAuthentication no in sshd_config yourself."
        )
    if s.keys == 0:
        return (
            f"No SSH key has been added for {s.user} yet, so with passwords off nobody could sign in. On the other computer, "
            f"run  ssh-copy-id {s.user}@{s.address}  (it asks for the password once), then come back here."
        )
    return ""


def passwords_argv(s, allow, ssh_dir=SSH_DIR):
    """Write the drop-in, check the whole configuration with sshd -t (taking the drop-in out again if sshd rejects it)
    and reload the server when it runs."""
    value = "yes" if allow else "no"
    text = (
        f"# Written by TVWCS Settings (System information > SSH). Delete this file to undo it.\n"
        f"PasswordAuthentication {value}\nKbdInteractiveAuthentication {value}\n"
    )
    reload = f"systemctl reload-or-restart {s.unit}.service 2>/dev/null || true" if s.unit and s.active else "true"
    script = (
        'set -e; d="$1"; f="$d/$2"; mkdir -p "$d"; printf "%s" "$3" > "$f.new"; mv "$f.new" "$f"; chmod 644 "$f"; '
        "mkdir -p -m 0755 /run/sshd 2>/dev/null || true; "  # sshd -t wants its privilege separation folder, which only exists while it runs
        'if ! "$4" -t; then rm -f "$f"; echo "sshd rejected the change, so it was undone." >&2; exit 1; fi; ' + reload
    )
    return ["sh", "-c", script, "sh", str(Path(ssh_dir) / "sshd_config.d"), DROPIN_NAME, text, sshd_path() or "sshd"]
