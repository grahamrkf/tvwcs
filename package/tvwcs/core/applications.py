"""Discover graphical Linux applications from XDG .desktop entries."""

from __future__ import annotations
import configparser, os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CATEGORY_ORDER = ("Media", "Internet", "Games", "Office", "Graphics", "Development", "Utilities", "System", "Other")
_CATEGORY_MAP = {
    "AudioVideo": "Media",
    "Audio": "Media",
    "Video": "Media",
    "Player": "Media",
    "Recorder": "Media",
    "Network": "Internet",
    "WebBrowser": "Internet",
    "Email": "Internet",
    "Chat": "Internet",
    "Game": "Games",
    "Office": "Office",
    "WordProcessor": "Office",
    "Spreadsheet": "Office",
    "Presentation": "Office",
    "Graphics": "Graphics",
    "2DGraphics": "Graphics",
    "3DGraphics": "Graphics",
    "Photography": "Graphics",
    "Publishing": "Graphics",
    "Development": "Development",
    "IDE": "Development",
    "Debugger": "Development",
    "Utility": "Utilities",
    "TextEditor": "Utilities",
    "FileManager": "Utilities",
    "Settings": "System",
    "System": "System",
    "Monitor": "System",
    "Security": "System",
}


@dataclass(frozen=True)
class Application:
    desktop_id: str
    name: str
    generic_name: str | None
    comment: str | None
    icon: str | None
    categories: tuple[str, ...]
    desktop_file: str
    exec_line: str | None
    desktop_actions: tuple[tuple[str, str], ...] = ()
    wm_class: str | None = None  # StartupWMClass: the window class the app's windows use

    @property
    def primary_category(self) -> str:
        return self.categories[0] if self.categories else "Other"


class ApplicationCatalogue:
    def __init__(self, applications: Iterable[Application] = ()):
        self.applications = tuple(applications)

    @classmethod
    def discover(cls) -> "ApplicationCatalogue":
        found = []
        seen = set()
        for desktop_id, path in _desktop_files_in_precedence_order():
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            app = _parse_desktop_file(desktop_id, path)
            if app:
                found.append(app)
        found.sort(key=lambda a: (CATEGORY_ORDER.index(a.primary_category), a.name.casefold()))
        return cls(found)

    def by_category(self) -> dict[str, tuple[Application, ...]]:
        groups = {c: [] for c in CATEGORY_ORDER}
        for app in self.applications:
            groups.setdefault(app.primary_category, []).append(app)
        return {c: tuple(groups[c]) for c in CATEGORY_ORDER if groups.get(c)}

    def by_id(self) -> dict[str, Application]:
        return {app.desktop_id: app for app in self.applications}


def _application_directories() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    dirs = [home / "applications"]
    dirs.extend(
        Path(p) / "applications" for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p
    )
    return dirs


def _desktop_files_in_precedence_order():
    seen = set()
    for directory in _application_directories():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.desktop"), key=lambda p: p.as_posix().casefold()):
            # XDG nested desktop IDs encode subdirectories with hyphens.
            desktop_id = path.relative_to(directory).as_posix().replace("/", "-")
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            yield desktop_id, path


def _parse_desktop_file(desktop_id: str, path: Path) -> Application | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            parser.read_file(f)
    except (OSError, configparser.Error):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    e = parser["Desktop Entry"]
    if e.get("Type", "Application") != "Application" or _boolean(e.get("Hidden")) or _boolean(e.get("NoDisplay")):
        return None
    if _boolean(e.get("Terminal")) or not _environment_allows(e):
        return None
    name = _localized(e, "Name")
    if not name:
        return None
    cats = []
    for raw in _split(e.get("Categories", "")):
        mapped = _CATEGORY_MAP.get(raw)
        if mapped and mapped not in cats:
            cats.append(mapped)
    cats.sort(key=lambda c: CATEGORY_ORDER.index(c))
    action_ids = _split(e.get("Actions", ""))
    actions = []
    for action_id in action_ids:
        section = f"Desktop Action {action_id}"
        if parser.has_section(section):
            action_name = _localized(parser[section], "Name") or action_id
            if parser[section].get("Exec"):
                actions.append((action_id, action_name))
    return Application(
        desktop_id,
        name,
        _localized(e, "GenericName"),
        _localized(e, "Comment"),
        e.get("Icon") or None,
        tuple(cats[:1] or ["Other"]),
        str(path),
        e.get("Exec") or None,
        tuple(actions),
        e.get("StartupWMClass") or None,
    )


def _localized(section, key):
    candidates = []
    candidates.extend(x for x in os.environ.get("LANGUAGE", "").split(":") if x)
    lang = os.environ.get("LANG", "")
    if lang:
        candidates.extend([lang, lang.split(".", 1)[0], lang.split("_", 1)[0]])
    for locale in dict.fromkeys(candidates):
        locale = locale.split("@", 1)[0]
        if f"{key}[{locale}]" in section:
            return section.get(f"{key}[{locale}]")
    return section.get(key) or None


def _boolean(value):
    return (value or "").strip().casefold() == "true"


def _split(value):
    return [x for x in (value or "").split(";") if x]


def _environment_allows(e):
    current = {x.casefold() for x in os.environ.get("XDG_CURRENT_DESKTOP", "").replace(":", ";").split(";") if x}
    only = {x.casefold() for x in _split(e.get("OnlyShowIn", ""))}
    not_show = {x.casefold() for x in _split(e.get("NotShowIn", ""))}
    return (not only or bool(current & only)) and not bool(current & not_show)


def _norm(s):
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


def match_window(window, applications):
    """Best-effort: find the Application a window belongs to (or None).
    Exact StartupWMClass / class / instance matches win over fuzzy name matching."""
    cls = _norm(window.get("class"))
    inst = _norm(window.get("instance"))
    title = _norm(window.get("title"))
    ids = {cls, inst} - {""}
    apps = list(applications)
    for app in apps:
        w = _norm(app.wm_class)
        if w and w in ids:
            return app

    def candidates(app):
        return {
            c
            for c in (_norm(app.name), _norm(app.desktop_id.split(".")[0]), _norm(app.desktop_id.rsplit(".", 1)[0]))
            if c
        }

    for app in apps:
        if candidates(app) & ids:
            return app
    for app in apps:
        if any(len(c) > 4 and c in title for c in candidates(app)):
            return app
    return None
