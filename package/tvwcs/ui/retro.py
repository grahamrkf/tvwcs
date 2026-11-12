"""The Retro theme's files (retro/, built by scripts/make-retro-assets.py) and the names of its pixel icons. No GTK
dependency: widgets.use_retro puts them to use, theme.py has its colours and rules."""

from __future__ import annotations
import ctypes, ctypes.util, re
from pathlib import Path

RETRO_DIR = Path(__file__).resolve().parent / "retro_assets"
ICON_DIR = (
    RETRO_DIR / "icons"
)  # an icon theme folder: the icons are in hicolor/scalable/actions, so GTK colours them in
ICON_FILES = ICON_DIR / "hicolor" / "scalable" / "actions"
STATIC_PICTURE = RETRO_DIR / "static.png"
FONT_FILES = (
    RETRO_DIR / "TVWCSPixel5x7.ttf",
    RETRO_DIR / "TVWCSPixel8x16.ttf",
    RETRO_DIR / "TVWCSPixel8x8.ttf",
    RETRO_DIR / "VT323-Regular.ttf",
)

# The icon names TVWCS asks for (without -symbolic), and the pixel icon drawn for each. Wi-Fi and battery levels
# are worked out in retro_icon_name. An icon without a pixel one keeps the icon theme's (in the phosphor colour).
ICONS = {
    "system-shutdown": "power",
    "system-lock-screen": "lock",
    "changes-prevent": "lock",
    "weather-clear-night": "moon",
    "system-log-out": "logout",
    "system-reboot": "refresh",
    "view-refresh": "refresh",
    "emblem-synchronizing": "refresh",
    "view-more": "dots",
    "view-list": "dots",
    "view-grid": "grid",
    "document-edit": "pencil",
    "input-tablet": "pencil",
    "window-close": "close",
    "network-offline": "close",
    "object-select": "check",
    "network-wired": "network",
    "preferences-system-network": "network",
    "network-wireless": "wifi-5",
    "network-wireless-encrypted": "wifi-5",
    "audio-volume-muted": "volume-muted",
    "audio-volume-low": "volume-low",
    "audio-volume-medium": "volume-medium",
    "audio-volume-high": "volume-high",
    "audio-speakers": "volume-high",
    "bluetooth": "bluetooth",
    "bluetooth-active": "bluetooth",
    "bluetooth-disabled": "bluetooth",
    "battery": "battery-3",
    "battery-caution": "battery-0",
    "battery-missing": "battery-0",
    "software-update-available": "update",
    "folder-download": "update",
    "list-add": "plus",
    "list-remove": "minus",
    "pan-down": "down",
    "pan-end": "right",
    "edit-find": "search",
    "video-display": "display",
    "computer": "computer",
    "input-keyboard": "keyboard",
    "input-mouse": "mouse",
    "input-gaming": "gamepad",
    "audio-headset": "headphones",
    "audio-headphones": "headphones",
    "phone": "phone",
    "multimedia-player": "music",
    "audio-input-microphone": "microphone",
    "emblem-system": "gear",
    "preferences-desktop-appearance": "appearance",
    "user-trash": "trash",
    "avatar-default": "user",
    "preferences-system-time": "clock",
    "drive-harddisk": "drive",
    "drive-removable-media": "removable",
    "starred": "star",
    "non-starred": "star-off",
}
WIFI_LEVELS = ("none", "weak", "ok", "good", "excellent")  # 1 to 5 bars lit

ICON_SETS = {
    "pixel": "tvwcs-retro",
    "vt323": "tvwcs-vt",
}  # by Settings > Appearance > Font: square pixels, or VT323's rounded ones


def retro_icon_name(name, prefix="tvwcs-retro"):
    """The pixel icon for an icon theme name ("audio-volume-high-symbolic" -> "tvwcs-retro-volume-high-symbolic"),
    or None when there is none. `prefix` picks the set (ICON_SETS)."""
    base = re.sub(r"-symbolic$", "", name or "")
    wifi = re.fullmatch(r"network-wireless-signal-(\w+)", base)
    battery = re.fullmatch(r"battery-level-(\d+)(-charging|-charged)?", base)
    if wifi and wifi.group(1) in WIFI_LEVELS:
        key = f"wifi-{WIFI_LEVELS.index(wifi.group(1))+1}"
    elif battery:
        level = int(battery.group(1))
        key = (
            "battery-charging"
            if battery.group(2) == "-charging"
            else f"battery-{0 if level<=10 else 1 if level<=40 else 2 if level<=70 else 3}"
        )
    else:
        key = ICONS.get(base)
    return f"{prefix}-{key}-symbolic" if key else None


def icon_pixel_size(px):
    """An icon's size in screen px: a whole multiple of its 9 pixels, so none is blurred."""
    return max(9, round(px / 9) * 9)


_fonts_added = [False]


def add_fonts():
    """Make the TVWCS Pixel fonts available to this process (fontconfig's application fonts), whether or not they are
    installed. Done once, before the first text is drawn. -> whether fontconfig took them."""
    if _fonts_added[0]:
        return True
    name = ctypes.util.find_library("fontconfig") or "libfontconfig.so.1"
    try:
        lib = ctypes.CDLL(name)
        lib.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.FcConfigAppFontAddFile.restype = ctypes.c_int
    except (OSError, AttributeError):
        return False
    ok = all(lib.FcConfigAppFontAddFile(None, str(f).encode()) for f in FONT_FILES if f.exists())
    _fonts_added[0] = ok
    return ok
