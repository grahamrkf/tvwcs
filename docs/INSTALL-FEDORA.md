# Installing TVWCS on Fedora

TVWCS runs on Fedora 42 and later (any edition with dnf: the Sway spin, Workstation, Server, Everything) and on Nobara and Ultramarine. Each [release](https://github.com/grahamrkf/tvwcs/releases) from 5.15.0 has an `.rpm` attached, and dnf installs what TVWCS needs with it (sway, swayidle, swaylock, GTK 4 for Python and so on). Fedora's Atomic editions (Silverblue, Kinoite, Sway Atomic) work differently: see [Fedora Atomic](#fedora-atomic) below. Red Hat Enterprise Linux, CentOS Stream, AlmaLinux and Rocky Linux aren't supported (their sway comes from EPEL, and isn't tested).

## Install

The installer asks its questions first (which version, logging in automatically, adding TVWCS to your usual sway session), then downloads the release's `.rpm` and installs it with dnf. Run it in a terminal, as a user who can use `sudo` (one in the `wheel` group, which is what Fedora's installer makes for an administrator):

```sh
curl -fsSL https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash
```

### By hand

```sh
curl -LO https://github.com/grahamrkf/tvwcs/releases/latest/download/tvwcs-<version>-1.noarch.rpm
sudo dnf install ./tvwcs-<version>-1.noarch.rpm
```

**From a copy of the repository** (to try a branch): `sudo dnf install rpm-build python3`, then `scripts/build-rpm.sh` and `sudo dnf install resources/fedora/tvwcs-*.noarch.rpm`.

## Start it

- **With a login screen:** pick the **TVWCS** session. The Sway spin's SDDM (and LightDM, and greetd) can log you in to it automatically from Settings › User; on Workstation's GDM, choose it at the login screen.
- **Without one** (Server, Everything): type `tvwcs` at a text console. Settings › User can then log you in automatically on the first console.
- **In your usual sway session:** Settings › Remote and hotkeys › Add TVWCS to sway adds one line to your sway config, and TVWCS then runs in desktop mode.

## Things Fedora does differently

- **Software updates** lists waiting updates with `dnf check-update` and installs them with `sudo dnf upgrade --refresh`. Fedora keeps the last few kernels, so the page asks `dnf needs-restarting -r` (from dnf5-plugins, which the package recommends) whether a restart is due.
- **Sound, Bluetooth and SSH.** When their software is missing, the Sound, Bluetooth and System pages offer to install it with dnf (PipeWire with `pipewire-pulseaudio`, BlueZ, `openssh-server`). Bluetooth's service is started with it.
- **TVWCS's own updates.** Settings › Software updates › Check for TVWCS updates downloads the new release's `.rpm` and installs it with dnf, as it does with the `.deb` on Debian. Prereleases and rolling back to the latest release work too (rolling back runs `dnf downgrade`).
- **SELinux** stays on. Files TVWCS writes in `/etc` (greetd's config, the automatic-login drop-ins, server mode's polkit rule) get their usual labels with `restorecon`.
- **greetd** is set up with Fedora's `greetd` user, `/usr/bin/agreety` and the first console.

## Fedora Atomic

On Silverblue, Kinoite, Sway Atomic and the systems built on them (Bazzite, Bluefin...), `/usr` is a read-only image that only changes through `rpm-ostree`, at the next start-up. The installer stops there and says so. TVWCS itself works once it is part of the image:

```sh
curl -LO https://github.com/grahamrkf/tvwcs/releases/latest/download/tvwcs-<version>-1.noarch.rpm
sudo rpm-ostree install ./tvwcs-<version>-1.noarch.rpm
systemctl reboot
```

What doesn't work on Atomic yet:

- **TVWCS's own updates.** A package layered from a file isn't updated by `rpm-ostree upgrade`. Install a new release the same way (`sudo rpm-ostree install ./tvwcs-<new>-1.noarch.rpm --uninstall tvwcs`) and restart. Settings › Software updates tells you when one is out.
- **System updates in Settings.** The page says to run `sudo rpm-ostree upgrade` (or leave it to the system's automatic updates); it doesn't drive rpm-ostree itself.
- **Installing what a page needs** (Bluetooth, the SSH server, greetd) from Settings. Layer those with `rpm-ostree install` too; most Atomic images already have them.

Everything TVWCS sets up in `/etc` (the automatic login, server mode) works as on Fedora.

## Remove it

```sh
sudo dnf remove tvwcs
```

(or the installer's `--remove`, which also takes TVWCS out of your usual sway config and can delete your TVWCS settings; on Atomic, `sudo rpm-ostree uninstall tvwcs`).

This also ends an automatic login into TVWCS and turns server mode off. greetd keeps its config, greeter and all: only the automatic login into TVWCS goes. Your settings in `~/.config/tvwcs` are kept.
