"""What the launcher keeps an eye on while it runs: idle times (swayidle), the pointer, the volume, the TV remote
over HDMI-CEC and the Quick Menu's status icons. Each watcher belongs to the running TVWCSApp (main.py)."""

from __future__ import annotations
import sys, threading, time
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib

from tvwcs.system import cursor, power, quick_status, sway_include, tv_mode
from tvwcs.settings import sound
from tvwcs.system.session import runtime_dir

# from tvwcs.main import sway_include.launcher(), runtime_dir()


BAR_MODES_FILE = (
    runtime_dir() / "tvwcs-bar-modes.json"
)  # the modes the bars had before TV mode hid them (see tv_mode.py)


class IdleWatcher:
    """The Power and sleep times (Settings > Power and sleep): after so long without input, turn the screen off, lock,
    sleep. TVWCS runs swayidle with them, which calls `tvwcs idle …` back. Nothing happens while sound plays or an
    application keeps the computer awake (see power.py)."""

    BATTERY_TICK = 20  # seconds between looks at the battery

    def __init__(self, app):
        self.app = app
        self.swayidle = power.SwayIdle()
        self.battery = power.read_battery()
        self.battery_source = 0
        self.critical_done = False

    def times(self):
        return power.active_idle(self.app.store.settings, self.battery)

    def apply(self):
        if self.battery.present and not self.battery_source:
            self.battery_source = GLib.timeout_add_seconds(self.BATTERY_TICK, self._battery_tick)
        problem = self.swayidle.apply(self.times(), sway_include.launcher())
        if problem:
            print(problem, file=sys.stderr)

    def _battery_tick(self):
        """Plugging in or unplugging switches between the two sets of times; a nearly empty battery does what
        Settings > Power and sleep says (once, until the charger is plugged in)."""
        before = self.battery.on_battery
        self.battery = power.read_battery()
        if self.battery.on_battery != before:
            self.apply()
        if not self.battery.on_battery:
            self.critical_done = False
        action = power.critical(self.app.store.settings, self.battery)
        if action and not self.critical_done:
            self.critical_done = True
            print(f"The battery is at {self.battery.percent}%: {action}.", file=sys.stderr)
            self.app.run_system_action(action)
        return GLib.SOURCE_CONTINUE

    def stop(self):
        self.swayidle.stop()


class CursorWatcher:
    """Hides the mouse pointer in TV mode (cursor.py)."""

    def __init__(self, app):
        self.app = app
        self.hider = cursor.CursorHider()

    def apply(self):
        problem = self.hider.apply(self.app.store.settings)
        if problem:
            print(problem, file=sys.stderr)

    def stop(self):
        pass


class VolumeWatcher:
    """Keeps every output at or under the volume limit (100 %, or 150 % with Settings > Sound > Allow
    over-amplification), whatever raised it (sound.VolumeGuard)."""

    def __init__(self, app):
        self.guard = sound.VolumeGuard(lambda: app.store.settings.get("audio_boost"))

    def apply(self):
        self.guard.start()

    def stop(self):
        self.guard.stop()


class CecWatcher:
    """The TV's remote over HDMI-CEC (cec.py), when this computer has a CEC port and it is on in Settings."""

    def __init__(self, app):
        self.app = app
        self.service = None

    def apply(self):
        from tvwcs.system import cec

        options = self.app.store.settings["cec"]
        if not options["enabled"] or not cec.present():
            if self.service is not None:
                self.service.stop(release=True)
                self.service = None
            return
        if self.service is not None:
            self.service.update(options)
            return
        self.service = cec.CecService(runtime_dir(), self._hotkey, self._tv_off)
        if not self.service.start(options):
            self.service = None

    def _hotkey(self, action):
        if action == "menu":
            self.app.show_mode("toggle")
        elif action == "last":
            self.app.switch_to_last_app()

    def _tv_off(self):
        print("TVWCS: the TV turned off; sleeping (Settings > Remote and hotkeys)", file=sys.stderr)
        self.app.run_system_action("sleep")

    def stop(self):
        if self.service is not None:
            self.service.stop()
            self.service = None


class StatusWatcher:
    """Keeps the bottom of the Quick Menu current (the clock, and the network, volume, Bluetooth and updates icons) and
    does TV mode's housekeeping: the bar stays hidden, and the Quick Menu comes back once no application is open.
    Everything that runs a command runs on a worker thread."""

    TICK = 2  # seconds between looks
    READ_EVERY = 4  # seconds between reads of the status while the Quick Menu is on screen
    BAR_EVERY = 4  # seconds between checks that the bar is still hidden (a sway reload shows it again)
    UPDATES_EVERY = 3 * 3600  # seconds between update checks (the package lists, Flathub)

    def __init__(self, app):
        self.app = app
        self.source = 0
        self.reading = False
        self.last_read = 0.0
        self.last_bar = 0.0
        self.updates = 0
        self.reboot = False
        self.updates_due = time.monotonic() + 90
        self.checking_updates = False
        self.bar_hidden = False
        self.kept_open = False
        self.had_windows = False

    def start(self):
        if not self.source:
            self.source = GLib.timeout_add_seconds(self.TICK, self._tick)
        self.apply_bar()
        self.read_now()

    def stop(self):
        if self.source:
            GLib.source_remove(self.source)
            self.source = 0
        if self.bar_hidden:
            tv_mode.restore_bars(self.app.wm, BAR_MODES_FILE)
            self.bar_hidden = False

    def _tick(self):
        app = self.app
        w = app.window
        now = time.monotonic()
        if w is None:
            return GLib.SOURCE_CONTINUE
        visible = w.is_visible()
        if visible:
            w.tick_clock()
            if now - self.last_read >= self.READ_EVERY:
                self.read_now()
        if app.tv:
            # "No application open" means nothing on screen: an app left on a workspace out of sight (Settings closed
            # over it, say) still leaves an empty screen to come back to
            has_windows = app.wm.screen_has_windows()
            if visible and self.had_windows and not has_windows and not w._modal_groups:
                w.focus_pane_soon(
                    "search"
                )  # the last app on screen closed (from the ⋯ menu, say): back to the search field
            self.had_windows = has_windows
            if not visible:
                self.kept_open = False
                if has_windows:
                    app.grace_until = 0.0  # an app is open: whatever was launched has arrived
                elif (
                    tv_mode.should_show_menu(True, visible, has_windows, now, app.grace_until) and not app.has_dialogs()
                ):
                    app.show_mode("toggle")
            elif not has_windows:
                self.kept_open = True
            elif self.kept_open and tv_mode.should_step_aside(
                True, w.is_active(), has_windows, w._popovers > 0 or app.has_dialogs()
            ):
                # kept open over an empty screen, and a window opened from elsewhere (Settings from a shell, an app
                # started by a hotkey) took the focus: it would be hidden under the floating menu
                self.kept_open = False
                app.hide_window(launched=True)
        if now - self.last_bar >= self.BAR_EVERY:
            self.apply_bar()
        if now >= self.updates_due and not self.checking_updates:
            self._check_updates()
        return GLib.SOURCE_CONTINUE

    def read_now(self):
        if self.reading:
            return
        self.reading = True
        self.last_read = time.monotonic()
        updates = self.updates
        reboot = self.reboot

        def work():
            try:
                status = quick_status.read(updates, reboot)
            except Exception:
                status = None  # a status icon must never break the menu
            GLib.idle_add(lambda: (self._got(status), GLib.SOURCE_REMOVE)[1])

        threading.Thread(target=work, daemon=True).start()

    def _got(self, status):
        self.reading = False
        if status is None or status == self.app.status:
            return
        self.app.status = status
        if self.app.window is not None:
            self.app.window.show_status(status)

    def _check_updates(self):
        self.checking_updates = True

        def work():
            n, reboot = quick_status.check_updates()
            GLib.idle_add(lambda: (self._got_updates(n, reboot), GLib.SOURCE_REMOVE)[1])

        threading.Thread(target=work, daemon=True).start()

    def _got_updates(self, n, reboot=False):
        self.checking_updates = False
        self.updates = n
        self.reboot = reboot
        self.updates_due = time.monotonic() + self.UPDATES_EVERY
        self.read_now()

    def updates_changed(self):
        """Updates were installed or checked in Settings: count them again soon."""
        self.updates_due = min(self.updates_due, time.monotonic() + 5)

    def apply_bar(self):
        """Hide the bar in TV mode, or give back one hidden before (desktop mode never changes it)."""
        self.last_bar = time.monotonic()
        app = self.app
        if not app.wm.available:
            return
        hide = app.tv
        if not hide and not self.bar_hidden and not BAR_MODES_FILE.exists():
            return

        def work():
            if hide:
                tv_mode.hide_bars(app.wm, BAR_MODES_FILE)
            else:
                tv_mode.restore_bars(app.wm, BAR_MODES_FILE)

        self.bar_hidden = hide
        threading.Thread(target=work, daemon=True).start()
