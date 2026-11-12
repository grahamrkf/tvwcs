"""Displays for Settings: resolution, refresh rate, scale and arrangement, through swaymsg. No GTK dependency.

Scale makes text and controls bigger: sway scales each display by itself, by any amount (`output X scale 1.5`).

The arrangement is kept as "this display is right of / left of / above / below / the same as that one", so changing
one display's resolution moves its neighbours with it instead of leaving a gap or an overlap. What Settings
applies is saved to ~/.config/tvwcs/displays.json, and TVWCS applies it again when it starts with the same displays
connected (sway forgets runtime changes at log-out)."""

from __future__ import annotations
import copy, json, math, os, re
from dataclasses import dataclass, field
from pathlib import Path

from tvwcs.control_cmd import run
from tvwcs.model import CONFIG_HOME

SAVED = CONFIG_HOME / "tvwcs" / "displays.json"
SCALES = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)  # Settings' row of scale buttons: 75 % to 200 % in 25 % steps
MIN_SCALED_HEIGHT = 540  # a scale is offered while the display still shows at least this many (logical) pixels high
RELATIONS = ("right", "left", "below", "above", "mirror")
RELATION_TEXT = {
    "right": "Right of {}",
    "left": "Left of {}",
    "below": "Below {}",
    "above": "Above {}",
    "mirror": "Same picture as {}",
}


@dataclass
class Mode:
    width: int
    height: int
    interlaced: bool = False
    rates: list = field(default_factory=list)  # Hz, highest first
    preferred: bool = False

    @property
    def key(self):
        return (self.width, self.height, self.interlaced)


@dataclass
class Output:
    name: str  # the connector: HDMI-A-1
    label: str = ""  # the display's own name when known (DELL U2720Q)
    enabled: bool = False
    x: int = 0
    y: int = 0
    width: int = 0  # the mode in use, in pixels, before rotation and scaling
    height: int = 0
    interlaced: bool = False
    rate: float = 0.0
    rotated: bool = False  # turned a quarter (portrait): width and height swap on the desktop
    scale: float = 1.0  # how much bigger things look: sway's output scale
    modes: list = field(default_factory=list)

    @property
    def title(self):
        return self.label or self.name

    @property
    def size(self):
        """How much of the desktop it covers (sway rounds a scaled size down)."""
        w, h = (self.height, self.width) if self.rotated else (self.width, self.height)
        z = 1 / (self.scale or 1)
        return (math.floor(w * z + 1e-6), math.floor(h * z + 1e-6))

    def mode(self, key=None):
        key = key or (self.width, self.height, self.interlaced)
        return next((m for m in self.modes if m.key == key), None)

    def preferred_mode(self):
        return next((m for m in self.modes if m.preferred), self.modes[0] if self.modes else None)


@dataclass
class DisplayState:
    available: bool
    message: str = ""
    outputs: list = field(default_factory=list)  # connected displays only


# ---------------------------------------------------------------------- reading
def rate_text(rate):
    """60.0 -> '60 Hz', 59.94 -> '59.94 Hz'."""
    return f"{rate:.2f}".rstrip("0").rstrip(".") + " Hz"


def mode_text(mode):
    return f"{mode.width} × {mode.height}" + (" (interlaced)" if mode.interlaced else "")


def _add_rate(mode, rate):
    if not any(abs(r - rate) < 0.005 for r in mode.rates):
        mode.rates.append(rate)


def _sort(modes):
    for m in modes:
        m.rates.sort(reverse=True)
    modes.sort(key=lambda m: (m.width * m.height, m.width, not m.interlaced), reverse=True)
    return modes


def parse_sway(text):
    """`swaymsg -t get_outputs -r` (JSON) -> the outputs. sway gives refresh rates in mHz."""
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return []
    outputs = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        label = " ".join(x for x in (d.get("make"), d.get("model")) if x and x != "Unknown").strip()
        o = Output(
            name=d["name"],
            label=label,
            enabled=bool(d.get("active")),
            rotated=str(d.get("transform", "normal")).replace("flipped-", "") in ("90", "270"),
            scale=float(d.get("scale") or 1) if d.get("active") else 1.0,
        )
        rect = d.get("rect") or {}
        o.x, o.y = int(rect.get("x", 0)), int(rect.get("y", 0))
        cm = d.get("current_mode") or {}
        if cm:
            o.width, o.height, o.rate = (
                int(cm.get("width", 0)),
                int(cm.get("height", 0)),
                round(int(cm.get("refresh", 0)) / 1000, 3),
            )
        for mode in d.get("modes") or []:
            w, h = int(mode.get("width", 0)), int(mode.get("height", 0))
            rate = round(int(mode.get("refresh", 0)) / 1000, 3)
            m = next((x for x in o.modes if x.key == (w, h, False)), None)
            if m is None:
                m = Mode(w, h)
                o.modes.append(m)
            _add_rate(m, rate)
        pm = d.get("preferred_mode") or {}  # not in every sway version; else the largest mode counts as preferred
        _sort(o.modes)
        best = next(
            (m for m in o.modes if (m.width, m.height) == (pm.get("width"), pm.get("height"))),
            o.modes[0] if o.modes else None,
        )
        if best is not None:
            best.preferred = True
        outputs.append(o)
    return outputs


def read_state(env=None):
    env = os.environ if env is None else env
    if not env.get("SWAYSOCK"):
        return DisplayState(False, "Display settings work in sway.")
    r = run(["swaymsg", "-t", "get_outputs", "-r"], timeout=10)
    if not r.ok:
        return DisplayState(False, f"Could not read the displays: {r.message}")
    outputs = parse_sway(r.out)
    if not outputs:
        return DisplayState(False, "No display was found.")
    return DisplayState(True, "", outputs)


# ---------------------------------------------------------------------- scale
def scale_text(s):
    """1.5 -> '150 %'."""
    return f"{round(s*100)} %"


def scale_choices(outputs, current=None):
    """The scales to offer for a display: those that still leave it at least MIN_SCALED_HEIGHT pixels high, and the one
    in use."""
    heights = [(o.width if o.rotated else o.height) for o in outputs if o.enabled and o.width]
    out = [s for s in SCALES if s == 1 or all(h / s >= MIN_SCALED_HEIGHT for h in heights)]
    if current and not any(abs(current - s) < 0.005 for s in out):
        out = sorted(out + [current])
    return out


# ---------------------------------------------------------------------- arranging
def _rect(o):
    w, h = o.size
    return (o.x, o.y, o.x + w, o.y + h)


def _overlap(a, b):
    ax, ay, ar, ab = a
    bx, by, br, bb = b
    return ax < br and bx < ar and ay < bb and by < ab


def reference(outputs):
    """The display the others are arranged around: the first that is on."""
    return next((o for o in outputs if o.enabled), None)


def relation(o, anchor):
    """Where o is, seen from anchor: one of RELATIONS."""
    ox, oy, orr, ob = _rect(o)
    ax, ay, ar, ab = _rect(anchor)
    if (ox, oy) == (ax, ay):
        return "mirror"
    if ox >= ar:
        return "right"
    if orr <= ax:
        return "left"
    if oy >= ab:
        return "below"
    if ob <= ay:
        return "above"
    dx = (ox + orr) - (ax + ar)
    dy = (oy + ob) - (ay + ab)  # overlapping: the way it leans
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "below" if dy > 0 else "above"


def placements(outputs):
    """{name: (relation, anchor name)} for every display that is on, except the reference. Each display is anchored
    to the nearest one already placed, nearest to the reference first, so a row A B C reads "B right of A, C right of B".
    """
    ref = reference(outputs)
    if ref is None:
        return {}
    rx, ry, rr, rb = _rect(ref)
    centre = lambda o: ((_rect(o)[0] + _rect(o)[2]) / 2, (_rect(o)[1] + _rect(o)[3]) / 2)
    rc = ((rx + rr) / 2, (ry + rb) / 2)
    dist = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1])
    others = sorted((o for o in outputs if o.enabled and o is not ref), key=lambda o: dist(centre(o), rc))
    placed = [ref]
    out = {}
    for o in others:
        anchor = min(placed, key=lambda p: (_gap(o, p), -_shared(o, p), dist(centre(o), centre(p))))
        out[o.name] = (relation(o, anchor), anchor.name)
        placed.append(o)
    return out


def _gap(a, b):
    ax, ay, ar, ab = _rect(a)
    bx, by, br, bb = _rect(b)
    return max(bx - ar, ax - br, 0) + max(by - ab, ay - bb, 0)


def _shared(a, b):
    """How long an edge two displays share (0 when they only touch at a corner, or not at all)."""
    ax, ay, ar, ab = _rect(a)
    bx, by, br, bb = _rect(b)
    return max(0, min(ar, br) - max(ax, bx)) + max(0, min(ab, bb) - max(ay, by))


def arrange(outputs, where):
    """Set every display's position from where = {name: (relation, anchor name)}: each is put against its anchor (top
    or left edges lined up), past any display already in that spot, and the whole desktop then starts at 0,0."""
    by_name = {o.name: o for o in outputs}
    ref = reference(outputs)
    if ref is None:
        return outputs
    ref.x = ref.y = 0
    done = {ref.name}
    todo = [o for o in outputs if o.enabled and o is not ref]

    def anchor_of(o):  # an anchor that is off, missing or the display itself: the reference instead
        rel, a = where.get(o.name, ("right", ref.name))
        return rel, (a if a in by_name and by_name[a].enabled and a != o.name else ref.name)

    while todo:
        ready = [o for o in todo if anchor_of(o)[1] in done]
        o = ready[0] if ready else todo[0]  # a loop: arranged around the reference
        rel, a = anchor_of(o)
        _place(o, rel, by_name[a] if a in done else ref, [by_name[n] for n in done])
        done.add(o.name)
        todo.remove(o)
    on = [o for o in outputs if o.enabled]
    mx = min(o.x for o in on)
    my = min(o.y for o in on)
    for o in on:
        o.x -= mx
        o.y -= my
    return outputs


def _place(o, rel, anchor, placed):
    w, h = o.size
    aw, ah = anchor.size
    if rel == "mirror":
        o.x, o.y = anchor.x, anchor.y
        return
    o.x, o.y = {
        "right": (anchor.x + aw, anchor.y),
        "left": (anchor.x - w, anchor.y),
        "below": (anchor.x, anchor.y + ah),
        "above": (anchor.x, anchor.y - h),
    }.get(rel, (anchor.x + aw, anchor.y))
    for _ in range(len(placed) + 1):
        hit = next((p for p in placed if p is not o and _overlap(_rect(o), _rect(p))), None)
        if hit is None:
            return
        hx, hy, hr, hb = _rect(hit)
        if rel == "right":
            o.x = hr
        elif rel == "left":
            o.x = hx - w
        elif rel == "below":
            o.y = hb
        else:
            o.y = hy - h


def choices(outputs, o):
    """[(key, text)] for where o can go: "relation:anchor" against every other display that is on."""
    out = []
    for a in outputs:
        if a is o or not a.enabled:
            continue
        out += [(f"{rel}:{a.name}", RELATION_TEXT[rel].format(a.title)) for rel in RELATIONS]
    return out


def best_rate(mode, wanted):
    """The rate to use for mode: wanted when it has it, else its highest."""
    near = [r for r in mode.rates if abs(r - wanted) < 0.02]
    return near[0] if near else (mode.rates[0] if mode.rates else 0.0)


# ---------------------------------------------------------------------- changing
def edited(outputs, name, **changes):
    """A copy of outputs with changes to one display (enabled, mode=(w,h,interlaced), rate, scale, place=(rel, anchor)),
    arranged again so the others stay against it."""
    new = copy.deepcopy(outputs)
    where = placements(new)
    o = next(x for x in new if x.name == name)
    if "mode" in changes:
        m = o.mode(changes["mode"])
        if m is not None:
            o.width, o.height, o.interlaced = m.width, m.height, m.interlaced
            o.rate = best_rate(m, changes.get("rate", o.rate))
    elif "rate" in changes:
        o.rate = changes["rate"]
    if "scale" in changes:
        o.scale = float(changes["scale"])
    if "enabled" in changes:
        o.enabled = changes["enabled"]
        if o.enabled:
            ref = reference(new)
            if not o.width:
                m = o.preferred_mode()
                if m is not None:
                    o.width, o.height, o.interlaced, o.rate = (
                        m.width,
                        m.height,
                        m.interlaced,
                        m.rates[0] if m.rates else 0,
                    )
            on = [x for x in new if x.enabled and x is not o]
            if on and o.name not in where:
                where[o.name] = ("right", max(on, key=lambda x: x.x + x.size[0]).name)
        else:
            for k, (rel, anchor) in list(where.items()):  # whatever leaned on it now leans on what it leaned on
                if anchor == name:
                    where[k] = where.get(name, (rel, (reference(new) or o).name))
            where.pop(name, None)
    if "place" in changes:
        rel, anchor = changes["place"]
        where[name] = (rel, anchor)
        if anchor in where and where[anchor][1] == name:
            where.pop(anchor)  # it was anchored to this one: no loop
        ref = reference(new)
        if ref is not None and ref.name == name:  # moving the reference: keep it fixed, move the rest around it instead
            where.pop(name)
            where[anchor] = ({"right": "left", "left": "right", "below": "above", "above": "below"}.get(rel, rel), name)
    return arrange(new, where)


def sway_command(outputs):
    parts = []
    for o in outputs:
        q = '"' + o.name.replace('"', "") + '"'
        if not o.enabled:
            parts.append(f"output {q} disable")
            continue
        parts.append(
            f"output {q} enable mode {o.width}x{o.height}@{o.rate:.3f}Hz scale {o.scale:g} position {o.x} {o.y}"
        )
    return "; ".join(parts)


def apply(state, outputs):
    """Use these settings now. "" when it worked, else why not."""
    if not any(o.enabled for o in outputs):
        return "At least one display has to stay on."
    r = run(["swaymsg", sway_command(outputs)], timeout=20)
    if not r.ok:
        return r.message or "The displays did not accept the change."
    if '"success": false' in r.out.replace("\n", ""):
        return "sway did not accept the change."
    return ""


# ---------------------------------------------------------------------- keeping it
# displays.json keeps its settings under "sway" ({"sway": {"outputs": …}}). Before 5.0 there was also an "xrandr" entry
# for i3, which names the same connectors differently (HDMI-1 / HDMI-A-1); its modes are used once when sway has none.
# A file from before 3.0.1 ({"backend": …, "outputs": …}) is read as the entry for its backend.
def _entries(saved):
    if not isinstance(saved, dict):
        return {}
    if "backend" in saved and "outputs" in saved:
        return {str(saved["backend"]): {"outputs": saved["outputs"]}}
    return {k: v for k, v in saved.items() if k in ("xrandr", "sway") and isinstance(v, dict)}


def to_saved(outputs, saved=None):
    entries = _entries(saved)
    entries.pop("xrandr", None)
    entries["sway"] = {
        "outputs": {
            o.name: {
                "enabled": o.enabled,
                "x": o.x,
                "y": o.y,
                "width": o.width,
                "height": o.height,
                "interlaced": o.interlaced,
                "rate": o.rate,
                "scale": o.scale,
            }
            for o in outputs
        }
    }
    return entries


def save(outputs, path=SAVED):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = None
    tmp.write_text(json.dumps(to_saved(outputs, saved), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def connector_key(name):
    """A connector name the same under X (before 5.0) and sway: X's HDMI-1 is sway's HDMI-A-1 (DRM's HDMI type A)."""
    return re.sub(r"^HDMI-A-", "HDMI-", str(name))


def _matching(state, want):
    """`want` (name -> settings) keyed by the names connected now, or None when they are other displays."""
    names = {o.name for o in state.outputs}
    if set(want) == names:
        return want
    by_key = {connector_key(k): v for k, v in want.items()}
    if len(by_key) == len(want) and set(by_key) == {connector_key(n) for n in names}:
        return {n: by_key[connector_key(n)] for n in names}
    if len(want) == 1 and len(names) == 1:
        return {next(iter(names)): next(iter(want.values()))}  # one display either way
    return None


def from_saved(state, saved):
    """The saved settings applied to what is connected now, or None when they were saved for other displays. Without
    a sway entry, the modes kept under i3 before 5.0 are used (not their scale: X11 scaled the whole session)."""
    entries = _entries(saved)
    want = None
    same = False
    for b in ("sway", "xrandr"):
        if b in entries and entries[b].get("outputs"):
            want = _matching(state, entries[b].get("outputs") or {})
            same = b == "sway"
            break
    if not want:
        return None
    new = copy.deepcopy(state.outputs)
    for o in new:
        s = want[o.name]
        o.enabled = bool(s.get("enabled"))
        o.x, o.y = int(s.get("x", 0)), int(s.get("y", 0))
        m = o.mode((int(s.get("width", 0)), int(s.get("height", 0)), bool(s.get("interlaced"))))
        if o.enabled and m is None:
            return None  # that mode is gone (another display on the same connector)
        if m is not None:
            o.width, o.height, o.interlaced, o.rate = (
                m.width,
                m.height,
                m.interlaced,
                best_rate(m, float(s.get("rate", 0))),
            )
        if same and "scale" in s:
            try:
                o.scale = float(s["scale"]) or 1.0
            except (TypeError, ValueError):
                pass
    return new if any(o.enabled for o in new) else None


def restore(path=SAVED):
    """Apply the saved settings if they were saved for the displays connected now (TVWCS calls this as it starts)."""
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    state = read_state()
    if not state.available:
        return state.message
    new = from_saved(state, saved)
    if new is None:
        return ""
    look = lambda outs: [(o.enabled, o.x, o.y, o.width, o.height, o.rate, o.scale) for o in outs]
    if look(new) == look(state.outputs):
        return ""
    return apply(state, new)
