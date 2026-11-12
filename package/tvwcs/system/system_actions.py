"""System actions offered by the Quick Menu's power menu; no GTK dependency.

Power actions use systemd's systemctl (TVWCS supports systemd systems only)."""

from __future__ import annotations
import os, shlex, shutil, subprocess
from dataclasses import dataclass
from tvwcs.system import lockscreen, servermode


@dataclass(frozen=True)
class SystemAction:
    id: str
    label: str
    icon: str  # symbolic icon name from the icon theme
    fallback: str  # text glyph used when the theme lacks the icon
    confirm: str = ""  # non-empty = ask for confirmation first; the text is the question


SYSTEM_ACTIONS = (
    SystemAction("lock", "Lock", "system-lock-screen-symbolic", "🔒"),
    SystemAction("refresh", "Refresh applications", "view-refresh-symbolic", "⟳"),
    SystemAction("sleep", "Sleep", "weather-clear-night-symbolic", "☾"),
    SystemAction(
        "logout",
        "Log out",
        "system-log-out-symbolic",
        "⇥",
        "Log out and end this session? Unsaved work in open applications may be lost.",
    ),
    SystemAction(
        "reboot",
        "Reboot",
        "system-reboot-symbolic",
        "↻",
        "Restart the computer now? Unsaved work in open applications may be lost.",
    ),
    SystemAction(
        "shutdown",
        "Shut down",
        "system-shutdown-symbolic",
        "⏻",
        "Power off the computer now? Unsaved work in open applications may be lost.",
    ),
)

POWER_MENU = (
    "lock",
    "sleep",
    "reboot",
    "shutdown",
    "logout",
)  # the power menu's order; logout only with a login screen
SERVER_KEEPS = (
    "lock",
    "logout",
)  # in server mode (servermode.py) the TV never sleeps, restarts or shuts the server down


def login_manager_installed(exists=os.path.exists, which=shutil.which):
    """True when a login screen (display manager) runs at start-up. Without one, logging out of sway only leaves a
    text console, or with Settings' automatic login on the console starts TVWCS again, so the power menu offers Log
    out only with one. One installed but not set up to start does not count.
    `which` is accepted for older callers."""
    if exists("/etc/systemd/system/display-manager.service"):
        return True
    # under systemd the link is the whole answer (disabling a login screen leaves default-display-manager behind)
    if exists("/run/systemd/system") or not exists("/etc/X11/default-display-manager"):
        return False
    try:
        with open("/etc/X11/default-display-manager", encoding="utf-8") as f:
            return bool(f.read().strip())
    except OSError:
        return False


def login_service(env=None, run=subprocess.run) -> str:
    """The PAM service logind recorded for this login: "login" for a text console (typing tvwcs there, or the
    console's automatic login), "greetd", "gdm-password", "sddm"... for a login screen; "" when logind cannot say."""
    env = os.environ if env is None else env
    sid = env.get("XDG_SESSION_ID")
    if not sid:
        return ""
    try:
        out = run(
            ["loginctl", "show-session", sid, "-p", "Service", "--value"], capture_output=True, text=True, timeout=2
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def can_log_out(env=None, run=subprocess.run, exists=os.path.exists) -> bool:
    """Logging out reaches a login screen: this session came from one (logind says so), or, when logind cannot say,
    one starts at boot. A session started at a text console only goes back to it, or with the automatic login
    straight back into TVWCS, even with a login screen installed."""
    service = login_service(env, run)
    if service:
        return service != "login"
    return login_manager_installed(exists)


def power_menu(settings=None, display_manager=None, server=None):
    """The actions the Quick Menu's power menu offers, in order. `settings` is accepted for older callers."""
    dm = can_log_out() if display_manager is None else display_manager
    server = servermode.active() if server is None else server
    by_id = {a.id: a for a in SYSTEM_ACTIONS}
    return [by_id[i] for i in POWER_MENU if (i != "logout" or dm) and (not server or i in SERVER_KEEPS)]


def allowed(action_id, server=None) -> bool:
    """Server mode refuses Sleep, Restart and Shut down, however they are asked for (a hotkey, the idle timer)."""
    server = servermode.active() if server is None else server
    return not server or action_id not in POWER_VERBS or action_id in SERVER_KEEPS


def logout_command(env=None, which=shutil.which):
    return ["swaymsg", "exit"] if which("swaymsg") else None


POWER_VERBS = {"sleep": "suspend", "reboot": "reboot", "shutdown": "poweroff"}


def systemd_running(exists=os.path.isdir):
    """sd_booted(): systemd is the init system when this folder exists."""
    return exists("/run/systemd/system")


def power_command(action_id, which=shutil.which, systemd=None):
    """How to suspend, reboot or power off here, or None when nothing installed can."""
    verb = POWER_VERBS[action_id]
    if (systemd_running() if systemd is None else systemd) and which("systemctl"):
        return ["systemctl", verb]
    return None


def lock_command(configured="", env=None, which=shutil.which):
    """A user-configured command wins; otherwise the first locker that is installed."""
    env = os.environ if env is None else env
    if configured and configured.strip():
        try:
            parts = shlex.split(configured)
            if parts:
                return parts
        except ValueError:
            pass
    candidates = [["swaylock", "-f", "-c", "000000"], ["loginctl", "lock-session"]]
    return next((cmd for cmd in candidates if which(cmd[0])), None)


def command_for(action_id, settings=None, env=None, which=shutil.which, systemd=None):
    """The command for a system action, or None when this system has nothing that does it (or it is not a command)."""
    settings = settings or {}
    if action_id == "lock":  # TVWCS's own lock screen when chosen (lockscreen.py), else the usual locker
        return lockscreen.command(settings, env, which) or lock_command(settings.get("lock_command", ""), env, which)
    if action_id == "logout":
        return logout_command(env, which)
    if action_id in POWER_VERBS:
        return power_command(action_id, which, systemd)
    return None


def unavailable_message(action_id):
    if action_id == "lock":
        return "No screen locker was found. Install swaylock, or set " '"lock_command" in ~/.config/tvwcs/config.json.'
    return "Nothing on this system can do that: TVWCS needs systemd (systemctl) for sleep, reboot and shut down."
