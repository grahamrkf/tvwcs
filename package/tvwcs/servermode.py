"""Server mode: TVWCS on a computer that is a server first, so the TV can never get in its way. No GTK dependency.

It is one root-owned file, /etc/tvwcs/server-mode, naming the account that uses the TV (the server user), so nobody
in TVWCS can turn it off without an administrator. While it is there, in every TVWCS session on this computer:
- the Quick Menu's power menu has no Sleep, Restart or Shut down, the idle timer never puts the computer to sleep and
  a nearly empty battery does nothing (system_actions, power);
- Settings turns off Power and sleep, Software updates and Network, and hides every other setting that needs an
  administrator, except turning server mode off (ui_control_pages, ui_control_login).
A polkit rule backs it up for the server user, whatever program asks: logind refuses to suspend, hibernate, restart
or shut down, UDisks to unmount drives the user did not mount or to switch drives off, and NetworkManager to change
the system's connections.

Turning it on also logs the server user in automatically into TVWCS at start-up (loginscreen: the login screen's
automatic login, or the first text console's without one). Turning it off leaves the automatic login as it is.

As root: python3 -m tvwcs.servermode on USER | off | start USER | status. As anyone, the `tvwcs` launcher passes
`server-mode on [--user=NAME] | off | status` and `start-session [--user=NAME]` here (cli; also the older -s, --no-server-mode and --start), which ask sudo for the rest;
over SSH plain `tvwcs` offers the same as a short menu."""

from __future__ import annotations
import fcntl, json, os, pwd, re, shlex, shutil, subprocess, sys, time
from pathlib import Path
from tvwcs import loginscreen
from tvwcs.loginscreen import path

CONF = "/etc/tvwcs/server-mode"
POLKIT_RULE = "/etc/polkit-1/rules.d/50-tvwcs-server-mode.rules"
START_UNIT = "tvwcs-start"  # the transient unit `start` runs TVWCS's session in
_USER = re.compile(r"[a-z_][a-z0-9_.-]*\$?")
# The polkit actions the server user is refused. logind's carry suffixes (-multiple-sessions, -ignore-inhibit).
POLKIT_TEXT = """// Written by TVWCS (server mode). {user} uses the TV: they cannot put this computer to sleep, restart it or shut
// it down, unmount drives they did not mount or switch drives off, or change the system's network connections.
// Removed when server mode is turned off (TVWCS Settings > User, or: tvwcs server-mode off).
polkit.addRule(function(action, subject) {{
    if (subject.user != "{user}") return polkit.Result.NOT_HANDLED;
    var id = action.id;
    if (/^org\\.freedesktop\\.login1\\.(power-off|reboot|halt|suspend|hibernate|set-reboot)/.test(id) ||
        /^org\\.freedesktop\\.udisks2\\.(filesystem-unmount-others|power-off-drive)/.test(id) ||
        /^org\\.freedesktop\\.NetworkManager\\.(settings\\.modify\\.(system|hostname|global-dns)|network-control|enable-disable-|wifi\\.share|checkpoint-rollback|reload)/.test(id))
        return polkit.Result.NO;
    return polkit.Result.NOT_HANDLED;
}});
"""


# ---------------------------------------------------------------------- reading (anyone)
def server_user() -> str:
    """The server user while server mode is on, else ""."""
    try:
        text = path(CONF).read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "user" and _USER.fullmatch(v.strip()):
            return v.strip()
    return "" if not text.strip() else "?"  # a file without a valid user still means on


def active() -> bool:
    return bool(server_user())


def accounts():
    """The people's accounts here, by name: UID 1000 and up (not nobody), with a shell to log in with."""
    out = []
    for e in pwd.getpwall():
        if e.pw_uid < 1000 or e.pw_uid >= 60000 or os.path.basename(e.pw_shell or "") in ("nologin", "false", ""):
            continue
        out.append(e.pw_name)
    return sorted(out)


def admins():
    """The accounts that may use sudo (the sudo, wheel or admin group), by name."""
    import grp
    from tvwcs.account import ADMIN_GROUPS

    names = set()
    for g in ADMIN_GROUPS:
        try:
            e = grp.getgrnam(g)
        except KeyError:
            continue
        names |= set(e.gr_mem) | {p.pw_name for p in pwd.getpwall() if p.pw_gid == e.gr_gid}
    return sorted(n for n in names if n != "root")


# ---------------------------------------------------------------------- changing the system (as root)
class Changer(loginscreen.Changer):
    def check_user(self, user):
        if not _USER.fullmatch(user or ""):
            raise SystemExit(f"Unexpected user name: {user}")
        try:
            e = pwd.getpwnam(user)
        except KeyError:
            raise SystemExit(f"There is no account called {user} here. Make one first (sudo adduser {user}).")
        if e.pw_uid == 0:
            raise SystemExit("Server mode cannot use root's account for the TV.")
        return e

    def user_profile(self, entry, on):
        """The server user's shell profile starts TVWCS's session at a login on the first console (or not)."""
        if os.environ.get("TVWCS_ROOT"):
            problem = loginscreen.set_profile(on, home=path(entry.pw_dir), shell=entry.pw_shell)
        else:  # as the user, so the file stays theirs
            r = subprocess.run(
                [
                    "runuser",
                    "-u",
                    entry.pw_name,
                    "--",
                    "env",
                    f"HOME={entry.pw_dir}",
                    f"PYTHONPATH={Path(__file__).resolve().parent.parent}",
                    "python3",
                    "-m",
                    "tvwcs.loginscreen",
                    "profile",
                    "on" if on else "off",
                ],
                capture_output=True,
                text=True,
            )
            problem = (r.stderr or r.stdout).strip() if r.returncode else ""
        if problem:
            raise SystemExit(problem)

    def turn_on(self, user, autologin=True):
        entry = self.check_user(user)
        self.write(
            CONF,
            f"# Written by TVWCS: server mode is on, and {user} uses the TV. Turn it off in TVWCS Settings > User, or\n"
            f"# with: tvwcs server-mode off\nuser={user}\n",
        )
        self.write(POLKIT_RULE, POLKIT_TEXT.format(user=user))
        said = f"Server mode is on: {user} uses the TV, without power, update, network or other administrator settings."
        if autologin:
            unit = loginscreen.active_unit()
            if unit in loginscreen.AUTOLOGIN:
                if unit == "":
                    self.user_profile(entry, True)
                self.set_autologin(user, loginscreen.SESSION, unit)
            else:
                said += f" Set {loginscreen.name(unit)}'s automatic login to {user} and the TVWCS session in its own settings."
        self.out(said)

    def turn_off(self):
        gone = self.remove(CONF)
        self.remove(POLKIT_RULE)
        try:
            path(CONF).parent.rmdir()
        except OSError:
            pass
        self.out(
            "Server mode is off. The automatic login is unchanged (Settings > User)."
            if gone
            else "Server mode was not on."
        )

    def start(self, user, run=subprocess.run, sleep=time.sleep):
        """Start TVWCS's session for `user` on the computer's screen now, on a free console (tty1 when it is free),
        once: a transient service logs them in there (PAM's login service, as a console login does). When the session
        ends the console goes back to its login prompt."""
        entry = self.check_user(user)
        if run(["pgrep", "-u", user, "-x", "sway"], capture_output=True).returncode == 0:
            raise SystemExit(f"{user} has a sway session running already; TVWCS runs once per user.")
        vt = free_console(run)
        if not vt:
            raise SystemExit("Every text console (tty1 to tty6) is in use, so there is nowhere to start TVWCS.")
        unit = f"{START_UNIT}-{user}"
        argv = [
            "systemd-run",
            f"--unit={unit}",
            "--collect",
            "--service-type=simple",
            "-p",
            "PAMName=login",
            f"-p",
            f"User={user}",
            f"-p",
            f"WorkingDirectory={entry.pw_dir}",
            "-p",
            f"TTYPath=/dev/tty{vt}",
            "-p",
            "TTYReset=yes",
            "-p",
            "TTYVHangup=yes",
            "-p",
            "TTYVTDisallocate=yes",
            "-p",
            "StandardInput=tty-fail",
            "-p",
            "StandardOutput=journal",
            "-p",
            "StandardError=journal",
            "-p",
            f"UtmpIdentifier=tty{vt}",
            "-p",
            "UtmpMode=user",
            "-p",
            f"Conflicts=getty@tty{vt}.service",
            "-p",
            f"After=getty@tty{vt}.service",
            "-p",
            f"ExecStopPost=+/bin/systemctl --no-block start getty@tty{vt}.service",  # + : as root (the user may not start a getty)
            "-E",
            "XDG_SESSION_TYPE=wayland",
            "-E",
            "XDG_SESSION_CLASS=user",
            loginscreen.SESSION_COMMAND,
        ]
        self.calls.append(argv)
        if self._run is not None:
            r = run(argv, capture_output=True, text=True)
            if r.returncode:
                raise SystemExit((r.stderr or r.stdout).strip() or "systemd-run could not start TVWCS's session.")
            switch_console(vt)
        self.out(f"TVWCS is starting for {user} on the computer's screen (console {vt}).")


def switch_console(vt, opener=os.open) -> bool:
    """Show console `vt` on the screen, as chvt does (that comes with kbd, which is not always installed)."""
    try:
        fd = opener("/dev/tty0", os.O_RDWR | os.O_NOCTTY)
        try:
            fcntl.ioctl(fd, 0x5606, vt)  # VT_ACTIVATE
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def free_console(run=subprocess.run) -> int:
    """The first of consoles 1-6 that no login session (a console login, a login screen or its session) is on, or 0."""
    used = set()
    try:
        out = run(
            ["loginctl", "list-sessions", "--no-legend", "--no-pager"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            sid = line.split()[0] if line.split() else ""
            if not sid:
                continue
            v = run(
                ["loginctl", "show-session", sid, "-p", "VTNr", "-p", "TTY", "--value"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.split()
            for x in v:
                if x.isdigit() and int(x):
                    used.add(int(x))
                m = re.fullmatch(r"tty(\d+)", x)
                if m:
                    used.add(int(m.group(1)))
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return next((n for n in range(1, 7) if n not in used), 0)


# ---------------------------------------------------------------------- the command line
USAGE = """Usage: tvwcs server-mode on [--user=NAME]   turn on server mode, NAME (you, by default) using the TV and
                                           logged in automatically into TVWCS
       tvwcs server-mode off                 turn server mode off (the automatic login stays)
       tvwcs server-mode status              say whether server mode is on, and for whom
       tvwcs start-session [--user=NAME]     start TVWCS for NAME on this computer's screen now (for example over SSH)
They ask for an administrator's password (sudo). Over SSH, plain tvwcs offers them as a menu. (The older spellings
-s / --server-mode, --no-server-mode and --start still work.)"""


def me() -> str:
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return os.environ.get("USER", "")


def as_root(args, run=subprocess.run) -> int:
    """`python3 -m tvwcs.servermode args` as root from this copy of TVWCS: sudo asks for the password at the terminal."""
    argv = [
        "env",
        "PYTHONDONTWRITEBYTECODE=1",
        f"PYTHONPATH={Path(__file__).resolve().parent.parent}",
        "python3",
        "-m",
        "tvwcs.servermode",
        *args,
    ]
    if os.geteuid() != 0:
        if not shutil.which("sudo"):
            print("This needs root, and sudo is not installed.", file=sys.stderr)
            return 1
        argv = ["sudo", "--", *argv]
    return run(argv).returncode


def parse(args):
    """-> (what, user): what is "on", "off", "status", "start" or "" (not ours / wrong); user "" for the default.
    `server-mode on|off|status` and `start-session`, or the older -s / --server-mode, --no-server-mode and --start."""
    words = {
        ("server-mode", "on"): "on",
        ("server-mode", "off"): "off",
        ("server-mode", "status"): "status",
        ("start-session",): "start",
    }
    what = ""
    rest = list(args)
    for key, name in words.items():
        if tuple(args[: len(key)]) == key:
            what = name
            rest = list(args[len(key) :])
            break
    user = ""
    for a in rest:
        if a.startswith("--user=") and a[7:]:
            user = a[7:]
        elif not what and a in ("-s", "--server-mode"):
            what = "on"
        elif not what and a == "--no-server-mode":
            what = "off"
        elif not what and a == "--start":
            what = "start"
        else:
            return "", ""
    if what in ("off", "status") and user:
        return "", ""
    return what, user


def status_text() -> str:
    user = server_user()
    if not user:
        return "Server mode is off."
    if user == "?":
        return f"Server mode is on, but {CONF} names no valid account."
    return f"Server mode is on for {user}."


def menu(ask=input, out=print) -> int:
    """Plain `tvwcs` over SSH: what can be done from here, asked in turn."""
    user = server_user()
    out("TVWCS starts on this computer's own screen, not over SSH. From here you can:")
    out("  1  start TVWCS on this computer's screen now")
    out("  2  turn on server mode (an account uses the TV, logs in automatically, and has no power, update,")
    out(
        "     network or other administrator settings)"
        if not user
        else "     network or other administrator settings; on now for " + user + ")"
    )
    out("  3  turn server mode off")
    try:
        choice = ask("Choose 1, 2 or 3 (Enter for nothing): ").strip()
        if choice not in ("1", "2", "3"):
            return 0
        if choice == "3":
            return as_root(["off"])
        default = user if user and user != "?" else me()
        name = ask(f"Which account? [{default}]: ").strip() or default
    except (EOFError, KeyboardInterrupt):
        out("")
        return 1
    return as_root(["start" if choice == "1" else "on", name])


def cli(args) -> int:
    """The launcher's server mode options, and its plain `tvwcs` over SSH (no args)."""
    if not args:
        if sys.stdin.isatty():
            return menu()
        print(USAGE, file=sys.stderr)
        return 2
    what, user = parse(args)
    if not what:
        print(USAGE, file=sys.stderr)
        return 2
    if what == "status":
        print(status_text())
        return 0
    if what == "off":
        return as_root(["off"])
    return as_root([what, user or me()])


def main(argv):
    args = list(argv)
    if args[:1] == ["cli"]:
        return cli(args[1:])
    if args == ["status"]:
        print(json.dumps({"on": active(), "user": server_user()}))
        return 0
    if os.geteuid() != 0 and not os.environ.get("TVWCS_ROOT"):
        print("This needs root.", file=sys.stderr)
        return 1
    c = Changer()
    try:
        if args[:1] == ["on"] and len(args) == 2:
            c.turn_on(args[1])
        elif args == ["off"]:
            c.turn_off()
        elif args[:1] == ["start"] and len(args) == 2:
            c.start(args[1])
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
