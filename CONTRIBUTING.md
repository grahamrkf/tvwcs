# Working on TVWCS

TVWCS is plain Python 3 with GTK 4 (through python3-gi): nothing is compiled, and there is no pip install. This page
is how to run it, test a change and get it released. What TVWCS is and how it works inside is in
[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md); which file to open for a given change is in
[docs/WHERE-TO-CHANGE.md](docs/WHERE-TO-CHANGE.md).

## Run it from the repository

```sh
sudo apt install sway gir1.2-gtk-4.0 python3-gi python3-gi-cairo   # Debian/Ubuntu; see docs/ for Arch and Fedora
./package/bin/tvwcs            # inside a sway session: the launcher, from this checkout
./package/bin/tvwcs settings   # the Settings app
```

`package/bin/tvwcs` finds the `tvwcs` package next to it, so nothing needs installing. To try it as users get it,
build the package (`./scripts/build-debs.sh`) and install `resources/tvwcs_<version>_all.deb`.

No TV at hand? `tools/demo/README.md` runs TVWCS in a headless sway session and takes screenshots, which is also how
the README's pictures are made.

## Test a change

```sh
./scripts/run-tests.sh   # every unit test, in a few seconds, with no display
```

- Code without GTK (everything outside `ui/`, `settings/app.py` and `settings/pages/`) is unit-tested in
  `package/tests/test_<module>.py`. A change there comes with a test.
- The GTK parts are checked by hand, in a sway session or the headless one. `test_navigation.py` covers the
  launcher's remote navigation without GTK.
- System changes (`install.sh`, the login screen, packages) are tested in a pretend root folder (`TVWCS_ROOT`) and,
  before a release is marked latest, on a real or virtual TV computer.

## Style

- Format with **black** before committing: `black .` (the settings are in `pyproject.toml`).
- Every module starts with a docstring that says what it is for; keep it true when the module changes.
- Write for someone reading the code for the first time: say why, not only what, in comments.
- Keep GTK out of `core/`, `system/` and the Settings back ends, so they stay testable.
- TVWCS drives standard tools (`swaymsg`, `pactl`, `nmcli`, `systemctl` …) rather than adding services of its own.

## Get it released

1. Bump `VERSION` and add a section at the top of `CHANGELOG.md` (a change to docs, tests or CI only can skip this).
2. Open a pull request. CI runs the tests and builds the Debian, Arch and Fedora packages.
3. Merging to `main` publishes a prerelease; it is marked latest once tried on a TV computer.

The details are in [PROJECT_OVERVIEW.md › Releases](PROJECT_OVERVIEW.md#releases).

## What TVWCS deliberately leaves out

TVWCS 5 is sway only, and dropped i3/X11, Flatpak, its own login screen, the Terminal page, the screen saver and the
boot logo. Please don't bring them back without talking about it first: the CHANGELOG says why each went.
