"""TV mode's extras: the sway bar is hidden (the Quick Menu shows the time and status instead), and the Quick Menu
stays on screen while no application is open. No GTK dependency.

The bar is hidden with `bar mode invisible`, which lasts until sway reloads its config, so it is applied again now and
then. The modes the bars had first are kept in a file, so the bars come back as they were when TV mode or the option is
turned off, or TVWCS stops, even after TVWCS was restarted in between."""

from __future__ import annotations
import json, os
from pathlib import Path

HIDDEN = "invisible"
LAUNCH_GRACE = (
    45  # seconds after a launch during which an empty screen is not yet "nothing open": the app may be starting
)


def _load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, modes):
    path = Path(path)
    try:
        if not modes:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(modes), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def hide_bars(wm, saved_path):
    """Hide every bar that is showing, remembering the mode it had. Returns the number of bars changed."""
    saved = _load(saved_path)
    changed = 0
    for bar_id, mode in wm.bar_modes().items():
        if mode == HIDDEN:
            continue
        saved.setdefault(
            bar_id, mode
        )  # after a reload the bar is back in its config's mode: that is still the one to restore
        if wm.set_bar_mode(bar_id, HIDDEN):
            changed += 1
    _save(saved_path, saved)
    return changed


def restore_bars(wm, saved_path):
    """Put back the modes the bars had before TVWCS hid them (nothing when it never did)."""
    saved = _load(saved_path)
    if not saved:
        return 0
    current = wm.bar_modes()
    n = 0
    for bar_id, mode in saved.items():
        if bar_id in current and current[bar_id] != mode and wm.set_bar_mode(bar_id, mode):
            n += 1
    _save(saved_path, {})
    return n


def should_show_menu(keep_open, visible, has_windows, now, grace_until):
    """The Quick Menu comes back when TV mode keeps it open, it is hidden, no application is open and nothing was just launched."""
    return keep_open and not visible and not has_windows and now >= grace_until


def should_step_aside(keep_open, active, has_windows, busy):
    """The kept-open Quick Menu hides when a window opened behind it and took the focus (not while a popover or dialog
    of TVWCS's own has it)."""
    return keep_open and has_windows and not active and not busy
