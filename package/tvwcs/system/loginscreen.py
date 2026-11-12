"""The computer's login screen and automatic login (Settings > User > Logging in). No GTK dependency.

TVWCS has no login screen of its own (from 5.0). It works with the one installed: greetd (with its text login,
agreety, or another greeter), LightDM or SDDM. Logging in automatically into TVWCS's session is set where the login
screen in use keeps it: greetd's initial session, or LightDM's and SDDM's own settings. On a computer without a login
screen, install.sh sets up greetd with its text login and the automatic login.

TVWCS 4.x had its own greeter, run by greetd. `migrate` removes it: greetd then shows its text login after logging out,
or the computer switches to another installed login screen.

Changes take effect at the next start: a running login screen (and the session it started) is never stopped.
Changing the system needs root: `python3 -m tvwcs.system.loginscreen <command>` is what Settings and install.sh run as root.
TVWCS_ROOT puts every system path under another folder (the tests), and then nothing is run."""

from __future__ import annotations
import json, os, pwd, re, shlex, shutil, subprocess, sys
from pathlib import Path

from tvwcs import LIB_DIR
from tvwcs.system import distro

SESSION = "tvwcs-sway"  # TVWCS's session (/usr/share/wayland-sessions/tvwcs-sway.desktop)
SESSION_COMMAND = "/usr/bin/tvwcs-session"  # what that session runs
GREETD_CONF = "/etc/greetd/config.toml"
# greetd's user, its text login (agreety) and its console come from distro.greetd(): on Debian _greetd, /usr/sbin/agreety
# (not on _greetd's PATH) and the seventh console, like other login screens; on Arch greeter, /usr/bin/agreety and the first.
LIGHTDM_AUTOLOGIN = "/etc/lightdm/lightdm.conf.d/50-tvwcs-autologin.conf"
SDDM_AUTOLOGIN = "/etc/sddm.conf.d/50-tvwcs-autologin.conf"
SESSION_DIRS = (
    "/usr/share/wayland-sessions",
    "/usr/local/share/wayland-sessions",
    "/usr/share/xsessions",
    "/usr/local/share/xsessions",
)
UNIT_DIRS = ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system")
# What TVWCS 4.x's own login screen left behind
OLD_GREETER_MARK = "tvwcs-greeter/greeter"
OLD_FILES = (
    "/usr/local/lib/tvwcs-greeter",
    "/etc/tvwcs/login-screen.json",
    "/etc/tvwcs/previous-login-screen",
    "/var/lib/tvwcs-greeter",
)
OLD_GREETD_BACKUP = "/etc/greetd/config.toml.tvwcs-backup"
PAM_FILE = "/etc/pam.d/greetd"
PAM_BACKUP = "/etc/pam.d/greetd.tvwcs-backup"
PAM_MARK = "# Written by TVWCS"

# Login screens, by systemd unit. wayland: it can start Wayland sessions such as sway reliably.
KNOWN = {
    "gdm3": ("GNOME's login screen (GDM)", True),
    "gdm": ("GNOME's login screen (GDM)", True),
    "sddm": ("SDDM", True),
    "lightdm": ("LightDM", False),
    "lxdm": ("LXDM", False),
    "xdm": ("XDM", False),
    "slim": ("SLiM", False),
    "greetd": ("greetd", True),
    "ly": ("Ly", True),
    "emptty": ("emptty", True),
    "nodm": ("nodm", False),
    "entrance": ("Entrance", False),
    "lemurs": ("lemurs", True),
}
GRAPHICAL = (
    "gdm3",
    "gdm",
    "sddm",
    "lightdm",
    "lxdm",
    "slim",
    "ly",
    "emptty",
    "lemurs",
)  # switched to when TVWCS's old greeter goes
AUTOLOGIN = (
    "greetd",
    "lightdm",
    "sddm",
    "",
)  # the login screens whose automatic login TVWCS can set ("": none, the text console)
# Without a login screen: the first text console logs the user in (a getty drop-in), and their shell profile starts
# TVWCS's session there
GETTY_DROPIN = "/etc/systemd/system/getty@tty1.service.d/tvwcs-autologin.conf"
GETTY_DROPIN_DIRS = (
    "/etc/systemd/system/getty@.service.d",
    "/etc/systemd/system/getty@tty1.service.d",
)  # in the order systemd applies them
GETTY_TEXT = """# Written by TVWCS (Settings > User): the first text console logs {user} in automatically at start-up, and their
# shell profile starts TVWCS's session. Delete this file to undo it.
[Service]
ExecStart=
ExecStart=-/sbin/agetty -o '-p -f -- \\\\u' --noclear --autologin {user} %I $TERM
"""
PROFILE_BEGIN = (
    "# >>> TVWCS: start TVWCS's session at a login on the first text console (Settings > User; delete to undo) >>>"
)
PROFILE_END = "# <<< TVWCS <<<"
# Back at the console after the session: logging out has the automatic login start it again. Not when it stopped
# straight away (it would only stop again, over and over): the console then stays logged in, at the shell.
PROFILE_BODY = """if [ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] && [ "$(tty)" = /dev/tty1 ] && [ -x /usr/bin/tvwcs-session ]; then
    tvwcs_started=$(date +%s)
    /usr/bin/tvwcs-session
    if [ $(( $(date +%s) - tvwcs_started )) -ge 20 ]; then exit 0; fi
    echo "TVWCS's session stopped straight away, so it is not started again. Type tvwcs to try again."
fi"""
PROFILE_FILES = (".profile", ".bash_profile", ".bash_login", ".zprofile")
_USER = re.compile(r"[a-z_][a-z0-9_.-]*\$?")


def path(p) -> Path:
    """A system path, under TVWCS_ROOT when the tests set it."""
    return Path(os.environ.get("TVWCS_ROOT", "") + p)


def name(unit) -> str:
    """A login screen's name for people."""
    if unit == "greetd" and current_greeter() == "agreety":
        return "greetd (text login)"
    return KNOWN.get(unit, (unit or "no login screen", False))[0]


def wayland_ok(unit) -> bool:
    """Whether this login screen can start sway."""
    return KNOWN.get(unit, ("", False))[1]


# ---------------------------------------------------------------------- what is here
def _read(p, default=""):
    try:
        return path(p).read_text(encoding="utf-8")
    except OSError:
        return default


def active_unit() -> str:
    """The login screen that runs at start-up, by unit name (lightdm, gdm3, greetd...), or "" for none."""
    link = path("/etc/systemd/system/display-manager.service")
    if link.is_symlink():
        unit = os.path.basename(os.readlink(link))
        return unit[: -len(".service")] if unit.endswith(".service") else unit
    # Under systemd that link is the whole answer: disabling a login screen removes it but leaves the old
    # default-display-manager file behind, naming one that no longer starts.
    if path("/run/systemd/system").is_dir():
        return ""
    first = _read("/etc/X11/default-display-manager").strip()
    return os.path.basename(first) if first else ""


current = active_unit


def greetd_config() -> dict:
    """greetd's config, as {section: {key: value}} (a small TOML reader: greetd's config is flat)."""
    out = {}
    section = ""
    for line in _read(GREETD_CONF).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[([A-Za-z0-9_.-]+)\]", line)
        if m:
            section = m.group(1)
            out.setdefault(section, {})
            continue
        m = re.fullmatch(r"([A-Za-z0-9_]+)\s*=\s*(.+?)\s*(#.*)?", line)
        if not m:
            continue
        raw = m.group(2)
        if raw.startswith('"') and raw.endswith('"'):
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw[1:-1]
        elif raw.isdigit():
            value = int(raw)
        elif raw in ("true", "false"):
            value = raw == "true"
        else:
            value = raw
        out.setdefault(section, {})[m.group(1)] = value
    return out


def current_greeter(config=None) -> str:
    """greetd's greeter program (agreety, tuigreet...), "tvwcs" for TVWCS 4.x's, "" without greetd's config."""
    config = greetd_config() if config is None else config
    cmd = str(config.get("default_session", {}).get("command", ""))
    if OLD_GREETER_MARK in cmd:
        return "tvwcs"
    try:
        argv = shlex.split(cmd)
    except ValueError:
        argv = cmd.split()
    while argv and argv[0] in ("cage", "env") or argv and (argv[0].startswith("-") or "=" in argv[0]):
        argv = argv[1:]
    return os.path.basename(argv[0]) if argv else ""


def old_greeter() -> bool:
    """TVWCS 4.x's own login screen is still set up."""
    return current_greeter() == "tvwcs" or any(path(p).exists() for p in OLD_FILES[:1])


def unit_installed(unit) -> bool:
    return any(path(f"{d}/{unit}.service").exists() for d in UNIT_DIRS)


def installed_screens() -> list:
    """The login screens installed here, by unit."""
    found = []
    for unit in KNOWN:
        if not unit_installed(unit) or unit == "gdm" and "gdm3" in found:
            continue
        found.append(unit)
    return found


def status() -> dict:
    """What Settings shows: the login screen in use, the others installed, and whether TVWCS 4.x's is still set up."""
    cur = active_unit()
    return {"current": cur, "installed": installed_screens(), "old_greeter": old_greeter(), "autologin": autologin(cur)}


# ---------------------------------------------------------------------- sessions
def _desktop_entry(text):
    """The [Desktop Entry] keys of a .desktop file."""
    keys = {}
    inside = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
            continue
        if inside and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            keys.setdefault(k.strip(), v.strip())
    return keys


def session_exec(sid) -> list:
    """The command of the session `sid` (a .desktop file's name), or []."""
    for d in SESSION_DIRS:
        try:
            e = _desktop_entry(path(f"{d}/{sid}.desktop").read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        try:
            return shlex.split(e.get("Exec", ""))
        except ValueError:
            return []
    return []


def session_command(sid=SESSION) -> list:
    return session_exec(sid) or ([SESSION_COMMAND] if sid == SESSION else [])


# ---------------------------------------------------------------------- the automatic login
def _ini_values(files, section_ok, keys):
    """The last value of each of `keys` in the sections section_ok accepts, across `files` (later files win)."""
    found = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        section = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line
                continue
            if not section_ok(section):
                continue
            for k in keys:
                m = re.fullmatch(rf"{k}\s*=\s*(\S*)", line)
                if m:
                    found[k] = m.group(1)
    return found


def _conf_files(main, folder):
    files = [path(main)]
    try:
        files += sorted(path(folder).glob("*.conf"))
    except OSError:
        pass
    return files


def console_autologin() -> str:
    """Who the first text console logs in automatically (agetty --autologin in a getty drop-in), or ""."""
    who = ""
    for d in GETTY_DROPIN_DIRS:
        try:
            files = sorted(path(d).glob("*.conf"))
        except OSError:
            continue
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                m = re.fullmatch(r"\s*ExecStart\s*=\s*(.*?)\s*", line)
                if not m:
                    continue
                try:
                    argv = shlex.split(m.group(1).lstrip("-@+!:"))
                except ValueError:
                    argv = m.group(1).split()
                who = ""
                for i, a in enumerate(argv):
                    if a in ("--autologin", "-a") and i + 1 < len(argv):
                        who = argv[i + 1]
                    elif a.startswith("--autologin="):
                        who = a.split("=", 1)[1]
    return who


def autologin(unit=None) -> tuple:
    """(user, session id) logged in automatically at start-up by the login screen in use, or ("", "")."""
    unit = active_unit() if unit is None else unit
    if unit == "":
        who = console_autologin()
        return (who, SESSION) if who else ("", "")
    if unit == "greetd":
        init = greetd_config().get("initial_session", {})
        who = init.get("user", "")
        if not who:
            return ("", "")
        try:
            argv = shlex.split(str(init.get("command", "")))
        except ValueError:
            argv = []
        sid = (
            SESSION
            if argv
            and (
                argv == session_command()
                or os.path.basename(argv[0]) == "tvwcs-session"
                or "tvwcs-session" in " ".join(argv)
            )
            else ""
        )
        return (who, sid)
    if unit == "lightdm":
        v = _ini_values(
            _conf_files("/etc/lightdm/lightdm.conf", "/etc/lightdm/lightdm.conf.d"),
            lambda s: s.startswith("[Seat:") or s == "[SeatDefaults]",
            ("autologin-user", "autologin-session"),
        )
        return (v.get("autologin-user", ""), v.get("autologin-session", "")) if v.get("autologin-user") else ("", "")
    if unit == "sddm":
        v = _ini_values(
            _conf_files("/etc/sddm.conf", "/etc/sddm.conf.d"), lambda s: s == "[Autologin]", ("User", "Session")
        )
        return (v.get("User", ""), v.get("Session", "").removesuffix(".desktop")) if v.get("User") else ("", "")
    return ("", "")


def autologin_supported(unit=None) -> bool:
    return (active_unit() if unit is None else unit) in AUTOLOGIN


# ---------------------------------------------------------------------- the shell profile (as the user)
def profile_file(home=None, shell=None):
    """The profile the user's login shell reads at a console login, where TVWCS's session is started; None for a
    shell TVWCS does not know (fish...)."""
    home = Path(home or Path.home())
    if shell is None:
        try:
            shell = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            shell = ""
    shell = os.path.basename(shell or "sh")
    if shell == "bash":  # bash reads the first of these that exists
        return next((home / n for n in (".bash_profile", ".bash_login") if (home / n).exists()), home / ".profile")
    if shell in ("sh", "dash", "ksh", "mksh"):
        return home / ".profile"
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR") or home) / ".zprofile"
    return None


def _profiles(home=None):
    home = Path(home or Path.home())
    return [home / n for n in PROFILE_FILES] + (
        [Path(os.environ["ZDOTDIR"]) / ".zprofile"] if os.environ.get("ZDOTDIR") else []
    )


def profile_starts(home=None) -> bool:
    """A shell profile of the user's starts TVWCS's session at a login on the first console."""
    for f in _profiles(home):
        try:
            if PROFILE_BEGIN in f.read_text(encoding="utf-8", errors="replace").splitlines():
                return True
        except OSError:
            pass
    return False


def set_profile(on, home=None, shell=None) -> str:
    """Add TVWCS's lines to the user's shell profile (on) or take them out of every one; "" when it worked, else why not."""
    try:
        for f in _profiles(home):
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                continue
            if PROFILE_BEGIN not in lines:
                continue
            out = []
            skip = False
            for line in lines:
                if line == PROFILE_BEGIN:
                    skip = True
                    continue
                if skip and line == PROFILE_END:
                    skip = False
                    continue
                if not skip:
                    out.append(line)
            while out and not out[-1].strip():
                out.pop()
            f.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
        if not on:
            return ""
        f = profile_file(home, shell)
        if f is None:
            return (
                "Your login shell is not one TVWCS knows (it knows bash, sh, dash and zsh). Make it start "
                "/usr/bin/tvwcs-session at a login on /dev/tty1 yourself."
            )
        try:
            text = f.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        if text and not text.endswith("\n"):
            text += "\n"
        f.write_text(f"{text}\n{PROFILE_BEGIN}\n{PROFILE_BODY}\n{PROFILE_END}\n", encoding="utf-8")
        return ""
    except OSError as exc:
        return f"Could not change your shell profile: {exc}"


def greetd_text(greeter_command, user, autologin_to=None, vt=None) -> str:
    """greetd's config. autologin_to: (user, command) for the initial session, which logs that user in at start-up (the
    greeter then shows after logging out)."""
    vt = distro.greetd()[2] if vt is None else vt
    lines = [
        "# Written by TVWCS (Settings > User > Logging in).",
        "[terminal]",
        f"vt = {vt}",
        "",
        "[default_session]",
        f"command = {json.dumps(greeter_command)}",
        f"user = {json.dumps(user)}",
    ]
    if autologin_to:
        who, cmd = autologin_to
        lines += ["", "[initial_session]", f"command = {json.dumps(cmd)}", f"user = {json.dumps(who)}"]
    return "\n".join(lines) + "\n"


def agreety_command() -> str:
    """greetd's text login, which starts TVWCS's session after the password."""
    return f"{distro.greetd()[1]} --cmd {shlex.quote(shlex.join(session_command()))}"


# ---------------------------------------------------------------------- changing the system (as root)
def relabel(f):
    """With SELinux (Fedora), give a file TVWCS wrote the label its place calls for: one made under another name and
    renamed could otherwise keep the label of that name."""
    if os.environ.get("TVWCS_ROOT") or not os.path.exists("/sys/fs/selinux/enforce"):
        return
    tool = shutil.which("restorecon", path="/usr/sbin:/usr/bin:/sbin:/bin")
    if tool:
        subprocess.run([tool, "-F", str(f)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Changer:
    """The system changes, done as root by `python3 -m tvwcs.system.loginscreen`. `run` runs systemctl (not run at all under
    TVWCS_ROOT, where it only records)."""

    def __init__(self, run=None, out=print):
        self.calls = []
        self.out = out
        self._run = run or (
            None if os.environ.get("TVWCS_ROOT") else (lambda argv: subprocess.run(argv, check=False).returncode)
        )

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        return 0 if self._run is None else self._run(["systemctl", *args])

    def write(self, p, text, mode=0o644):
        f = path(p)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tvwcs-new")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, mode)
        os.replace(tmp, f)
        relabel(f)

    def remove(self, p):
        try:
            path(p).unlink()
            return True
        except FileNotFoundError:
            return False

    def switch_to(self, unit):
        """Make `unit` the login screen at the next start: the old one is disabled, never stopped."""
        old = active_unit()
        if old and old != unit:
            self.systemctl("disable", f"{old}.service")
        if self.remove(GETTY_DROPIN):
            self.systemctl("daemon-reload")  # the text console's automatic login (no login screen) would log in too
        self.systemctl("enable", "--force", f"{unit}.service")
        # Debian's and Ubuntu's lightdm.service has no [Install] section: enable does nothing for it (its postinst makes
        # the link by hand), and with the old one disabled, no login screen would start. The link is made here too.
        link = path("/etc/systemd/system/display-manager.service")
        target = next(
            (f"{d}/{unit}.service" for d in UNIT_DIRS[1:] if path(f"{d}/{unit}.service").exists()),
            f"/lib/systemd/system/{unit}.service",
        )
        if not (link.is_symlink() and os.path.basename(os.readlink(link)) == f"{unit}.service"):
            if link.is_symlink() or link.exists():
                link.unlink()
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
            self.systemctl("daemon-reload")
        if distro.family() not in (distro.ARCH, distro.FEDORA):  # only Debian's family reads it
            exe = shutil.which(unit, path="/usr/sbin:/usr/bin:/sbin:/bin") or f"/usr/sbin/{unit}"
            self.write("/etc/X11/default-display-manager", exe + "\n")
        self.systemctl("set-default", "graphical.target")  # greetd is only started by graphical.target

    def write_greetd(self, autologin_to=None, greeter=None):
        """greetd's config, keeping its greeter (agreety when it was TVWCS 4.x's or there was none) and console.
        autologin_to: (user, session id), or None for no automatic login."""
        cfg = greetd_config()
        ds = cfg.get("default_session", {})
        cmd = (
            greeter
            or ("" if current_greeter(cfg) in ("", "tvwcs") else str(ds.get("command", "")))
            or agreety_command()
        )
        default_user, _agreety, default_vt = distro.greetd()
        user = ds.get("user") or default_user
        vt = cfg.get("terminal", {}).get("vt", default_vt)
        init = None
        if autologin_to and autologin_to[0]:
            argv = session_command(autologin_to[1] or SESSION)
            if not argv:
                raise SystemExit(
                    f"There is no session called {autologin_to[1]} (no .desktop file in /usr/share/wayland-sessions)."
                )
            init = (autologin_to[0], shlex.join(argv))
        self.write(GREETD_CONF, greetd_text(cmd, user, init, vt if isinstance(vt, (int, str)) else default_vt))

    def set_autologin(self, user, session=SESSION, unit=None):
        """Log `user` in automatically at start-up into `session` (a session id), or stop it (user "")."""
        unit = active_unit() if unit is None else unit
        if unit == "greetd":
            self.write_greetd((user, session) if user else None)
        elif unit == "lightdm":
            if user:
                self.write(
                    LIGHTDM_AUTOLOGIN,
                    "# Written by TVWCS (Settings > User).\n[Seat:*]\n"
                    f"autologin-user={user}\n" + (f"autologin-session={session}\n" if session else ""),
                )
            else:
                self.remove(LIGHTDM_AUTOLOGIN)
                if autologin(unit)[0]:
                    raise SystemExit("LightDM's own settings log someone in automatically; change it in /etc/lightdm.")
        elif unit == "sddm":
            if user:
                self.write(
                    SDDM_AUTOLOGIN,
                    "# Written by TVWCS (Settings > User).\n[Autologin]\n"
                    f"User={user}\n" + (f"Session={session}.desktop\n" if session else ""),
                )
            else:
                self.remove(SDDM_AUTOLOGIN)
                if autologin(unit)[0]:
                    raise SystemExit("SDDM's own settings log someone in automatically; change it in /etc/sddm.conf.")
        elif unit == "":
            if user:
                if not _USER.fullmatch(user):
                    raise SystemExit(f"Unexpected user name: {user}")
                self.write(GETTY_DROPIN, GETTY_TEXT.format(user=user))
            else:
                self.remove(GETTY_DROPIN)
                try:
                    path(GETTY_DROPIN).parent.rmdir()  # only when it holds nothing else
                except OSError:
                    pass
            self.systemctl("daemon-reload")
            if not user and console_autologin():
                raise SystemExit(
                    "Another file in /etc/systemd/system/getty@tty1.service.d logs someone in automatically; change it there."
                )
        else:
            raise SystemExit(f"TVWCS cannot change the automatic login of {name(unit)}; use its own settings.")
        self.out(
            f"From the next start, {user} is logged in automatically."
            if user
            else "From the next start, nobody is logged in automatically."
        )

    def use_greetd(self, user):
        """For a computer without a login screen: greetd with its text login, logging `user` in automatically."""
        self.write_greetd((user, SESSION) if user else None)
        self.switch_to("greetd")
        self.out(
            "From the next start, greetd logs " + (f"{user} in automatically." if user else "people in (a text login).")
        )

    def migrate(self, user=""):
        """Remove TVWCS 4.x's own login screen. Another graphical login screen installed here takes over (with the
        automatic login for `user`, when given); otherwise greetd stays, with its text login and the automatic login."""
        was_on = active_unit() == "greetd" and current_greeter() == "tvwcs"
        auto = autologin("greetd")[0] if was_on else ""
        user = user or auto
        other = next((u for u in GRAPHICAL if u in installed_screens()), "")
        if path(OLD_GREETD_BACKUP).exists() and current_greeter() == "tvwcs":
            os.replace(path(OLD_GREETD_BACKUP), path(GREETD_CONF))
        self.remove(OLD_GREETD_BACKUP)
        if was_on and not other or current_greeter() == "tvwcs":
            self.write_greetd((user, SESSION) if user and not other else None)
        if path(PAM_BACKUP).exists() and PAM_MARK in _read(PAM_FILE):
            os.replace(path(PAM_BACKUP), path(PAM_FILE))
        for p in OLD_FILES:
            f = path(p)
            if f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
            else:
                self.remove(p)
        if was_on and other:
            self.switch_to(other)
            if user and other in AUTOLOGIN:
                self.set_autologin(user, SESSION, other)
            self.out(f"TVWCS's old login screen is removed. From the next start, the computer uses {name(other)}.")
        elif was_on:
            self.out(
                "TVWCS's old login screen is removed. From the next start, greetd "
                + (
                    f"logs {user} in automatically, and shows its text login after logging out."
                    if user
                    else "shows its text login."
                )
            )
        else:
            self.out("TVWCS's old login screen is removed.")


INSTALL_THEN = """set -e
n=$1; shift; packages=""
while [ "$n" -gt 0 ]; do packages="$packages $1"; shift; n=$((n-1)); done
if [ -n "$packages" ]; then {install}; fi
exec "$@"
"""


def root_command(args, packages=(), module="tvwcs.system.loginscreen") -> list:
    """The command (for sudo) that installs `packages` with apt or pacman, then runs `python3 -m <module> args` (this module, or
    tvwcs.system.servermode) from this copy of TVWCS."""
    run = [
        "env",
        "PYTHONDONTWRITEBYTECODE=1",
        f"PYTHONPATH={LIB_DIR}",
        "python3",
        "-m",
        module,
        *args,
    ]
    if not packages:
        return run
    if not all(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", p) for p in packages):
        raise ValueError("Unexpected package name.")
    return ["sh", "-c", INSTALL_THEN.format(install=distro.install_script()), "sh", str(len(packages)), *packages, *run]


USAGE = """Usage (as root): python3 -m tvwcs.system.loginscreen <command>
  autologin USER [SESSION] | autologin --off   log USER in at start-up into SESSION (default: tvwcs-sway)
  switch UNIT                                  use another installed login screen (sddm...) from the next start
  greetd [USER]                                use greetd's text login, logging USER in automatically
  migrate [USER]                               remove TVWCS 4.x's own login screen
Without root: status | profile on|off   (profile: start TVWCS's session at a login on the first text console)"""


def main(argv):
    args = list(argv)
    if not args:
        print(USAGE, file=sys.stderr)
        return 2
    cmd = args.pop(0)
    if cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "profile" and args in (["on"], ["off"]):
        problem = set_profile(args == ["on"])
        if problem:
            print(problem, file=sys.stderr)
            return 1
        return 0
    if os.geteuid() != 0 and not os.environ.get("TVWCS_ROOT"):
        print("This needs root.", file=sys.stderr)
        return 1
    c = Changer()
    try:
        if cmd == "autologin" and args == ["--off"]:
            c.set_autologin("", "")
        elif cmd == "autologin" and len(args) in (1, 2):
            c.set_autologin(args[0], args[1] if len(args) == 2 else SESSION)
        elif cmd == "switch" and len(args) == 1:
            if not unit_installed(args[0]):
                raise SystemExit(f"{name(args[0])} is not installed.")
            c.switch_to(args[0])
            c.out(f"From the next start, the computer uses {name(args[0])}.")
        elif cmd == "greetd" and len(args) <= 1:
            c.use_greetd(args[0] if args else "")
        elif cmd == "migrate" and len(args) <= 1:
            c.migrate(args[0] if args else "")
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
