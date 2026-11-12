"""Hiding the mouse pointer in TV mode. No GTK dependency.

In TV mode (a TVWCS session) sway hides the pointer after 3 seconds without moving (`seat * hide_cursor`) and shows it
again as soon as it moves; in desktop mode TVWCS leaves it alone. sway also takes the pointer's focus away while it is
hidden, so whatever it rested on stops showing hover. TVWCS's own windows also stop showing hover then
(widgets.PointerWatch)."""

from __future__ import annotations
import subprocess

DEFAULT_SECONDS = 3


def hide_enabled(settings=None, env=None):
    """On in TV mode only."""
    from tvwcs.model import tv_mode

    return tv_mode(env)


def hide_seconds(settings=None):
    return DEFAULT_SECONDS


def hide_ms(settings):
    """The hiding time in ms, or None when the pointer is never hidden."""
    return hide_seconds(settings) * 1000 if hide_enabled(settings) else None


def sway_command(enabled, seconds):
    return f"seat * hide_cursor {seconds*1000 if enabled else 0}"


class CursorHider:
    """Tells sway to hide the pointer, or not, as the mode says."""

    def __init__(self, run=subprocess.run):
        self.run = run
        self.applied = None

    def apply(self, settings, env=None):
        on, seconds = hide_enabled(settings, env), hide_seconds(settings)
        if (on, seconds) == self.applied:
            return ""
        self.applied = (on, seconds)
        try:
            self.run(["swaymsg", sway_command(on, seconds)], capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        return ""
