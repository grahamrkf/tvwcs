"""Hotkey specs ("F2", "Shift+F2", "Mod4+space", or a lone modifier such as "Mod4") and the sway config they produce.
No GTK dependency.

There are three sets of hotkeys, one per input device: keyboard, remote and gamepad. Each set has a key for the
Quick Menu ("menu") and one that switches to the app used last ("last", see last_app.py); either may be unset ("").
(Before 4.0 there were Applications and Fullscreen keys too: they are dropped.) A gamepad sends no key presses by
itself: map its
buttons to keys with a tool such as AntiMicroX, then capture those keys here. Any launch profile can have a hotkey of
its own too (see model.LaunchProfile.hotkey); it is bound here as `tvwcs launch <profile id>`.

A lone modifier (tapping Super by itself) is bound by its X keycode on release, for example
`bindcode --release 133 ...` for the left Super key. Binding it on press would steal Super from every Super+key
shortcut; on release, Super+Enter and the rest keep working."""
from __future__ import annotations
import re, shlex

DEVICES=("keyboard","remote","gamepad")
ACTIONS=("menu","last")   # what every device's set has
DEVICE_ACTIONS={"keyboard":ACTIONS,"remote":ACTIONS,"gamepad":ACTIONS}
DEVICE_LABELS={"keyboard":"Keyboard","remote":"Remote","gamepad":"Gamepad"}
ACTION_LABELS={"menu":"Quick Menu","last":"Last app","guide":"Applications","fullscreen":"Fullscreen"}
ACTION_COMMANDS={"menu":"toggle","last":"last-app"}   # `tvwcs <command>` each runs
DEFAULT_HOTKEYS={
    "keyboard":{"menu":"Mod4","last":"Mod4+Tab"},   # tap Super for the Quick Menu; Super+Tab for the app used last
    "remote":{"menu":"F2","last":""},
    "gamepad":{"menu":"","last":""},
}
_SAFE_ID=re.compile(r"[A-Za-z0-9_-]+")
MODIFIER_ORDER=("Mod4","Mod1","Control","Shift")
MODIFIER_NAMES={"Mod4":"Super","Mod1":"Alt","Control":"Ctrl","Shift":"Shift"}
# GDK key names of physical modifier keys -> sway modifier names
MODIFIER_KEYS={"Super_L":"Mod4","Super_R":"Mod4","Alt_L":"Mod1","Alt_R":"Mod1","Meta_L":"Mod1","Meta_R":"Mod1",
               "Control_L":"Control","Control_R":"Control","Shift_L":"Shift","Shift_R":"Shift"}
MODIFIER_KEYSYMS={"Mod4":"Super_L","Mod1":"Alt_L","Control":"Control_L","Shift":"Shift_L"}   # the left-hand key of each
DEFAULT_KEYCODES={"Mod4":133,"Mod1":64,"Control":37,"Shift":50}   # their X keycodes on standard (evdev) keyboards

# The multimedia keys of remotes and keyboards (X's XF86 keysyms). GTK 4 names them without their "XF86" prefix
# ("Mail" for XF86Mail), which is how a captured hotkey is stored; sway only knows them with it.
XF86_KEYS=frozenset("""
ModeLock MonBrightnessUp MonBrightnessDown KbdLightOnOff KbdBrightnessUp KbdBrightnessDown Standby AudioLowerVolume
AudioMute AudioRaiseVolume AudioPlay AudioStop AudioPrev AudioNext HomePage Mail Start Search AudioRecord Calculator
Memo ToDoList Calendar PowerDown ContrastAdjust RockerUp RockerDown RockerEnter Back Forward Stop Refresh PowerOff
WakeUp Eject ScreenSaver WWW Sleep Favorites AudioPause AudioMedia MyComputer VendorHome LightBulb Shop History
OpenURL AddFavorite HotLinks BrightnessAdjust Finance Community AudioRewind BackForward Launch0 Launch1 Launch2
Launch3 Launch4 Launch5 Launch6 Launch7 Launch8 Launch9 LaunchA LaunchB LaunchC LaunchD LaunchE LaunchF
ApplicationLeft ApplicationRight Book CD WindowClear Close Copy Cut Display DOS Documents Excel Explorer Game Go
iTouch LogOff Market Meeting MenuKB MenuPB MySites New News OfficeHome Open Option Paste Phone Reply Reload
RotateWindows RotationPB RotationKB Save ScrollUp ScrollDown ScrollClick Send Spell SplitScreen Support TaskPane
Terminal Tools Travel UserPB User1KB User2KB Video WheelButton Word Xfer ZoomIn ZoomOut Away Messenger WebCam
MailForward Pictures Music Battery Bluetooth WLAN UWB AudioForward AudioRepeat AudioRandomPlay Subtitle
AudioCycleTrack CycleAngle FrameBack FrameForward Time SelectButton View TopMenu Red Green Yellow Blue Suspend
Hibernate TouchpadToggle TouchpadOn TouchpadOff AudioMicMute""".split())

def x_keysym(key):
    """A key name as sway (xkb) knows it: "Mail" -> "XF86Mail"; other names unchanged."""
    return f"XF86{key}" if key in XF86_KEYS else key

def parse_spec(spec):
    """-> (modifiers, key) where key is None for a lone modifier; raises ValueError if malformed."""
    parts=[p for p in (spec or "").split("+") if p]
    if not parts: raise ValueError("empty hotkey")
    mods=[p for p in parts if p in MODIFIER_ORDER]
    keys=[p for p in parts if p not in MODIFIER_ORDER]
    if len(keys)>1 or len(set(mods))!=len(mods): raise ValueError("malformed hotkey")
    if keys and not all(c.isalnum() or c=="_" for c in keys[0]): raise ValueError("bad key name")
    if not keys and len(mods)!=1: raise ValueError("a lone modifier hotkey must be a single modifier")
    return mods,(keys[0] if keys else None)

def valid_spec(spec) -> bool:
    try: parse_spec(spec); return True
    except ValueError: return False

def normalize_spec(parts) -> str:
    mods=[m for m in MODIFIER_ORDER if m in parts]
    keys=[p for p in parts if p not in MODIFIER_ORDER]
    return "+".join(mods+keys[:1])

def is_modifier_only(spec) -> bool:
    return parse_spec(spec)[1] is None

def describe(spec) -> str:
    if not spec: return "Not set"
    mods,key=parse_spec(spec)
    names=[MODIFIER_NAMES[m] for m in mods]
    if key is None: return f"{names[0]} (tap)"
    return " + ".join(names+[key.upper() if len(key)==1 else key])

def binding(spec,keycodes=None) -> str:
    """What follows `bindsym`/`bindcode` in sway's config for a hotkey. A lone modifier binds its key's keycode on release.
    `keycodes` maps modifiers to this keyboard's keycodes (the running X server knows them); defaults otherwise."""
    if not is_modifier_only(spec):
        mods,key=parse_spec(spec); return "bindsym "+"+".join(mods+[x_keysym(key)])
    mod=parse_spec(spec)[0][0]
    return f"bindcode --release {(keycodes or {}).get(mod,DEFAULT_KEYCODES[mod])}"

def assigned(hotkeys):
    """(device, action, spec) for every hotkey that is set, keyboard first."""
    return [(d,a,hotkeys[d][a]) for d in DEVICES for a in DEVICE_ACTIONS[d] if hotkeys.get(d,{}).get(a)]

def clean_hotkeys(raw):
    """Valid hotkeys from a settings value. The old single set ({"menu":..,"guide":..}) becomes the remote set.
    A key may do only one thing, so a spec already used by an earlier slot is dropped."""
    hk={d:dict(DEFAULT_HOTKEYS[d]) for d in DEVICES}
    if not isinstance(raw,dict): return hk
    if any(a in raw for a in ACTIONS) and not any(d in raw for d in DEVICES): raw={"remote":raw}
    for d in DEVICES:
        given=raw.get(d)
        if not isinstance(given,dict): continue
        for a in DEVICE_ACTIONS[d]:
            spec=given.get(a)
            if isinstance(spec,str) and (spec=="" or valid_spec(spec)): hk[d][a]=spec
    seen=set()
    for d,a,spec in assigned(hk):
        if spec in seen: hk[d][a]=""
        else: seen.add(spec)
    return hk

def defaulted(raw):
    """The (device, action) slots a saved settings value does not set, so clean_hotkeys gave them their default: the
    "last" slots in a config from before 5.21. Only for a saved set; with none at all, nothing is reported."""
    if not isinstance(raw,dict): return []
    if any(a in raw for a in ACTIONS) and not any(d in raw for d in DEVICES): raw={"remote":raw}
    return [(d,a) for d in DEVICES for a in DEVICE_ACTIONS[d] if not isinstance((raw.get(d) if isinstance(raw.get(d),dict) else {}).get(a),str)]

def used_by(hotkeys,spec,skip=None):
    """The (device, action) that already has `spec`, ignoring the slot `skip`; None when it is free."""
    return next(((d,a) for d,a,s in assigned(hotkeys) if s==spec and (d,a)!=skip),None)

TV_BORDERS=("# Used on a TV: a window alone on its workspace has no border or title bar; side by side, a thin border shows which has focus",
            "default_border pixel 2","hide_edge_borders smart")

def render_bindings(hotkeys, command, keycodes=None, app_keys=(), tv=False) -> str:
    """Contents of hotkeys.conf, included from tvwcs.conf. `command` is the path of the tvwcs launcher.
    `app_keys` lists (spec, profile id, profile name) for the launch profiles that have a hotkey. On a TV (`tv`) it
    also turns window borders off where they show nothing (it is the one file TVWCS rewrites and reloads)."""
    q=shlex.quote(command); lines=["# Generated by TVWCS Settings. Change hotkeys there; edits made here are overwritten."]; bound=set()
    def add(spec,comment,action):
        key=binding(spec,keycodes)
        if key in bound: return   # sway warns about a config that binds the same key twice
        bound.add(key)   # sway has no end-of-line comments: a trailing "# ..." would become arguments to the command
        lines.append(f"# {comment} ({describe(spec)})"); lines.append(f"{key} {action}")
    for device,action,spec in assigned(hotkeys):
        add(spec,f"{DEVICE_LABELS[device]}: {ACTION_LABELS[action]}",f"exec --no-startup-id {q} {ACTION_COMMANDS[action]}")
    for spec,profile_id,name in app_keys:
        if spec and valid_spec(spec) and _SAFE_ID.fullmatch(profile_id or ""):   # an id from a hand-edited config must not break the line
            add(spec,f"Application: {' '.join(str(name).split())}",f"exec --no-startup-id {q} launch {profile_id}")
    if tv: lines+=TV_BORDERS
    return "\n".join(lines)+"\n"

# The keys that move around and choose in TVWCS (the D-pad, OK, Back). While a hotkey is being chosen they keep moving
# between Cancel and Clear and pressing them, so they are never taken as the new hotkey (with a modifier held they are).
NAVIGATION_KEYS=frozenset(("Up","Down","Left","Right","KP_Up","KP_Down","KP_Left","KP_Right","Return","KP_Enter","ISO_Enter",
                           "Escape","Back","Select","Tab","ISO_Left_Tab"))
def is_navigation(key_name, held=()):
    """A D-pad, OK or Back key pressed on its own: it navigates the hotkey dialog instead of becoming the hotkey."""
    return not held and key_name in NAVIGATION_KEYS

class HotkeyCapture:
    """Turns raw key events into a spec while the user is choosing a hotkey.
    A lone modifier is only accepted when it is released without any other key having been pressed."""
    def __init__(self): self.pending=None
    def press(self,key_name,held=()):
        if key_name in MODIFIER_KEYS:
            self.pending=MODIFIER_KEYS[key_name] if (self.pending is None and not held) else None
            return None
        self.pending=None
        return normalize_spec(list(held)+[key_name])
    def release(self,key_name):
        if key_name in MODIFIER_KEYS and self.pending==MODIFIER_KEYS[key_name]:
            spec,self.pending=self.pending,None; return spec
        return None
