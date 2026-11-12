"""Power and sleep: turning the screen off, locking and sleeping after a time without input. No GTK dependency.

The times are TVWCS options ("idle" in config.json), set on the Settings app's Power and sleep page. sway has no idle
manager of its own, so TVWCS runs `swayidle` with them; swayidle calls `tvwcs idle <action>` back when a time is
reached. Nothing happens then while sound is playing (a film with no one touching the remote), or while an application
holds an idle inhibitor (systemd-inhibit --what=idle; swayidle itself also honours Wayland's idle inhibitors).

Also read, to show what the system does on its own: logind's idle action and lid switch handling."""

from __future__ import annotations
import os, shutil, subprocess
from dataclasses import dataclass, field

from tvwcs.settings.cmd import have, run
from tvwcs.system import servermode

ACTIONS = ("screen_off", "lock", "sleep")
LABELS = {"screen_off": "Turn off the screen after", "lock": "Lock after", "sleep": "Sleep after"}
CHOICES = (0, 60, 120, 300, 600, 900, 1200, 1800, 2700, 3600, 7200)  # seconds; 0 is Never


def duration_text(seconds):
    if not seconds:
        return "Never"
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    if minutes < 60 or minutes % 60:
        return f"{minutes} minute{'s' if minutes!=1 else ''}"
    hours = minutes // 60
    return f"{hours} hour{'s' if hours!=1 else ''}"


def clean_idle(raw):
    """The "idle" option: {"screen_off": seconds or 0 (Never), "lock": ..., "sleep": ...}. Unknown values become Never
    (so does the "Let the system decide" of TVWCS before 5.0, None: sway never turns the screen off by itself)."""
    out = {a: 0 for a in ACTIONS}
    if isinstance(raw, dict):
        for a in ACTIONS:
            v = raw.get(a)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 86400:
                out[a] = v
    return out


def due(settings, idle_seconds, done):
    """The actions whose time has come and that have not run in this idle period, in the order they should run."""
    order = sorted((a for a in ACTIONS if settings.get(a)), key=lambda a: (settings[a], ACTIONS.index(a)))
    return [a for a in order if idle_seconds >= settings[a] and a not in done]


# ---------------------------------------------------------------------- battery
# A computer with a battery has a second set of times for when it runs on the battery ("idle_battery"), and an action
# for when the battery is nearly empty ("battery_critical"). A desktop has neither, and the page does not show them.
CRITICAL_ACTIONS = {"nothing": "Nothing", "sleep": "Sleep", "shutdown": "Shut down"}
CRITICAL_PERCENTS = (2, 3, 5, 7, 10, 15)
POWER_SUPPLY = "/sys/class/power_supply"


def clean_critical(raw):
    """The "battery_critical" option: {"action": a CRITICAL_ACTIONS key, "percent": 1-50}. Shut down at 5% unless set."""
    out = {"action": "shutdown", "percent": 5}
    if isinstance(raw, dict):
        if raw.get("action") in CRITICAL_ACTIONS:
            out["action"] = raw["action"]
        p = raw.get("percent")
        if isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= 50:
            out["percent"] = p
    return out


@dataclass
class Battery:
    present: bool = False  # the computer runs on a battery of its own (not a mouse's or a phone's)
    percent: int = 100
    on_battery: bool = False  # not plugged in
    charging: bool = False  # plugged in and charging (plugged in and not charging: full, or held below full)


def read_battery(root=None):
    """The computer's batteries in /sys/class/power_supply (a mouse's or headset's, scope "Device", are left out) and
    whether the charger is plugged in. Several batteries count as one."""

    def value(path, name):
        try:
            with open(os.path.join(path, name), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    try:
        entries = sorted(os.scandir(root or POWER_SUPPLY), key=lambda e: e.name)
    except OSError:
        return Battery()
    now = full = 0
    percents = []
    discharging = charging = False
    mains = None
    for e in entries:
        kind = value(e.path, "type")
        if kind == "Mains" or (kind.startswith("USB") and value(e.path, "online")):
            if value(e.path, "online") == "1":
                mains = True
            elif mains is None:
                mains = False
            continue
        if kind != "Battery" or value(e.path, "scope") == "Device" or value(e.path, "present") == "0":
            continue
        status = value(e.path, "status")
        if status == "Discharging":
            discharging = True
        elif status == "Charging":
            charging = True
        for a, b in (("energy_now", "energy_full"), ("charge_now", "charge_full")):
            n, f = value(e.path, a), value(e.path, b)
            if n.isdigit() and f.isdigit() and int(f) > 0:
                now += int(n)
                full += int(f)
                break
        else:
            c = value(e.path, "capacity")
            if c.isdigit():
                percents.append(int(c))
    if not full and not percents:
        return Battery()
    percent = round(100 * now / full) if full else round(sum(percents) / len(percents))
    on_battery = discharging or mains is False
    return Battery(True, max(0, min(100, percent)), on_battery, charging and not on_battery)


def battery_time(root=None):
    """(seconds, "empty" | "full"): how long until the battery runs out (on battery) or is charged, from the kernel's own
    estimate or from the rate it drains or charges at. Seconds is None when it cannot be told yet (no battery, a full
    one, or no rate reported)."""

    def value(path, name):
        try:
            with open(os.path.join(path, name), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def number(path, name):
        v = value(path, name)
        return int(v) if v.lstrip("-").isdigit() else None

    try:
        entries = sorted(os.scandir(root or POWER_SUPPLY), key=lambda e: e.name)
    except OSError:
        return None, ""
    now = full = rate = 0
    told = 0
    direction = ""
    for e in entries:
        if value(e.path, "type") != "Battery" or value(e.path, "scope") == "Device" or value(e.path, "present") == "0":
            continue
        status = value(e.path, "status")
        if status == "Discharging":
            direction = "empty"
        elif status == "Charging" and direction != "empty":
            direction = "full"
        t = number(e.path, "time_to_empty_now" if status == "Discharging" else "time_to_full_now")
        if t:
            told += t
        for n, f, r in (("energy_now", "energy_full", "power_now"), ("charge_now", "charge_full", "current_now")):
            a, b, c = number(e.path, n), number(e.path, f), number(e.path, r)
            if a is not None and b:
                now += a
                full += b
                rate += abs(c or 0)
                break
    if not direction:
        return None, ""
    if told:
        return told, direction
    if rate <= 0:
        return None, direction
    left = now if direction == "empty" else max(0, full - now)
    return round(left * 3600 / rate), direction


def time_text(seconds):
    """3 h 20 min, 45 min, 1 min."""
    minutes = max(1, round(seconds / 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h and m else f"{h} h" if h else f"{m} min"


def active_idle(settings, battery, server=None):
    """The times in use now: the battery's while the computer runs on it, else the plugged-in ones. In server mode
    (servermode.py) the computer never sleeps from here."""
    times = settings["idle_battery"] if battery.present and battery.on_battery else settings["idle"]
    if servermode.active() if server is None else server:
        times = {**times, "sleep": 0}
    return times


def critical(settings, battery, server=None):
    """The action to take now because the battery is nearly empty ("" for none; always none in server mode)."""
    c = settings["battery_critical"]
    if servermode.active() if server is None else server:
        return ""
    if not (battery.present and battery.on_battery) or c["action"] == "nothing":
        return ""
    return c["action"] if battery.percent <= c["percent"] else ""


# ---------------------------------------------------------------------- what the system does by itself
@dataclass
class Logind:
    available: bool = False
    idle_action: str = "ignore"
    idle_seconds: int = 0
    lid: str = ""


def parse_logind(props):
    """`busctl get-property` answers ({name: 's "suspend"' / 't 1800000000'}) -> Logind."""

    def value(name):
        raw = props.get(name, "").split(" ", 1)
        return raw[1].strip().strip('"') if len(raw) == 2 else ""

    usec = value("IdleActionUSec")
    return Logind(
        bool(props),
        value("IdleAction") or "ignore",
        int(usec) // 1_000_000 if usec.isdigit() else 0,
        value("HandleLidSwitch"),
    )


def read_logind():
    if not have("busctl"):
        return Logind()
    props = {}
    for name in ("IdleAction", "IdleActionUSec", "HandleLidSwitch"):
        r = run(
            [
                "busctl",
                "--system",
                "get-property",
                "org.freedesktop.login1",
                "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager",
                name,
            ],
            timeout=5,
        )
        if r.ok:
            props[name] = r.out.strip()
    state = parse_logind(props)
    if not has_lid():
        state.lid = ""  # logind has a lid setting everywhere; only show it where there is a lid
    return state


LID_PATHS = ("/proc/acpi/button/lid", "/sys/bus/acpi/devices")


def has_lid(paths=LID_PATHS):
    """Whether the computer has a lid switch: an ACPI lid button (LID0, or the PNP0C0D device). A desktop has none."""
    proc, acpi = paths
    try:
        if any(os.scandir(proc)):
            return True
    except OSError:
        pass
    try:
        return any(e.name.startswith("PNP0C0D") for e in os.scandir(acpi))
    except OSError:
        return False


# ---------------------------------------------------------------------- what keeps it awake
def parse_playing(text):
    """`pactl list sink-inputs`: True when a stream is playing (not corked)."""
    return any(line.strip() == "Corked: no" for line in text.splitlines())


def sound_playing():
    if not have("pactl"):
        return False
    r = run(["pactl", "list", "sink-inputs"], timeout=5)
    return r.ok and parse_playing(r.out)


def parse_inhibitors(text):
    """`systemd-inhibit --list --no-legend` (WHO UID USER PID COMM WHAT WHY MODE): who blocks idle, by name."""
    who = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 7 and "idle" in parts[5].split(":") and parts[-1] == "block":
            who.append(parts[0])
    return who


def idle_blocked():
    if not have("systemd-inhibit"):
        return []
    r = run(["systemd-inhibit", "--list", "--no-legend", "--no-pager"], timeout=5)
    return parse_inhibitors(r.out) if r.ok else []


def keep_awake():
    """Why nothing should happen now ("" when something may): sound playing, or an idle inhibitor."""
    if sound_playing():
        return "sound is playing"
    who = idle_blocked()
    return f"{who[0]} is keeping the computer awake" if who else ""


# ---------------------------------------------------------------------- acting
def screen_off(env=None):
    return run(["swaymsg", "output * power off"], timeout=5)


def screen_on(env=None):
    return run(["swaymsg", "output * power on"], timeout=5)


# ---------------------------------------------------------------------- swayidle
def swayidle_argv(settings, launcher):
    """swayidle with one timeout per action; each calls `tvwcs idle <action>` back, which checks sound and inhibitors."""
    argv = ["swayidle", "-w"]
    for a in ACTIONS:
        if settings.get(a):
            argv += ["timeout", str(settings[a]), f"'{launcher}' idle {a}"]
            if a == "screen_off":
                argv += ["resume", f"'{launcher}' idle resume"]
    return argv if len(argv) > 2 else None


class SwayIdle:
    """The swayidle process TVWCS runs; restarted when the times change."""

    def __init__(self):
        self.proc = None
        self.argv = None

    def apply(self, settings, launcher):
        argv = swayidle_argv(settings, launcher)
        if argv == self.argv and self.proc is not None and self.proc.poll() is None:
            return ""
        self.stop()
        self.argv = argv
        if argv is None:
            return ""
        if not shutil.which("swayidle"):
            return "swayidle is not installed, so the Power and sleep times cannot be used."
        try:
            self.proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return f"Could not start swayidle: {exc}"
        return ""

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


@dataclass
class PowerState:
    """What the Power and sleep page shows."""

    settings: dict = field(default_factory=dict)
    logind: Logind = field(default_factory=Logind)
    idle_works: bool = True  # swayidle is installed
    locker: bool = True  # swaylock is installed
    can_sleep: bool = True
    battery: Battery = field(default_factory=Battery)
    battery_settings: dict = field(default_factory=dict)
    critical: dict = field(default_factory=dict)


def read_state(settings, lock_ok, sleep_ok):
    return PowerState(
        clean_idle(settings.get("idle")),
        read_logind(),
        bool(shutil.which("swayidle")),
        lock_ok,
        sleep_ok,
        read_battery(),
        clean_idle(settings.get("idle_battery")),
        clean_critical(settings.get("battery_critical")),
    )
