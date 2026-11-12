"""TVWCS's lock screen: swaylock, dressed in TVWCS's theme. A TVWCS session (TV mode) always locks with it; a desktop
session's own locker is left alone. Unlocking is as with any swaylock: type the password and press Enter.

Each screen gets a picture made for its size (an SVG, which swaylock loads through gdk-pixbuf and librsvg): a padlock,
"Locked" and how to unlock, in the Modern theme's light or dark colours with the accent, or in the Retro theme's
phosphor and pixel fonts on its background, or in the Media theme's colours for its look. swaylock's ring stays on screen below the text, so it is clear where the
password goes. The Retro fonts reach swaylock through a fontconfig file of its own (they are not installed for the
whole system). No GTK dependency, so it locks quickly.

"Lock the screen when TVWCS starts" (Settings > User, the "lock_at_start" setting): the session's config runs
`tvwcs lock-at-start` as sway starts, which locks straight away in a TVWCS session, for computers that log in
automatically. It never locks an account without a usable password, which could not be unlocked."""

from __future__ import annotations
import base64, json, os, re, shutil, subprocess, sys
from dataclasses import dataclass
from html import escape

from tvwcs import PACKAGE_DIR
from tvwcs.ui.retro import FONT_FILES, STATIC_PICTURE

# The colours theme.py gives the Settings window (theme.py loads GTK, so they are repeated here; a test keeps them
# the same): BG, FG and MUTED of the Modern looks and the Retro phosphors, with the Retro panel's LINE.
MODERN = {"dark": ("#1b1b1b", "#ffffff", "#b5b5b5"), "light": ("#f2f2f2", "#000000", "#4a4a4a")}
RETRO = {
    "green": ("#020a04", "#39ff6a", "#1fa845", "#0f5c24"),
    "amber": ("#0a0600", "#ffb000", "#b57a00", "#5c3f00"),
    "white": ("#05060a", "#e8eef8", "#97a0ae", "#3a404a"),
}
# The Media theme's looks: PANE, FG, MUTED and ACCENT, and the font (theme.MEDIA_PALETTES)
MEDIA = {
    "jellyfin": ("#181824", "#ffffff", "#b1b1c8", "#8e5ad8", "'Noto Sans', 'Open Sans', sans-serif", "Noto Sans"),
    "emby": ("#191919", "#ffffff", "#b8b8b8", "#4caf50", "Roboto, 'Noto Sans', 'Open Sans', sans-serif", "Roboto"),
    "plex": ("#1f2124", "#eeeeee", "#b4b6b9", "#e8a90f", "'Open Sans', 'Noto Sans', sans-serif", "Open Sans"),
}
RETRO_BACKGROUNDS = {"gray": "#808080", "blue": "#0000ff", "static": "static"}  # model.RETRO_WALLPAPERS
MODERN_FONT = "'Segoe UI', Selawik, 'Open Sans', 'Noto Sans', Cantarell, sans-serif"
RING_RADIUS = 70  # swaylock's ring, in its own (logical) pixels; the text sits above it
TITLE = "Locked"
HINT = "Type your password, then press Enter"


@dataclass(frozen=True)
class Look:
    retro: bool
    background: str  # the screen: a colour, or "static"
    panel: str  # Retro: the black box the text is in
    text: str
    muted: str
    accent: str  # the padlock and the ring
    line: str
    font: str  # the picture's text (CSS: a name such as 8x8 must be quoted)
    ring_font: str  # swaylock's own words in the ring ("Verifying", "Wrong")


def _hex(colour, fallback):
    return colour if isinstance(colour, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", colour) else fallback


def look_of(settings) -> Look:
    settings = settings or {}
    if settings.get("style") == "retro":
        bg, fg, muted, line = RETRO.get(settings.get("phosphor"), RETRO["green"])
        return Look(
            True,
            RETRO_BACKGROUNDS.get(settings.get("retro_wallpaper"), "#808080"),
            bg,
            fg,
            muted,
            fg,
            line,
            "'TVWCS Pixel 8x8', monospace",
            "TVWCS Pixel 5x7",
        )
    if settings.get("style") == "media":
        bg, fg, muted, accent, font, ring = MEDIA.get(settings.get("media_look"), MEDIA["jellyfin"])
        return Look(False, bg, bg, fg, muted, accent, muted, font, ring)
    bg, fg, muted = MODERN["light" if settings.get("theme") == "light" else "dark"]
    return Look(
        False, bg, bg, fg, muted, _hex(settings.get("accent"), "#0078d7").lower(), muted, MODERN_FONT, "Open Sans"
    )


def available(which=shutil.which):
    """True when swaylock is installed."""
    return bool(which("swaylock"))


def launcher():
    """The tvwcs launcher script, next to the package (as main.LAUNCHER finds it)."""
    here = PACKAGE_DIR
    for cand in (here.parent / "bin" / "tvwcs", here / "tvwcs", here.parent.parent / "bin" / "tvwcs"):
        if cand.exists():
            return str(cand)
    return "tvwcs"


def command(settings, env=None, which=shutil.which):
    """`tvwcs lock` in TV mode (a TVWCS session) when swaylock is installed, else None (the desktop's usual locker)."""
    from tvwcs.core.model import tv_mode

    if not tv_mode(env) or not available(which):
        return None
    return [launcher(), "lock"]


def _static_uri():
    try:
        return "data:image/png;base64," + base64.b64encode(STATIC_PICTURE.read_bytes()).decode()
    except OSError:
        return ""


def picture(width, height, look, static_uri=None) -> str:
    """The SVG for one screen of width x height pixels. The text is in its upper part: swaylock draws its ring in the
    middle (RING_RADIUS, at the screen's scale, stays clear of it from 720p up)."""
    w, h = max(int(width), 320), max(int(height), 240)
    u = h / 1080  # sizes are for 1080p, scaled to the screen
    title, hint = round(64 * u), round(30 * u)
    if look.retro:
        title, hint = max(8, round(title / 8) * 8), max(
            7, round(hint / 7) * 7
        )  # whole pixels of the 8 x 8 and 5 x 7 fonts
    cx = w / 2
    icon_top = 0.12 * h
    s = round(84 * u)  # the padlock: a shackle over a body, in the accent
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    if look.background == "static":
        uri = _static_uri() if static_uri is None else static_uri
        parts.append(f'<rect width="{w}" height="{h}" fill="#808080"/>')
        if uri:
            parts.append(
                f'<image width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice" style="image-rendering:pixelated" href="{uri}"/>'
            )
    else:
        parts.append(f'<rect width="{w}" height="{h}" fill="{look.background}"/>')
    if look.retro:  # a TV menu: a black box with a line round it, the text glowing a little
        bw, bh = min(w * 0.8, round(1000 * u)), 0.72 * h - icon_top + 0.04 * h  # the ring is inside it too
        parts.append(
            f'<defs><filter id="glow" x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation="{max(1.0,3*u):.1f}"/></filter></defs>'
        )
        parts.append(
            f'<rect x="{cx-bw/2:.0f}" y="{icon_top-0.04*h:.0f}" width="{bw:.0f}" height="{bh:.0f}" fill="{look.panel}" '
            f'stroke="{look.line}" stroke-width="{max(2,round(4*u))}"/>'
        )
    sw = max(4, round(s * 0.13))
    bx, by, bwid, bhei = cx - s / 2, icon_top + s * 0.45, s, s * 0.62
    lock = (
        f'<path d="M {cx-s*0.3:.1f} {by:.1f} V {icon_top+s*0.3:.1f} A {s*0.3:.1f} {s*0.3:.1f} 0 0 1 {cx+s*0.3:.1f} {icon_top+s*0.3:.1f} V {by:.1f}" '
        f'fill="none" stroke="{look.accent}" stroke-width="{sw}"{"" if look.retro else " stroke-linecap=\"square\""}/>'
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bwid:.1f}" height="{bhei:.1f}" fill="{look.accent}"/>'
        f'<rect x="{cx-sw/2:.1f}" y="{by+bhei*0.3:.1f}" width="{sw:.1f}" height="{bhei*0.36:.1f}" fill="{look.panel}"/>'
    )
    y1 = icon_top + s * 1.07 + title * 1.05
    y2 = y1 + hint * 1.9
    text = (
        f'<text x="{cx:.0f}" y="{y1:.0f}" text-anchor="middle" font-family="{escape(look.font)}" font-size="{title}" '
        f'font-weight="{"normal" if look.retro else "300"}" fill="{look.text}">{escape(TITLE)}</text>'
        f'<text x="{cx:.0f}" y="{y2:.0f}" text-anchor="middle" font-family="{escape(look.font if not look.retro else "'TVWCS Pixel 5x7', monospace")}" '
        f'font-size="{hint}" fill="{look.muted}">{escape(HINT)}</text>'
    )
    if look.retro:
        parts.append(f'<g filter="url(#glow)" opacity="0.6">{lock}{text}</g>')
    parts.append(lock + text + "</svg>")
    return "".join(parts)


def outputs(run=None):
    """The screens that are on: [(name, width, height)] in pixels, from sway."""
    try:
        out = (run or (lambda a: subprocess.run(a, capture_output=True, text=True, timeout=3).stdout))(
            ["swaymsg", "-r", "-t", "get_outputs"]
        )
        data = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    found = []
    for o in data if isinstance(data, list) else []:
        mode = o.get("current_mode") or {}
        if o.get("active") and o.get("name") and mode.get("width") and mode.get("height"):
            found.append((o["name"], int(mode["width"]), int(mode["height"])))
    return found


def fonts_conf(folder) -> str:
    """A fontconfig file for swaylock: the system's fonts and the Retro theme's."""
    dirs = "".join(f"<dir>{escape(str(d))}</dir>" for d in sorted({str(f.parent) for f in FONT_FILES}))
    return (
        f'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
        f'<include ignore_missing="yes">/etc/fonts/fonts.conf</include>{dirs}'
        f'<cachedir>{escape(str(folder/"fontconfig"))}</cachedir></fontconfig>\n'
    )


def locker_argv(settings=None, pictures=()):
    """swaylock's command line. -f: it goes to the background once the screen is locked; -e: an empty Enter is not a
    wrong password; -F: failed attempts show. pictures: [(output, path)], one per screen. The ring is always shown,
    in the theme's colours, with the screen's own colour inside."""
    look = look_of(settings)
    c = lambda col: col[1:].lower()
    inside = look.panel  # Modern: the screen's colour; Retro: its black box
    argv = ["swaylock", "-f", "-e", "-F", "-c", c(look.background if look.background.startswith("#") else "#808080")]
    for name, path in pictures:
        argv += ["-i", f"{name}:{path}"]
    if pictures:
        argv += ["-s", "fill"]
    argv += [
        "--indicator-idle-visible",
        "--indicator-radius",
        str(RING_RADIUS),
        "--indicator-thickness",
        "8",
        "--font",
        look.ring_font,
        "--ring-color",
        c(look.accent),
        "--key-hl-color",
        c(look.text),
        "--bs-hl-color",
        c(look.muted),
        "--inside-color",
        c(inside),
        "--line-color",
        c(inside),
        "--separator-color",
        c(inside),
        "--text-color",
        c(look.text),
    ]
    for state in ("clear", "ver", "wrong", "caps-lock"):
        argv += [
            f"--inside-{state}-color",
            c(inside),
            f"--line-{state}-color",
            c(inside),
            f"--text-{state}-color",
            c(look.text),
        ]
    argv += ["--ring-ver-color", c(look.muted), "--ring-clear-color", c(look.muted)]
    return argv


def make_pictures(settings, folder, screens=None):
    """Write one picture per screen into folder -> [(output, path)] (empty when sway cannot be asked)."""
    look = look_of(settings)
    made = []
    static = _static_uri() if look.background == "static" else ""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    for name, w, h in (outputs() if screens is None else screens):
        path = folder / f"lock-{re.sub(r'[^A-Za-z0-9_.-]','_',name)}.svg"
        try:
            path.write_text(picture(w, h, look, static), encoding="utf-8")
            made.append((name, str(path)))
        except OSError:
            pass
    return made


def can_unlock(status) -> bool:
    """False when `passwd -S` says the account has no password or a locked one: swaylock would never let it back in."""
    return status not in ("NP", "L")


def lock_at_start(settings, env=None, which=shutil.which, status=None) -> str:
    """Why the session does not start locked, or "" when it does."""
    from tvwcs.settings.account import password_status

    if not settings.get("lock_at_start"):
        return "off"
    if command(settings, env, which) is None:
        return "not a TVWCS session, or swaylock is not installed"
    if not can_unlock(password_status() if status is None else status):
        return "the account has no password to unlock it with"
    return ""


def lock(settings=None):
    """`tvwcs lock`: start swaylock."""
    if not available():
        print("TVWCS's lock screen needs swaylock.", file=sys.stderr)
        return 1
    from tvwcs.system.session import runtime_dir

    folder = runtime_dir() / "tvwcs-lock"
    argv = locker_argv(settings, make_pictures(settings, folder))
    try:
        (folder / "fonts.conf").write_text(fonts_conf(folder), encoding="utf-8")
        os.environ["FONTCONFIG_FILE"] = str(folder / "fonts.conf")
    except OSError:
        pass
    os.execvp(argv[0], argv)


def main(args):
    """`tvwcs lock` and `tvwcs lock-at-start` (the launcher runs these without loading GTK)."""
    from tvwcs.core.model import ConfigStore

    settings = ConfigStore().settings
    if args == ["lock-at-start"]:
        why = lock_at_start(settings)
        if why:
            return 0 if why == "off" else (print(f"TVWCS: not locking at start: {why}.", file=sys.stderr) or 0)
    return lock(settings)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
