"""Running a power action (sleep, reboot, shut down) as root when it needs that. No GTK dependency.

Under systemd, polkit normally lets the user at the screen do these without a password; it refuses
("Interactive authentication required") when, for instance, another user is logged in, because sway runs no
polkit agent to ask. A plain reboot or poweroff command always needs root. Then TVWCS tries,
in order: doas -n and sudo -n (a no-password rule, such as the one install.sh offers), and finally sudo -S with a
password typed into TVWCS's own dialog. The password goes to sudo through a pipe; it is never stored."""

from __future__ import annotations
import os, shutil

# Every child is run with these, so the messages below can be recognised whatever the user's language is.
C_LOCALE = {"LC_ALL": "C", "LANG": "C", "LANGUAGE": ""}
PLAIN_ROOT_COMMANDS = {"reboot", "poweroff", "halt", "shutdown"}


def c_locale_env(env=None):
    return {**(os.environ if env is None else env), **C_LOCALE}


def needs_root(command, euid=None) -> bool:
    """Plain commands that only root may run (systemctl / loginctl go through polkit instead)."""
    euid = os.geteuid() if euid is None else euid
    return euid != 0 and os.path.basename(command[0]) in PLAIN_ROOT_COMMANDS


def polkit_refused(stderr) -> bool:
    """systemctl / loginctl failed because polkit wants a password nobody can give it."""
    s = (stderr or "").casefold()
    return any(
        t in s
        for t in (
            "interactive authentication required",
            "access denied",
            "authentication is required",
            "not authorized",
        )
    )


def absolute(command, which=shutil.which):
    """The command with its program as a full path: sudo and doas rules name programs by path."""
    path = which(command[0]) if not os.path.isabs(command[0]) else command[0]
    return [path or command[0], *command[1:]]


def doas_command(command, which=shutil.which):
    return ["doas", "-n", *absolute(command, which)] if which("doas") else None


def sudo_command(command, with_password=False, which=shutil.which):
    """sudo -n (only a no-password rule can let it through), or sudo -S, which reads the password from stdin."""
    if not which("sudo"):
        return None
    flags = ["-S", "-p", ""] if with_password else ["-n"]
    return ["sudo", *flags, "--", *absolute(command, which)]


def sudo_outcome(code, stderr) -> str:
    """What a sudo run came to: ok, password (one is needed), wrong (it was wrong), denied (this user may not run
    it), tty (sudo insists on a terminal), or error (sudo let it run, and the command itself failed)."""
    if code == 0:
        return "ok"
    s = (stderr or "").casefold()
    if "incorrect password" in s or "sorry, try again" in s:
        return "wrong"
    if "password is required" in s or "no password was provided" in s:
        return "password"
    if "not in the sudoers" in s or "not allowed to" in s or "may not run sudo" in s:
        return "denied"
    if "terminal is required" in s or "must have a tty" in s:
        return "tty"
    return "error"
