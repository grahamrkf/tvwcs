"""Where a running TVWCS keeps its per-session files, and what identifies one login. No GTK dependency.

systemd-logind and elogind give every login a private XDG_RUNTIME_DIR that is emptied at logout. A system with
neither may leave it unset; TVWCS then uses ~/.cache/tvwcs, which is private to the user but survives logouts and
reboots. So "once per login" cannot rely on a file disappearing: the marker records which login it was written in."""

from __future__ import annotations
import os
from pathlib import Path

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")  # Linux: changes at every boot, with or without systemd


def runtime_dir(env=None) -> Path:
    """XDG_RUNTIME_DIR, else ~/.cache/tvwcs (XDG_CACHE_HOME). install.sh uses the same rule for the PID file."""
    env = os.environ if env is None else env
    if env.get("XDG_RUNTIME_DIR"):
        return Path(env["XDG_RUNTIME_DIR"])
    return Path(env.get("XDG_CACHE_HOME") or Path(env.get("HOME") or Path.home()) / ".cache") / "tvwcs"


def session_key(env=None, boot_id=BOOT_ID) -> str:
    """Text that differs between logins: this boot, and the window manager's IPC socket (its path holds the window
    manager's process id, and the file is created anew each time it starts)."""
    env = os.environ if env is None else env
    parts = []
    try:
        parts.append(Path(boot_id).read_text().strip())
    except OSError:
        pass
    sock = env.get("SWAYSOCK")
    if sock:
        parts.append(sock)
        try:
            parts.append(str(os.stat(sock).st_mtime_ns))
        except OSError:
            pass
    else:
        parts.append(env.get("WAYLAND_DISPLAY", ""))
    return "|".join(parts)


def first_time_this_login(marker, env=None, boot_id=BOOT_ID) -> bool:
    """True once per login: the first call records this login in `marker`, later calls in the same login find it."""
    key = session_key(env, boot_id)
    marker = Path(marker)
    try:
        if marker.read_text(encoding="utf-8") == key:
            return False
    except OSError:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(key, encoding="utf-8")
    except OSError:
        pass
    return True


def is_tvwcs_process(pid, proc=Path("/proc")) -> bool:
    """Whether `pid` is alive and is TVWCS. A PID file that outlived a reboot (no systemd to clean the runtime
    folder) may name an unrelated process that got the same number."""
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    try:
        return b"tvwcs" in (Path(proc) / str(int(pid)) / "cmdline").read_bytes()
    except OSError:
        return True  # no /proc to ask: trust the signal check
