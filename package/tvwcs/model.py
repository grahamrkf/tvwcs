"""TVWCS preferences, profiles, layout maths and search helpers; no GTK dependency."""

from __future__ import annotations
import copy, json, os, re, shlex, uuid
from dataclasses import dataclass, asdict
from pathlib import Path

from tvwcs.cec import DEFAULTS as CEC_DEFAULTS, clean_settings as clean_cec
from tvwcs.hotkeys import ACTION_LABELS, DEFAULT_HOTKEYS, DEVICE_LABELS, assigned, clean_hotkeys, defaulted, valid_spec
from tvwcs.pinlock import valid_hash
from tvwcs.power import clean_critical, clean_idle
from tvwcs import vendor as vendor_presets

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
DEFAULT_CONFIG = CONFIG_HOME / "tvwcs" / "config.json"

# How a profile is placed when launched or when its open window is selected.
LAUNCH_SAME = "same"  # tile alongside whatever is on the current workspace
LAUNCH_NEW_WORKSPACE = "new_workspace"  # always get a workspace of its own
LAUNCH_MODES = (LAUNCH_SAME, LAUNCH_NEW_WORKSPACE)
LAUNCH_PLAIN = "plain"  # desktop mode: as sway places it (opened where it opens, focused where it is)

# TVWCS's own windows are recognised by title. The prefix is deliberately unusual: a document called
# "tvwcs notes" in a text editor must never be mistaken for one of them (it would vanish from Open applications).
MAIN_TITLE = "TVWCS"
DIALOG_PREFIX = "TVWCS · "


def is_tvwcs_title(title: str) -> bool:
    return title == MAIN_TITLE or (title or "").startswith(DIALOG_PREFIX)


# TV mode and desktop mode. TVWCS runs in TV mode in a TVWCS session (the login screen's "TVWCS", whose tvwcs-session
# wrapper exports TVWCS_SESSION), and in desktop mode in any other sway session (TVWCS included in the usual sway
# config). In TV mode apps open full screen in workspaces of their own, the bar is hidden, the Quick Menu stays open
# while nothing is, the mouse pointer hides when it rests and TVWCS's lock screen is used. In desktop mode sway places
# apps as it always does and TVWCS changes nothing about the bar, the pointer or locking.
# TVWCS_MODE=tv|desktop overrides it (for trying one mode in the other's session, and for the tests).
def tv_mode(env=None) -> bool:
    env = os.environ if env is None else env
    forced = env.get("TVWCS_MODE")
    if forced in ("tv", "desktop"):
        return forced == "tv"
    return bool(env.get("TVWCS_SESSION"))


# Settings > Appearance > Interface size: 1 to 5, the size of TVWCS's text and controls on a 1080p screen. 3 is the
# desktop size and 4 the TV size (Desktop and TV Mode before 5.8). Automatic ("scale": "") picks by the mode and the
# theme: the Retro theme's pixel text reads well a size smaller.
SIZES = {1: 0.6, 2: 0.8, 3: 1.0, 4: 1.6, 5: 2.0}
SIZE_NAMES = {3: "desktop size", 4: "TV size"}
AUTO_SIZE = {(True, False): 4, (False, False): 3, (True, True): 3, (False, True): 2}  # (TV mode, Retro) -> size
LEGACY_SCALES = {
    "desktop": 3,
    "tenfoot": 4,
    "tenfoot_4k": 4,
}  # the sizes' names before 5.8 ("tenfoot_4k" also set scale_4k)
UHD_FACTOR = 3.0 / 1.6  # "Sized for a 4K screen": TV size 4 is then 3.0, 4K TV Mode before 5.8


def auto_size(settings, tv=None) -> int:
    return AUTO_SIZE[(tv_mode() if tv is None else tv, settings.get("style") == "retro")]


def size_of(settings, tv=None) -> int:
    """The interface size in use, 1 to 5: the one chosen, else the mode's and theme's own (auto_size)."""
    try:
        size = int(settings.get("scale") or 0)
    except (TypeError, ValueError):
        size = 0
    return size if size in SIZES else auto_size(settings, tv)


def scale_key(settings, tv=None):
    """What decides the interface scale (the size and whether it is sized for 4K): when it changes, TVWCS redraws."""
    return (size_of(settings, tv), bool(settings.get("scale_4k")))


# The screen height each size is drawn for: the larger sizes, and every size sized for 4K, shrink to fit a shorter
# screen (a 720p TV, or a 1080p one), never below the size they would be without it.
def effective_scale(key, screen_height=0) -> float:
    """The interface scale actually used, for a scale_key: the size's, made smaller on a screen shorter than the one it
    is drawn for."""
    size, uhd = key
    scale = SIZES.get(size, 1.0)
    floor = min(scale, 1.0)
    design = 1080 if size >= 4 else 0
    if uhd:
        floor, scale, design = scale, scale * UHD_FACTOR, 2160
    if design and screen_height and screen_height < design:
        scale = max(floor, round(scale * screen_height / design, 3))
    return round(scale, 3)


def size_label(size) -> str:
    return f"{size} ({SIZE_NAMES[size]})" if size in SIZE_NAMES else str(size)


def is_4k(width, height) -> bool:
    return max(width, height) >= 3840 and min(width, height) >= 2160


STARTUP_MODES = ("none", "last", "app")
STARTUP_LABELS = {"none": "None", "last": "Last application", "app": "Chosen application"}

# Settings > Appearance > Accent colour: the Metro colours (also the letter tiles' colours), and their names (a hand-set colour keeps its hex).
METRO_COLORS = (
    "#0078d7",
    "#e81123",
    "#00b294",
    "#ff8c00",
    "#881798",
    "#107c10",
    "#ea005e",
    "#6b69d6",
    "#00cc6a",
    "#c239b3",
)
ACCENT_NAMES = {
    "#0078d7": "Blue",
    "#e81123": "Red",
    "#00b294": "Teal",
    "#ff8c00": "Orange",
    "#881798": "Purple",
    "#107c10": "Green",
    "#ea005e": "Magenta",
    "#6b69d6": "Iris",
    "#00cc6a": "Mint",
    "#c239b3": "Orchid",
}


def accent_name(colour) -> str:
    return ACCENT_NAMES.get((colour or "").lower(), colour or "")


# Settings > Appearance > Screen edge margin, in px at desktop scale: many TVs crop the picture's edges (overscan).
MARGIN_RANGE = (0, 120)
# Channel numbers have 1 to 4 digits (the channel_digits setting, 2 by default): 00 to 99 with two. Channel 0 goes to
# TVWCS's own Settings app, once, on a new or updated install.
CHANNEL_DIGITS = (1, 2, 3, 4)
DEFAULT_CHANNEL_DIGITS = 2
CHANNEL_MIN, CHANNEL_MAX = 0, 10 ** max(CHANNEL_DIGITS) - 1  # what any number of digits allows


def channel_max(digits):
    return 10**digits - 1


def channel_text(number, digits):
    return f"{number:0{digits}d}"  # 7 with two digits: "07"


def channel_range(digits):
    return f"{channel_text(0,digits)} to {channel_text(channel_max(digits),digits)}"


SETTINGS_DESKTOP_ID = "com.tvwcs.ControlPanel.desktop"
# Settings > Appearance > Quick Menu corner: the corner of the screen the Quick Menu sits in. Its layout mirrors to
# match: on the right its rows run right to left (Applications opens to its left), at the top its lists grow downwards.
CORNERS = {
    "bottom-left": "Bottom left",
    "bottom-right": "Bottom right",
    "top-left": "Top left",
    "top-right": "Top right",
}
DEFAULT_CORNER = "bottom-left"


def corner_right(corner) -> bool:
    return str(corner or "").endswith("right")


def corner_top(corner) -> bool:
    return str(corner or "").startswith("top")


# Settings > Appearance > Theme: the Modern (Metro) look or the Retro one, green, amber or white text on black like an
# old CRT television's menus, in pixel fonts with pixel icons and no application icons; or Media, dark with rounded
# corners in colours that go with the media server app chosen in MEDIA_LOOKS (TVWCS's own colours, not the apps' art).
STYLES = {"modern": "Modern", "retro": "Retro", "media": "Media"}
MEDIA_LOOKS = {"jellyfin": "Jellyfin", "emby": "Emby", "plex": "Plex"}
# The Media theme's background for each look (theme.MEDIA_PALETTES has the rest of its colours)
MEDIA_WALLPAPERS = {"jellyfin": "#0b0b12", "emby": "#0e0e0e", "plex": "#111214"}
PHOSPHORS = {"green": "Green", "amber": "Amber", "white": "White"}
# Settings > Appearance > Font (Retro): TVWCS's pixel fonts, sharp at whole pixels; VT323, after a 1970s DEC terminal's
# font (bundled); or Inter, smooth and easy to read (the fonts-inter package, else Open Sans).
RETRO_FONTS = {"pixel": "Pixel", "vt323": "VT323", "readable": "Inter (easy to read)"}
# Settings > Appearance > Light or dark (Modern): TVWCS's light or dark look; applications that follow the desktop's
# colour scheme follow it. The Retro and Media themes are always dark.
THEMES = {"dark": "Dark", "light": "Light"}


def dark_look(settings) -> bool:
    return settings.get("style") in ("retro", "media") or settings.get("theme") != "light"


# Settings > Appearance > Background colour: what shows where no application is open, and behind the Quick Menu.
# Six greys from white to black, six bright colours and the same six darkened. Shown as swatches without names.
WALLPAPER_GREYS = ("#ffffff", "#c8c8c8", "#969696", "#646464", "#323232", "#000000")
WALLPAPER_COLOURS = ("#e81123", "#ff8c00", "#ffd800", "#107c10", "#0078d7", "#881798")
WALLPAPER_DARK = ("#740912", "#804600", "#806c00", "#083e08", "#003c6c", "#440c4c")
WALLPAPERS = WALLPAPER_GREYS + WALLPAPER_COLOURS + WALLPAPER_DARK
DEFAULT_WALLPAPER = "#323232"  # dark grey
# The Retro theme's backgrounds: a CRT grey, the primary blue of a TV with no signal, or TV static (retro/static.png).
RETRO_WALLPAPERS = {"gray": "#808080", "blue": "#0000ff", "static": "static"}
RETRO_WALLPAPER_LABELS = {"gray": "Gray", "blue": "Blue", "static": "TV static"}


def wallpaper_of(settings) -> str:
    """The background to paint: a colour, or "static" for the TV static picture."""
    if settings.get("style") == "retro":
        return RETRO_WALLPAPERS[settings.get("retro_wallpaper", "gray")]
    if settings.get("style") == "media":
        return MEDIA_WALLPAPERS.get(settings.get("media_look"), MEDIA_WALLPAPERS["jellyfin"])
    return settings.get("wallpaper", DEFAULT_WALLPAPER)


# The on-screen keyboard: hidden (a button shows it), the full keyboard, or a number pad. The one last used comes back.
KEYBOARDS = {"hidden": "Hidden", "full": "Full keyboard", "digits": "Number pad"}


def key_hints(tv) -> str:
    """The Settings app's footer: a remote's key is called Back, a keyboard's Esc."""
    back = "Back" if tv else "Esc"
    return f"↑ ↓ ← →  Navigate    {'OK' if tv else 'Enter'}  Select\n{back}  Go back"


DEFAULT_SETTINGS = {
    "margin": 0,  # px (at desktop scale) between the panels and the edges of the usable workspace
    "quick_width": 460,  # px (at desktop scale) width of the Quick Menu; the Settings panel matches it
    "accent": "#0078d7",  # Metro accent colour
    "lock_command": "",  # empty = auto-detect a screen locker (desktop mode; TV mode uses TVWCS's lock screen)
    "scale": "",  # Interface size "1" to "5" (SIZES), or "" for the mode's own size (size_of)
    "scale_4k": False,  # the interface size is sized for a 4K screen (UHD_FACTOR larger)
    "close_on_click_outside": True,  # close TVWCS when it loses focus (another window takes it)
    "hide_options_buttons": False,  # hide the Quick Menu rows' ⋯ buttons; ← on a row (or a right-click) still opens its options
    "search_icon": False,  # hide the Quick Menu's search bar behind a search icon in the status row (typing still opens it)
    "update_prereleases": False,  # TVWCS's updater also offers prereleases (releases not yet tested and marked latest)
    "clock_24h": False,  # the Quick Menu's clock shows 14:05 instead of 2:05 PM
    "quick_corner": DEFAULT_CORNER,  # CORNERS: where the Quick Menu sits, its layout mirrored to match
    "style": "modern",  # STYLES: the Modern, Retro or Media theme
    "media_look": "jellyfin",  # MEDIA_LOOKS: the media server app whose colours the Media theme goes with
    "phosphor": "green",  # PHOSPHORS: the Retro theme's colour
    "retro_font": "pixel",  # RETRO_FONTS: the Retro theme's font
    "retro_wallpaper": "gray",  # RETRO_WALLPAPERS: the Retro theme's background (Modern keeps its own in wallpaper)
    "theme": "dark",  # THEMES: the Modern theme's light or dark, passed on to applications that follow the desktop's colour scheme
    "wallpaper": DEFAULT_WALLPAPER,  # WALLPAPERS: the background where no application is open
    "keyboard": "hidden",  # KEYBOARDS: the on-screen keyboard as it was last left (hidden, full or the number pad)
    "channel_digits": DEFAULT_CHANNEL_DIGITS,  # CHANNEL_DIGITS: how many digits a channel number has
    "channel_zero_done": False,  # channel 0 has been given to Settings (once; afterwards it is the user's)
    "audio_boost": False,  # Settings > Sound: volumes may go over 100% (else they stop there)
    "lock_at_start": False,  # Settings > User: a TVWCS session starts locked (for the automatic login), see lockscreen.py
    "idle": {"screen_off": 0, "lock": 0, "sleep": 0},  # seconds without input before each (0 never), see power.py
    "idle_battery": {"screen_off": 0, "lock": 0, "sleep": 0},  # the same, while a laptop runs on its battery
    "battery_critical": {
        "action": "shutdown",
        "percent": 5,
    },  # what to do when the battery is nearly empty (power.CRITICAL_ACTIONS)
    "hotkeys": DEFAULT_HOTKEYS,  # keyboard / remote / gamepad sets; deep-copied with the rest of the defaults
    "cec": CEC_DEFAULTS,  # the TV's remote over HDMI-CEC (cec.py): on, TV power, the button that opens the Quick Menu
    "startup": {"mode": "none", "profile_id": "", "last_profile_id": ""},  # mode: STARTUP_MODES
}
PIN_LAUNCH = "launch"  # the PIN is asked when the profile is launched
PIN_LAUNCH_AND_SHOW = (
    "launch_and_show"  # ... and when an open app of it is shown from a workspace that is not on screen
)
PIN_SCOPES = (PIN_LAUNCH, PIN_LAUNCH_AND_SHOW)
PIN_SCOPE_LABELS = {
    PIN_LAUNCH: "Only when launching",
    PIN_LAUNCH_AND_SHOW: "When launching, and when showing it if it is open on a hidden workspace",
}
MAX_DESCRIPTION = 200


@dataclass
class LaunchProfile:
    id: str
    desktop_id: str
    name: str
    command: str = ""  # empty means use the desktop entry's standard launcher
    channel: int | None = None
    favorite: bool = False
    launch_mode: str = LAUNCH_SAME
    desktop_action: str = ""  # optional named Desktop Action from the .desktop file
    pin_hash: str = ""  # salted hash of the PIN that protects this profile ("" = unprotected)
    pin_scope: str = PIN_LAUNCH
    description: str = ""  # secondary profiles: replaces the default description (the launch options)
    hotkey: str = ""  # a hotkey spec (see hotkeys.py) that launches this profile ("" = none)


def _clean_text(value) -> str:
    return " ".join(str(value or "").split())[:MAX_DESCRIPTION]


def _clean_settings(raw) -> dict:
    s = copy.deepcopy(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return s
    for key, lo, hi in (("margin", *MARGIN_RANGE), ("quick_width", 320, 900)):
        try:
            v = int(raw.get(key, s[key]))
            if lo <= v <= hi:
                s[key] = v
        except (TypeError, ValueError):
            pass
    accent = raw.get("accent")
    if isinstance(accent, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        s["accent"] = accent
    if isinstance(raw.get("lock_command"), str):
        s["lock_command"] = raw["lock_command"].strip()
    scale = str(raw.get("scale") or "")
    if scale in LEGACY_SCALES:  # before 5.8: a named size
        s["scale"] = str(LEGACY_SCALES[scale])
        s["scale_4k"] = scale == "tenfoot_4k"
        # before 4.0, "Used on" (use) set the size along with it: a size that only followed it now follows the mode
        if raw.get("use") in ("tv", "desktop") and scale == ("tenfoot" if raw["use"] == "tv" else "desktop"):
            s["scale"] = ""
    elif scale.isdigit() and int(scale) in SIZES:
        s["scale"] = scale
    if isinstance(raw.get("scale_4k"), bool) and scale not in LEGACY_SCALES:
        s["scale_4k"] = raw["scale_4k"]
    if raw.get("theme") in THEMES:
        s["theme"] = raw["theme"]
    for key, allowed in (
        ("style", STYLES),
        ("phosphor", PHOSPHORS),
        ("retro_font", RETRO_FONTS),
        ("retro_wallpaper", RETRO_WALLPAPERS),
        ("media_look", MEDIA_LOOKS),
    ):
        if raw.get(key) in allowed:
            s[key] = raw[key]
    if raw.get("quick_corner") in CORNERS:
        s["quick_corner"] = raw["quick_corner"]
    if isinstance(raw.get("wallpaper"), str) and raw["wallpaper"].lower() in WALLPAPERS:
        s["wallpaper"] = raw["wallpaper"].lower()
    if raw.get("keyboard") in KEYBOARDS:
        s["keyboard"] = raw["keyboard"]
    if raw.get("channel_digits") in CHANNEL_DIGITS and not isinstance(raw["channel_digits"], bool):
        s["channel_digits"] = raw["channel_digits"]
    for key in (
        "close_on_click_outside",
        "hide_options_buttons",
        "search_icon",
        "update_prereleases",
        "clock_24h",
        "channel_zero_done",
        "audio_boost",
        "lock_at_start",
    ):
        if isinstance(raw.get(key), bool):
            s[key] = raw[key]
    s["hotkeys"] = clean_hotkeys(raw.get("hotkeys"))
    s["cec"] = clean_cec(raw.get("cec"))
    s["idle"] = clean_idle(raw.get("idle"))
    s["idle_battery"] = clean_idle(raw.get("idle_battery"))
    s["battery_critical"] = clean_critical(raw.get("battery_critical"))
    st = raw.get("startup")
    if isinstance(st, dict):
        if st.get("mode") in STARTUP_MODES:
            s["startup"]["mode"] = st["mode"]
        for key in ("profile_id", "last_profile_id"):
            if isinstance(st.get(key), str):
                s["startup"][key] = st[key]
    return s


# Names TVWCS's own Settings entry had before its .desktop file was renamed (profiles made then still carry them).
LEGACY_NAMES_ALL = {"com.tvwcs.ControlPanel.desktop": ("Control Panel", "Settings", "TVWCS Settings")}
LEGACY_NAMES = {k: v[0] for k, v in LEGACY_NAMES_ALL.items()}


def _user_hotkeys(raw):
    """A user's settings with the hotkeys of before 4.0 (one set, {"menu": ..}) made the remote's set, so they merge
    over a vendor's per-device presets."""
    if not isinstance(raw, dict):
        return {}
    hk = raw.get("hotkeys")
    if isinstance(hk, dict) and any(a in hk for a in ACTION_LABELS) and not any(d in hk for d in DEVICE_LABELS):
        raw = dict(raw, hotkeys={"remote": hk})
    return raw


class ConfigStore:
    """config.json: the user's launch profiles and settings. The settings start from TVWCS's defaults with the vendor's
    and administrator's presets over them (vendor.py: base); only what the user changed from that is saved, so the
    rest keeps following the presets (and TVWCS's own defaults) when they change."""

    def __init__(self, path: Path | str = DEFAULT_CONFIG):
        self.path = Path(path)
        self.profiles: list[LaunchProfile] = []
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.app_descriptions: dict[str, str] = {}
        self.app_names: dict[str, str] = {}
        self.vendor = vendor_presets.Vendor()
        self.base = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        self.vendor = vendor_presets.load(report=False)
        presets = self.vendor.settings
        if self.vendor.startup_app and not (isinstance(presets.get("startup"), dict) and "mode" in presets["startup"]):
            presets = vendor_presets.merge(presets, {"startup": {"mode": "app"}})
        self.base = _clean_settings(presets)
        self.profiles = []
        self.settings = copy.deepcopy(self.base)
        self.app_descriptions = {}
        self.app_names = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        user = _user_hotkeys(data.get("settings"))
        self.settings = _clean_settings(vendor_presets.merge(presets, user))
        raw_descriptions = data.get("app_descriptions")
        if isinstance(raw_descriptions, dict):
            self.app_descriptions = {str(k): _clean_text(v) for k, v in raw_descriptions.items() if _clean_text(v)}
        raw_names = data.get("app_names")
        if isinstance(raw_names, dict):
            self.app_names = {str(k): str(v) for k, v in raw_names.items() if isinstance(v, str)}
        for raw in data.get("profiles", []):
            try:
                channel = raw.get("channel")
                channel = int(channel) if channel not in (None, "") else None
                if channel is not None and not CHANNEL_MIN <= channel <= CHANNEL_MAX:
                    channel = None
                # Files written before 2.3 have a boolean "tile" and no launch_mode; they load as LAUNCH_SAME.
                mode = raw.get("launch_mode")
                if mode not in LAUNCH_MODES:
                    mode = LAUNCH_SAME
                self.profiles.append(
                    LaunchProfile(
                        str(raw.get("id") or uuid.uuid4()),
                        str(raw["desktop_id"]),
                        str(raw.get("name") or "Launch"),
                        str(raw.get("command") or ""),
                        channel,
                        bool(raw.get("favorite", False)),
                        mode,
                        str(raw.get("desktop_action") or ""),
                        raw["pin_hash"] if valid_hash(raw.get("pin_hash")) else "",
                        raw["pin_scope"] if raw.get("pin_scope") in PIN_SCOPES else PIN_LAUNCH,
                        _clean_text(raw.get("description")),
                        raw["hotkey"] if isinstance(raw.get("hotkey"), str) and valid_spec(raw["hotkey"]) else "",
                    )
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        if "channel_digits" not in user:
            # Before 5.12 every channel had three digits: keep enough of them for the channels already set (a config
            # saved with vendor-file support leaves the digits out when they are the default, and then its channels fit them)
            top = max((p.channel for p in self.profiles if p.channel is not None), default=0)
            self.settings["channel_digits"] = max(self.settings["channel_digits"], len(str(top)))
        for p in self.profiles:
            if p.channel is not None and p.channel > self.channel_max():
                p.channel = None
        # The Last app key (Super+Tab, 5.21) is new: where the user never set it, it gives way to an app that has the key
        taken = {p.hotkey for p in self.profiles if p.hotkey}
        for d, a in defaulted(user.get("hotkeys")):
            if a == "last" and self.settings["hotkeys"][d][a] in taken:
                self.settings["hotkeys"][d][a] = ""
        self._deduplicate_channels()
        self._deduplicate_hotkeys()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        changed = vendor_presets.difference(self.settings, self.base)
        temp.write_text(
            json.dumps(
                {
                    "version": 2,
                    "settings": changed,
                    "app_descriptions": self.app_descriptions,
                    "app_names": self.app_names,
                    "profiles": [asdict(p) for p in self.profiles],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, self.path)

    def ensure_defaults(self, applications):
        """Give every application a launch profile, and keep a plain profile's name in step when the application is
        renamed (its .desktop file now has another Name): a name the user typed is left alone."""
        known = {p.desktop_id for p in self.profiles}
        changed = False
        for app in applications:
            old = self.app_names.get(app.desktop_id) or LEGACY_NAMES.get(app.desktop_id)
            if self.app_names.get(app.desktop_id) != app.name:
                self.app_names[app.desktop_id] = app.name
                changed = True
            for p in self.profiles:
                if (
                    p.desktop_id == app.desktop_id
                    and p.name != app.name
                    and not p.command
                    and not p.desktop_action
                    and (p.name == old or p.name in LEGACY_NAMES_ALL.get(app.desktop_id, ()))
                ):
                    p.name = app.name
                    changed = True
            if app.desktop_id not in known:
                profile = LaunchProfile(str(uuid.uuid4()), app.desktop_id, app.name)
                self._vendor_channel(profile)
                self.profiles.append(profile)
                known.add(app.desktop_id)
                changed = True
            if (
                app.desktop_id in self.app_descriptions
            ):  # before 4.0 an application had one description: its default profile's now
                main = default_of(self.for_app(app.desktop_id), app.name)
                text = self.app_descriptions.pop(app.desktop_id)
                changed = True
                if main is not None and not main.description:
                    main.description = text
        if self._give_settings_channel_zero():
            changed = True
        if self._vendor_startup_app():
            changed = True
        if changed:
            self.save()

    def _vendor_channel(self, profile):
        """A new application's profile gets the vendor's channel and favorite for it (vendor.py "channels"), when the
        channel is free and fits the channel digits."""
        preset = self.vendor.channels.get(profile.desktop_id)
        if not preset:
            return
        ch = preset["channel"]
        if (
            ch is not None
            and CHANNEL_MIN <= ch <= self.channel_max()
            and not any(p.channel == ch for p in self.profiles)
        ):
            profile.channel = ch
        profile.favorite = preset["favorite"]

    def _vendor_startup_app(self):
        """The vendor's application to open at login (vendor.py "startup_app"), for a user who has not chosen one."""
        st = self.settings["startup"]
        if not self.vendor.startup_app or st["profile_id"]:
            return False
        main = next((p for p in self.for_app(self.vendor.startup_app) if not p.command and not p.desktop_action), None)
        if main is None:
            return False  # not installed (yet)
        st["profile_id"] = main.id
        return True

    def _give_settings_channel_zero(self):
        """Channel 0 opens Settings: given once (a new install, or the first start after updating to 3.1), to the
        Settings app's main profile, when no other profile has it. The user may change it afterwards."""
        if self.settings["channel_zero_done"]:
            return False
        main = next((p for p in self.for_app(SETTINGS_DESKTOP_ID) if not p.command and not p.desktop_action), None)
        if main is None:
            return False  # Settings is not installed (yet): try again next time
        if not any(p.channel == 0 for p in self.profiles):
            main.channel = 0
        self.settings["channel_zero_done"] = True
        return True

    def channel_digits(self):
        return self.settings["channel_digits"]

    def channel_max(self):
        return channel_max(self.channel_digits())

    def channel_text(self, number):
        return channel_text(number, self.channel_digits())

    def too_long_channels(self, digits):
        """The profiles whose channel numbers do not fit in this many digits, lowest number first."""
        return sorted(
            (p for p in self.profiles if p.channel is not None and p.channel > channel_max(digits)),
            key=lambda p: p.channel,
        )

    def set_channel_digits(self, digits):
        """Channel numbers get this many digits; those too long for them are removed."""
        if digits not in CHANNEL_DIGITS:
            raise ValueError("A channel number has 1 to 4 digits.")
        for p in self.too_long_channels(digits):
            p.channel = None
        self.settings["channel_digits"] = digits

    def get(self, profile_id):
        return next((p for p in self.profiles if p.id == profile_id), None)

    def for_app(self, desktop_id):
        return sorted(
            (p for p in self.profiles if p.desktop_id == desktop_id),
            key=lambda p: (p.channel is None, p.channel or 0, p.name.casefold()),
        )

    def assigned(self):
        return sorted((p for p in self.profiles if p.channel is not None), key=lambda p: (p.channel, p.name.casefold()))

    def favorites(self):
        return sorted(
            (p for p in self.profiles if p.favorite),
            key=lambda p: (p.channel is None, p.channel or 0, p.name.casefold()),
        )

    def set_profile(self, profile: LaunchProfile):
        if profile.channel is not None:
            if not CHANNEL_MIN <= int(profile.channel) <= self.channel_max():
                raise ValueError(f"The channel must be from {channel_range(self.channel_digits())}.")
            for other in self.profiles:
                if other.id != profile.id and other.channel == profile.channel:
                    raise ValueError(f"Channel {profile.channel} is already assigned to {other.name}.")
        if profile.launch_mode not in LAUNCH_MODES:
            raise ValueError("Unknown launch mode.")
        if profile.pin_scope not in PIN_SCOPES:
            raise ValueError("Unknown PIN scope.")
        if profile.pin_hash and not valid_hash(profile.pin_hash):
            raise ValueError("The PIN is not stored in a valid form.")
        if profile.hotkey and not valid_spec(profile.hotkey):
            raise ValueError("The hotkey is not valid.")
        profile.description = _clean_text(profile.description)
        profile.name = profile.name.strip()
        if not profile.name:
            raise ValueError("The name cannot be empty.")
        if profile.command.strip():
            try:
                parts = shlex.split(profile.command)
            except ValueError as exc:
                raise ValueError(f"Command quoting is invalid: {exc}")
            if not parts:
                raise ValueError("Custom command cannot be empty.")
        # A key does one thing: the editor has already asked before taking a hotkey from somewhere else.
        if profile.hotkey:
            self._release_hotkey(profile.hotkey, ("profile", profile.id))
        for i, p in enumerate(self.profiles):
            if p.id == profile.id:
                self.profiles[i] = profile
                break
        else:
            self.profiles.append(profile)
        self.save()

    def toggle_launch_mode(self, profile_id):
        """Flip a profile between 'same workspace (tiled)' and 'own new workspace'. Returns the new mode."""
        p = self.get(profile_id)
        if p is None:
            return None
        p.launch_mode = LAUNCH_SAME if p.launch_mode == LAUNCH_NEW_WORKSPACE else LAUNCH_NEW_WORKSPACE
        self.save()
        return p.launch_mode

    def save_settings(self):
        self.save()

    def set_app_description(self, desktop_id, text):
        """Override an application's description in Applications. Empty restores the one from its .desktop file."""
        text = _clean_text(text)
        if text:
            self.app_descriptions[desktop_id] = text
        else:
            self.app_descriptions.pop(desktop_id, None)
        self.save()

    def record_last_profile(self, profile_id):
        if self.settings["startup"]["last_profile_id"] != profile_id:
            self.settings["startup"]["last_profile_id"] = profile_id
            self.save()

    def delete(self, profile_id):
        self.profiles = [p for p in self.profiles if p.id != profile_id]
        self.save()

    # ---- hotkeys. Every hotkey has one owner: a device slot ("slot", device, action) or a profile ("profile", id).
    def hotkey_owner(self, spec, skip=None):
        """The owner of `spec` other than `skip`, or None when the key is free."""
        if not spec:
            return None
        for d, a, s in assigned(self.settings["hotkeys"]):
            if s == spec and ("slot", d, a) != skip:
                return ("slot", d, a)
        return next((("profile", p.id) for p in self.profiles if p.hotkey == spec and ("profile", p.id) != skip), None)

    def owner_label(self, owner) -> str:
        if owner is None:
            return ""
        if owner[0] == "slot":
            return f"{DEVICE_LABELS[owner[1]]}: {ACTION_LABELS[owner[2]]}"
        p = self.get(owner[1])
        return p.name if p else "an application"

    def _release_hotkey(self, spec, keep):
        """Take `spec` away from every owner but `keep` (not saved)."""
        for d, a, s in assigned(self.settings["hotkeys"]):
            if s == spec and ("slot", d, a) != keep:
                self.settings["hotkeys"][d][a] = ""
        for p in self.profiles:
            if p.hotkey == spec and ("profile", p.id) != keep:
                p.hotkey = ""

    def set_slot_hotkey(self, device, action, spec):
        """Set (or, with "", clear) a device's hotkey, taking the key from whatever had it."""
        if spec:
            self._release_hotkey(spec, ("slot", device, action))
        self.settings["hotkeys"][device][action] = spec
        self.save()

    def set_profile_hotkey(self, profile_id, spec):
        """Set (or, with "", clear) a profile's hotkey, taking the key from whatever had it."""
        p = self.get(profile_id)
        if p is None:
            return
        if spec:
            if not valid_spec(spec):
                raise ValueError("The hotkey is not valid.")
            self._release_hotkey(spec, ("profile", p.id))
        p.hotkey = spec
        self.save()

    def hotkey_profiles(self):
        """Profiles that have a hotkey, by name."""
        return sorted((p for p in self.profiles if p.hotkey), key=lambda p: p.name.casefold())

    def app_hotkeys(self):
        """(spec, profile id, name) of every profile hotkey, for hotkeys.render_bindings."""
        return [(p.hotkey, p.id, p.name) for p in self.hotkey_profiles()]

    def _deduplicate_hotkeys(self):
        """A profile cannot have a key a device slot or an earlier profile already has (only a hand-edited file does that)."""
        seen = {s for _d, _a, s in assigned(self.settings["hotkeys"])}
        for p in sorted(self.profiles, key=lambda p: p.id):
            if p.hotkey:
                if p.hotkey in seen:
                    p.hotkey = ""
                else:
                    seen.add(p.hotkey)

    def _deduplicate_channels(self):
        seen = set()
        for p in sorted(self.profiles, key=lambda p: p.id):
            if p.channel is not None:
                if p.channel in seen:
                    p.channel = None
                else:
                    seen.add(p.channel)


# ---------------------------------------------------------------- layout


@dataclass(frozen=True)
class Layout:
    """Pixel geometry of the TVWCS window (absolute screen coordinates) and of the panels inside it."""

    x: int
    y: int
    width: int
    height: int
    quick_width: int
    margin: int
    guide_open: bool

    @property
    def guide_width(self) -> int:
        return 0 if not self.guide_open else max(0, self.width - self.quick_width - self.margin)


def compute_layout(
    area,
    margin,
    quick_width,
    guide_open,
    options_open=False,
    guide_width=None,
    quick_height=None,
    corner=DEFAULT_CORNER,
) -> Layout:
    """Panels side by side: Quick Menu | Applications (tabbed), separated by one `margin`; mirrored (Applications |
    Quick Menu) when `corner` is on the right. The Quick Menu sits at that side of `area` (the usable workspace
    rectangle) with `margin` px above, below and beside it. The tabbed Applications pane fills the rest; Settings is a tab
    inside it, so the window no longer grows when it opens. The window spans only what is open. `options_open` is
    accepted for compatibility with older callers and ignored. `guide_width` (desktop use) caps the Applications pane
    at what its contents need, so the window does not fill the screen. `quick_height` (desktop use, Applications closed)
    shrinks the Quick Menu to what its contents need, kept in its corner (CORNERS) with the same margins."""
    ax, ay, aw, ah = (int(area[k]) for k in ("x", "y", "width", "height"))
    margin = max(0, min(int(margin), aw // 4, ah // 4))
    full = max(1, aw - 2 * margin)
    height = max(1, ah - 2 * margin)
    qw = max(1, min(int(quick_width), int(full * 0.45)))
    width = full
    if guide_width:
        width = max(qw + margin + 1, min(full, qw + margin + int(guide_width)))
    if not guide_open:
        width = qw
    x = ax + aw - margin - width if corner_right(corner) else ax + margin
    if quick_height and not guide_open:
        h = max(1, min(height, int(quick_height)))
        return Layout(x, ay + margin if corner_top(corner) else ay + ah - margin - h, qw, h, qw, margin, False)
    return Layout(x, ay + margin, width, height, qw, margin, bool(guide_open))


# ---------------------------------------------------------------- badges

_BADGE_PATTERNS = (re.compile(r"^\s*\((\d{1,4})\+?\)\s*"), re.compile(r"^\s*\[(\d{1,4})\]\s*"))


def extract_badge(title, urgent=False):
    """Return (display_title, badge_text_or_None). Many apps (mail, chat) put an unread count at
    the start of the window title, e.g. '(3) Inbox'; sway also flags windows as urgent."""
    t = title or ""
    for pattern in _BADGE_PATTERNS:
        m = pattern.match(t)
        if m:
            n = int(m.group(1))
            clean = t[m.end() :].strip() or t
            if n == 0:
                return clean, ("!" if urgent else None)
            return clean, ("99+" if n > 99 else str(n))
    return t, ("!" if urgent else None)


# ---------------------------------------------------------------- search


def search_items(query, profiles, applications, windows, digits=DEFAULT_CHANNEL_DIGITS):
    """Return tagged search results as dictionaries; search is case-insensitive."""
    q = (query or "").strip().casefold()
    results = []
    # A profile whose application was uninstalled cannot start (unless it runs its own command): it is not offered.
    profiles = [p for p in profiles if p.desktop_id in applications or p.command.strip()]

    def window_result(w):
        title, badge = extract_badge(w.get("title", ""), w.get("urgent", False))
        return {
            "kind": "window",
            "id": str(w.get("con_id")),
            "label": title or w.get("class") or "Untitled window",
            "detail": "Open window",
            "window": w,
            "badge": badge,
        }

    def detail_of(p, a):  # the application's name when the profile has another, else what the application is
        if not a:
            return p.desktop_id
        return a.name if a.name != p.name else (a.generic_name or a.comment or "")

    if q.isdigit():
        number = int(q)
        for p in profiles:
            if p.channel == number:
                a = applications.get(p.desktop_id)
                results.append(
                    {
                        "kind": "profile",
                        "id": p.id,
                        "label": f"{channel_text(p.channel,digits)}  {p.name}",
                        "detail": detail_of(p, a),
                        "profile": p,
                    }
                )
    else:
        for p in profiles:
            a = applications.get(p.desktop_id)
            label = p.name
            detail = detail_of(p, a)
            hay = " ".join([label, a.name if a else "", detail, p.desktop_id, p.command]).casefold()
            if not q or q in hay:
                results.append(
                    {
                        "kind": "profile",
                        "id": p.id,
                        "label": (f"{channel_text(p.channel,digits)}  " if p.channel is not None else "") + label,
                        "detail": detail,
                        "profile": p,
                    }
                )
        for w in windows:
            hay = f"{w.get('title','')} {w.get('class','')} {w.get('instance','')}".casefold()
            if not q or q in hay:
                results.append(window_result(w))
    # Profiles first, then windows; channel numbers before unassigned profiles.
    results.sort(
        key=lambda r: (
            0 if r["kind"] == "profile" else 1,
            r.get("profile").channel is None if r["kind"] == "profile" else False,
            r.get("profile").channel or 0 if r["kind"] == "profile" else 0,
            r["label"].casefold(),
        )
    )
    return results[:80]


def profile_detail(profile, app) -> str:
    """The launch options of a secondary profile: the chosen .desktop action and any custom launch command."""
    parts = []
    if profile.desktop_action:
        names = dict(app.desktop_actions) if app else {}
        parts.append(names.get(profile.desktop_action, profile.desktop_action))
    if profile.command.strip():
        parts.append(profile.command.strip())
    return "  ·  ".join(parts)


def row_description(profile, app, primary, app_override="") -> str:
    """The description shown beside a profile's name: each profile has its own (4.0). Without one, the default
    profile shows its application's (the .desktop file's), another profile its launch options. `app_override` is the
    one description per application from before 4.0, for a default profile that has none yet."""
    if profile.description.strip():
        return profile.description.strip()
    if primary:
        return app_override or ((app.comment or app.generic_name) if app else "") or ""
    return profile_detail(profile, app)


# ---------------------------------------------------------------- profile names
DEFAULT_LABEL = "Default"  # the default profile's name: never shown, never changed


def default_of(profiles, app_name):
    """An application's default profile among its `profiles`: the plain one (no command or desktop action) with the
    application's name, else the first plain one, else the first."""
    plain = [p for p in profiles if not p.command and not p.desktop_action]
    return next((p for p in plain if p.name == app_name), (plain or list(profiles) or [None])[0])


def profile_label(profile, app_name, primary) -> str:
    """A profile's own name, without the application's: "Default" for the default profile; for a profile named
    before 4.0 with the application's name in front ("Kodi profile 2"), what follows it."""
    if primary:
        return DEFAULT_LABEL
    name = profile.name.strip()
    if app_name and name.casefold().startswith(app_name.casefold() + " "):
        return name[len(app_name) + 1 :].strip() or name
    return name


def display_name(profile, app_name, primary) -> str:
    """The name shown in lists: the application's name, which is never changed, with the profile's name after it
    (none for the default profile)."""
    if not app_name:
        return profile.name
    return app_name if primary else f"{app_name} {profile_label(profile,app_name,False)}"


def next_label(labels) -> str:
    """A new profile's name: the first number from 2 that no other profile of the application has."""
    taken = {str(l).strip().casefold() for l in labels}
    n = 2
    while str(n) in taken:
        n += 1
    return str(n)


def startup_choices(profiles):
    """Applications to offer for 'open at login', most likely first: favorites, then channels, then everything else."""
    by_number = lambda p: (p.channel is None, p.channel or 0, p.name.casefold())
    favorites = sorted((p for p in profiles if p.favorite), key=by_number)
    channels = sorted((p for p in profiles if p.channel is not None and not p.favorite), key=by_number)
    others = sorted((p for p in profiles if not p.favorite and p.channel is None), key=lambda p: p.name.casefold())
    return [
        (title, group)
        for title, group in (("FAVORITES", favorites), ("CHANNELS", channels), ("ALL OTHER APPS", others))
        if group
    ]
