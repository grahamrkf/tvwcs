# Where to change what

Which file to open for a given change. Paths are under `package/tvwcs/` unless they start with another folder.
How the parts fit together is in [PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md#code); how to run and test a change is
in [CONTRIBUTING.md](../CONTRIBUTING.md).

A rule of thumb: what TVWCS **shows** is in `ui/` (the launcher) or `settings/pages/` (Settings). What it **does** to
the computer is in `system/` or in the Settings page's back end, `settings/<name>.py`. The data it keeps is in
`core/model.py`. Most bugs are in the second kind, which is also the kind with unit tests.

## The launcher (Quick Menu and Applications)

| I want to change… | Look in |
|---|---|
| How the window is built and placed on screen | `ui/window.py`; the position maths is `Layout` in `core/model.py` |
| The Quick Menu's rows (favorites, channels, open apps, their ⋯ options) | `ui/quick_menu.py` |
| The bottom row (clock, status icons, ⚙, ⊞, ⏻) and the panels they open | `ui/status_panels.py`; what each icon reads is `system/quick_status.py` |
| The Applications pane | `ui/applications_pane.py`; finding the installed apps and their categories is `core/applications.py` |
| Search and typing a channel number | `ui/search.py`; what matches is `search_items` in `core/model.py` |
| What the arrows, OK and Back do | `ui/navigation.py` |
| A dialog (confirm, notice, PIN) | `ui/dialogs.py` |
| The on-screen keyboard | `ui/onscreen_keyboard.py` |
| The profile editor (✎ Edit) | `ui/editors.py`, with its state in `core/profile_draft.py` |
| Colours, fonts, sizes, the Retro and Media looks | `ui/theme.py` (CSS), `ui/retro.py` and `ui/retro_assets/` (made by `scripts/make-retro-assets.py`), sizes in `core/model.py` |
| The volume indicator | `ui/osd.py`; the volume keys themselves are `tvwcs volume` in `settings/sound.py` |
| Which window belongs to which app, and where apps open | `core/workspaces.py`, `core/ownership.py`, `system/window_manager.py` (sway IPC) |

## Settings

| I want to change… | Look in |
|---|---|
| What a page shows | `settings/pages/<page>.py` (for example `settings/pages/sound.py`) |
| What a page does to the computer | Its back end: `settings/<name>.py` (for example `settings/sound.py`, which runs `pactl`). The page's docstring names it |
| The window, the tab list, the D-pad navigation, dialogs and running things as root | `settings/app.py`; the shared parts of every page are in `settings/pages/base.py` |
| Add a page | A new `Page` subclass in `settings/pages/<page>.py` (see `base.py`), listed in `PAGES` in `settings/pages/__init__.py`, with a `[Desktop Action]` in `data/com.tvwcs.ControlPanel.desktop` so it can be a channel. Put its system side in `settings/<name>.py` with tests in `package/tests/` |
| A page that needs software that may be missing | `system/features.py` |

## Options, hotkeys and remotes

| I want to change… | Look in |
|---|---|
| Add an option saved in `config.json` | Its default in `DEFAULT_SETTINGS` and its check in `_clean_settings`, both in `core/model.py`; then a row on its Settings page (usually `settings/pages/appearance.py`) |
| Default hotkeys and the sway bindings TVWCS writes | `core/hotkeys.py` (it writes `~/.config/tvwcs/hotkeys.conf`); Settings › Remote and hotkeys is `settings/pages/hotkeys.py` |
| The TV's own remote over HDMI-CEC | `system/cec.py`, started by `CecWatcher` in `watchers.py` |
| The Last app key | `system/last_app.py` |
| Channels, favorites, launch profiles | `LaunchProfile` and `ConfigStore` in `core/model.py`; PINs in `core/pinlock.py` |
| Presets from a distribution or vendor | `core/vendor.py` ([VENDORS.md](VENDORS.md)) |

## The computer

| I want to change… | Look in |
|---|---|
| The `tvwcs` command and its subcommands | `package/bin/tvwcs` (the ones without GTK), then `main()` in `main.py`; `tvwcs help` is `usage.py` |
| Sleep, screen off, locking after a time | `system/power.py` (swayidle), `IdleWatcher` in `watchers.py`; Settings › Power and sleep is `settings/pages/power.py` |
| The power menu (⏻) and running it as root | `system/system_actions.py`, `system/privilege.py` |
| The lock screen | `system/lockscreen.py` |
| The login screen and logging in automatically | `system/loginscreen.py`; Settings › User is `settings/pages/user.py` |
| Server mode | `system/servermode.py` |
| TV mode (no bar, hidden pointer, Quick Menu kept open) | `system/tv_mode.py`, `system/cursor.py`, `data/tvwcs-session` |
| TVWCS in an ordinary sway session (desktop mode) | `system/sway_include.py`, `data/tvwcs.conf` |
| Light or dark for other apps, and the background colour | `system/appearance.py` |
| TVWCS updating itself | `system/selfupdate.py`; the system's updates are `settings/updates.py` |
| Something that differs between Debian, Arch and Fedora | `system/distro.py` (package names, commands, greetd's details) |

## Packages, installer and releases

| I want to change… | Look in |
|---|---|
| The installer | `install.sh` (POSIX sh); its tests are `package/tests/test_install.py` |
| The packages | `scripts/build-debs.sh` and `packaging/tvwcs/` (Debian), `packaging/fedora/tvwcs.spec.in`, `packaging/arch/` |
| The sway fragment every TVWCS session includes | `data/tvwcs.conf` |
| Release steps | [PROJECT_OVERVIEW.md › Releases](../PROJECT_OVERVIEW.md#releases) and `.github/workflows/` |
| README screenshots and demo GIFs | `tools/demo/` |
