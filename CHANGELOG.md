# Changelog

## 5.18.0 — 2026-11-11

- **Closing Settings goes back to the app you were using.** Open Settings over an app (from the Quick Menu, a status icon, a hotkey, or `tvwcs settings` in a terminal) and closing it with Back/Esc brings that app back, full screen again if it was, instead of leaving an empty workspace and the Quick Menu in TV mode. Opened over an empty screen, closing it shows the Quick Menu as before. TVWCS notes the app just before it opens Settings (`return_focus.py`); Settings closed from elsewhere (the Quick Menu's ⋯ menu) leaves the focus where you are.

## 5.17.0 — 2026-11-11

- **On-screen volume indicator.** The remote's or keyboard's volume keys now show the volume for a second near the bottom of the screen: the speaker icon, a bar and the percentage (or "Muted"), in the current theme and interface size, above the screen edge margin. It shows over full-screen apps (a video, a game) without taking the keys from them, and stays up while a key is held. The bar measures up to the volume keys' limit: 100 %, or 150 % with over-amplification.
  - **The mute key** is now bound too (`tvwcs volume mute`), so muting shows the indicator as well.
  - It is a small process of its own (`python3 -m tvwcs.osd`), started by the first volume key and then kept running, so later presses show at once. It draws without the GPU to stay small (about 60 MB).
  - It needs **gtk4-layer-shell** to show over full-screen apps: the .deb recommends `gir1.2-gtk4layershell-1.0` and `libgtk4-layer-shell0`, the .rpm `gtk4-layer-shell`; on Arch install `gtk4-layer-shell`. Without it (Ubuntu 24.04 doesn't have it) the indicator is a floating window that never takes the focus, shown over everything but a full-screen app.

## 5.16.1 — 2026-11-11

- **The volume limit holds whatever raises the volume.** The remote's volume keys could still take the sound past 150 % (5.10.1 only changed sway's own key binding, so anything else that turned the volume up had no limit). TVWCS now watches the sound server (`pactl subscribe`) and brings any output above the limit straight back down: 100 %, or 150 % with Settings › Sound › Allow over-amplification. That covers volume keys bound somewhere else, apps, pavucontrol and `pactl` alike, and turning over-amplification off brings a louder volume down to 100 % at once. The volume keys and the Quick Menu's and Settings' − / + now take a volume that is above the limit down to it, instead of leaving it there.

## 5.16.0 — 2026-11-05

- **The Quick Menu's search bar can fold away.** Turn off **Settings › Appearance › Search bar on the Quick Menu** and a search icon takes its place at the start of the status row, beside the network and volume icons. Selecting the icon unfolds the full-width search bar ready to type in, and typing anywhere in the Quick Menu unfolds it with the keys already typed in it (a channel number too). It folds away again once the selection leaves it with nothing typed, with Back/Esc (which also clears it), or with the icon again. With the bar folded, the Quick Menu opens on the row nearest it.

## 5.15.0 — 2026-11-04

- **Fedora support.** TVWCS runs on Fedora 42 and later, and on Nobara and Ultramarine. Each release now has `tvwcs-<version>-1.noarch.rpm` attached, built by the new `scripts/build-rpm.sh` from `packaging/fedora/tvwcs.spec.in` (in a Fedora container in the release workflow). [docs/INSTALL-FEDORA.md](docs/INSTALL-FEDORA.md) has the steps and what Fedora does differently. Red Hat Enterprise Linux and its rebuilds aren't counted as Fedora.
  - **The installer** asks the same questions, then downloads the release's .rpm and installs it with dnf (`dnf downgrade` for an older version). It only offers releases with an .rpm (5.15.0 on), and `--remove` uses dnf.
  - **Software updates** uses dnf: `dnf check-update` lists what is waiting, Install runs `dnf upgrade --refresh`, "Download the latest package lists" runs `dnf makecache`, and `dnf needs-restarting -r` says when a restart is due (Fedora keeps old kernels, so the usual check can't tell).
  - **TVWCS updates** downloads the new release's .rpm and installs it with dnf, prereleases and rolling back included.
  - **Installing what a page needs** uses Fedora's names (`pipewire-pulseaudio`, `bluez`, `openssh-server`) and starts Bluetooth's service. greetd is set up with Fedora's `greetd` user and the first console.
  - **SELinux:** files TVWCS writes in `/etc` are relabelled with `restorecon`.
  - **Fedora Atomic** (Silverblue, Sway Atomic...): the installer stops and explains how to layer the .rpm with `rpm-ostree install`, and Software updates points to `rpm-ostree upgrade` instead of offering dnf. TVWCS's own updates and installing a page's software from Settings don't work there yet.
  - CI builds the .rpm in a Fedora container, installs it with dnf, lists updates as a normal user, installs Bluetooth, upgrades and rolls back TVWCS's own package, checks greetd's details and removes it again.

## 5.14.1 — 2026-11-04

- **New GitHub address.** The project moved from github.com/one-moment-please/tvwcs to github.com/grahamrkf/tvwcs. The updater in Settings, the installer, the package metadata (Debian control, PKGBUILD, pyproject.toml) and the docs now use the new address, and the LICENSE copyright line names grahamrkf. Older copies keep working while GitHub redirects the old address.

## 5.14.0 — 2026-10-31

- **The installer comes from the latest release.** Each release now has `install.sh` attached, and the README, the install guides, Settings and the installer's own hints download it from `releases/latest/download/install.sh` instead of the `main` branch. A change to the installer now reaches new installs only once its release is marked latest, like the package it installs.
- **New README screenshots and demos,** for the current Quick Menu (two-digit channels, status rows) and Settings › Appearance. The demos are GIFs only: the MP4 copies are gone from the repository, since the GIFs show the whole demo. They are recorded in a headless sway session with mockup apps.
- PROJECT_OVERVIEW.md: a change to docs, tests or CI only can skip the version bump. pyproject.toml no longer describes TVWCS as an i3 app.

## 5.13.1 — 2026-10-31

- **Shorter docs.** README's install, update and removal steps are one section, with the installer's questions in it, and the Quick Menu and Settings descriptions are tighter. PROJECT_OVERVIEW.md is now only for people working on TVWCS (how it works inside, the code, releases, sending it to the AUR), brought up to date for sway, Arch and server mode, and it takes in docs/RELEASES.md. The Debian guide no longer mentions the startup logo.
- **TODO.md is gone.** Tablet mode and a dedicated passwordless TV user won't be built, and other distributions won't come back. Its research is in git history (`git show 1055fc0:TODO.md`).

## 5.13.0 — 2026-10-31

- **Wi-Fi through iwd.** On a computer whose network NetworkManager doesn't run, such as Arch with systemd-networkd and iwd, Settings › Network lists the Wi-Fi networks iwd sees and joins and forgets them. The new `control_iwd.py` reads iwd over D-Bus (`busctl`) as you. Joining, connecting, leaving and forgetting run as root (iwd's D-Bus policy only promises that to root), so each asks for your password. A password is saved where iwd keeps it (`/var/lib/iwd/<network>.psk`) and handed over in a file only you can read, never on a command line. A network that doesn't connect the first time is forgotten again, so a mistyped password isn't kept, and typing the right one straight after works (Settings waits until iwd has let the wrong one go). Connecting to a saved or open network, leaving and forgetting are tried without your password first: Arch's iwd lets the wheel group do those. Only a new password always needs it.
- **The installer works on Arch.** `install.sh` asks the same questions there, then downloads the release's PKGBUILD, builds it with makepkg as you (installing fakeroot first if it's missing) and installs it with pacman. As before, it downloads and changes nothing until you agree to its list. It only offers releases that have a PKGBUILD (5.11.0 on), refuses to run as root on Arch (makepkg won't build as root), and `--remove` uses pacman there.
- **Upgrading from TVWCS 4.x is gone** from the installer: its old copy, login screen, console login and include-line handling, and the `--missing` option 4.x's updater asked.
- **DHCP or set by hand.** Without NetworkManager, the Network page says for each connected port whether DHCP gave its address, and what set it up (systemd-networkd, dhcpcd or iwd). An address set by hand gets a warning saying where to change it from the command line, since Settings can't change it there.

## 5.12.0 — 2026-10-30

- **Channel numbers have two digits,** 00 to 99, instead of three. Settings is channel 00. **Settings › Appearance › Channel number digits** chooses 1 to 4 digits; the Quick Menu's search field, the digit boxes for setting a channel, the numbers in every list and typing a full number to open its channel follow it.
  - Updating keeps three digits when an app already has a channel over 99, so no channel is lost. Otherwise it moves to two (channel 007 is now 07).
  - Choosing fewer digits than some channels need asks first and names them; their numbers are then removed.

## 5.11.0 — 2026-10-30

- **Arch support.** TVWCS runs on Arch Linux and on systems built on it (EndeavourOS, CachyOS, Manjaro). Each release now has a `PKGBUILD` and `tvwcs.install` attached, built by the new `scripts/build-arch.sh`. Build and install it with `makepkg -si`; [docs/INSTALL-ARCH.md](docs/INSTALL-ARCH.md) has the steps and what Arch does differently. The same files can go to the AUR later.
  - **Software updates** uses pacman. `checkupdates` (pacman-contrib) lists what is waiting without touching pacman's own database, and Install runs `pacman -Syu`. The page points to archlinux.org/news for updates that need a step by hand, and to your AUR helper for AUR packages.
  - **Software updates on Arch, step by step:** "Update step by step" runs pacman without `--noconfirm` and shows each question it asks with buttons (Yes / No, or a button for each package when it asks you to choose). Back answers No. It is also offered when an automatic update stops. The page lists Arch's news posted since the last full update (and the Install question mentions it), and the `.pacnew` files updates have left in `/etc`, with how to merge them.
  - **AUR packages** (TVWCS's own, once it's there): with yay or paru installed, Software updates lists their updates (`-Qua`) and the Quick Menu counts them. "Update AUR packages" runs the helper as you, always step by step: diffs of the build scripts first ("Show all" is the first button), its menus and questions as buttons, and sudo's password in Settings' password field (`--sudoflags=-S`).
  - **Installing what a page needs** (Sound, Bluetooth, the SSH server) uses Arch's package names and `pacman -S --needed`. Bluetooth's service is turned on with it, because Arch doesn't start services after installing them. The SSH page knows Arch's `sshd.service`.
  - **The login screen:** greetd is set up with Arch's `greeter` user, `/usr/bin/agreety` and the first console. Debian's `/etc/X11/default-display-manager` is only written on Debian.
  - **TVWCS updates** doesn't offer to install .debs on an Arch package. It says when a new release is out and how to build it.
  - Hints name Arch's packages there (sof-firmware, libpulse), and the Network page says how to hand the network to NetworkManager when systemd-networkd, iwd or dhcpcd runs it.
  - `install.sh` stays Debian-only and points Arch users to the guide.
  - The tests also run on Arch in CI: the unit tests, a package build, installing it with pacman (which checks every dependency's name), namcap and removing it again.
  - Behind it all is one new module, `distro.py`, that knows each family's package names, install commands and greetd details. Debian's behaviour is unchanged.
- **Removing TVWCS leaves the rest of greetd's config alone** (on Debian too). It used to replace the whole file with a plain agreety config, so another greeter (tuigreet, ReGreet) or its console was lost. Now only TVWCS's automatic login (`[initial_session]` starting `tvwcs-session`) goes, and agreety starts a shell where it was starting TVWCS. No `config.toml.tvwcs-backup` is left, and the removal says what it changed.
- Fixes found testing in an Arch VM: Bluetooth says no adapter was found when there is none (its service only starts with one), not that the service isn't answering. The note under pacman's updates only says "below" when there is news below. yay's and paru's questions are titled with their name, and the "Packages to exclude" question shows the question, not yay's warning under it. An answer pacman repeats is shown once in the log. A display without a name is no longer listed as "Unknown Unknown".

## 5.10.2 — 2026-10-30

- **Switching the login screen to LightDM leaves it starting.** Debian's and Ubuntu's (and so Mint's) `lightdm.service` has no `[Install]` section, so `systemctl enable lightdm` does nothing: after TVWCS disabled the old login screen (for example SDDM, or greetd when removing TVWCS 4.x's greeter), no login screen started at all. TVWCS now points `/etc/systemd/system/display-manager.service` at the new login screen itself. If a computer is already in that state (LightDM is the default but never starts), run `sudo ln -sf /usr/lib/systemd/system/lightdm.service /etc/systemd/system/display-manager.service`. Removing SDDM after installing KDE does the same thing, and that isn't TVWCS's doing.

## 5.10.1 — 2026-10-24

- **The volume keys of remotes and keyboards stop at 100 %** when Settings › Sound › Allow over-amplification is off (150 % when it is on), like the Sound page. Sway's standard config bound them to a plain `pactl ... +5%`, which went on past that. TVWCS's sway config (`tvwcs.conf`) now binds them to the new `tvwcs volume up|down`, also on the lock screen (with `--no-warn`, so replacing sway's binding shows no warning bar). A volume set louder by another program is not raised further, and goes down from where it is.

## 5.10.0 — 2026-10-23

- **The `tvwcs` command has a name for each thing it does,** and `tvwcs help` lists them. Plain `tvwcs` still does what fits where you type it (at a text console it starts TVWCS's session as you).
  - `tvwcs session` starts TVWCS's session at a text console. It refuses in a graphical session and over SSH, with a note on what to do instead.
  - Server mode: `tvwcs server-mode on [--user=NAME]`, `tvwcs server-mode off` and the new `tvwcs server-mode status`. Starting TVWCS on the screen for someone: `tvwcs start-session [--user=NAME]`.
  - TVWCS itself, as the sway config starts it: `tvwcs launcher` (it was `tvwcs start`, easy to mix up with `--start`).
  - The old spellings (`-s`, `--server-mode`, `--no-server-mode`, `--start`, `start`, `control`) still work, so existing hotkeys, scripts and a running older TVWCS's restart after an update are not broken. Settings' notes and the README use the new names.

## 5.9.2 — 2026-10-23

- README, server mode: how to set up a separate standard account for the TV, and why a numeric password of 4 to 6 digits is enough for it when it cannot sign in over SSH with a password (never for an administrator account).

## 5.9.1 — 2026-10-23

- Retro theme, VT323 font: ligatures are off, so "fi" and "ff" are two letters again ("Jellyfin" read as "Jellyfn" and "Off" had a joined ff).

## 5.9.0 — 2026-10-23

- **Settings › Appearance › Font (Retro theme):** Pixel (TVWCS's own pixel fonts, as before), **VT323** (after a 1970s DEC terminal's font; bundled, SIL Open Font License) or **Inter** (a smooth font made to be easy to read; from the fonts-inter package, now recommended, else Open Sans). Each has icons to match: Pixel keeps the square pixel icons, VT323 has the same drawings in its rounded dots, and Inter uses the icon theme's standard symbolic icons. VT323 and Inter are drawn smoothed and sized like Modern's text (VT323 40 % larger, as its letters are small for their size); Inter keeps Modern's bold and light weights.

## 5.8.1 — 2026-10-23

- Settings › Appearance: the "Interface size" heading (and Displays' "Scale") now changes size with the interface, like the rows around it. It was always GTK's default size, so it looked tiny at size 5 and in 4K.
- Development: CI no longer installs GTK, which its tests never used: they run on a separate Python. The theme's colour and size tests needed GTK only for the Metro colours (now in model.py). In a full run they had been passing against the fake GTK that the navigation tests load, which those tests now unload when they finish. Test comments no longer mention i3.

## 5.8.0 — 2026-10-23

- **Settings › Appearance › Interface size is now 1 to 5,** a row of buttons from smallest to largest. 3 is the old Desktop size and 4 the old TV Mode, with 1 and 2 smaller and 5 larger. Auto picks by the mode and the theme: 4 in TV mode and 3 in desktop mode, and a size smaller in the Retro theme (3 and 2), whose pixel text reads well smaller. 4K TV Mode is now the **Sized for a 4K screen** switch (shown when a 4K display is connected), which makes any size about twice as large; size 4 with it is the old 4K TV Mode. A size chosen before keeps its look.
- **Retro: a thinner font for lists, buttons and notes.** Application names, Settings rows and their notes are in TVWCS Pixel 8x16, built from Frederic Cambus's Spleen font (BSD licence), whose strokes are one pixel wide in a taller cell, so text is thinner at the same size. Large text keeps the 8 × 8 font and the smallest (badges) the 5 × 7 one. Characters Spleen lacks (★, ✓, ⋯) come from the 5 × 7 font.

## 5.7.2 — 2026-10-23

- In server mode, **Settings › User** also has **Turn off the screen after**, next to Lock after (Power and sleep is turned off there).

## 5.7.1 — 2026-10-23

- **Lock after, in server mode:** Power and sleep is turned off in server mode, so its lock time is now on **Settings › User**, under Server mode. It sets the time both plugged in and on battery.

## 5.7.0 — 2026-10-23

- **Server mode,** for a computer that is a server first: one account uses the TV and logs in automatically into TVWCS, and nothing in TVWCS can put the computer to sleep, restart or shut it down, update it, change its network or unmount its drives. The power menu keeps only Lock (and Log out with a login screen); the idle timer never sleeps and a nearly empty battery does nothing. Settings turns off Power and sleep, Software updates and Network, and hides every other setting that needs an administrator (SSH, the time zone and network time, the automatic login and login screen, your full name, installing a page's software). A polkit rule backs it up for the TV's account: logind, UDisks and NetworkManager refuse those actions whatever asks. It is a root-owned file, `/etc/tvwcs/server-mode`.
- Turn it on in **Settings › User › Server mode** (an administrator, choosing which account uses the TV) or with `tvwcs -s --user=NAME`; off there with an administrator's password (a standard account names the administrator), or with `tvwcs --no-server-mode`.
- **`tvwcs` over SSH** offers to start TVWCS on the computer's own screen, or to turn server mode on or off. `tvwcs --start --user=NAME` starts TVWCS for NAME on the first free text console, once.
- greetd is no longer suggested by the package either.
- Removing the package or `install.sh --remove` also turns server mode off.
- **Removing the package** also undoes a login screen's automatic login into TVWCS: greetd goes back to its plain text login (the old config is kept as `config.toml.tvwcs-backup`), and LightDM's and SDDM's TVWCS automatic-login files are deleted, as `install.sh --remove` already did.
- **TVWCS has its own badge on Linux Mint's login screen** (slick-greeter): the logo's TV, in place of a blank white disc.
- A login screen that was disabled (say `systemctl disable greetd`) no longer counts as the one in use: its old `/etc/X11/default-display-manager` file stays behind, and Settings' automatic login and the installer used to set up that login screen instead of the console's automatic login.
- The Quick Menu's network panel has no Network settings button in server mode. `tvwcs --help` lists the server mode options.
- **The Quick Menu no longer flashes in the middle of the screen** before it moves to its corner. sway shows a new floating window centred first and TVWCS's placement came a moment later; the window now starts out invisible until it is in place.
- The demo videos in the README now play there, as animated previews; click one for the full video.

## 5.6.0 — 2026-10-22

- **`tvwcs` on its own does what fits where you type it.** At a text console with no graphical session it starts the TVWCS session (in TV mode). In a sway session TVWCS isn't part of, it opens Settings and offers to add TVWCS to it: one `include /usr/share/tvwcs/tvwcs.conf` line in your sway config (backed up first as `config.tvwcs-backup`), then sway reloads, TVWCS starts in desktop mode and Settings asks for the key that opens the Quick Menu. Where TVWCS already runs, it shows the Quick Menu. In GNOME, KDE or an X11 session it opens Settings. `tvwcs start` starts the launcher itself, as sway's config now does.
- **Settings outside sway:** the pages that only work in sway (Appearance, Remote and hotkeys, Displays, Power and sleep, and User's logging-in rows) are shown turned off, with a note saying where they work. The other pages (sound, Bluetooth, the network, updates and so on) work as before.
- **Settings › Remote and hotkeys › Add TVWCS to sway**, in a sway session TVWCS isn't part of yet.
- **No login screen needed.** On a computer without one, **Settings › User › Log in automatically after startup** now works: the first text console logs you in (a getty drop-in, `/etc/systemd/system/getty@tty1.service.d/tvwcs-autologin.conf`) and your shell profile starts the TVWCS session there. Logging out starts it again; if the session stops straight away, the console stays at the shell instead of trying over and over. The installer uses this too, instead of installing greetd. Switching to a login screen, `install.sh --remove` and removing the package end it.
- The power menu's **Log out** shows only where logging out reaches a login screen: when this login came from one (logind says which), or, when logind can't say, when one starts at boot. A session started at a text console (typing `tvwcs`, or the console's automatic login) has no Log out, even with a login screen installed: logging out would only have left a text console, or started TVWCS again.
- **Installing the package changes no settings.** greetd is now only suggested by the package instead of recommended, so `apt install tvwcs` no longer installs a login screen. Computers already using greetd keep it.

## 5.5.0 — 2026-10-22

- **The lock screen matches TVWCS's theme and says it is locked.** Each screen shows a padlock, "Locked" and "Type your password, then press Enter". In the Modern theme it uses Modern's dark or light colours with your accent colour. In the Retro theme it's a TV menu box in your Retro colour and pixel fonts, on the Retro background (gray, blue or TV static). swaylock's ring now stays on screen below the text, so it's clear where the password goes, and it is drawn in the theme's colours too. This applies everywhere TVWCS locks: Lock in the power menu, the idle lock, and Lock the screen when TVWCS starts.
- The tvwcs package now depends on librsvg2-common, which lets swaylock show the lock screen's picture.

## 5.4.1 — 2026-10-22

- **Retro theme fixes, found on a real TV:** the TV static (and Modern's background colour) no longer disappears a moment after TVWCS first starts. Writing the hotkeys reloads sway, which dropped the background, and it is now set again after that reload. Pixel icons are always placed on whole screen pixels, so the ones in a box an odd number of pixels bigger (the Settings sidebar, and the Quick Menu's status icons at 4K) are no longer blurred by half a pixel. The favourite stars in Applications are now pixel icons too (★ and ☆) instead of the icon theme's small ones.

## 5.4.0 — 2026-10-22

- **Settings › User › Lock the screen when TVWCS starts:** the TVWCS session can start locked, for computers that log in automatically (greetd's automatic login, or no login screen at all), so the computer is never left open after a restart. The lock screen comes up as sway starts, before the Quick Menu, and your password unlocks it. An application set to open at login still opens, behind the lock. It is off by default, only works in the TVWCS session (desktop mode keeps its login), and can't be turned on for an account with no password or a locked one, which the lock screen could not unlock. `tvwcs lock` and the new `tvwcs lock-at-start` now start the lock screen without loading GTK, so it appears a little sooner.

## 5.3.0 — 2026-10-22

- **Settings › Appearance › Theme: Modern or Retro.** Retro looks like the menus of an old CRT TV: text in one colour on black, in pixel fonts (a 5 × 7 font for small text, an 8 × 8 font for large text such as the clock and the titles), with pixel icons to match. Buttons have no border until the mouse is over one (a dashed border) or one is selected (a solid one). Applications have no icons in Retro, only their names. Text sizes are rounded to whole multiples of the fonts' pixels, so they stay sharp at every interface size. The Quick Menu, Applications and Settings all use it.
- Retro has its own **Colour** (green, amber or white) and **Background** (gray, blue or TV static). The TV static is a small picture of grey noise, stretched to fill the screen, so its grains look the same on a 1080p and a 4K TV. Modern keeps its light or dark choice, accent colour and background colour, so switching back brings them back. Applications that follow the desktop's colour scheme are dark in Retro.
- The fonts are built from public bitmap fonts (Adafruit's 5 × 7 GFX font and Daniel Hepper's 8 × 8 font8x8, after IBM's VGA font) by `scripts/make-retro-assets.py`, which also draws the icons and the static from `scripts/retro/glyphs.txt`.

## 5.2.2 — 2026-10-22

- Logging into the TVWCS session from LightDM's login screen (as on Linux Mint) no longer sometimes ends back at the login screen after 10 seconds. LightDM switches to the session's console a moment after starting it, and the libseat in Ubuntu 24.04 and Linux Mint 22 (0.8.0) checks only once, when sway starts, so it could miss the switch ("Timeout waiting session to become active"). The session now waits until logind says it is active before starting sway (at most 5 seconds; usually 0.1–0.2 s). The plain "Sway" session isn't TVWCS's and can still hit it there.

## 5.2.1 — 2026-10-22

- The TVWCS session no longer flashes sway's bar at startup. Its sway config (`~/.config/tvwcs/sway-session.conf`) is made without the standard config's bar, so swaybar never starts; before, it showed for a moment until TV mode hid it. A config made by an earlier version has its bar blocks commented out once, the next time the session starts. Your usual sway session and its bar are not changed.

## 5.2.0 — 2026-10-22

- **Settings › Appearance › Quick Menu corner:** the Quick Menu can sit in any corner of the screen, not only the bottom left. Its layout mirrors to match. In a right-hand corner its rows, status icons and clock run right to left, ← and → swap (→ on a row opens its options), and Applications opens to its left. In a top corner the clock and status icons are at the top, then the search field; the favorites and open apps, the search results, a row's options and the status panels all open downwards, and ↑ and ↓ swap to match. The Screen edge margin preview shows the chosen corner. Dialogs and the on-screen keyboard keep their usual layout.
- **Settings › Appearance › Options buttons (⋯) on Quick Menu rows** is back: turn it off to hide the ⋯ buttons. ← on a row (→ in a right-hand corner), or a right-click, still opens the row's options.

## 5.1.2 — 2026-10-22

- Installer, upgrading with greetd already logging you into TVWCS: it says the automatic login is kept, instead of asking again (the question read as if greetd would be removed), and its last line says a restart logs in by itself.
- The installer purges 5.0's tvwcs-boot-logo when apt has only removed it, so nothing of it stays in dpkg. `install.sh --remove` does the same.

## 5.1.1 — 2026-10-22

- greetd's text login now uses its full path, /usr/sbin/agreety. Debian doesn't have it on the login screen's PATH, so after logging out of TVWCS (or after `install.sh --remove`) there was no login at all, only "agreety: not found". Updating fixes a config 5.0 wrote. Found testing in a Debian 13 VM.
- The installer no longer lists the same version twice when it runs from an unpacked release.

## 5.1.0 — 2026-10-22

- The TVWCS logo at startup is removed: the tvwcs-boot-logo package, its question in the installer and its switch in Settings › User. Releases now have one package, tvwcs. Updating from 5.0.x removes tvwcs-boot-logo (the tvwcs package conflicts with it), and the computer shows its usual start-up again.

## 5.0.1 — 2026-10-22

- Settings › Network, handing Ubuntu Server's netplan network to NetworkManager: systemd-networkd no longer starts again a second later and takes the same port with DHCP beside NetworkManager (until the next restart). Its other sockets started it again; it is now masked, and the catch-all network file dracut leaves in /run is removed. Found testing on Ubuntu 26.04.1 LTS.

## 5.0.0 — 2026-10-22

A leaner TVWCS: sway only, installed as Debian packages, with the parts that cost a lot of code for little use on a TV taken out.

**Installing**
- TVWCS is now two Debian packages, built from this one repository and attached to each release: **tvwcs** (the program, its sway session and Settings) and **tvwcs-boot-logo**. apt installs what they need. The installer is much shorter: it picks the release, asks about the boot logo, the automatic login and your usual sway session, then installs the packages. `install.sh --remove` removes them.
- **Settings › Software updates** downloads a new release's packages and installs them with apt (it asks for your password).
- **Upgrading from 4.x:** run the installer in a terminal once; 4.x's updater can't install packages and says so. The copy in `~/.local/share/tvwcs` is removed. Channels, favorites, options and hotkeys are kept.
- The installer no longer offers the sudo rule for sleeping, rebooting and shutting down without a password. An existing rule keeps working; without one, TVWCS asks for the password on screen when polkit refuses.

**sway only**
- TV mode and desktop mode run on sway. i3 support is removed, with Xorg, startx, xrandr, xdotool, xsettingsd, unclutter, i3lock and xss-lock. The TVWCS session makes its sway config from sway's standard one the first time (`~/.config/tvwcs/sway-session.conf`). An i3 config's TVWCS include line is taken out.
- **Power and sleep** runs on swayidle only: screen off, lock and sleep.
- The lock screen is plain swaylock, on a dark screen with a ring in your accent colour.
- **Displays**: one scale per display; the i3-only Fractional scaling and Tear-free video settings are gone.

**The login screen**
- TVWCS's own login screen (the greeter and its on-screen keyboard) is removed. Upgrading switches to another graphical login screen installed on the computer; without one, greetd stays with its text login, and the automatic login into TVWCS is kept. On a computer without a login screen, the installer sets up greetd with the automatic login.
- **Settings › User** sets the automatic login (greetd, LightDM or SDDM) and switches between installed login screens.

**New: the TVWCS logo at startup**
- **Settings › User › TVWCS logo at startup** shows the TVWCS logo while the computer starts and shuts down, instead of lines of text (the tvwcs-boot-logo package: a Plymouth theme, with GRUB's `splash` option). Turning it off removes the package.

**Removed**
- The screen saver.
- Settings › **Apps** and all Flatpak support (Flatpak updates on the Software updates page too). Apps installed with Flatpak still show in Applications.
- Settings › **Terminal**.
- Network shares on the Storage page.
- Setting the time by hand, and the region-then-city time zone picker: Date and time has one list of time zones.
- The pycairo source tarball in the repository.

## 4.4.1 — 2026-10-22

**Quick Menu**
- The date is beside the time, on one line.
- On a TV, the hint beside the channel field is shorter ("Channel number or search"), so it fits on one line and the menu is a little smaller.
- New README screenshots and demo videos.

## 4.4.0 — 2026-10-22

**Ubuntu LTS support** (tested on Ubuntu 26.04.1 LTS)
- **Installer**: on Ubuntu, a new "Ubuntu extras" step offers to remove Snap (snapd), cloud-init and the Ubuntu Pro client, each asked separately (No is the default). Only installed ones are offered, and the Snap apps that would go are listed. Packages that metapackages such as ubuntu-server brought in are kept as installed by hand, so `apt autoremove` does not take them later. Nothing is pinned, so a package that needs snapd can bring it back.
- **Settings > Apps > Settings**: an **Ubuntu extras** section offers the same removals, saying what else apt would remove with each.
- **Settings > Network**: when netplan gives the network to systemd-networkd (as Ubuntu Server does), **Let NetworkManager manage the network** switches netplan's renderer to NetworkManager. `/etc/netplan` is backed up first and put back if it fails. Saved Wi-Fi networks and fixed addresses carry over, and systemd-networkd is turned off once nothing uses it, so start-up does not wait for it.

## 4.3.0 — 2026-10-22

**Quick Menu**
- The status icons (updates, network, volume, Bluetooth, battery, ⏻) have a row of their own, and the clock and date a row below them with ⊞ Applications at its right. An update count no longer pushes the buttons past the edge of the menu.
- Favorites have a grey ★, and open apps (and workspaces) a thin band down their left side, so a favorite that is open has both.
- The menu grows to fit the on-screen keyboard while it is open, and goes back to its size after.
- New README screenshots and demo videos.

## 4.2.2 — 2026-10-22

- The screen saver on sway failed to start on Debian: its gtk4-layer-shell package (gir1.2-gtk4layershell-1.0) does not bring the library itself. Settings > Power and sleep now installs libgtk4-layer-shell0 with it, and checks for both before offering the screen saver.

## 4.2.1 — 2026-10-21

- Picking a page of an open Settings window (or another open app's shortcut) from its ⋯ menu shows that window on the page, on sway too. Before, sway left you on a new, empty workspace with a "Starting TVWCS Settings…" card, because the open window doesn't flag itself there.

## 4.2.0 — 2026-10-21

**Quick Menu**
- Favorites and open applications are one list, without the "Favorites" and "Open applications" headings: favorites first, in their order, then the other open apps. A favorite that is open stays in its place, shown as the open app with ★.
- In TV mode the channel search field is three characters wide and shows **___** (no "#").
- While an app starts, a spinner turns in place of its icon in its button, instead of the large "Starting…" notice. The notice only shows when the app was started with no button of it on screen (by its hotkey, say). Selecting the button again while it spins does nothing.
- A row's options list the app's own shortcuts at the top (such as each Settings page), then opening it the other way, then **Close this application** at the bottom, nearest the row. The selection lands on the option just above Close.
- Picking one of an open app's shortcuts (such as a Settings page) shows that app, instead of leaving you on a new, empty workspace when the app only flags its window.

## 4.1.0 — 2026-10-21

**Settings**
- **Apps**: the buttons along the top are tabs. **Search** puts a search bar right under them that searches as you type, with a ⌨ button on its left for the on-screen keyboard. **Featured** is now **Categories**: two rows of buttons with every category, Featured first. **Settings** shows on the page instead of in a pop-up, and explains how apps are installed and what each choice does.
- **Power and sleep**: the screen saver now works on sway too, drawn over every window (with gtk4-layer-shell, which the page offers to install), so a video playing full screen stays full screen under it. The DVD logo is gone: the TVWCS logo or a picture of your own. A DVD logo chosen before shows the TVWCS logo.
- **Remote and hotkeys**: clearing a Quick Menu hotkey asks first, and says whether another device's hotkey still opens it.
- **Storage**: a button to uninstall network shares (Samba), beside the one that installs them.
- The ✕ at the top of the tabs is gone. Esc (or Back) from the tabs closes Settings, as does the window manager.
- In a text field on a page, ← at its start and → at its end move to the button beside it, so a remote can reach Search's ⌨ button.

## 4.0.2 — 2026-10-21

- The Quick Menu no longer flickers when a status panel (Wi-Fi, volume, Bluetooth, battery or ⏻) or an app's options open or close at a desk. It now grows and shrinks upwards with the clock and status row held still, instead of first growing off the bottom of the screen and then jumping into place.

## 4.0.1 — 2026-10-21

- Settings > User no longer says the login screen "needs updating" right after an upgrade from 3.x. The installer and Settings now read the interface size the same way, and Automatic gives the login screen its TV size.
- Settings > Sound: a volume already above the top (such as 160 %, set by another program) is shown where it is on the bar, instead of the bar sitting at its end.
- After moving auto-login to TVWCS's session, the installer names that session instead of telling you to pick the sway one.
- New screenshots in the README.

## 4.0.0 — 2026-10-21

**Two modes**
- **TV mode** is now the **TVWCS** session at the login screen; any other session (your usual i3 or sway) is **desktop mode**. The "Used on a TV or a desktop" choice is gone. In TV mode every app opens full screen in a workspace of its own, the bar is off, the pointer hides, and the computer locks with TVWCS's lock screen. Desktop mode leaves your bar, pointer and lock screen alone.

**Installer**
- One installer, `install.sh` at the top of the repository, run with `wget -qO- https://raw.githubusercontent.com/one-moment-please/tvwcs/main/install.sh | bash`. It downloads the release you choose, or offers the one it came in when run from an unpacked release.
- It asks everything first (upgrade, another version or remove; i3, sway or both, with sway suggested on a new computer; the login screen; whether to add TVWCS to your usual session; the packages, grouped by what they are for) and changes nothing until you agree. A failure undoes what it had done.
- Login screens that can't start sway reliably (such as LightDM) get a warning with a choice: TVWCS's login screen, i3 instead, SDDM, go on anyway, or cancel. TVWCS's login screen starts the TVWCS session by default (the sway one when both are set up).
- **Remove** takes out every part of TVWCS, switching away from TVWCS's login screen first, and offers to mark the packages it installed for `apt autoremove`.
- Upgrading from 3.x cleans up the old setup and says what changed and how to put your usual session back.

**Quick Menu**
- It sits in the bottom-left corner, only as tall as what it shows. Favorites, open apps and search are at the bottom; empty sections are hidden. An open favorite shows once, as an open app with ★; a favorite that is not installed is hidden.
- TV mode has no header. The clock is smaller and the date short ("Sat, Oct 17"). The search field shows **# _ _ _** in TV mode.
- A row's options open the app once the other way: **Open in new workspace** in desktop mode, **Open alongside …** in TV mode. The mode switch is gone from them.
- Long names scroll by after 3 seconds on the selected row.
- The Wi-Fi panel can find networks and connect (asking for a password), and the Bluetooth panel can find and pair devices.
- Clicking with the mouse no longer moves the remote's selection.
- The on-screen keyboard can be hidden (the default), full or a number pad wherever text is typed, and opens next time as it was left.
- Fixed: ⏻ showed an empty box, and ⊞ needed two clicks (and the first scrolled Applications) to close Applications.

**Applications and profiles**
- ✎ opens the app's launch profile directly: channel, hotkey, Desktop Action, command, description and PIN. **Copy** makes another profile ("Firefox 2", to rename); the app's own name no longer changes. Descriptions belong to each profile.

**Settings**
- **Options** is now **Appearance**: interface size (with Automatic), theme, accent, background, closing TVWCS when it loses focus, and the screen edge margin, now set on a full-screen preview with a slider.
- **Features** is gone. A page whose software is missing offers to install it.
- **User** shows Administrator or Standard User, and holds logging in automatically, the login screen (update, switch, remove TVWCS's) and the app to open at login.
- **Remote and hotkeys** only sets the Quick Menu key per device, lists the apps with their own hotkeys (removable with ✕), and **Reset all hotkeys** also removes app hotkeys. The Applications and Fullscreen keys are gone.
- **Sound** shows only the output and input in use; the others fold under "N inactive outputs". **Allow over-amplification** lets volumes go up to 150 %.
- **Displays**: scale is a row of buttons from 75 % to 200 % (100 % and 200 % in i3 unless Fractional scaling is on). In i3, **Tear-free video** turns on Xorg's TearFree or NVIDIA's full composition pipeline, and NVIDIA's settings can be opened.
- **Power and sleep**: "Show it when the computer locks" is TV mode only. Once the screen has turned off, a lock keeps it off instead of bringing the screen saver back. The lock screen choice is gone: TV mode always uses TVWCS's.
- **Apps** offers to install Flatpak and Flathub. **⚙ Settings** adds, turns off or removes repositories (Flathub is always kept), shows unverified apps, and uninstalls every Flatpak app.
- Fixed: a long lock could stop TVWCS from responding until it ended.

## 3.6.1 — 2026-10-21

- Settings > Sound folds outputs and inputs with nothing plugged in (an empty headphone jack, an HDMI port without a TV) under one "Not plugged in" row, closed until it is chosen. They can still be tried from there. The output or input in use is always shown.
- On sway, Settings > Power and sleep no longer offers the screen saver, and swayidle no longer starts it: it was an ordinary fullscreen window there, which took fullscreen away from a video and moved focus. It comes back once it is drawn as an overlay (TODO.md).

## 3.6.0 — 2026-10-21

**Quick Menu**
- A row's options (⋯, ← or a right-click) unfold in the Quick Menu itself instead of a dialog: upwards, just above their app or workspace, indented a little on both sides and with a small gap to the row above, so it is clear whose they are. ↑ from the row goes into them; Back, ⋯ again or moving away folds them.
- A workspace's individual apps unfold upwards too, above the workspace (▴ shows them, ▾ folds them).
- ⏻ has moved to the bottom right, beside the status icons. Its menu unfolds above it and now always has **Lock**, as well as Sleep, Reboot, Shut down and (with a login screen) Log out. The "Lock in the power menu" option is gone.
- The network, volume, Bluetooth and battery icons unfold a panel above the status row: the connections, the one in use first (a wired port NetworkManager leaves to ifupdown included), with address and signal, and Wi-Fi on or off; mute, − and + for the output and the input; the connected Bluetooth devices with Disconnect, and Bluetooth on or off; the battery's estimated time left, or time until fully charged. Each panel has a button for its Settings page.
- The ⚙ Settings button and its option are gone: Settings is channel 000, and each status panel opens its own page.
- The ⊞ Applications button has moved to the Quick Menu's bottom-right corner, after ⏻. It stays highlighted while Applications is open, and pressing it again closes them.

## 3.5.2 — 2026-10-21

- Settings > Features no longer turns the whole Storage page on or off: opening, closing and switching off drives is always there (udisks2 is always installed). In its place is **Network shares (Samba)**, which installs gvfs-backends (the Samba client and the other network-share back ends) and shows the Storage page's network shares. It is off until turned on, even after a full install, so the Samba client is not installed unless it is wanted.

## 3.5.1 — 2026-10-17

- Settings > Network can take over the network of a minimal Debian install. There ifupdown runs the network (/etc/network/interfaces), and NetworkManager will not touch it, so Wi-Fi networks could not be chosen or changed (an install over Wi-Fi) and Ethernet could only be shown. Choosing the "Not managed" Ethernet port or Wi-Fi adapter now offers one button that uninstalls ifupdown, removes /etc/network and restarts NetworkManager, which then manages every port. It warns first that the Wi-Fi network has to be chosen again, and any IP address, gateway or DNS servers set by hand set again. This replaces the earlier Ethernet-only take-over. If uninstalling ifupdown fails, its ports are brought back up.
- Network is no longer one of Settings > Features: NetworkManager is always installed, even in a minimal install, and is never offered for uninstalling.

## 3.5.0 — 2026-10-16

- Settings > Displays has a **Scale** that makes text and controls bigger. In sway each display has its own, from 100 % to 300 % in steps of 25 %. In i3 (X11) there is one scale for every display, in whole steps (100 %, 200 %, 300 %); turning on **Fractional scaling** also offers 125 %, 150 %, 175 % and so on. A fractional scale is drawn at the next whole step and shrunk by xrandr, as GNOME does it, so it is a little less sharp. Only scales that leave a display at least 540 pixels high are offered, and a new scale goes back after 15 seconds unless it is kept.
- In i3 the scale reaches apps through Xft.dpi (and ~/.Xresources, so i3 and the next log-in use it too) and, for GTK apps, through xsettingsd, which install.sh now asks for in i3.

## 3.4.3 — 2026-10-16

- The real cause of "Logging in…" hanging is fixed: greetd's worker locks its memory, and pam_ecryptfs ran out of stack under the default memory-lock limit about one login in three. TVWCS's login screen now lifts greetd's limit (/etc/systemd/system/greetd.service.d/tvwcs-memlock.conf, removed when the login screen is turned off) and no longer rewrites greetd's PAM config: greetd's own comes back on update, so home folders encrypted with eCryptfs unlock as usual.
- The oval under "TV" in TVWCS's icon is filled in.

## 3.4.2 — 2026-10-16

- When the computer's login system stops answering (greetd waits for ever if a PAM module crashes while checking the password, as pam_ecryptfs can), the login screen says so and suggests restarting, instead of showing "Logging in…" until the computer is restarted. Any other failure while logging in is shown too.
- Logging in through TVWCS's login screen no longer goes through pam_ecryptfs when no home folder is encrypted with eCryptfs: TVWCS writes greetd's PAM config (/etc/pam.d/greetd) with that module left out, keeping greetd's own as greetd.tvwcs-backup and putting it back when the login screen is turned off, so pam_ecryptfs no longer needs unticking in pam-auth-update.
- The login screen fits a 1280×800 screen again: the keyboard, the Session row and Sleep / Restart / Shut down no longer overlap, the TV icon no longer crowds the user's tile, and the icon in the Session button is small.

## 3.4.1 — 2026-10-16

- TVWCS's login screen starts the "TVWCS (i3)" session again. Its command reached Debian's Xsession split in two, which showed "Xsession: unsupported number of arguments (2); falling back to default session."
- The login screen's on-screen keyboard is narrower: square letter keys with letters twice as tall, and a matching number pad.
- If greetd stops answering, the login screen says so after a while instead of showing "Logging in…" for ever.

## 3.4.0 — 2026-10-16

**TVWCS's login screen**
- A login screen in TVWCS's look: big tiles for the people who can log in, the password typed on a keyboard or with the remote on an on-screen keyboard (the full one, or a number pad), and a choice of session: TVWCS's own i3 and sway sessions, plain i3 and sway, and any other desktop installed. Sleep, Restart and Shut down are at the bottom. It remembers who logged in last, and each person's session and keyboard. It runs on greetd with cage, and starts X sessions such as i3 through startx and Wayland ones such as sway directly.
- The installer installs it by default where there is no login screen, also when the computer logs in by itself: the automatic login then goes through the login screen, which shows after logging out. Next to another login screen it is offered, and the default is no.
- Setting TVWCS up for sway with a login screen that cannot start sway (such as LightDM) now offers TVWCS's login screen first, then SDDM, then keeping it anyway or leaving sway out.
- Settings › Features turns it on or off. Off goes back to the login screen used before; with none, it asks whether to have no login screen (logging you in by itself) or to install SDDM or LightDM. Going back to one that cannot start sway, while in sway, warns and offers SDDM. Changes show from the next start. It also offers to update the login screen when its copy of TVWCS or its colours are out of date.

**Installer**
- It now asks where TVWCS should start: in your usual i3/sway session (the include line in its config), only in a "TVWCS" session of its own at the login screen, leaving the usual sessions alone, or both. Before, declining the login screen entry next to other desktops left TVWCS in neither. On a computer only for TVWCS it is asked when there is a login screen.
- With neither i3 nor sway installed, it offers to install both as well as either one.
- TVWCS has an icon: the letters TV, underlined with a thin oval. The TVWCS sessions at the login screen and TVWCS's login screen show it.

**Settings › User** (new)
- Change your name and password, see whether you are an administrator and which login screen is in use, and turn the automatic login at start-up on or off (with TVWCS's login screen, LightDM, SDDM or no login screen).

**Settings › Options**
- Open at login says that some applications, such as Steam, can start at login by themselves, and to set it to None when using that.

**On-screen keyboard**
- Password dialogs open with the keyboard a password was last typed on: the full keyboard at first, the number pad once a password was typed on it. Settings › Options › Password keyboard shows and changes it.

## 3.3.1 — 2026-10-16

- The Quick Menu no longer shows a line of key hints (OK Select, Back Close, ...) under its title and buttons.

## 3.3.0 — 2026-10-16

**Quick Menu**
- A new order, built up from the bottom: the status row stays at the bottom, the search field is just above it with the search results above the field (the best match nearest it; ↑ and ↓ move the highlight while you keep typing), then your open applications, then your favorites. The title and buttons stay at the top, with the key hints under them. Open applications and favorites are hidden when there are none; with neither, a note points to the guide (⊞) for the installed applications.
- The status row has a battery button on a computer with a battery: the charge in percent, with a mark while charging or plugged in. It opens Power and sleep.
- At a desk, the Quick Menu is only as tall as its contents, in the bottom-left corner with the same margins, and grows upwards as search results appear. Opening Applications stretches it to the full height, with everything but the title and buttons kept at the bottom.

**Hiding the mouse pointer**
- Only TVWCS's own session hides the pointer. The unclutter TVWCS starts now always ends with TVWCS, so it never outlives the i3 session.
- Installing unclutter-xfixes (by the installer or Settings › Features) no longer brings in unclutter-startup, which started unclutter in every X session, so other desktops hid their pointer too. When that autostart is already on, the installer explains it and offers to turn it off (a "no" is remembered).

**Installer**
- When the login screen cannot reliably start Wayland sessions (LightDM, as on Linux Mint, and other X-only ones), the installer warns before setting TVWCS up for sway and asks whether to go on. Going on suggests a login screen that can, such as SDDM or greetd with tuigreet. Declining leaves sway out; the answer is remembered for that login screen.

## 3.2.3 — 2026-10-16

- Power and sleep: the TVWCS logo's inner oval holds a QR code instead of a barcode, with its square-in-a-square finder pattern on the left.

## 3.2.2 — 2026-10-16

- In the Quick Menu, a workspace with more than one application has a square ▾ button between ⋯ and its name that shows or hides its individual apps. It is always visible, even when the options buttons are hidden, and the option has left the workspace's ⋯ menu. On the name, ← moves onto it; ← again opens the row's menu.
- The ⋯ options buttons on Quick Menu rows are half as wide as they are tall.

## 3.2.1 — 2026-10-16

- The screen saver covers every monitor, each with its own bouncing logo, instead of only the one in use. Any key, click or pointer movement ends it on all of them, and focus goes back to the workspace that had it.
- On a laptop whose battery times leave "Turn off the screen after" to the system, the screen turns off on battery again. TVWCS now keeps the system's own screen times when it takes them over, and gives them back when the setting is left to the system.

## 3.2.0 — 2026-10-16

**Quick Menu and Applications**
- On a TV the search field starts three digits wide with a short hint beside it. Typing a letter or a fourth digit hides the hint and widens the field. At a desk the hint line is gone.
- The search results scroll to keep the selected result in view when moving with the D-pad or arrow keys.
- At a desk, TVWCS no longer fills the screen: Applications is only as wide as its rows and most descriptions need. A description that does not fit scrolls by while its app is selected, and the pointer shows it in full.
- Opening Settings follows the rules for opening apps (full screen in its own workspace on a TV), instead of always opening as a tile.
- The volume and Bluetooth icons are hidden when their features are turned off.

**Settings**
- A new Features page turns sound, Bluetooth, network, storage, the terminal, Flathub apps, the screen saver, the screen saver when locked and hiding the pointer on or off. Turning one on installs what it needs. Turning one off can uninstall its packages, but only when nothing else installed needs them. A feature that is off keeps its tab, which offers to turn it on.
- Options: hide the mouse pointer after a time without moving, with − and + for the seconds. It is on by default on a TV (3 seconds) and now off at a desk. A hidden pointer no longer leaves anything highlighted: on i3 it is moved to the bottom-right corner of the focused window.
- Power and sleep: a laptop gets separate times plugged in and on battery, and a choice of what to do when the battery is nearly empty (shut down at 5% unless changed).
- Power and sleep: the screen saver can show while the computer is locked (i3, with xsecurelock). A key shows the password box; after a minute without one the screen saver comes back. The screen saver no longer runs while the screen is off.
- Power and sleep: the TVWCS logo's oval now holds a smaller oval with a barcode, instead of "TV".
- Date and time: setting the time by hand is one dialog with a box for each of year, month, day, hour and minute, each with ▲ and ▼, and AM/PM with the 12-hour clock. The three ways to set it are gone.
- Storage: partitions are indented under their drive, and say Mounted or Not mounted. Partitions of the running system (such as / and /home) are marked as part of the system and named after what they hold.
- When the Settings window is taller than it is wide, the tabs show only their icons and the "Settings" title is left out.

**Installer**
- A first install asks for everything or a minimal install (the Quick Menu, the applications list and basic Settings). `TVWCS_INSTALL=minimal` chooses it without asking.
- The packages of features that are turned off are no longer asked for.
- xsecurelock is offered for the screen saver when locked (i3).
- With an i3 config but no sway config, running sway on its own reads the i3 config and fails (for example on `tiling_drag modifier titlebar`). The installer now explains this, offers to create a sway config, and shows how to start TVWCS's sway session from a text console (`tvwcs-session sway`), for login screens that do not list it.
- The mouse pointer is no longer hidden by a line in `tvwcs.conf`; TVWCS hides it itself, as Options says.

## 3.1.0 — 2026-10-15

**Quick Menu**
- The search bar is selected when the Quick Menu opens, and it says you can type a channel number.
- Each row has one menu (⋯) with labelled choices: open in a new workspace or this one, the app's own actions, and Close when the app is open. It replaces the sliding options and the second popup.
- Channels run from 000 to 999. Channel 000 opens Settings: on the first start of 3.1, Settings moves to 000 unless another app already has it.
- Setting a channel shows three digit boxes that start empty each time, with a number pad.
- A slow app shows "Starting…" instead of a blank screen, and the Quick Menu can still be opened meanwhile. An app that is already running and only asks for attention when started again is brought to the front.
- With "Keep the Quick Menu open" on, the Quick Menu now comes back when Settings (or the last app on screen) closes, even when apps are open on other workspaces.
- A hidden mouse pointer no longer highlights what it was resting on.
- Search results no longer repeat an app's name when its profile has the same name.
- Password dialogs can show a number pad, with a key to switch to the full keyboard and back.

**Settings**
- Options: light or dark mode (dark by default), passed on to GTK, Flatpak and browser apps that follow the system's choice. A background colour from 18 swatches (dark grey by default), shown when no app is open and behind the Quick Menu. Password dialogs can open with the number pad.
- With the number pad chosen and SSH on, Settings recommends turning off SSH password login.
- Power and sleep: a screen saver (the DVD logo, TVWCS's logo or a picture of your own) with its own idle time and a preview.
- Date and time: set the time by hand in one of three ways: fields with ▲ and ▼, steps, or four digits.
- Network: an Ethernet port the Debian installer set up in `/etc/network/interfaces` showed as "not managed". Settings now says why and can hand it to NetworkManager, keeping a backup of the old file.
- A new Storage page: open, close and safely remove drives, and add, connect and disconnect network shares (Samba, NFS, SFTP, WebDAV, FTP).
- Choosing a hotkey ignores the D-pad, OK and Back, so the Clear button can be reached with a remote.

**Session**
- Apps no longer take up to half a minute to start when TVWCS is started from `startx`: the session's display is now passed to systemd and D-Bus, so the desktop portal that Flatpak apps wait for can start. Run the installer again (or log in again after updating) to get it.
- Updating TVWCS from Settings now checks first whether the new version needs packages that are not installed, lists them with what each is for, and installs them (asking for your password) before updating. This works from 3.1.0 on: the update to 3.1.0 itself still only lists them on the pages that need them.
- `install.sh --help` explains the installer's options, and `install.sh --missing` lists what is missing without installing anything. An unknown option no longer runs a full install.
- The installer offers udisks2, gvfs-backends, libglib2.0-bin, xdg-desktop-portal-gtk, python3-gi-cairo and x11-xserver-utils for the new features.
- The README lists what does not work on systems that are not Debian-based.

## 3.0.3 — 2026-10-15

- The install command in the README and the Debian guide now downloads the latest release instead of the development version on `main`. Every release includes `tvwcs.tar.gz` for it. Installing from `main` is still described, for testing.

## 3.0.2 — 2026-10-15

- openSUSE is no longer supported: TVWCS supports Debian and Debian-based systems (Debian, Ubuntu, Mint, Pop!_OS, Raspberry Pi OS) with systemd. The installer no longer installs packages with zypper, and Settings no longer offers zypper updates. `TODO.md` lists what bringing openSUSE back would take.

## 3.0.1 — 2026-10-15

- Displays: the resolution kept under i3 and the one kept under sway are saved separately, so one never overwrites the other. The first time sway runs, it uses the resolution kept under i3 (X calls the TV's port HDMI-1, sway calls it HDMI-A-1).
- On a 720p TV, TV Mode and 4K TV Mode shrink to fit, so Settings and the Quick Menu are no longer cut off. On a 1080p TV nothing changes.
- Power and sleep no longer mentions X when running under sway.

## 3.0.0 — 2026-10-15

**Supported systems**
- TVWCS now supports Debian and Debian-based systems (Debian, Ubuntu, Mint, Pop!_OS, Raspberry Pi OS) and openSUSE, with systemd. Arch, Fedora, Void, Alpine, Gentoo and systems without systemd are no longer supported; `TODO.md` lists what bringing them back would take.

**Installer**
- It first asks how TVWCS is used: as this computer's only interface (it can log in and start TVWCS at boot, as before), or next to your other desktops. The second adds "TVWCS (i3)" and "TVWCS (sway)" to the login screen, with TVWCS's own session config in `~/.config/tvwcs/`. It never sets up automatic login, and adding TVWCS to your usual i3 or sway config is optional (default no). `TVWCS_SETUP=dedicated` or `alongside` answers the question.
- It starts by saying what it found: a login screen, other desktops, i3 and sway.
- It offers an icon theme and the Open Sans font when they are missing.

**Quick Menu**
- An on-screen keyboard and number keypad: press OK on the empty search field to type with a remote.
- The launch profile editor and an app's list of profiles open inside the TVWCS window and work fully with a remote: each field is a row, with Save, Cancel and Delete. A PIN-protected profile asks for its PIN first.
- A welcome on first start asks whether TVWCS is used on a TV or at a desk.
- Errors, messages and a "Starting <app>…" card show in the window.
- New icons: ⊞ opens Applications, ⋯ opens a row's options, ≡ starts an app with one of its own shortcuts.
- "Guide" is now called Applications, and its channel list Channels.
- On a TV, the key hints at the bottom name the remote's keys (OK, Back).
- Text has more contrast, and fades follow the new Reduce motion option.
- Plain launch profiles keep working when their app is renamed (such as the old "Control Panel").

**Settings app**
- A new **Remote and hotkeys** page (`tvwcs settings hotkeys`). TVWCS's own updates moved to **Software updates**.
- **Where apps open** is one choice: Full screen, one per workspace; Side by side; or As each app's profile says.
- Choosing TV turns on button hints. Interface size applies at once.
- New options: accent colour, screen edge margin (for TVs that cut off the edges), and Reduce motion.
- Pages show key hints at the bottom.
- The launcher is called "TVWCS Settings" and is hidden in GNOME and KDE menus.

**Lock screen**
- An optional TVWCS lock screen (Settings › Power and sleep › Lock screen, off by default). It shows "Locked" and says whose password to type, using i3lock (swaylock on sway). The power menu's Lock, the idle lock and xss-lock (when the i3 config starts it) use it; switching back restores the previous locker. `tvwcs lock` locks by hand.

## 2.11.2 — 2026-10-15

- TV mode: when the Quick Menu is kept open over an empty screen and a window opens from elsewhere (Settings started from a terminal or a hotkey, an app started by its hotkey), the menu now steps aside for it. Before, the new window opened hidden under the menu while taking the keyboard.

## 2.11.1 — 2026-10-15

- Hotkeys set to a remote's media keys (such as Search, Mail or Tools) work: GTK names those keys without the "XF86" that i3 needs, so i3 ignored the bindings ("Could not translate string to key symbol"). They are now written as XF86Search and so on; no need to set them again.
- TV mode: with nothing open, the Quick Menu shows about 2 seconds after TVWCS starts instead of 10 (unless it is set to open an app at login), and the bar hides again within about 4 seconds after i3 reloads its config.
- README: new screenshots of the Quick Menu, with its clock and status icons.

## 2.11.0 — 2026-10-15

**Quick Menu**
- The bottom of the Quick Menu shows the time and date, and icons for the network (wired, Wi-Fi with its signal strength, or offline), the volume, Bluetooth and waiting updates (only when there are some). Each opens its page of Settings; the clock opens Date and time. They are reached with ↑ from the top of the menu, or ↓ past its last row.

**TV mode**
- The i3 (or sway) bar is hidden, since the Quick Menu now shows the time and status. It comes back as it was when TVWCS stops, or when Options › Hide the i3 bar is turned off.
- While no application is open, the Quick Menu stays on screen (Esc does not close it), and it comes back by itself when the last application closes. Options › Keep the Quick Menu open turns this off.

**Settings app**
- A **Date and time** page: the time zone, chosen as a region and then a city; setting the time from the network; and a 12-hour or 24-hour clock for the Quick Menu. Changes go through `timedatectl`, asking for your password when polkit needs one.
- After installing updates, the Quick Menu's updates icon counts them again.

**Installer**
- When an X server is already installed, such as XLibre, `install.sh` offers i3 for it and no longer installs the Xorg server over it.

## 2.10.4 — 2026-10-15

- Updating from Settings restarts TVWCS again. Updating 2.10.2 to 2.10.3 installed it but left the old TVWCS running, with nothing said: Settings imported the new `main.py` to send the restart, and that needed a name the old modules still loaded in Settings did not have. Settings now sends the request itself, and the new start-up code lives in a module of its own, so an update from 2.10.2 or 2.10.3 restarts properly.

## 2.10.3 — 2026-10-15

- Flatpak apps launch from the Quick Menu and the guide, and show their icons, when the session's `XDG_DATA_DIRS` lacks Flatpak's folders (X started with `startx`, or Flatpak installed during this login): TVWCS adds them for itself at start-up, the way Flatpak's profile script does. Before, such an app was listed but nothing happened when it was chosen.
- `install.sh` no longer lists libXss (`libxss1`) as missing when it is installed: it asked `ldconfig`, which is not on an ordinary user's PATH on Debian.
- README: new screenshots of the Quick Menu and the Applications guide, taken on a TV.

## 2.10.2 — 2026-10-15

**Releases**
- Each change merged into TVWCS is now released at once as a prerelease, and marked as the latest release once it has been tested on a TV computer (the Promote workflow).

**Settings app**
- Options: **Include prereleases** makes Check for updates offer prereleases too, and **Roll back to the latest release** installs the release marked latest, even when it is older than the one installed.
- System information: a session started with `startx` from a console shows as X11, not "tty".
- A page's rows drawn again behind a dialog (such as the update dialog) keep their scroll position.
- Power and sleep: where `xss-lock` runs (Debian's and Ubuntu's stock i3 config starts `xss-lock -- i3lock`), turning the screen off also locked the computer, even with "Lock after" set to Never, so a TV woke up to a password prompt. The page now says so, and a **Locks when the screen turns off** row comments the line out of the i3 config (keeping a copy as `config.before-tvwcs`) and stops xss-lock.
- Power and sleep: "Closing the lid" is only shown on a computer that has a lid.
- Sound: when the volume or mute cannot be changed, the reason is shown and the page shows the real values again, instead of looking changed. − from a volume above 100 % (set by another program) goes down 5 % at a time rather than straight to 100 %. After choosing an output, the selection stays on it.
- Network: Wi-Fi names with characters outside ASCII (such as "Taylor’s") show and join correctly: the tools Settings runs now use the C.UTF-8 locale instead of C.
- Network: joining Wi-Fi on a computer that is also on a wired connection NetworkManager does not manage (ifupdown on Debian) no longer moves all traffic to Wi-Fi: its route metric is set above the wired one, so Wi-Fi stays as a backup.
- Displays: "Keep these display settings?" now starts on Go back, so pressing Enter on a screen that shows nothing undoes the change.
- Long choice lists open scrolled to the current choice.

## 2.10.1 — 2026-10-15

**Installer**
- `install.sh` asks whether TVWCS will be used on a TV or a desktop monitor (until it is answered), and sets the interface size and how apps open to match.

**Settings app**
- New **Apps** page, a store for Flatpak apps from Flathub: a grid of tiles with icons, names and summaries; Featured apps that suit a TV first, then categories (Video & music, Games, Internet, Graphics & photos, Office & education, Utilities), a search typed on the on-screen keyboard, and the installed apps. A tile opens the app's description with Install, or Open and Remove. Apps are installed for the user (`flatpak install --user`, no password); one installed system-wide is removed as root. The page offers to install Flatpak with the package manager and to set up Flathub for the user, and reads the catalog flatpak downloads (`flatpak update --appstream`), so it works with the remote alone. `tvwcs settings apps` opens it.
- Options: a new **Used on** row (A TV, or A desktop monitor) sets the interface size and where apps open: on a TV every app opens in a workspace of its own; on a desktop monitor apps open tiled in the current workspace. Each can still be changed on its own. On a TV, a window alone on its workspace also has no border or title bar (i3 and sway's `hide_edge_borders smart`, with thin borders instead of title bars when windows share a workspace).
- Options: **Open at login** is now one choice: None, TVWCS Quick Menu, Last application or Chosen application; choosing the last shows an **Application** row to pick it with. The separate "Open the Quick Menu at login" switch is gone (a config that had it on, with nothing else chosen, opens the Quick Menu).
- The applications guide finds Flatpak apps even when the session's `XDG_DATA_DIRS` does not include Flatpak's folders (as right after installing Flatpak, before logging in again).

## 2.10.0 — 2026-10-14

**Settings app**
- New application, `tvwcs settings` (opened by the Quick Menu's ⚙ and listed under System in the applications guide; `tvwcs control` still works): Options, Sound, Displays, Bluetooth, Software updates, System information, Terminal and Network as vertical tabs on the left, in the TVWCS Metro style and at its interface size, and usable with a D-pad alone.
- Displays: resolution and refresh rate of each display; with several, which are on, how they are arranged and (X11) which is primary, through `xrandr` or `swaymsg`. Changes that can blank a screen go back after 15 seconds unless kept, and kept settings are applied again when TVWCS starts with the same displays.
- Options: TVWCS's own settings, moved here from the applications guide's ⚙ view: the Quick Menu's buttons, interface size, behavior, what opens at login, hotkeys, application hotkeys and TVWCS's own updates. Each change is saved and the running TVWCS reads it again at once. The power buttons are no longer here; they are in the Quick Menu's power menu.
- Sound: volume and mute of the output and the input, and which output and microphone to use (sound already playing follows), through `pactl` (PipeWire or PulseAudio). Outputs of a sound card's other profiles are listed too (often HDMI, which PipeWire only shows once the card is switched to it), and choosing one switches the card over. With no sound card at all, it names the firmware packages to install.
- Power and sleep: turn the screen off, lock and sleep after a chosen time without input (or never), skipped while sound plays or an app holds an idle inhibitor; TVWCS keeps the times (watching the X idle time on i3, running `swayidle` on sway, which calls the new `tvwcs idle …` back). The page also shows X's blanking and DPMS times and logind's idle action and lid switch. `install.sh` lists `libxss1` (i3) or `swayidle` (sway) when missing.
- Bluetooth: on and off, search, pair, connect, disconnect and forget devices, with battery levels, through `bluetoothctl`.
- Software updates: waiting updates from apt, dnf, pacman, zypper, xbps or apk and from Flatpak; installs them with the output on screen, asking for the sudo password in an on-screen dialog when needed; offers a restart when one is needed.
- System information: computer, processor, memory, graphics (named from the kernel driver without `lspci`), displays, every drive in use, battery and versions; and remote access: the SSH server on or off (or installed), passwords or keys only (refused while the user has no key), and the command, user, local name and IP addresses to connect with.
- Terminal: your shell in a full terminal (VTE for GTK 4), or a one-command-at-a-time console without VTE.
- Network: Ethernet and Wi-Fi status, connect and disconnect, Wi-Fi on and off, join (with a password) and forget networks, and IP settings, through NetworkManager's `nmcli`; shown read-only from `ip` without it.
- Text is typed on a keyboard or on an on-screen keyboard driven by the D-pad.
- Terminal: coming in from the tabs lands on the buttons above the terminal, and Esc or Back inside the terminal goes back up to them, so they can always be reached with a remote. New **Tab** and **Esc** buttons type those keys into the shell.
- Network: Wi-Fi networks are searched for only when you choose **Search for networks**; the page no longer makes the adapter scan in the background. Each connection has an **IP settings** row that shows whether it uses DHCP and opens its settings: a fixed IP address, default gateway and DNS servers (filled in from the ones in use), or back to automatic (DHCP).
- Software updates: when downloading the package lists or installing updates finishes, the page says so, with the time and what the check found ("Everything is up to date." or how many updates are available). `apt-get update` prints no "Done" when it is not run in a terminal, so the log used to end at "Reading package lists...".
- `install.sh` installs the Settings app's launcher (with an action for each page) and lists the optional tools its pages use.

**Quick Menu**
- At the top: ⚙ opens Settings and ⏻ opens a power menu with Sleep, Reboot and Shut down, plus Log out when a login screen is installed and Lock when it is switched on in Options. ⚙ and ✕ can be hidden in Options.
- The applications guide no longer has the ⚙ button that switched it to TVWCS's settings.

**Installer**
- New guide, `docs/INSTALL-DEBIAN.md`: Debian's network installer with no desktop, SSH and Avahi, then TVWCS installed over SSH from another computer.
- The mouse pointer hides after 3 seconds without moving and comes back when it moves: sway does it itself, and in i3 the TVWCS config runs `unclutter`, which `install.sh` offers to install.
- `install.sh` lists every missing package with what it is for (including PipeWire, with `pipewire-pulse` and WirePlumber, when no sound server is installed) and offers to install them all with the package manager (on a terminal, on a known distribution). On Debian this adds `dbus-user-session`, which WirePlumber needs on a minimal install, and PipeWire is started for the current user right away; systemd starts it at every log-in after that. Without systemd, the TVWCS i3/sway config starts PipeWire, WirePlumber and `pipewire-pulse` when they are not running.
- With neither i3 nor sway installed, `install.sh` offers to install one with the package manager (i3 with Xorg, `startx`, `xdotool` and `xrandr`, recommended; or sway), then sets it up and offers the automatic login.
- On a computer with no login screen, `install.sh` offers (default no) to log the user in automatically at boot and start i3 (through `startx`) or sway, through systemd's or runit's console login and the login shell's profile. When set up, TVWCS opens its Quick Menu at log-in, and the session starts on the screen as soon as the install is done.
- `install.sh` works over SSH: it reaches the running i3 or sway through its socket (no DISPLAY needed) to reload it and restart TVWCS, never starts TVWCS where there is no display, and says to use `ssh -t` when it has no terminal to ask on.

## 2.7.0 — 2026-10-14

**Hotkeys**
- The remote set has a new *Fullscreen* key (unset by default) that toggles fullscreen on the focused app. It never acts on TVWCS's own windows.
- The remote's Applications key now starts unset (it was Shift+F2). A key you already chose is kept.
- Any launch profile can have a hotkey that launches it, set in its editor (`tvwcs launch <profile id>` from a terminal). A profile with a PIN shows the Quick Menu to ask for it.
- New *Application hotkeys* section in Settings: it counts the mapped application hotkeys and opens a list where each can be changed or removed.
- Choosing a key that is already used (by another device slot or an application) now warns and asks for confirmation, then moves the key, instead of refusing it.

**Behavior**
- New setting *Always open apps in a new workspace*: every app, launched or selected while open, gets a workspace of its own.
- An app that was fullscreen when TVWCS opened is made fullscreen again when TVWCS closes or switches to it.
- Clicking the TVWCS window while a profile editor or the application profiles window is open closes those windows (unsaved changes are dropped), instead of leaving TVWCS in front and frozen.

**Install**
- TVWCS now installs into `~/.local/share/tvwcs` (it was `~/.config/i3/tvwcs`); your data stays in `~/.config/tvwcs`. `install.sh` points `tvwcs.conf`'s exec line at wherever it installs, so `TVWCS_DEST` needs no hand edit any more.
- `install.sh` offers (asking first, and backing the file up as `config.tvwcs-backup`) to add the include line to your i3 and/or sway config, and reloads the window manager if it is running.
- An install in the old location is moved: the include line is updated after asking, hotkeys point at the new launcher, and the old copy is deleted after asking once nothing uses it. *Check for updates* moves it too, after saying so in its confirmation.
- With no i3 or sway config, `install.sh` offers to create one from the standard template (i3-config-wizard's, or sway's), asking for the `$mod` key (Super or Alt) and whether to use the current keyboard layout or another one.

**Other distributions, and systems without systemd**
- `install.sh` names missing packages for the distribution it runs on (apt, pacman, dnf, zypper, xbps, apk, emerge), finds the keyboard layout where Arch and Fedora keep it, and no longer needs `cmp` (minimal Fedora and Arch installs lack it).
- Sleep, Reboot and Shut down use systemd when it runs the system, else elogind's `loginctl`, else `zzz` / `reboot` / `poweroff`; a refused command now shows its error instead of failing silently. Lock says so when no screen locker is installed.
- Without `XDG_RUNTIME_DIR`, TVWCS keeps its PID file and hotkey requests in `~/.cache/tvwcs` (it used the shared `/tmp`). *Open at login* now records which login it ran in, so it still runs once per login where nothing empties that folder at logout. A PID file left from before a reboot no longer blocks TVWCS from starting.

**Power actions that need a password**
- When Sleep, Reboot or Shut down needs root (no systemd or elogind, or polkit refuses because no agent can ask), TVWCS tries a no-password `doas` or `sudo` rule, then asks for your sudo password in its own dialog: a hidden field for a keyboard (such as the one on the back of a remote) and a keypad for numeric passwords. The password goes to `sudo -S` through a pipe and is never stored; a wrong one asks again, up to 3 times. A user sudo refuses, or a sudo that demands a terminal, gets a clear message.
- `install.sh` offers (on a terminal, default no) a no-password rule for exactly those commands: `/etc/sudoers.d/zz-tvwcs-power-<user>`, checked with `visudo` first and named to come after the user's other sudo rules (the last match wins), or lines in `/etc/doas.conf`, checked with `doas -C`. It says when such a rule is already in effect.

**sway**
- TVWCS runs on sway: it uses `swaymsg`, lists native Wayland windows (by app_id), and takes the monitor from sway's focus instead of xdotool.
- Opening TVWCS over a fullscreen app takes the app out of fullscreen while TVWCS is open (sway would otherwise keep TVWCS hidden behind it); it is made fullscreen again when TVWCS closes.

**At login**
- New setting *Open the Quick Menu at login* (off by default): shows the Quick Menu once per login, after the login app if one is chosen.

**Quick Menu**
- Typing a three-digit channel number and then nothing for a second launches that channel, without Enter.

**Display**
- The interface sizes are now *Desktop*, *TV Mode* and *4K TV Mode*. 4K TV Mode is only offered when a 4K or larger display is connected (or when it is already the chosen size).

## 2.6.0 — 2026-10-14

**Applications pane**
- Removed the Networking and Updates tabs (and their `network`, `updates`, `ui_network`, `ui_updates` modules); TVWCS no longer needs NetworkManager or apt.
- No more tab bar: the pane always opens on the applications guide, and a button at its top right switches between the guide and Settings. Esc in Settings returns to the guide.
- Settings rows are reachable with the arrow keys again (they were registered with a panel that no longer exists).

**Settings**
- New *Check for updates*: looks up the latest published GitHub release, and if it is newer asks whether to install it, then downloads it to a temporary folder, runs its `install.sh` over the current install (your data is kept), deletes the download and restarts TVWCS.

**Quick Menu rows**
- ← on a favorite, search result, open application or workspace opens its options, with the option next to it selected. The options close again as soon as the selection moves away from them (they stay open while a pop-up or confirmation opened from them is up).
- The options button is a ☰ and every option inside is a square button.

**Look and feel**
- Every close button is red.
- The Quick Menu's close and Applications buttons are square, and the Applications button (now a ☰ menu symbol) lines up with the right edge of the search field.
- *Your channels* is now *Channel Guide*. Each application's Edit button is a ✎ symbol, and it and the favorite star are square.
- New *Button hints* setting (off by default): an icon-only button selected for 3 seconds shows its tooltip for 6 seconds.

**Hotkeys: one set per device**
- A modifier tapped on its own (the default keyboard hotkey, Super) is now bound directly in i3 as `bindcode --release <keycode>`, using the keyboard's real keycode. xcape is no longer used or needed; it depended on spare F13/F14 keys that many keyboard layouts do not define.
- Separate hotkeys for the keyboard, the remote and a gamepad, each with a Quick Menu key and an Applications key. Defaults: keyboard taps Super for the Quick Menu; remote keeps F2 / Shift+F2; gamepad is unset (map its buttons to keys with a tool such as AntiMicroX, then capture them).
- Any hotkey can be cleared from its capture dialog, and a key can only be used once across all sets.
- An existing single hotkey pair is kept as the remote set.

**Settings layout**
- Settings uses the pane's width: two columns (Display and Behavior; Hotkeys, At login and Updates), with the System actions in a grid across the bottom. ← and → jump between the columns; ↑ and ↓ stay in one.

**Install and release**
- README rewritten: shorter, screenshots side by side with descriptions, and the zip install now extracts into a temporary folder instead of `~/.config/i3/`.
- The installed copy reports its real version (it read `VERSION` from the wrong folder).
- `install.sh` notices a running TVWCS and, after asking (Y/n), restarts it on the version just installed (through i3 when i3 is running). Without a terminal it only says how to restart; the in-app updater skips this and restarts TVWCS itself.
- `make-release.sh` replaces an existing zip of the same name instead of adding to it.

**Quick Menu**
- Swapped the positions of the "＋ ›" (open applications) button and the "✕" (close) button in the Quick Menu header; keyboard focus order follows the new left-to-right layout.

## 2.5.0

**Removed: launching a profile as another Linux user** (the same result is available with a custom launch command). The *Launch as user* choice, the password prompt, the `runas` module and its tests are gone, along with the `.desktop` action command parsing that only it used. Old config files that contain a `run_as_user` key load fine; the key is ignored and dropped on the next save.

**PIN-protected profiles (replaces it)**
- Any profile can be protected with a 4–8 digit PIN of its own, set in the profile editor. PINs are stored only as salted hashes.
- Choose when it is asked: *only when launching*, or *when launching and when showing it* — bringing up an open app (or a workspace holding one) from a workspace that is not on screen. Showing an app that is already visible never asks.
- The PIN is entered on an on-screen keypad that works with the D-pad (digit keys and Backspace work too). Five wrong tries lock that profile for 30 seconds. Protected profiles carry a lock mark in the Guide and Favorites.
- Changing or deleting a protected profile needs its current PIN, and the application's own desktop actions respect the main profile's PIN, so neither is a way around the lock.
- Which profile an open window belongs to is remembered when TVWCS launches it (for this session); a window TVWCS did not launch falls back to its application's main profile.
- The app chosen under *At login* is opened without a PIN, since the owner chose it in Settings.
- This is a convenience lock for a shared TV, not strong security: anyone who can edit `~/.config/tvwcs/config.json` can remove it.

**Descriptions can be overridden**
- The application's page (Guide > Edit on a main profile) has a Description field; empty uses the `.desktop` description, shown as the hint.
- A secondary profile's editor has its own Description field; empty shows its launch options (action and command).

**Settings**
- Multiple-choice settings (Interface size, Open at login) now open a small pop-up of the choices with the current one ticked, instead of cycling.
- Choosing an app for *Open at login* lists Favorites first, then apps with channel numbers, then everything else.

**Remote**
- The browser Back key (XF86Back) works exactly like Esc: it closes dialogs, Settings, the Guide and the Quick Menu in turn, cancels hotkey capture and the PIN keypad, and dismisses pop-up menus.

**Code**
- New `pinlock` (hashing and the try limit) and `ownership` modules; 111 tests.

## 2.4.0

**Bug fix: apps missing from Open applications**
- TVWCS used to hide any window whose title *began with "tvwcs"* (meant for its own dialogs). Opening a document called `tvwcs.conf`, `TVWCS notes.txt` and so on made the editor disappear from the list. TVWCS's own windows are now recognised by an exact title (`TVWCS`) or the distinctive prefix `TVWCS · `, so no other app's window can match. Windows with no title are also kept (listed by their class) instead of dropped.

**Navigation**
- Pressing Right at the end of a Quick Menu row opens the Guide (or moves into it if it is open). Past the end of the Guide it opens Settings; Left in Settings closes it and returns to the Guide.
- Pressing Left on a Quick Menu row's options button expands that row's options.
- Typing anywhere in TVWCS goes into the search field and searches. (Not while a dialog is open, in another text field, or with Ctrl/Alt/Super held.)

**Quick Menu: workspace-centric**
- Favorites now sit *below* Open applications.
- Open applications lists workspaces, not windows. An app alone on its workspace is listed as that app; apps sharing a workspace are grouped into one entry named after what is in it ("Brave + Text Editor").
- A workspace entry's options (left): move to another monitor (only shown when there is another monitor; offers a choice of monitors), expand into its individual apps (to open just one, or use that app's own options), and close the workspace and all its apps (asks first).
- An open app's options now include opening it the other way: tiled in the current workspace, or in a workspace of its own.

**Guide**
- Secondary profiles show a "↳" mark in the logo's place and list their `.desktop` action, custom command and run-as user instead of the application's description.
- A Settings button at the top right of the Guide opens a third panel, as wide as the Quick Menu. The Guide now fills only the middle.
- Secondary profiles can be launched as another Linux user (see below).

**Settings panel (new; the System menu moved here)**
- Interface size: Desktop, 10-foot (1080p TV), 10-foot (4K TV).
- Close when clicking outside TVWCS.
- Open running apps in a new workspace (instead of tiling them into the current one). Apps individually set to always launch in a new workspace are unaffected.
- Hotkeys: choose the keys that show the Quick Menu and the Guide. A lone modifier such as Super can be used and does not break Super+key shortcuts (uses xcape). Written to `~/.config/tvwcs/hotkeys.conf`, which `tvwcs.conf` includes.
- At login: open a chosen app, or reopen the last app, once per login.
- System: Lock, Refresh applications, Sleep, Log out, Reboot, Shut down (the last three still confirm). The System button is gone from the Quick Menu header.

**Run a profile as another user**
- Secondary profiles have a *Launch as user* choice. If sudo allows it without a password the app just starts; otherwise a password prompt appears. Authentication uses `su` over a pseudo-terminal; the app is given access to your X display with `xhost`.

**Code**
- Split into smaller modules: `widgets`, `theme`, `ui_window`, `ui_settings`, `ui_editors`, `main`, plus `hotkeys`, `workspaces`, `runas`. 90 tests, including navigation tests that run without a display.

**Upgrade notes**
- `tvwcs.conf` no longer binds keys; run `install.sh` (or create `~/.config/tvwcs/hotkeys.conf`) so its `include` line has a file to read. Dialog titles changed to start with `TVWCS · `, matching the new window rules in `tvwcs.conf`; replace your copy of that file.
- `config.json` gains settings keys and a per-profile `run_as_user`; older files load unchanged.

## 2.3.1

- **Guide navigation fixed.** Application categories are now focusable header buttons (▾ open / ▸ closed) instead of expanders. The focused category is highlighted like every other control, Enter folds or unfolds it, and Up/Down/Left/Right work on every application inside it. (The old behaviour came from the category being treated as the owner of the rows inside it, and from its focus not being styleable.)
- **Descriptions in the Guide.** Application rows (and the channel lineup) show the application's description beside its name, in a smaller, dimmer font.
- **Quick Menu rows mirror the Guide.** Favorites, open applications and search results now have one options button on the *left*. It expands in place into launch mode, desktop actions (only when the app has any) and, for open windows, close. The application button stays on the right and is where Up/Down lands. From the search field, Right at the end of the text jumps to the highlighted result's options; Left returns to typing.
- **No more jumping when favoriting.** Starring or un-starring now updates the star and the Quick Menu's favorites in place. The Guide keeps its scroll position, focus and open categories. Open categories and scroll position are also kept when a profile is edited or applications are refreshed; a freshly opened Guide starts at the top.

## 2.3.0

**Look and layout**
- Metro / Modern UI theme: flat solid colours, light Segoe-style type, square 90° corners on every button, entry, popover and dialog, and a solid accent block with a white frame for remote focus. The accent colour is a setting.
- The Quick Menu is now a full-height column at the left of the active workspace, with the same margin on the top, bottom and left. Geometry comes from the usable rectangle of the workspace on the pointer's monitor (bar excluded), so it works on any monitor.
- The Guide is no longer a separate mode. It opens beside the Quick Menu in the same window, fills the rest of the workspace and keeps the same margin on every side. The Quick Menu is always open while the Guide is, but can be open alone. Shift+F2 opens the Guide; pressing it again, or Esc, closes only the Guide.
- Left/Right at the edge of a row hops between the Quick Menu and the Guide.

**System controls**
- The System button is now a power icon grouped with the Close button, as a caption-button pair.
- Refresh moved into the new System dialog, and a Lock action was added (auto-detects swaylock, i3lock, cinnamon-screensaver, xdg-screensaver or loginctl; override with `settings.lock_command`).
- Log out, Reboot and Shut down now ask for confirmation first. Cancel is focused by default and Esc returns to the System dialog.

**Workspaces**
- New per-profile launch mode: *Always launch in a new workspace* (checkbox in the profile editor). Such apps open alone on a fresh workspace; everything else stays on its own workspace, out of sight.
- A mode icon beside the app name in the Quick Menu (favorites and open applications) flips that app between "own new workspace" and "tiled in the current workspace".
- Open Applications now lists every workspace holding more than one app, with member icons. Open shows the whole workspace on the pointer's monitor; on multi-monitor setups a button moves it to the next screen.

**Icons and badges**
- Application logos are used in favorites, search results, the Guide and open-window rows, with a coloured letter tile when no icon is found.
- Open windows show a badge for an unread count in the title (`(3) Inbox`) or i3's urgent flag.
- `.desktop` `StartupWMClass` is read, which makes window-to-app matching (and so icons and launch modes for open windows) more accurate.

**Install**
- Recommended location is `~/.config/i3/tvwcs`. i3 loads `tvwcs.conf` from that folder through one `include` line; it holds the startup, key bindings and window rules. `install.sh` copies the files into place.

**Behaviour changes to know about**
- The scratchpad-hiding "exclusive" launch behaviour is gone; workspaces replace it. The old `tile` field is ignored, and every existing profile loads as "tiled in the current workspace" (the new default). Mark apps that should be alone with the new checkbox or the Quick Menu icon.
- `config.json` is now version 2 and gains an optional `settings` block (`margin`, `quick_width`, `accent`, `lock_command`). Older files load unchanged.
- `i3.conf.tvwcs` is replaced by `tvwcs.conf`.

## 2.2.0

- Simplified guide rows to one line per launch profile: channel (or dash), clickable profile name, favorite toggle, and edit control.
- Moved profile creation into an application profile-management page with a compact `+` button.
- Parsed named `Desktop Action` entries from `.desktop` files and added a None/desktop-action selector to profile editing.
- Added a Quick Menu System popover with Log out, Sleep, Shut down, and Reboot.
- Left-aligned favorite and open-application controls; added close and desktop-action controls for open windows.
- Search-result highlighting integrated with Up/Down navigation while focus stays in the search field.
- Added a persisted optional `desktop_action` field.

## 2.1.0

- Higher-visibility remote focus, vertical guide navigation, per-profile tile option, mouse-monitor targeting, bar/dock windows excluded from the open-application list.
