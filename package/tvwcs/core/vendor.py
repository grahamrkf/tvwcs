"""Vendor and system-wide presets: for a distribution, or a ready-made TV computer image, that ships TVWCS.

Optional JSON files, read in this order, each one's values winning over the one before:

  /usr/lib/tvwcs/updates.json    TVWCS's own: only in the packages TVWCS's GitHub releases attach (.deb, .rpm, Arch's
                                 PKGBUILD), turning on its updater for its GitHub releases
  /usr/share/tvwcs/vendor.json   the vendor's: shipped by the vendor's own package (TVWCS's packages never ship it)
  /etc/tvwcs/defaults.json       the local administrator's: same keys, for one computer or a fleet

and then each user's ~/.config/tvwcs/config.json. Neither file is needed; without them TVWCS behaves as it always has.
They hold (every key optional; docs/VENDORS.md has the full list and an example):

  "name"         the vendor's or system's name, shown in Settings > System information (e.g. "Example TV")
  "support_url"  a web page for help, shown there too
  "updates"      where TVWCS looks for its own updates: {"source": "github", "repo": "owner/name"} (a fork's releases),
                 {"source": "url", "url": "https://.../releases.json"} (a release list on the vendor's site),
                 {"source": "system"} (the vendor's apt/dnf repository delivers TVWCS: no updater of its own),
                 or {"source": "off"}. Without any: "system", as for TVWCS packaged by a distribution, which updates
                 it with the rest of the system (TVWCS's own packages have updates.json for their GitHub updates).
  "settings"     preset values for any of config.json's "settings" (theme, hotkeys, idle times, ...): the defaults a
                 user starts from. What a user changes is saved in their config.json; the rest keeps following these.
  "channels"     [{"desktop_id": "org.example.Player.desktop", "channel": 1, "favorite": true}, ...]: given to an
                 application the first time TVWCS sees it, when that channel is still free
  "startup_app"  the .desktop file of the application to open at login ("Open at login: Chosen application"), set
                 once for a user who has not chosen one

A file that cannot be read, or a value that is not valid, is skipped (with a line on stderr naming it) and the rest is
used, so a mistake in a preset never stops TVWCS from starting. `tvwcs vendor` shows what was read and what was skipped.
No GTK here."""

from __future__ import annotations
import copy, json, os, re, sys
from dataclasses import dataclass, field

PACKAGE_FILE = "/usr/lib/tvwcs/updates.json"
VENDOR_FILE = "/usr/share/tvwcs/vendor.json"
ADMIN_FILE = "/etc/tvwcs/defaults.json"
UPDATE_SOURCES = ("github", "url", "system", "off")
_REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
_DESKTOP = re.compile(r"[^/\s]+\.desktop")
MAX_NAME = 60


def paths():
    """The files, in reading order (TVWCS_PACKAGE_FILE, TVWCS_VENDOR_FILE and TVWCS_DEFAULTS_FILE change them, for
    tests and for trying a file out before packaging it)."""
    return (
        os.environ.get("TVWCS_PACKAGE_FILE", PACKAGE_FILE),
        os.environ.get("TVWCS_VENDOR_FILE", VENDOR_FILE),
        os.environ.get("TVWCS_DEFAULTS_FILE", ADMIN_FILE),
    )


@dataclass
class Updates:
    source: str = "system"
    repo: str = ""  # source github: owner/name ("" = TVWCS's own)
    url: str = ""  # source url: the release list


@dataclass
class Vendor:
    name: str = ""
    support_url: str = ""
    updates: Updates = field(default_factory=Updates)
    settings: dict = field(default_factory=dict)  # raw preset values, merged; model._clean_settings checks them
    channels: dict = field(default_factory=dict)  # desktop_id -> {"channel": int or None, "favorite": bool}
    startup_app: str = ""
    files: list = field(default_factory=list)  # the files that were read
    problems: list = field(default_factory=list)  # "file: what was skipped"


def merge(base, top):
    """A copy of base with top's values over it; dicts are merged key by key, all the way down."""
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for k, v in (top.items() if isinstance(top, dict) else ()):
        out[k] = merge(out.get(k), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def difference(values, base):
    """What in values differs from base: the keys a user changed. Dicts are compared key by key, so a changed hotkey
    is saved without freezing the others."""
    out = {}
    for k, v in values.items():
        b = base.get(k) if isinstance(base, dict) else None
        if isinstance(v, dict) and isinstance(b, dict):
            d = difference(v, b)
            if d:
                out[k] = d
        elif k not in (base or {}) or v != b:
            out[k] = copy.deepcopy(v)
    return out


def _web(url):
    return isinstance(url, str) and re.fullmatch(r"https://[^\s/]+(/\S*)?", url.strip()) is not None


def _apply(v, data, where):
    """Take one file's valid keys into v; note what is skipped."""

    def bad(what):
        v.problems.append(f"{where}: {what}")

    if not isinstance(data, dict):
        bad("not a JSON object, ignored")
        return
    known = {"name", "support_url", "updates", "settings", "channels", "startup_app", "comment", "_comment"}
    for k in data:
        if k not in known:
            bad(f"unknown key “{k}”, ignored")
    if "name" in data:
        if isinstance(data["name"], str) and data["name"].strip():
            v.name = " ".join(data["name"].split())[:MAX_NAME]
        else:
            bad("name is not text")
    if "support_url" in data:
        if _web(data["support_url"]):
            v.support_url = data["support_url"].strip()
        else:
            bad("support_url is not an https:// address")
    if "updates" in data:
        u = data["updates"]
        src = u.get("source") if isinstance(u, dict) else None
        if src not in UPDATE_SOURCES:
            bad(f"updates.source must be one of {', '.join(UPDATE_SOURCES)}")
        elif (
            src == "github"
            and u.get("repo") not in (None, "")
            and not (isinstance(u.get("repo"), str) and _REPO.fullmatch(u["repo"]))
        ):
            bad("updates.repo must look like owner/name")
        elif src == "url" and not _web(u.get("url")):
            bad("updates.url must be an https:// address")
        else:
            v.updates = Updates(
                src, str(u.get("repo") or "") if src == "github" else "", u["url"].strip() if src == "url" else ""
            )
    if "settings" in data:
        if isinstance(data["settings"], dict):
            v.settings = merge(v.settings, data["settings"])
        else:
            bad("settings is not a JSON object")
    if "channels" in data:
        if not isinstance(data["channels"], list):
            bad("channels is not a list")
        else:
            for i, c in enumerate(data["channels"]):
                d = c.get("desktop_id") if isinstance(c, dict) else None
                if not (isinstance(d, str) and _DESKTOP.fullmatch(d)):
                    bad(f"channels[{i}] has no desktop_id ending in .desktop")
                    continue
                ch = c.get("channel")
                if ch is not None and (isinstance(ch, bool) or not isinstance(ch, int) or ch < 0):
                    bad(f"channels[{i}] channel is not a number")
                    ch = None
                fav = c.get("favorite", False)
                v.channels[d] = {"channel": ch, "favorite": fav if isinstance(fav, bool) else False}
    if "startup_app" in data:
        if isinstance(data["startup_app"], str) and _DESKTOP.fullmatch(data["startup_app"]):
            v.startup_app = data["startup_app"]
        else:
            bad("startup_app is not a .desktop file name")


def load(files=None, report=True) -> Vendor:
    """The presets from the vendor's and the administrator's files (either or both may be missing)."""
    v = Vendor()
    for path in files if files is not None else paths():
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            continue
        except OSError as exc:
            v.problems.append(f"{path}: cannot be read ({exc.strerror})")
            continue
        try:
            data = json.loads(text)
        except ValueError as exc:
            v.problems.append(f"{path}: not valid JSON ({exc}), ignored")
            continue
        v.files.append(path)
        _apply(v, data, path)
    if report:
        for p in v.problems:
            print("tvwcs: " + p, file=sys.stderr)
    return v


def describe(v=None) -> str:
    """`tvwcs vendor`: what TVWCS read from the preset files, for a packager checking theirs."""
    v = v or load(report=False)
    lines = []
    for path in paths():
        lines.append(f"{path}: {'read' if path in v.files else 'not used'}")
    lines.append(f"Name: {v.name or '(none)'}")
    lines.append(f"Support page: {v.support_url or '(none)'}")
    u = v.updates
    lines.append(
        "TVWCS updates: "
        + {
            "github": f"GitHub releases of {u.repo or 'TVWCS'}",
            "url": f"the release list at {u.url}",
            "system": "delivered by the system's package manager",
            "off": "off",
        }[u.source]
    )
    from tvwcs.core.model import _clean_settings

    clean = _clean_settings(v.settings)
    for k in sorted(v.settings):
        if k not in clean:
            v.problems.append(f"settings: unknown setting “{k}”, ignored")
        elif v.settings[k] != clean[k] and not isinstance(v.settings[k], dict):
            v.problems.append(f"settings: “{k}”: {json.dumps(v.settings[k])} is not valid, ignored")
    for k in sorted(v.settings):
        if k in clean:
            lines.append(f"  setting {k} = {json.dumps(clean[k])}")
    for d, c in v.channels.items():
        lines.append(
            f"  channel {c['channel'] if c['channel'] is not None else '-'}: {d}"
            + (" (favorite)" if c["favorite"] else "")
        )
    if v.startup_app:
        lines.append(f"  open at login: {v.startup_app}")
    lines += ["Problems:", *("  " + p for p in v.problems)] if v.problems else ["No problems found."]
    return "\n".join(lines)


if __name__ == "__main__":
    v = load(report=False)
    print(describe(v))
    raise SystemExit(1 if v.problems else 0)
