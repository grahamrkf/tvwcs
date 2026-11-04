# Installing TVWCS on Arch

TVWCS runs on Arch Linux and on systems built on it (EndeavourOS, CachyOS, Manjaro). It isn't in the AUR yet, so its package is built from the PKGBUILD attached to each [release](https://github.com/grahamrkf/tvwcs/releases). That takes a few seconds, since there is nothing to compile. pacman installs what TVWCS needs with it (sway, swayidle, swaylock, GTK 4 for Python and so on).

## Install

The installer does it all, asking its questions first (which version, logging in automatically, adding TVWCS to your usual sway session). Once you agree, it downloads the release's PKGBUILD, builds the package with `makepkg` as you, and installs it with pacman (installing `fakeroot` first if it's missing). Run it in a terminal, as your own user (not root), who can use `sudo`:

```sh
curl -fsSL https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash
```

If pacman says it can't find a package TVWCS needs, update the system first (`sudo pacman -Syu`) and run it again.

### By hand

You need `base-devel` (for `makepkg`) and a user who can use `sudo`:

```sh
sudo pacman -S --needed base-devel
mkdir -p ~/tvwcs-pkg && cd ~/tvwcs-pkg
curl -LO https://github.com/grahamrkf/tvwcs/releases/latest/download/PKGBUILD
curl -LO https://github.com/grahamrkf/tvwcs/releases/latest/download/tvwcs.install
makepkg -si
```

`makepkg -si` downloads the source, checks its checksum, builds the package and installs it with pacman, which asks for your password. Read the PKGBUILD first if you like: it only copies files into place.

**From a copy of the repository** (to try a branch): `scripts/build-arch.sh --package`, then `sudo pacman -U resources/arch/tvwcs-*.pkg.tar.zst`.

## Start it

- **With a login screen** (greetd, LightDM, SDDM, GDM): pick the **TVWCS** session. Settings › User can log you in to it automatically.
- **Without one:** type `tvwcs` at a text console. Settings › User can then log you in automatically on the first console. TVWCS never installs a login screen itself: if you want one, install greetd (or another) and Settings › User sets up its automatic login.
- **In your usual sway session:** Settings › Remote and hotkeys › Add TVWCS to sway adds one line to your sway config, and TVWCS then runs in desktop mode.

## Things Arch does differently

- **sudo.** Settings asks for your password and runs administrator actions with `sudo`. Your user has to be allowed to use it: the `%wheel ALL=(ALL:ALL) ALL` line in `/etc/sudoers` must not be commented out (edit it with `sudo EDITOR=nano visudo`), and you have to be in `wheel`. archinstall sets this up for the user you create.
- **The network.** Arch doesn't start a network manager by itself, so many installs use systemd-networkd with iwd, or dhcpcd, instead of NetworkManager. Without NetworkManager, Settings › Network:
  - with **iwd** running, lists the Wi-Fi networks it sees, and joins and forgets them (a new password asks for yours, since only an administrator can save it where iwd keeps passwords). iwd saves a network's password in `/var/lib/iwd`, as `iwctl` does.
  - shows each port's addresses and whether DHCP gave them. An address set by hand (in a `.network` file in `/etc/systemd/network`, in `/etc/dhcpcd.conf`, or in a network's file in `/var/lib/iwd`) gets a warning that says where to change it: Settings can't, there.
  - can't change Ethernet or IP settings. For those, hand the network to NetworkManager:

  ```sh
  sudo pacman -S networkmanager
  sudo systemctl disable --now systemd-networkd iwd dhcpcd
  sudo systemctl enable --now NetworkManager
  ```

  Do this at the computer itself, or be ready to reconnect: SSH drops while the network changes over. Wi-Fi networks you saved with iwd have to be joined again from Settings › Network.
- **Sound and Bluetooth.** When their software is missing, the Sound and Bluetooth pages offer to install it (PipeWire, BlueZ). Bluetooth's service is turned on with it, since Arch doesn't start services after installing them.
- **Software updates** lists waiting updates with `checkupdates`, which never touches pacman's own database, and installs them with `sudo pacman -Syu`, all at once, as Arch expects.
  - **AUR packages:** pacman can't see them, but with **yay** or **paru** installed the page lists their updates too (and the Quick Menu counts them). "Update AUR packages" runs the helper as you, step by step: it shows what changed in each package's build script first (choose **Show all**, and stop if anything looks wrong, since AUR packages are written by their users and not checked by Arch), then builds them and asks for your password to install them.
  - **Arch news:** the page shows what Arch has posted at <https://archlinux.org/news/> since your last full update, and the Install question mentions it. Read those first: they're how Arch announces the rare update that needs a step by hand.
  - **Update step by step** runs pacman without `--noconfirm`. Each question it asks (go ahead, replace a package, remove one that conflicts, choose between packages that provide the same thing, import a key) appears with a button for each answer. Back answers No. Install offers it too when an automatic run stops, which is usually a question whose default answer is No.
  - **New default settings files:** when an update brings a new default version of a settings file you (or a program) changed, pacman keeps yours and saves the new one next to it as `.pacnew`. The page lists those files. Merge each by hand (`sudo pacdiff` walks through them) and delete the `.pacnew`.
- **TVWCS's own updates.** Settings › Software updates › Check for TVWCS updates tells you when a new release is out. To install it, run the installer again (or the commands above, in a new folder).

## Remove it

```sh
sudo pacman -R tvwcs
```

(or the installer's `--remove`, which also takes TVWCS out of your usual sway config and can delete your TVWCS settings).

This also ends an automatic login into TVWCS and turns server mode off. greetd keeps its config, greeter and all: only the automatic login into TVWCS goes (and agreety, if it was starting TVWCS after the password, starts a shell instead). Your settings in `~/.config/tvwcs` are kept.
