"""Updating TVWCS itself from its GitHub releases: find the latest published release (or, for those who want them,
the newest prerelease), compare it with the running version, download its .deb packages and install them as root with
apt. Each merged change is released as a prerelease first and marked latest once it has been tested, so "the latest
release" is also what a prerelease rolls back to.

A release has one .deb, tvwcs. (5.0.x also had tvwcs-boot-logo; the tvwcs package now conflicts with it, so apt
removes it with the update.) From 5.15.0 it also has an .rpm for Fedora, which is installed the same way with dnf.
A vendor that ships TVWCS can point this elsewhere in its vendor.json (vendor.py): its fork's GitHub releases, a
release list on its own site in the same form as GitHub's answer, or nowhere ("system": its package repository
delivers TVWCS; "off"). No GTK here, so it can be tested without a display; the Settings panel runs these calls on a
worker thread."""

from __future__ import annotations
import json, os, re, shutil, subprocess, tempfile, urllib.error, urllib.request
from dataclasses import dataclass
from pathlib import Path

from tvwcs import vendor

GITHUB_REPO = "grahamrkf/tvwcs"
LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
PACKAGES = ("tvwcs",)
LIB = "/usr/lib/tvwcs"  # where the tvwcs package puts the Python package
MAX_DOWNLOAD = 50 * 1024 * 1024  # a release's .deb is a few hundred KB; anything near this is not one
TIMEOUT = 20


class UpdateError(Exception):
    """A readable reason the check or the install did not work."""


@dataclass
class Release:
    version: str
    tag: str
    debs: dict  # package name -> download URL
    page_url: str
    prerelease: bool = False
    rpm: str = ""  # the Fedora package's download URL (5.15.0 and later)


def parse_version(text):
    """'v2.6.0' or '2.6.0' -> (2, 6, 0). Anything after the numbers (such as '-beta.2') is ignored."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not m:
        raise UpdateError(f"Cannot read the version number “{text}”.")
    return tuple(int(n) for n in m.group(1).split("."))


def is_newer(candidate, current):
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


_DEB = re.compile(r"(tvwcs(?:-[a-z-]+)?)_([0-9][0-9.]*)_all\.deb")
_RPM = re.compile(r"tvwcs-([0-9][0-9.]*)-[0-9]+\.noarch\.rpm")


def release_from_json(data):
    """Pick the version and the .deb packages out of one of GitHub's release answers."""
    tag = str(data.get("tag_name") or "")
    debs = {}
    rpm = ""
    for a in data.get("assets") or []:
        m = _DEB.fullmatch(str(a.get("name", "")))
        if m and m.group(1) in PACKAGES:
            debs[m.group(1)] = a.get("browser_download_url")
        if _RPM.fullmatch(str(a.get("name", ""))):
            rpm = str(a.get("browser_download_url") or "")
    if not tag or "tvwcs" not in debs:
        raise UpdateError("That release on GitHub has no TVWCS .deb package attached.")
    return Release(
        ".".join(map(str, parse_version(tag))),
        tag,
        debs,
        str(data.get("html_url") or ""),
        bool(data.get("prerelease")),
        rpm,
    )


def newest_release(items):
    """The newest version among GitHub's /releases list, prereleases included; drafts and releases without TVWCS's
    .deb (4.x and older) are skipped. None when there is none."""
    found = []
    for data in items if isinstance(items, list) else []:
        if not isinstance(data, dict) or data.get("draft"):
            continue
        try:
            found.append(release_from_json(data))
        except UpdateError:
            continue
    return max(found, key=lambda r: parse_version(r.version), default=None)


def _open(url, accept):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "TVWCS-updater"})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def source():
    """Where TVWCS's own updates come from: vendor.Updates (source github, url, system or off)."""
    return vendor.load(report=False).updates


def repo(updates=None):
    """The GitHub repository whose releases are TVWCS's updates."""
    u = updates or source()
    return u.repo if u.source == "github" and u.repo else GITHUB_REPO


def self_updates(updates=None):
    """Settings offers to check for and install TVWCS updates itself (not when the system's packages deliver them,
    or the vendor turned them off)."""
    return (updates or source()).source in ("github", "url")


def where(updates=None):
    """Where the updates are looked for, for Settings' note: "GitHub (owner/name)" or the release list's site."""
    u = updates or source()
    if u.source == "url":
        return re.sub(r"^https://([^/]+).*$", r"\1", u.url)
    return f"GitHub ({repo(u)})"


def installer_url(updates=None):
    """Where the installer for the latest release is (for Arch, which builds TVWCS with it)."""
    return f"https://github.com/{repo(updates)}/releases/latest/download/install.sh"


def _get_json(url):
    try:
        with _open(url, "application/vnd.github+json") as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(f"No published release was found at {_host(url)}.") from exc
        raise UpdateError(f"{_host(url)} answered {exc.code} {exc.reason}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Could not reach {_host(url)}: {getattr(exc,'reason',exc)}") from exc


def _host(url):
    return "GitHub" if url.startswith("https://api.github.com/") else re.sub(r"^https?://([^/]+).*$", r"\1", url)


def _from_list(items, prereleases):
    """A vendor's release list: GitHub's /releases answer, or {"releases": [...]} with the same entries. The latest
    release is the newest that is not a prerelease."""
    if isinstance(items, dict):
        items = items.get("releases")
    if not isinstance(items, list):
        raise UpdateError("The release list is not in the form TVWCS reads (a list of releases).")
    newest = newest_release([r for r in items if prereleases or not (isinstance(r, dict) and r.get("prerelease"))])
    if newest is None:
        raise UpdateError("The release list has no release with a TVWCS package.")
    return newest


def _https(release):
    """A vendor's list may only send TVWCS to https:// downloads."""
    for u in [*release.debs.values(), *([release.rpm] if release.rpm else [])]:
        if not str(u).startswith("https://"):
            raise UpdateError("The release list names a download that is not https://.")
    return release


def latest_release(prereleases=False, updates=None):
    """The release marked latest (on GitHub, or in the vendor's list); with prereleases, the newest release of all,
    when that is newer."""
    u = updates or source()
    if u.source == "url":
        return _https(_from_list(_get_json(u.url), prereleases))
    if u.source != "github":
        raise UpdateError("TVWCS is updated with this system's own updates.")
    r = repo(u)
    latest_url, releases_url = (
        (LATEST_URL, RELEASES_URL)
        if r == GITHUB_REPO
        else (
            f"https://api.github.com/repos/{r}/releases/latest",
            f"https://api.github.com/repos/{r}/releases?per_page=30",
        )
    )
    latest = release_from_json(_get_json(latest_url))
    if not prereleases:
        return latest
    newest = newest_release(_get_json(releases_url))
    return newest if newest is not None and is_newer(newest.version, latest.version) else latest


def packaged(package_dir=None):
    """True when this TVWCS was installed from its .deb (it runs from /usr/lib/tvwcs), not from a source checkout,
    which is updated with git instead."""
    return Path(package_dir or Path(__file__).resolve().parent).resolve().parent == Path(LIB)


PACKAGE_MARK = (
    "PACKAGE"  # in LIB: names the distribution package TVWCS came from when it is not the .deb (arch, fedora)
)
RPM = "fedora"


def other_package(lib=LIB):
    """The kind of package this TVWCS was installed from when it is not the .deb from GitHub ("arch": built from its
    PKGBUILD; "fedora": the .rpm from GitHub), or ""."""
    try:
        return Path(lib, PACKAGE_MARK).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def builds_itself(lib=LIB):
    """Arch's package is built from its PKGBUILD, so a new release is installed with TVWCS's installer, never from here."""
    return other_package(lib) == "arch"


def installed_packages(run=subprocess.run, kind=None):
    """Which of TVWCS's packages are installed here."""
    if (other_package() if kind is None else kind) == RPM:
        try:
            done = run(["rpm", "-q", "--qf", "%{NAME}\\n", *PACKAGES], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return []
        found = [l.strip() for l in (done.stdout or "").splitlines()]  # 'package tvwcs is not installed' when it is not
        return [p for p in PACKAGES if p in found]
    try:
        done = run(
            ["dpkg-query", "-W", "-f=${Package} ${db:Status-Status}\\n", *PACKAGES],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = [
        l.split()[0] for l in (done.stdout or "").splitlines() if len(l.split()) == 2 and l.split()[1] == "installed"
    ]
    return [p for p in PACKAGES if p in found]


def _download(url, target):
    try:
        with _open(url, "application/octet-stream") as r, open(target, "wb") as out:
            total = 0
            while chunk := r.read(65536):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise UpdateError("The download is far larger than a TVWCS package; stopped.")
                out.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"Download failed: {getattr(exc,'reason',exc)}") from exc


def download(release, packages, kind=None):
    """Download the release's .deb of each package in `packages` (on Fedora, its .rpm) into a new temporary folder.
    Returns (folder, files); the caller deletes the folder (discard) once it has been installed or the update was
    cancelled. The folder and files can be read by everyone: apt reads them as its own _apt user."""
    kind = other_package() if kind is None else kind
    if kind == RPM and not release.rpm:
        raise UpdateError(
            f"TVWCS {release.version} has no Fedora package (.rpm): the first release with one is 5.15.0."
        )
    wanted = [p for p in packages if p in release.debs] or list(release.debs)[:1]
    tmp = Path(tempfile.mkdtemp(prefix="tvwcs-update-"))
    try:
        os.chmod(tmp, 0o755)
        files = []
        if kind == RPM:
            f = tmp / f"tvwcs-{release.version}-1.noarch.rpm"
            _download(release.rpm, f)
            os.chmod(f, 0o644)
            with open(f, "rb") as fh:
                if fh.read(4) != b"\xed\xab\xee\xdb":
                    raise UpdateError("The downloaded TVWCS package is not an .rpm.")
            return tmp, [f]
        for name in wanted:
            f = tmp / f"{name}_{release.version}_all.deb"
            _download(release.debs[name], f)
            os.chmod(f, 0o644)
            with open(f, "rb") as fh:
                if fh.read(8) != b"!<arch>\n":
                    raise UpdateError(f"The downloaded {name} package is not a .deb.")
            files.append(f)
    except BaseException:
        discard(tmp)
        raise
    return tmp, files


def discard(folder):
    shutil.rmtree(folder, ignore_errors=True)


def install_argv(files, kind=None, current=None, version=None):
    """The root command that installs downloaded .deb files with apt (or an .rpm with dnf), with the packages they need.
    A rollback is an older version, so downgrades are allowed: dnf needs to be told (current: the version installed,
    version: the one in `files`)."""
    names = [str(f) for f in files]
    if (other_package() if kind is None else kind) == RPM:
        verb = "install"
        if current and version and parse_version(version) != parse_version(current):
            verb = "install" if is_newer(version, current) else "downgrade"
        elif current and version:
            verb = "reinstall"
        return ["dnf", verb, "-y", *names]
    return ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "--allow-downgrades", *names]
