"""Switching to the app used last (the "Last app" hotkeys, `tvwcs last-app`), like a TV remote's Previous channel
button. No GTK dependency.

sway does not keep a history of which window had the focus, so TVWCS follows its window events (`swaymsg -t subscribe`)
and remembers the order application windows were focused in (`FocusHistory`). TVWCS's own windows (the Quick Menu,
its dialogs, the volume indicator) are left out, so the app the Quick Menu shows over stays the one in use. Windows
focused before TVWCS started (after an update restarts it) come from sway's tree, whose `focus` lists say which child
of each container had the focus last (`tree_order`).

Pressing the key again goes back, so it flips between two apps."""
from __future__ import annotations
import json, shutil, subprocess, threading
from tvwcs.model import is_tvwcs_title

OWN_APP_IDS=("com.tvwcs.TVWCS","com.tvwcs.Osd")   # the launcher (Quick Menu and its dialogs) and the volume indicator
KEEP=50   # windows remembered

def _is_app(container) -> bool:
    """An application window, not one of TVWCS's own."""
    if not isinstance(container,dict) or container.get("id") is None: return False
    if container.get("app_id") in OWN_APP_IDS: return False
    name=container.get("name") or ((container.get("window_properties") or {}).get("title")) or ""
    return not is_tvwcs_title(name)

def parse_event(line):
    """A line of `swaymsg -t subscribe -m '["window"]'` -> ("focus", con_id), ("close", con_id) or None."""
    try: event=json.loads(line)
    except ValueError: return None
    if not isinstance(event,dict): return None
    change=event.get("change"); container=event.get("container")
    if change=="close" and isinstance(container,dict) and container.get("id") is not None: return ("close",int(container["id"]))
    if change=="focus" and _is_app(container): return ("focus",int(container["id"]))
    return None

class FocusHistory:
    """Application windows, the one focused last first. Thread-safe: the follower thread writes, the main loop reads."""
    def __init__(self):
        self._ids=[]; self._lock=threading.Lock()
    def focused(self, con_id):
        with self._lock:
            con_id=int(con_id)
            if con_id in self._ids: self._ids.remove(con_id)
            self._ids.insert(0,con_id); del self._ids[KEEP:]
    def closed(self, con_id):
        with self._lock:
            if int(con_id) in self._ids: self._ids.remove(int(con_id))
    def event(self, parsed):
        if parsed is None: return
        (self.focused if parsed[0]=="focus" else self.closed)(parsed[1])
    def ids(self):
        with self._lock: return list(self._ids)

def tree_order(tree):
    """con_ids of every window in sway's tree, the one focused most recently first, following each container's `focus`
    list. Exact within a workspace; across workspaces it is the order the workspaces were last visited."""
    found=[]
    def walk(node):
        if not isinstance(node,dict): return
        children=list(node.get("nodes") or [])+list(node.get("floating_nodes") or [])
        if not children:
            if node.get("type") in ("con","floating_con") and (node.get("window") is not None or node.get("app_id")) and node.get("id") is not None:
                found.append(int(node["id"]))
            return
        rank={cid:i for i,cid in enumerate(node.get("focus") or [])}
        for child in sorted(children,key=lambda c:rank.get(c.get("id"),len(rank))): walk(child)
    walk(tree)
    return found

def pick(history, windows, current, order=()):
    """The window to switch to: the open application window focused most recently that is not `current` (the con_id of
    the app in use; None when none is), else None. `windows`: WindowManager.windows() (open app windows); `history`:
    FocusHistory.ids(); `order`: tree_order(), for windows focused before TVWCS was following."""
    open_ids={int(w["con_id"]):w for w in windows}
    for con_id in list(history)+[i for i in order if i not in history]:
        if con_id in open_ids and con_id!=current: return open_ids[con_id]
    return None

class FocusFollower:
    """Follows sway's window events into a FocusHistory, on a thread of its own (run by the launcher). It starts
    `swaymsg -t subscribe` again if it ends (sway restarted)."""
    RETRY=5   # seconds before following again
    def __init__(self, history, popen=subprocess.Popen, which=shutil.which):
        self.history=history; self.popen=popen; self.binary=which("swaymsg")
        self.proc=None; self.thread=None; self.stopping=threading.Event()
    def start(self):
        if not self.binary or (self.thread is not None and self.thread.is_alive()): return
        self.stopping.clear(); self.thread=threading.Thread(target=self._follow,daemon=True); self.thread.start()
    def stop(self):
        self.stopping.set(); proc=self.proc
        if proc is not None:
            try: proc.terminate()
            except OSError: pass
    def _follow(self):
        while not self.stopping.is_set():
            try: self.proc=self.popen([self.binary,"-t","subscribe","-m",'["window"]'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,text=True)
            except OSError: self.stopping.wait(self.RETRY*6); continue
            try:
                for line in self.proc.stdout:
                    if self.stopping.is_set(): break
                    try: self.history.event(parse_event(line))
                    except Exception: pass   # following must never take the launcher down
            finally:
                try: self.proc.terminate(); self.proc.wait(timeout=2)
                except (OSError,subprocess.SubprocessError): pass
                self.proc=None
            self.stopping.wait(self.RETRY)
