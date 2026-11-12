"""Small sway IPC adapter (swaymsg): monitor targeting, workspaces, per-profile workspace launch modes."""

from __future__ import annotations
import json, shutil, subprocess
from tvwcs.core.model import LAUNCH_NEW_WORKSPACE, LAUNCH_PLAIN, is_tvwcs_title

TVWCS_CRITERIA = '[title="^TVWCS$"]'
_BAR_CLASSES = {
    "i3bar",
    "swaybar",
    "waybar",
    "polybar",
    "tint2",
    "xfce4panel",
    "matepanel",
    "gnomepanel",
    "plasmashell",
    "latte",
    "cairodock",
    "plank",
    "cairo dock",
    "eww",
}


def _norm(s):
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


def _quote(name):
    return str(name).replace("\\", "\\\\").replace('"', '\\"')


def _internal(name):
    return (name or "").startswith("__i3")


def _all_ok(out):
    if not out:
        return False
    try:
        return all(item.get("success", False) for item in json.loads(out))
    except (ValueError, TypeError, AttributeError):
        return False


class WindowManager:
    def __init__(self, env=None):
        self.binary = shutil.which("swaymsg")

    @property
    def available(self):
        return bool(self.binary)

    def _call(self, *args, timeout=2):
        if not self.binary:
            return None
        try:
            p = subprocess.run([self.binary, *args], capture_output=True, text=True, timeout=timeout, check=False)
            return p.stdout if p.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _json(self, *args):
        raw = self._call(*args)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    def _tree(self):
        return self._json("-t", "get_tree")

    # ------------------------------------------------------------ windows
    def _all_windows(self):
        tree = self._tree()
        if not tree:
            return []
        found = []

        def walk(node, output="", workspace="", workspace_visible=False):
            if node.get("type") == "output":
                output = node.get("name", output)
            if node.get("type") == "workspace":
                workspace = node.get("name", workspace)
                workspace_visible = bool(node.get("visible", False))
            wid = node.get("window")
            props = node.get("window_properties") or {}
            cls = props.get("class") or node.get("app_id") or ""
            inst = props.get("instance") or ""
            title = node.get("name") or props.get("title") or cls or inst  # untitled windows stay listed
            # A native Wayland window under sway has an app_id and no X window id.
            is_window = wid is not None or (node.get("type") in ("con", "floating_con") and bool(node.get("app_id")))
            if is_window and node.get("id") is not None and title:
                ncls = _norm(cls)
                ntitle = _norm(title)
                window_type = (props.get("window_type") or node.get("window_type") or "").casefold()
                # Bars/docks are infrastructure; TVWCS's own windows are not applications. They are matched by their
                # exact title (see model.is_tvwcs_title), never by a prefix a document name could share.
                is_bar = ncls in _BAR_CLASSES or "i3bar" in ntitle or "swaybar" in ntitle or window_type == "dock"
                if not is_bar and not is_tvwcs_title(title):
                    found.append(
                        {
                            "con_id": node["id"],
                            "window": wid,
                            "title": title,
                            "class": cls,
                            "instance": inst,
                            "workspace": workspace,
                            "output": output,
                            "workspace_visible": workspace_visible,
                            "focused": bool(node.get("focused", False)),
                            "urgent": bool(node.get("urgent", False)),
                            "fullscreen": bool(node.get("fullscreen_mode", 0)),
                        }
                    )
            for child in node.get("nodes", []):
                walk(child, output, workspace, workspace_visible)
            for child in node.get("floating_nodes", []):
                walk(child, output, workspace, workspace_visible)

        walk(tree)
        return list({str(w["con_id"]): w for w in found}.values())

    def focused_rect(self):
        """The screen rectangle of the focused window ({x, y, width, height}), or None."""
        tree = self._tree()

        def walk(node):
            if node.get("focused") and (node.get("window") is not None or node.get("app_id")):
                return node.get("rect")
            for child in node.get("nodes", []) + node.get("floating_nodes", []):
                found = walk(child)
                if found:
                    return found
            return None

        rect = walk(tree) if tree else None
        return rect if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0 else None

    def windows(self):
        """Open windows, each marked with whether its workspace is currently on screen (`workspace_visible`)."""
        wins = self._all_windows()
        shown = {w.get("name") for w in self.workspaces() if w.get("visible")}
        for w in wins:
            w["workspace_visible"] = w["workspace"] in shown
        return wins

    # ------------------------------------------------------------ outputs and workspaces
    def workspaces(self):
        data = self._json("-t", "get_workspaces")
        return [w for w in data if not _internal(w.get("name"))] if isinstance(data, list) else []

    def outputs(self):
        data = self._json("-t", "get_outputs")
        return [o for o in data if o.get("active") and o.get("name") != "xroot-0"] if isinstance(data, list) else []

    def current_workspace(self):
        return next((w for w in self.workspaces() if w.get("focused")), None)

    def usable_area(self, focus=True):
        """Rectangle of the workspace on the monitor under the pointer. sway already excludes the bar."""
        if not self.binary:
            return None
        if focus:
            self.focus_output_under_mouse()
        ws = self.current_workspace()
        rect = (ws or {}).get("rect")
        if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
            return {k: int(rect[k]) for k in ("x", "y", "width", "height")}
        return None

    def focus_output_under_mouse(self):
        """The output to show things on: sway's focus follows the mouse, so it is the focused one."""
        if not self.binary:
            return None
        ws = self.current_workspace()
        if ws and ws.get("output"):
            return ws["output"]
        return next((o.get("name") for o in self.outputs() if o.get("focused")), None)

    # ------------------------------------------------------------ the TVWCS window itself
    def move_tvwcs_to_current_workspace(self):
        if self.binary:
            self.focus_output_under_mouse()
            self._call(TVWCS_CRITERIA, "move", "container", "to", "workspace", "current")

    def place_tvwcs(self, x, y, width, height):
        """Float the TVWCS window with no border at an exact rectangle, and show it: tvwcs.conf maps it invisible, so it
        does not first flash in the middle of the screen."""
        if not self.binary:
            return False
        return bool(
            self._call(
                f"{TVWCS_CRITERIA} floating enable, border pixel 0, resize set {int(width)} {int(height)}, move absolute position {int(x)} {int(y)}, opacity 1"
            )
        )

    # ------------------------------------------------------------ launching and focusing
    def new_workspace_number(self):
        used = set()
        for ws in self.workspaces():
            if isinstance(ws.get("num"), int) and ws["num"] >= 0:
                used.add(ws["num"])
        n = 1
        while n in used:
            n += 1
        return n

    def prepare_for_launch(self, mode):
        """Target the pointer's monitor. In new-workspace mode, switch to a fresh empty workspace so
        the app opens alone there and every other app stays on its own workspace, out of sight."""
        if not self.binary:
            return None
        self.focus_output_under_mouse()
        if mode == LAUNCH_NEW_WORKSPACE:
            n = self.new_workspace_number()
            self._call(f"workspace number {n}")
            return str(n)
        return None

    def focus(self, con_id, mode):
        """Bring one window up. LAUNCH_NEW_WORKSPACE: it ends up alone on a workspace of its own (a window already
        alone is just shown, one that shares a workspace is split off to a new one). LAUNCH_SAME: it is tiled
        into the current workspace. LAUNCH_PLAIN: it is focused where it is, as sway would."""
        if not self.binary:
            return False
        con_id = int(con_id)
        if mode == LAUNCH_PLAIN:
            return _all_ok(self._call(f"[con_id={con_id}] focus"))
        target = self.focus_output_under_mouse()
        windows = self._all_windows()
        win = next((w for w in windows if int(w["con_id"]) == con_id), None)
        if win is None:
            return False
        parked = _internal(win.get("workspace"))  # left in the scratchpad by an older TVWCS
        moved = False
        if mode == LAUNCH_NEW_WORKSPACE:
            neighbours = sum(1 for w in windows if w["workspace"] == win["workspace"])
            if parked or neighbours > 1:
                n = self.new_workspace_number()
                self._call(f"[con_id={con_id}] move container to workspace number {n}")
                moved = True
        else:
            self._call(f"[con_id={con_id}] move container to workspace current")  # tile with the current workspace
        ok = _all_ok(self._call(f"[con_id={con_id}] focus"))
        if (
            ok
            and mode == LAUNCH_NEW_WORKSPACE
            and not moved
            and not parked
            and target
            and win.get("output")
            and win["output"] != target
        ):
            self._call(f"move workspace to output {target}")  # bring its workspace to the pointer's monitor
        return ok

    def focus_workspace(self, name):
        """Show a whole workspace on the pointer's monitor."""
        if not self.binary:
            return False
        target = self.focus_output_under_mouse()
        ws = next((w for w in self.workspaces() if w.get("name") == name), None)
        ok = bool(self._call(f'workspace "{_quote(name)}"'))
        if ok and ws and target and ws.get("output") and ws["output"] != target:
            self._call(f"move workspace to output {target}")
        return ok

    def move_workspace_to_output(self, name, output):
        """Send a whole workspace, and everything on it, to another monitor."""
        if not self.binary or output not in {o["name"] for o in self.outputs()}:
            return False
        return bool(self._call(f'workspace "{_quote(name)}"')) and bool(
            self._call(f"move workspace to output {output}")
        )

    def close_workspace(self, name):
        """Close every window on a workspace."""
        ids = [w["con_id"] for w in self._all_windows() if w["workspace"] == name]
        return bool(ids) and all(_all_ok(self._call(f"[con_id={int(i)}] kill")) for i in ids)

    def fullscreen_windows(self):
        """con_ids of the windows that are fullscreen now."""
        return {int(w["con_id"]) for w in self._all_windows() if w.get("fullscreen")}

    def leave_fullscreen(self):
        """Take the current workspace's fullscreen window out of fullscreen, so TVWCS can show over it: sway keeps a
        fullscreen window above every other window on its workspace. restore_fullscreen puts it back."""
        if not self.binary:
            return
        current = (self.current_workspace() or {}).get("name")
        for w in self._all_windows():
            if w.get("fullscreen") and w["workspace"] == current:
                self._call(f"[con_id={int(w['con_id'])}] fullscreen disable")

    def restore_fullscreen(self, con_ids, skip_current=False):
        """Put windows that were fullscreen back into fullscreen (leave_fullscreen took it away while TVWCS showed).
        On the current workspace only the focused window
        is restored, so a fullscreen window never covers the app just chosen; with `skip_current` (an app was just
        launched and may not have mapped yet) none is."""
        if not self.binary or not con_ids:
            return
        current = (self.current_workspace() or {}).get("name")
        for w in self._all_windows():
            if int(w["con_id"]) not in con_ids or w.get("fullscreen"):
                continue
            if w["workspace"] == current and (skip_current or not w.get("focused")):
                continue
            self._call(f"[con_id={int(w['con_id'])}] fullscreen enable")

    def reload(self):
        return bool(self._call("reload"))

    def has_windows(self):
        """True when any application window is open, on any workspace (TVWCS's own windows and bars do not count)."""
        return bool(self._all_windows())

    def screen_has_windows(self):
        """True when an application window is on a workspace that is on screen now (on any monitor). An app open on a
        workspace out of sight does not count: the screen shows nothing but the background."""
        return any(w.get("workspace_visible") for w in self.windows())

    def tvwcs_on_screen(self):
        """Whether TVWCS's main window is on a workspace that is on screen: False when it was left behind on a workspace
        that is out of sight (an app opened in a new workspace while it showed), None when that cannot be told."""
        tree = self._tree()
        if not tree:
            return None
        shown = {w.get("name") for w in self.workspaces() if w.get("visible")}

        def walk(node, workspace=""):
            if node.get("type") == "workspace":
                workspace = node.get("name", "")
            if node.get("name") == "TVWCS" and (node.get("window") is not None or node.get("app_id")):
                return workspace in shown
            for child in node.get("nodes", []) + node.get("floating_nodes", []):
                found = walk(child, workspace)
                if found is not None:
                    return found
            return None

        return walk(tree)

    def urgent_ids(self):
        """con_ids of the windows asking for attention (an app that was started again often only flags its open window)."""
        return {int(w["con_id"]) for w in self._all_windows() if w.get("urgent")}

    # ------------------------------------------------------------ bars
    def bar_modes(self):
        """{bar id: mode} of the bars in the sway config ("dock", "hide", "invisible" or "overlay")."""
        ids = self._json("-t", "get_bar_config")
        modes = {}
        for bar_id in ids if isinstance(ids, list) else []:
            cfg = self._json("-t", "get_bar_config", str(bar_id))
            if isinstance(cfg, dict) and cfg.get("mode"):
                modes[str(bar_id)] = cfg["mode"]
        return modes

    def set_bar_mode(self, bar_id, mode):
        return _all_ok(self._call("bar", bar_id, "mode", mode))

    def close_window(self, con_id):
        if not self.binary:
            return False
        return _all_ok(self._call(f"[con_id={int(con_id)}] kill"))

    def find_matching(self, profile, app):
        """An open window that looks like it belongs to `profile`'s application, or None."""
        needles = {
            _norm(profile.name),
            _norm(app.name if app else ""),
            _norm(profile.desktop_id.split(".")[0]),
            _norm(profile.desktop_id.rsplit(".", 1)[0]),
            _norm(getattr(app, "wm_class", None) or ""),
        }
        needles.discard("")
        for w in self.windows():
            cls = _norm(w.get("class", ""))
            inst = _norm(w.get("instance", ""))
            title = _norm(w.get("title", ""))
            if any(n in {cls, inst} for n in needles) or any(n in title for n in needles if len(n) > 4):
                return w
        return None

    def focus_matching(self, profile, app, mode):
        w = self.find_matching(profile, app)
        return bool(w) and self.focus(w["con_id"], mode)
