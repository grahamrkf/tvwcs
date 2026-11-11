# Shipping TVWCS in your own system

This page is for anyone who builds a distribution or a ready-made TV computer image with TVWCS in it. A vendor file sets where TVWCS gets its updates, your name and support page, and the defaults your users start from. TVWCS's code stays the same.

Every name below (Example TV, `example.org`, `org.example.Player.desktop`) is a placeholder.

## The files

TVWCS reads up to three JSON files. Each one's values win over the one before it, and each user's `~/.config/tvwcs/config.json` comes last:

| File | Who ships it | What it is for |
| --- | --- | --- |
| `/usr/lib/tvwcs/updates.json` | TVWCS's own packages from its GitHub releases | Turns on TVWCS's own updater for its GitHub releases |
| `/usr/share/tvwcs/vendor.json` | **Your** package (for example `example-tv-defaults`) | Your name, update source and presets |
| `/etc/tvwcs/defaults.json` | The administrator of one computer (or your config management) | Local changes, in the same format as `vendor.json` |

All three are optional. With none of them, TVWCS assumes a distribution packaged it, so it has no updater of its own and is updated along with the rest of the system.

TVWCS's packages never contain `vendor.json` or `defaults.json`, so your package can own them without a file conflict.

## An example `vendor.json`

```json
{
  "name": "Example TV",
  "support_url": "https://example.org/support",
  "updates": { "source": "system" },
  "settings": {
    "style": "media",
    "clock_24h": true,
    "lock_at_start": false,
    "idle": { "screen_off": 1800, "lock": 0, "sleep": 0 },
    "hotkeys": { "remote": { "menu": "F2" } }
  },
  "channels": [
    { "desktop_id": "org.example.Player.desktop", "channel": 1, "favorite": true },
    { "desktop_id": "org.example.Music.desktop", "channel": 2 }
  ],
  "startup_app": "org.example.Player.desktop"
}
```

Run `tvwcs vendor` to see what TVWCS read from each file and anything it skipped. It exits with status 1 when something was skipped, so you can use it as a check in your image build. To try a file out before you package it, point TVWCS at it with `TVWCS_VENDOR_FILE=/path/to/vendor.json tvwcs vendor`. `TVWCS_DEFAULTS_FILE` and `TVWCS_PACKAGE_FILE` do the same for the other two files.

A value TVWCS can't use is skipped, with a line on stderr, and the rest of the file still applies. A typo never stops TVWCS from starting.

## Keys

### `name` and `support_url`

These are shown in **Settings › System information**, under Software. `support_url` must start with `https://`.

### `updates`: where TVWCS's own updates come from

| Value | What Settings › Software updates does |
| --- | --- |
| `{"source": "system"}` | **Recommended for a distribution.** It shows no TVWCS updater. It only says that TVWCS is updated with the system, and its "Check for updates" installs new TVWCS versions from your package repository along with everything else. This is the default when no file sets `updates`. |
| `{"source": "github", "repo": "owner/name"}` | It checks the GitHub releases of that repository (your fork, say) and installs the `tvwcs_X.Y.Z_all.deb` (or `tvwcs-X.Y.Z-1.noarch.rpm`) attached to the newest one. Without `repo`, it uses TVWCS's own releases. |
| `{"source": "url", "url": "https://example.org/tvwcs/releases.json"}` | It reads a release list from your site, in the same form as GitHub's `/releases` answer (see below). |
| `{"source": "off"}` | It shows nothing about TVWCS updates. |

With `github` or `url`, TVWCS downloads the package and installs it with apt (or dnf) after the user enters their password. The download is trusted because it came over HTTPS, and nothing else is checked. A signed package repository is safer, and apt then also handles dependencies and unattended upgrades. That is why `system` is the recommended source.

A `url` release list is a JSON list, or `{"releases": [...]}`, of entries like this:

```json
[
  {
    "tag_name": "v5.21.0",
    "prerelease": false,
    "html_url": "https://example.org/tvwcs/5.21.0",
    "assets": [
      { "name": "tvwcs_5.21.0_all.deb", "browser_download_url": "https://example.org/tvwcs/tvwcs_5.21.0_all.deb" }
    ]
  }
]
```

The latest release is the newest entry that isn't a prerelease. Entries marked `"draft": true` are skipped, and every download must be `https://`.

### `settings`: the defaults your users start from

These can be any of the keys in `config.json`'s `"settings"`, such as `style`, `media_look`, `theme`, `accent`, `quick_corner`, `channel_digits`, `clock_24h`, `audio_boost`, `lock_at_start`, `hotkeys`, `cec`, `idle`, `idle_battery` and `startup`. Nested values merge key by key, so `{"hotkeys": {"remote": {"menu": "F2"}}}` changes only the remote's Quick Menu key. `model.py` lists every key in `DEFAULT_SETTINGS`, and `tvwcs vendor` names any it doesn't know.

These are defaults, not locks. Users can change anything in Settings. TVWCS saves only what a user changed, so every setting the user hasn't touched keeps following your file, including after you update it.

### `channels`

This gives an application a channel number, and optionally a place in Favorites, the first time TVWCS sees the application installed. The channel is only given if it's free and fits the channel digits. After that, the channel belongs to the user.

### `startup_app`

This names the application to open at login (**Settings › User › Open at login: Chosen application**). It applies once, for a user who hasn't chosen one yet.

## Building TVWCS's packages yourself

If you build TVWCS's `.deb` or `.rpm` with `scripts/build-debs.sh` or `scripts/build-rpm.sh`, set `TVWCS_NO_UPDATER=1` to leave out `updates.json`, so your repository is the only source of updates. If you ship `updates` in your `vendor.json`, it wins over `updates.json` anyway.

Some other things you can set up when you build an image:

- Your `/etc/os-release` can say `ID_LIKE=debian` (or `ubuntu`). TVWCS then treats the system as part of the Debian family.
- `tvwcs server-mode on --user=NAME` makes NAME the TV account with no administrator settings, and `PYTHONPATH=/usr/lib/tvwcs python3 -m tvwcs.loginscreen autologin NAME` logs that account in automatically. Both need root.
- TVWCS is MIT licensed, so you can ship it, rebrand your image and fork it.
