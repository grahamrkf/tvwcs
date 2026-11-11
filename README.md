# TVWCS

TVWCS (TV Window Channel Switcher) lets you use an ordinary Linux computer from the couch with a remote. It runs on top of the sway window manager and gives you:

- a **Quick Menu** in a corner of the screen (the bottom left unless you choose another): your favorites, your open apps, search, and a status row with the clock, network, sound, Bluetooth and battery;
- an **Applications** pane beside it: every installed app by category, plus your own numbered **Channels**;
- a **Settings** app for the things a TV computer needs: sound, displays, Wi-Fi, Bluetooth, power, updates and more.

It works with normal desktop apps. It is not a media center and needs no plugins. What's new is in [CHANGELOG.md](CHANGELOG.md).

TVWCS has two modes:

- **TV mode** is the **TVWCS** session you pick at the login screen. It is made for a remote: every app opens full screen in a workspace of its own, the sway bar is off (the Quick Menu shows the time and status instead), the mouse pointer hides after 3 seconds, the Quick Menu stays open while nothing else is, and the computer locks with a swaylock screen in TVWCS's theme.
- **Desktop mode** is TVWCS inside your usual sway session. The Quick Menu is a launcher and switcher; apps open the way sway opens them, and your bar, pointer and lock screen are left as they are.

<table>
  <tr>
    <th width="25%">Quick Menu</th>
    <th width="75%">Quick Menu and Applications</th>
  </tr>
  <tr>
    <td valign="top"><img src="assets/quick-menu.png" alt="The TVWCS Quick Menu" width="100%"></td>
    <td valign="top"><img src="assets/guide-menu.png" alt="The Quick Menu with the Applications pane open beside it" width="100%"></td>
  </tr>
  <tr>
    <td valign="top">Your favorites (★) and open apps in one list, search, and the status row: network, volume, Bluetooth, battery, ⏻ power, the time, ⚙ for Settings, and ⊞ for Applications. In desktop mode a header with ✕ sits at the top.</td>
    <td valign="top"><b>Channels</b> lists apps you gave a number. <b>All applications</b> lists every app by category; OK/Enter folds a category. ☆ makes an app a favorite, ✎ edits it.</td>
  </tr>
  <tr>
    <th colspan="2">Settings › Appearance</th>
  </tr>
  <tr>
    <td colspan="2"><img src="assets/options.png" alt="The Appearance page of the Settings app" width="100%"></td>
  </tr>
  <tr>
    <td colspan="2" valign="top">Each row shows its current value on the right. OK/Enter changes it.</td>
  </tr>
</table>

### Demos

The apps in these demos are mockups (a window with a still picture), labelled MOCKUP on screen.

<table>
  <tr>
    <th width="50%">TV mode</th>
    <th width="50%">Desktop mode</th>
  </tr>
  <tr>
    <td valign="top"><img src="assets/demo-tv-mode.gif" alt="The TV mode demo" width="100%"></td>
    <td valign="top"><img src="assets/demo-desktop-mode.gif" alt="The desktop mode demo" width="100%"></td>
  </tr>
  <tr>
    <td valign="top">With the remote: open an app by its channel number, open a second one by channel, go back to the first from the Quick Menu's list, and open a third by searching its name. Each app gets a workspace of its own.</td>
    <td valign="top">With the keyboard, in the light theme: open apps by name so they tile side by side, fill a second workspace, switch between workspaces from the Quick Menu, close one app and then a whole workspace, open Applications from ⊞ in the corner, and unfold the power options above ⏻.</td>
  </tr>
</table>

## What you need

- **Debian, Ubuntu LTS (tested on 26.04), or another Debian-based system** (Linux Mint, Pop!_OS, Raspberry Pi OS), **Arch Linux or a system built on it** (EndeavourOS, CachyOS, Manjaro), or **Fedora 42 or later** (Nobara and Ultramarine too; the Atomic editions with limits). Other distributions are not supported.
- **systemd** and **sway**. apt, pacman or dnf installs sway with TVWCS.

**New computer?** [Setting up a TV computer with Debian](docs/INSTALL-DEBIAN.md) goes from an empty computer to one that boots into TVWCS. On Arch, see [Installing TVWCS on Arch](docs/INSTALL-ARCH.md), and on Fedora [Installing TVWCS on Fedora](docs/INSTALL-FEDORA.md), for the steps by hand and what each does differently.

## Install

Run the installer in a terminal, as your own user (not root):

```bash
wget -qO- https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash
```

(or `curl -fsSL https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash`). Over SSH, sign in with `ssh -t` so it can ask its questions. It asks everything first and changes nothing until you agree to its list of what it will do:

1. **Which version:** the latest release, the prerelease when there is one, or one of the two releases before the latest. (`TVWCS_VERSION=latest`, `package` or a version such as `5.13.0` answers this for scripted installs.)
2. **Logging in automatically into TVWCS.** With no login screen, it offers to log you in on the first text console at startup, straight into TVWCS. With greetd, LightDM or SDDM, it offers their automatic login. With another login screen, choose **TVWCS** there.
3. **Your usual sway session:** whether to add TVWCS to it too, in desktop mode (one `include /usr/share/tvwcs/tvwcs.conf` line in its config).
4. **On Ubuntu:** whether to remove Snap, cloud-init and the Ubuntu Pro client.

Then it downloads the release's package and installs it with apt (on Fedora, its .rpm with dnf), or on Arch builds it from the PKGBUILD with makepkg and installs it with pacman. Every file of yours it changes is backed up first as `<file>.tvwcs-backup`. Your own data (channels, favorites, settings, hotkeys) is kept in `~/.config/tvwcs/`.

The package (a .deb, an .rpm for Fedora, and a PKGBUILD for Arch) is also attached to each [release](https://github.com/grahamrkf/tvwcs/releases) if you'd rather install it yourself (`sudo apt install ./tvwcs_<version>_all.deb`). Installing it on its own only adds the **TVWCS** session to the login screen and changes no settings.

**Update:** **Settings › Software updates › Check for TVWCS updates** (or run the installer again; on Arch, run the installer again). Your data is never changed.

**Remove:** `install.sh --remove` (or `sudo apt purge tvwcs`, `sudo dnf remove tvwcs`, or `sudo pacman -R tvwcs`). It also takes TVWCS out of your usual sway config, ends its automatic login on the text console and in greetd, LightDM or SDDM, and leaves the rest of their settings alone.

### The `tvwcs` command

`tvwcs` does what fits where you type it:

- **At a text console:** it starts the TVWCS session, in TV mode. To have it start by itself, turn on **Settings › User › Log in automatically after startup**.
- **In your usual sway session:** it opens Settings and offers to add TVWCS to that session, then asks for the key that opens the Quick Menu. Once TVWCS is part of the session, `tvwcs` shows the Quick Menu.
- **In another desktop** (GNOME, KDE, an X11 session): it opens Settings, with the pages that only work in sway turned off.
- **Over SSH:** it offers to start TVWCS on the computer's own screen, or to turn server mode on or off.

`tvwcs help` lists the other commands, such as `tvwcs settings [page]`, `tvwcs lock`, `tvwcs server-mode on|off|status` and `tvwcs start-session`.

### Server mode

For a computer that is a server first and an HTPC second. One account uses the TV: it logs in automatically into TVWCS, and from TVWCS nobody can put the computer to sleep, restart it or shut it down, update it, change its network, or unmount its drives. The power menu keeps only Lock (and Log out with a login screen); in Settings, Power and sleep, Software updates and Network are turned off and every other setting that needs an administrator is hidden. A polkit rule backs this up for that account, whatever program asks.

- **On or off:** Settings › User › Server mode, or `tvwcs server-mode on --user=NAME` / `tvwcs server-mode off` (sudo asks for your password). Turning it off from Settings asks for an administrator's password. The automatic login stays.
- **Start TVWCS on the screen now,** for example over SSH: `tvwcs start-session --user=NAME`.
- **A separate account for the TV** keeps it away from your own files: create a standard account (`sudo adduser tv`), then `tvwcs server-mode on --user=tv`. A 6-digit numeric password is quick to type on a remote and enough for it, as long as it can't sign in over SSH with a password (Settings › System information › Sign in with › Keys only, or a `DenyUsers tv` line in `/etc/ssh/sshd_config.d/`). Never give an administrator a short numeric password: anyone at the TV could use it with sudo.

## Using it with a remote

Most remotes act like a keyboard. TVWCS names their keys in its hints: **OK** is Enter, **Back** is Esc.

| Key | What it does |
|---|---|
| **F2** on a remote, or tap **Super** on a keyboard | Show or hide the Quick Menu |
| **↑ ↓ ← →** | Move. **→** past the Quick Menu opens Applications |
| **OK** / Enter | Open, switch to or choose the selected item |
| **Back** / Esc | Go back one step |
| **OK** on the empty search field | Open the on-screen keyboard (or number keypad) |
| Any letter or digit | Search. A channel number then OK (or all its digits and a second's wait) opens that channel |
| **←** on a Quick Menu row (or right-click) | Open that row's menu |

- **Quick Menu corner:** the bottom left by default. **Settings › Appearance › Quick Menu corner** puts it in any corner, mirrored to match (in a right-hand corner ← and → swap and Applications opens to its left; in a top corner the lists open downwards). The rest of this section describes the bottom left.
- **The list:** your favorites (grey ★) and then the other open apps (a thin band down their left side), by workspace. A workspace with several apps has a ▴ button that unfolds them, to open just one. Search results appear above the search field. A name too long to fit scrolls by once it has been selected for 3 seconds.
- **Row options (⋯, or ← on a row):** the app's own shortcuts (such as Settings' pages), opening it this once the other way (**Open in new workspace** in desktop mode, **Open alongside …** in TV mode), and **Close this application** nearest the row. A workspace's can move it to another monitor. **Settings › Appearance › Options buttons** can hide the ⋯ buttons.
- **Search icon:** turn off **Settings › Appearance › Search bar on the Quick Menu** to fold the search bar away behind a search icon in the status row. The icon unfolds it, and so does typing anywhere in the Quick Menu, keeping what you typed.
- **Channels:** two digits by default, 00 to 99 (**Settings › Appearance › Channel number digits** chooses 1 to 4). Channel 00 opens Settings unless you give it to another app.
- **Editing an app (✎):** its launch profile has a channel number, a hotkey, one of the app's own shortcuts, a custom command, a description and a PIN. **Copy** makes a second profile, such as Firefox in a private window (listed as "Firefox 2" until you rename it). The PIN is a lock for a shared TV, not real security.
- **Volume keys:** the remote's or keyboard's volume and mute keys show the volume for a moment at the bottom of the screen, over full-screen apps too (with gtk4-layer-shell, which the package recommends; without it, over everything but a full-screen app).
- **Status row:** the network, volume, Bluetooth and battery icons each unfold a panel (Wi-Fi networks to join, output and input volume, Bluetooth devices to connect or pair, the time left on the battery) with a button for its Settings page. ⏻ at the right has Lock, Sleep, Reboot and Shut down (and Log out when there is a login screen); if one needs your password, TVWCS asks on screen and never stores it. ⚙ beside the clock opens Settings, and ⊞ in the corner opens and closes Applications.
- **Slow apps:** a spinner turns in place of the app's icon while it opens.
- **On-screen keyboard:** wherever text is typed, it can be hidden (it starts that way), full, or a number pad, and opens next time as you left it.
- **The TV's own remote (HDMI-CEC):** on a computer with a CEC-capable HDMI port (a Raspberry Pi 4 or 5, or a USB adapter such as Pulse-Eight's), the TV lists it as **TVWCS** and passes its remote's buttons on: the arrows, OK, Back (Exit or Return), the numbers and the play keys work in TVWCS and in apps, and the **Red** button opens the Quick Menu. The TV switches to the computer when TVWCS starts or the computer wakes, and goes to standby when it sleeps or shuts down. All of it is in **Settings › Remote and hotkeys › TV remote (HDMI-CEC)**, shown only on a computer with a CEC port. Which buttons a TV passes on depends on its make (the setting is called Anynet+ on Samsung, SimpLink on LG, Bravia Sync on Sony); most TVs keep the volume keys for themselves.
- **Other keys:** set the Quick Menu key for a keyboard, a remote or a gamepad in **Settings › Remote and hotkeys**. A gamepad needs a key mapper such as AntiMicroX. Clicking with the mouse does not move the remote's selection.

## Settings

Open **TVWCS Settings** with channel 00, from a status panel's settings button, from Applications (under System), or with `tvwcs settings [page]`. Pages are tabs on the left: **→** enters a page, **Back** returns to the tabs. Text is typed on a keyboard or on the on-screen keyboard.

| Page (`tvwcs settings …`) | What it does |
|---|---|
| **Appearance** (`appearance`) | Interface size 1 to 5 (Auto is 4 in TV mode and 3 otherwise; a 4K switch doubles it), the theme: Modern (dark or light with an accent and a background colour, passed on to apps) Retro (an old CRT TV's menus in green, amber or white, in a choice of fonts and backgrounds) or Media (dark and rounded, in colours that go with Jellyfin, Emby or Plex), the Quick Menu corner, the search bar or a search icon, channel digits, closing TVWCS when it loses focus, and the screen edge margin for TVs that cut off the edges (overscan). |
| **User** (`user`) | Your name and password, server mode, logging in automatically into TVWCS, locking when TVWCS starts, the login screen in use, and the app to open at login. |
| **Remote and hotkeys** (`hotkeys`) | **Add TVWCS to sway** (in a sway session without it), the Quick Menu key for keyboard, remote and gamepad (and the TV's remote over HDMI-CEC, with its TV power options, on a computer with a CEC port), the apps with hotkeys of their own, and **Reset all hotkeys**. |
| **Sound** (`sound`) | Volume and mute for each output and input (the inactive ones folded away), and **Allow over-amplification** up to 150 %. |
| **Displays** (`displays`) | Resolution, refresh rate, arrangement and scale for each display: a row of buttons from 75 % to 200 %. A change goes back after 15 seconds unless you keep it. |
| **Power and sleep** (`power`) | When the screen turns off, the computer locks and it sleeps (sway's swayidle times them; sound playing and apps that ask keep it awake). A laptop has these times twice, plugged in and on battery, and a choice of what to do when the battery is nearly empty. |
| **Bluetooth** (`bluetooth`) | Pair, connect and forget devices. Shows battery levels. |
| **Date and time** (`datetime`) | Time zone (one list), network time, 12- or 24-hour clock. |
| **Software updates** (`updates`) | System updates (apt, dnf, or pacman with AUR helpers on Arch) and TVWCS's own updates, including prereleases and rolling back. |
| **System information** (`system`) | Hardware and versions. Turns the SSH server on or off and shows how to connect. |
| **Network** (`network`) | Ethernet and Wi-Fi, and fixed IP settings. Without NetworkManager, Wi-Fi through iwd can be joined and forgotten. A port the Debian installer set up, or Ubuntu Server's netplan, can be handed to NetworkManager, keeping the old setup as a backup. |
| **Storage** (`storage`) | Drives and their partitions: mount, unmount and safely remove. |

A page whose software is missing offers to install it (Sound installs PipeWire, Bluetooth BlueZ, and so on). When the Settings window is taller than it is wide (a tile, or a monitor turned on its side), the tabs show only their icons.

**Locking in TV mode:** the TVWCS session locks with swaylock, in your theme (`tvwcs lock` locks by hand). A desktop session's own lock screen is not changed. With the automatic login, **Settings › User › Lock the screen when TVWCS starts** keeps a password between a restart and your apps.

## Troubleshooting

- **The hotkey does nothing:** check that `swaymsg -t get_config | grep -i tvwcs` shows TVWCS and that `~/.config/tvwcs/hotkeys.conf` exists. Logging in to the TVWCS session again creates it.
- **Tapping Super does nothing:** another tool may grab the key. `wev` shows the keycode your key sends; compare it with the line in `hotkeys.conf`.
- **"TVWCS is already running":** delete the stale `$XDG_RUNTIME_DIR/tvwcs.pid`.
- **The edges of TVWCS are cut off on the TV:** raise **Settings › Appearance › Screen edge margin**, or turn off overscan in the TV's picture settings.
- **The TVWCS session doesn't start:** run `tvwcs-session` from a text console to see sway's errors. Its config is `~/.config/tvwcs/sway-session.conf`; delete it to make a fresh one from sway's standard config.
- **Letters instead of icons:** install `adwaita-icon-theme` or `papirus-icon-theme`.
- **Check for updates fails:** TVWCS needs internet access to `api.github.com`.

How it works inside, the code layout, tests and releases are in [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).

## License

MIT. See `LICENSE`. Most of the code was written by AI from a project description and rounds of review. You may copy, reuse or adapt it freely.
