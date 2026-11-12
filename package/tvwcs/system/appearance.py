"""TVWCS's light or dark look passed on to applications, and the background colour. No GTK dependency.

Applications that follow the desktop's colour scheme read it from different places, so TVWCS sets each of them:
- GNOME's setting org.gnome.desktop.interface color-scheme ("prefer-dark" or "default"): GTK 4 and libadwaita apps,
  and, through xdg-desktop-portal's Settings interface, Firefox and Chromium-based browsers;
- gtk-application-prefer-dark-theme in ~/.config/gtk-3.0/settings.ini and gtk-4.0/settings.ini: GTK 3 and GTK 4 apps
  that do not read GNOME's settings.
Qt applications keep their own look.

The background colour (or the Retro theme's TV static picture, retro/static.png) is set as sway's output background."""

from __future__ import annotations
import configparser, io, os, re, shutil
from pathlib import Path

from tvwcs.settings.cmd import have, run
from tvwcs.ui.retro import STATIC_PICTURE

GTK_INI_KEY = "gtk-application-prefer-dark-theme"


def config_home(env=None):
    env = os.environ if env is None else env
    return Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME") or Path.home()) / ".config")


def with_dark_preference(text, dark):
    """settings.ini with gtk-application-prefer-dark-theme set in [Settings], everything else left as it was."""
    lines = (text or "").splitlines()
    out = []
    section = None
    done = False
    has_settings = False
    for line in lines:
        m = re.match(r"\s*\[([^\]]+)\]", line)
        if m:
            if section == "Settings" and not done:
                out.append(f"{GTK_INI_KEY}={'1' if dark else '0'}")
                done = True
            section = m.group(1).strip()
            has_settings = has_settings or section == "Settings"
        elif section == "Settings" and re.match(rf"\s*{re.escape(GTK_INI_KEY)}\s*=", line):
            if not done:
                out.append(f"{GTK_INI_KEY}={'1' if dark else '0'}")
                done = True
            continue
        out.append(line)
    if not done:
        if not has_settings:
            if out and out[-1].strip():
                out.append("")
            out.append("[Settings]")
        out.append(f"{GTK_INI_KEY}={'1' if dark else '0'}")
    return "\n".join(out) + "\n"


def gtk_prefers_dark(text):
    """The value of gtk-application-prefer-dark-theme in a settings.ini, or None."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read_file(io.StringIO(text or ""))
    except configparser.Error:
        return None
    value = parser.get("Settings", GTK_INI_KEY, fallback=None)
    return None if value is None else value.strip().lower() in ("1", "true", "yes")


def color_scheme(theme):
    return "prefer-dark" if theme != "light" else "default"


def apply_theme(theme, env=None):
    """Tell applications whether to be dark or light. Returns what could not be done ("" when everything worked)."""
    dark = theme != "light"
    problems = []
    if have("gsettings"):
        r = run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", color_scheme(theme)], timeout=5)
        if not r.ok and "No such schema" not in (r.err or ""):
            problems.append(r.message or "gsettings did not work")
    base = config_home(env)
    for folder in ("gtk-3.0", "gtk-4.0"):
        path = base / folder / "settings.ini"
        try:
            old = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            old = ""
        except OSError as exc:
            problems.append(f"{path}: {exc.strerror}")
            continue
        if gtk_prefers_dark(old) == dark:
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name("settings.ini.tvwcs-new")
            tmp.write_text(with_dark_preference(old, dark), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            problems.append(f"{path}: {exc.strerror}")
    return "; ".join(problems)


def portal_missing(which=shutil.which, exists=os.path.exists):
    """Browsers learn the colour scheme through xdg-desktop-portal's GTK (or GNOME) back end. True when
    neither is installed, so Settings can say what to install."""
    names = ("xdg-desktop-portal-gtk", "xdg-desktop-portal-gnome")
    places = ("/usr/libexec", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib")
    return not any(which(n) or any(exists(f"{p}/{n}") for p in places) for n in names)


# ---------------------------------------------------------------------- the background colour
def wallpaper_argv(colour):
    """A colour, or "static": the TV static picture, stretched over each screen (its grains are the same size on a
    1080p and a 4K screen)."""
    if colour == "static":
        return ["swaymsg", f'output * bg "{STATIC_PICTURE}" fill']
    return ["swaymsg", f"output * bg {colour} solid_color"]


def apply_wallpaper(colour, env=None):
    """Paint the background. Returns "" when it worked, else why not."""
    env = os.environ if env is None else env
    if not env.get("SWAYSOCK"):
        return "The background colour is set in sway only."
    argv = wallpaper_argv(colour)
    if not have(argv[0]):
        return "swaymsg was not found."
    r = run(argv, timeout=5)
    return "" if r.ok else (r.message or "The background colour could not be set.")
