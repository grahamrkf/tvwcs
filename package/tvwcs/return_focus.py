"""Closing Settings goes back to the application that was in use before it opened. No GTK dependency.

TVWCS knows best what that was: Settings is usually opened from the Quick Menu (shown over the app), a status icon or
a hotkey, and in TV mode TVWCS switches to an empty workspace before Settings starts. So TVWCS writes down the window
just before it starts or shows Settings (`note`), and Settings reads it when it is opened (`take`). Opened some other
way (a shell, a sway key binding of the user's own), Settings asks sway which window had the focus (`focused_app`).

The record says "nothing" too (con_id None): Settings opened from the Quick Menu over an empty screen in TV mode has
nothing to go back to, and the Quick Menu comes back as before."""
from __future__ import annotations
import json, time
from pathlib import Path
from tvwcs.session import runtime_dir
from tvwcs.window_manager import _all_ok

SETTINGS_APP_ID="com.tvwcs.ControlPanel"
FRESH_SECONDS=60   # a note older than this was not for this opening (Settings failed to start, say)

def record_file(env=None) -> Path: return runtime_dir(env)/"tvwcs-settings-return.json"

def is_settings(window) -> bool:
    return bool(window) and (window.get("class") or "")==SETTINGS_APP_ID

def target_of(window, fullscreen=None):
    """What to go back to for a window dict from WindowManager (None: nothing). `fullscreen`: whether it was full screen,
    when that is known better than the window says (the Quick Menu takes it out of full screen while it shows)."""
    if not window or is_settings(window) or window.get("con_id") is None: return None
    full=bool(window.get("fullscreen")) if fullscreen is None else bool(fullscreen)
    return {"con_id":int(window["con_id"]),"fullscreen":full}

def note(target, path=None, now=None):
    """TVWCS, just before it opens Settings: remember `target` (from target_of; None for nothing)."""
    path=Path(path) if path is not None else record_file()
    data={"con_id":None,"fullscreen":False} if target is None else dict(target)
    data["time"]=time.time() if now is None else now
    try:
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+".tmp")
        tmp.write_text(json.dumps(data),encoding="utf-8"); tmp.replace(path)
    except OSError: pass

MISSING=object()
def take(path=None, now=None, fresh=FRESH_SECONDS):
    """Settings, when it is opened: the target TVWCS noted (a dict, or None for nothing), or MISSING when there is no
    recent note. The note is used up."""
    path=Path(path) if path is not None else record_file()
    try: raw=path.read_text(encoding="utf-8")
    except OSError: return MISSING
    try: path.unlink()
    except OSError: pass
    try: data=json.loads(raw)
    except ValueError: return MISSING
    if not isinstance(data,dict): return MISSING
    age=(time.time() if now is None else now)-float(data.get("time") or 0)
    if not 0<=age<=fresh: return MISSING
    if data.get("con_id") is None: return None
    try: return {"con_id":int(data["con_id"]),"fullscreen":bool(data.get("fullscreen"))}
    except (TypeError,ValueError): return MISSING

def focused_app(wm):
    """The application window sway has focused now (not Settings, not TVWCS), as a target, or None."""
    return target_of(next((w for w in wm.windows() if w.get("focused")),None))

def go_back(wm, target):
    """Focus `target` again (sway shows its workspace), full screen again if it was. False when it has closed since."""
    if not target or not wm.available: return False
    con_id=int(target["con_id"])
    window=next((w for w in wm.windows() if int(w["con_id"])==con_id),None)
    if window is None or is_settings(window): return False
    ok=_all_ok(wm._call(f"[con_id={con_id}] focus"))
    if ok and target.get("fullscreen") and not window.get("fullscreen"): wm._call(f"[con_id={con_id}] fullscreen enable")
    return ok
