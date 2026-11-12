"""Settings > Date and time: time zone and clock format. Back end: settings/date_time.py (timedatectl)."""

from __future__ import annotations
import time
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from tvwcs.settings import date_time as timedate
from tvwcs.system import privilege, servermode
from tvwcs.core.model import ConfigStore
from tvwcs.settings.app import StreamedRun
from tvwcs.settings.pages.base import Page, SERVER_HIDDEN, _on_off, tell_tvwcs


# ====================================================================== Date and time
class DateTimePage(Page):
    """The time zone, the clock set from the network, and the Quick Menu's 12/24-hour clock."""

    key = "datetime"
    title = "Date and time"
    icon = "preferences-system-time-symbolic"
    fallback = "🕓"
    poll = 20

    def read(self):
        return timedate.read_state(), ConfigStore().settings["clock_24h"]

    def summary(self):
        return timedate.zone_label(self.state[0].timezone) if self.state else ""

    def draw(self, state):
        s, hours24 = state
        now = time.time()
        self.section("NOW")
        self.row(
            "Time",
            timedate.clock_text(now, hours24),
            None,
            detail=timedate.date_text(now),
            icon="preferences-system-time-symbolic",
            fallback="🕓",
            ident="dt:now",
        )
        self.section("TIME ZONE")
        admin = not servermode.active()  # server mode: shown, not changed here
        self.row("Time zone", timedate.zone_label(s.timezone), self.choose_zone if admin else None, ident="dt:zone")
        self.note(
            "The time zone is set for the whole computer. It may ask for your password." if admin else SERVER_HIDDEN
        )
        self.section("NETWORK TIME")
        if s.timedatectl:
            self.row(
                "Set the time from the network",
                _on_off(s.ntp),
                self.switch_ntp if admin else None,
                detail=(
                    ("Synchronized" if s.synced else "Not synchronized yet")
                    if s.ntp
                    else (
                        "Turn it on to keep the clock right by itself"
                        if s.can_ntp
                        else "No network time service is installed (such as systemd-timesyncd or chrony)"
                    )
                ),
                ident="dt:ntp",
                value_css="state-on" if s.ntp else "setting-value",
            )
        else:
            self.row(
                "Set the time from the network", "Unknown", None, detail="Needs systemd's timedatectl", ident="dt:ntp"
            )
        self.section("QUICK MENU CLOCK")
        self.row("Clock", "24-hour (14:05)" if hours24 else "12-hour (2:05 PM)", self.choose_clock, ident="dt:clock")
        self.note("How the time at the bottom of the Quick Menu is written.")

    def as_root_if_needed(self, argv, label, status, after=None):
        """timedatectl as the user first (polkit may allow it), then as root when polkit wants a password.
        after() runs when it worked."""
        self.set_status(status)
        lines = []

        def finish(code, tail):
            self.set_status("")
            if code:
                self.win.notice("Date and time", ("\n".join(lines[-6:]) or tail or f"{label} did not work.").strip())
            elif after:
                after()
            self.refresh(quiet=True)

        def first(code, tail):
            if code and (argv[0] != "timedatectl" or privilege.polkit_refused(tail)):
                self.win.run_as_root(argv, label, lines.append, finish)
            else:
                finish(code, tail)

        if argv[0] == "timedatectl":
            StreamedRun(argv, lambda _l: None, first)
        else:
            self.win.run_as_root(argv, label, lines.append, finish)

    def switch_ntp(self):
        s = self.state[0]
        if not s.ntp and not s.can_ntp:
            self.win.notice(
                "Network time",
                "Install a network time service first, such as systemd-timesyncd (or chrony), with your package manager.",
            )
            return
        self.focus_after = "dt:ntp"
        self.as_root_if_needed(
            timedate.ntp_argv(not s.ntp), "Network time", "Turning network time " + ("off…" if s.ntp else "on…")
        )

    def choose_zone(self):
        s = self.state[0]
        zones = timedate.zone_choices(s.zones)
        if not zones:
            self.win.notice("Time zone", "No time zones were found on this computer (/usr/share/zoneinfo is empty).")
            return

        def picked(zone):
            if zone == s.timezone or not timedate.valid_zone(zone, s.zones):
                return
            self.as_root_if_needed(
                timedate.timezone_argv(zone, s.timedatectl),
                "Time zone",
                f"Setting the time zone to {timedate.zone_label(zone)}…",
            )

        self.win.choose_option("Time zone", zones, s.timezone if s.timezone in dict(zones) else None, picked)

    def choose_clock(self):
        def picked(key):
            store = ConfigStore()
            store.settings["clock_24h"] = key == "24"
            store.save()
            tell_tvwcs("reload")
            self.refresh(quiet=True)

        self.win.choose_option(
            "Quick Menu clock",
            [("12", "12-hour (2:05 PM)"), ("24", "24-hour (14:05)")],
            "24" if self.state[1] else "12",
            picked,
        )
