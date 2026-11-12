"""Settings > Power and sleep: idle times, lid and power button, battery. Back end: system/power.py."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from tvwcs.system import power
from tvwcs.core.model import ConfigStore, tv_mode
from tvwcs.system.system_actions import command_for
from tvwcs.settings.pages.base import Page, tell_tvwcs


# ====================================================================== Power and sleep
class PowerPage(Page):
    """After how long without input the screen turns off, the computer locks and it sleeps (swayidle, see power.py),
    and what the system does by itself: logind's idle action and the lid."""

    key = "power"
    title = "Power and sleep"
    icon = "system-shutdown-symbolic"
    fallback = "⏻"
    sway_only = True
    server_off = True

    def read(self):
        store = ConfigStore()
        st = store.settings
        return power.read_state(st, command_for("lock", st) is not None, command_for("sleep", st) is not None)

    def draw(self, s):
        if s.battery.present:
            b = s.battery
            self.section("BATTERY")
            self.row(
                "Battery",
                f"{b.percent}%",
                None,
                detail="Running on the battery" if b.on_battery else "Plugged in",
                icon="battery-symbolic",
                fallback="🔋",
                ident="bat:now",
            )
            c = s.critical
            self.row(
                "When the battery is nearly empty",
                power.CRITICAL_ACTIONS[c["action"]],
                self.choose_critical,
                icon="battery-caution-symbolic",
                fallback="🪫",
                ident="bat:action",
                detail="" if c["action"] == "nothing" else f"At {c['percent']}% or less, while not plugged in",
            )
            if c["action"] != "nothing":
                self.row(
                    "Nearly empty means",
                    f"{c['percent']}%",
                    self.choose_critical_percent,
                    ident="bat:percent",
                    indent=44,
                )
            self.idle_rows(s, s.settings, "idle", "WHEN NOTHING IS TOUCHED, PLUGGED IN")
            self.idle_rows(s, s.battery_settings, "idle_battery", "WHEN NOTHING IS TOUCHED, ON BATTERY")
        else:
            self.idle_rows(s, s.settings, "idle", "WHEN NOTHING IS TOUCHED")
        self.note(
            "Times count from the last key, remote button or mouse movement. Nothing happens while sound is playing, "
            "or while an application keeps the computer awake."
        )
        if not s.idle_works and any(s.settings[a] or s.battery_settings[a] for a in power.ACTIONS):
            self.note("These times need swayidle. Install it, then sign out and in again.", "error")
        self.section("LOCKING")
        self.note(
            "In a TVWCS session the computer locks with swaylock, in TVWCS's theme: type your password and press Enter. "
            "In another session, Lock uses that desktop's own screen locker."
            if tv_mode()
            else "This is not a TVWCS session, so Lock uses this desktop's own screen locker, such as swaylock."
        )
        l = s.logind
        if l.available:
            self.section("WHAT THE SYSTEM DOES BY ITSELF")
            action = {
                "ignore": "Nothing",
                "suspend": "Sleep",
                "hibernate": "Hibernate",
                "hybrid-sleep": "Hybrid sleep",
                "suspend-then-hibernate": "Sleep, then hibernate",
                "poweroff": "Shut down",
                "lock": "Lock",
            }.get(l.idle_action, l.idle_action)
            self.row(
                "The system's idle action",
                action
                + (
                    f" after {power.duration_text(l.idle_seconds)}"
                    if l.idle_action != "ignore" and l.idle_seconds
                    else ""
                ),
                None,
                detail="logind's IdleAction, set in /etc/systemd/logind.conf",
                ident="sys:logind",
            )
            if l.lid:
                self.row(
                    "Closing the lid",
                    {
                        "suspend": "Sleep",
                        "ignore": "Nothing",
                        "poweroff": "Shut down",
                        "lock": "Lock",
                        "hibernate": "Hibernate",
                    }.get(l.lid, l.lid),
                    None,
                    detail="logind's HandleLidSwitch",
                    ident="sys:lid",
                )
            self.note("logind's settings are changed in /etc/systemd/logind.conf, as root.")

    def idle_rows(self, s, times, option, heading):
        """The three times of one set: "idle" (plugged in, or a computer without a battery) or "idle_battery"."""
        self.section(heading)
        tag = "" if option == "idle" else "bat"
        self.row(
            power.LABELS["screen_off"],
            power.duration_text(times["screen_off"]),
            lambda: self.choose("screen_off", times["screen_off"], option=option),
            icon="video-display-symbolic",
            fallback="🖵",
            ident=f"idle{tag}:screen_off",
        )
        self.row(
            power.LABELS["lock"],
            power.duration_text(times["lock"]),
            lambda: self.choose("lock", times["lock"], option=option),
            detail="" if s.locker else "swaylock is not installed",
            icon="system-lock-screen-symbolic",
            fallback="🔒",
            ident=f"idle{tag}:lock",
        )
        self.row(
            power.LABELS["sleep"],
            power.duration_text(times["sleep"]),
            lambda: self.choose("sleep", times["sleep"], option=option),
            detail="" if s.can_sleep else "Nothing on this computer can make it sleep",
            icon="weather-clear-night-symbolic",
            fallback="☾",
            ident=f"idle{tag}:sleep",
        )

    def choose_critical(self):
        def picked(key):
            store = ConfigStore()
            store.settings["battery_critical"]["action"] = key
            store.save()
            tell_tvwcs("reload")
            self.refresh(quiet=True)

        self.win.choose_option(
            "When the battery is nearly empty",
            list(power.CRITICAL_ACTIONS.items()),
            self.state.critical["action"],
            picked,
        )

    def choose_critical_percent(self):
        def picked(key):
            store = ConfigStore()
            store.settings["battery_critical"]["percent"] = int(key)
            store.save()
            tell_tvwcs("reload")
            self.refresh(quiet=True)

        self.win.choose_option(
            "Nearly empty means",
            [(str(p), f"{p}%") for p in power.CRITICAL_PERCENTS],
            str(self.state.critical["percent"]),
            picked,
        )

    def choose(self, action, current, option="idle"):
        options = [(str(v), power.duration_text(v)) for v in power.CHOICES]

        def picked(key):
            value = int(key)
            store = ConfigStore()
            store.settings[option][action] = value
            store.save()
            tell_tvwcs("reload")
            if (
                action in ("lock", "sleep")
                and value
                and not (self.state.locker if action == "lock" else self.state.can_sleep)
            ):
                self.win.notice(
                    power.LABELS[action].replace(" after", ""),
                    "Saved, but this computer has nothing to do that with yet.",
                )
            self.refresh(quiet=True)

        self.win.choose_option(power.LABELS[action], options, str(current), picked)
