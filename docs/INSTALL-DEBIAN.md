# Setting up a TV computer with Debian

This guide takes an empty computer to one that starts straight into TVWCS. You install Debian without a desktop, turn on SSH, and then install TVWCS from another computer. The TV computer needs a keyboard only for the first steps.

**You need:**
- the TV computer (64-bit PC, "amd64"), on your network, by cable if you can
- a USB stick of 1 GB or more (it will be erased)
- another computer on the same network (Windows 10 or 11, macOS or Linux)
- a keyboard for the TV computer, for the first steps

## 1. Write Debian to the USB stick

1. On the other computer, download the **amd64** network install image from <https://www.debian.org/distrib/netinst> (`debian-<version>-amd64-netinst.iso`, about 700 MB).
2. Write it to the stick:
   - **Windows:** [Rufus](https://rufus.ie) (choose the stick and the ISO, then **Start**; pick **DD image mode** if asked) or [balenaEtcher](https://etcher.balena.io).
   - **macOS:** balenaEtcher.
   - **Linux:** balenaEtcher, or `sudo dd if=debian-*-netinst.iso of=/dev/sdX bs=4M status=progress conv=fsync`. `/dev/sdX` is the whole stick, not a partition; `lsblk` lists drives. Everything on it is lost.

## 2. Install Debian without a desktop

1. Start the TV computer from the stick. The boot menu key is usually **F12**, **F11**, **F8** or **Esc**. You can leave Secure Boot on.
2. Choose **Graphical install** (or **Install**) and answer:
   - **Language, location, keyboard:** your own.
   - **Hostname:** a name such as `livingroom`. Other computers will reach it as **`livingroom.local`**. Use letters, digits and hyphens only.
   - **Domain name:** leave empty.
   - **Root password:** leave **empty** (press Continue twice). Your user then gets `sudo`, which the TVWCS installer needs. If you do set one, see the note in step 3.
   - **Your user:** a name (such as `tv`) and a password. You sign in over SSH as this user, and the computer logs in as it later.
   - **Partitioning:** **Guided – use entire disk**, then **All files in one partition**. This erases the disk.
   - **Package manager:** your country, then `deb.debian.org`. No proxy.
3. On **Software selection**, tick only:
   - [x] **SSH server**
   - [x] **standard system utilities**

   Clear everything else, including every desktop and the web server. In the text installer, **Space** ticks a box and **Enter** continues.
4. Install GRUB to the disk when asked. When it finishes, remove the stick and let the computer restart.

## 3. Turn on SSH and Avahi

The computer starts to a text login. Log in as your user, then run:

```bash
sudo apt update
sudo apt install openssh-server avahi-daemon libnss-mdns
sudo systemctl enable --now ssh avahi-daemon
hostname -I
```

- Avahi makes the computer reachable as `<hostname>.local`.
- `hostname -I` shows its IP address (such as `192.168.1.20`). Write it down in case the name does not work.

**If you set a root password:** run `su -`, then `apt install sudo openssh-server avahi-daemon libnss-mdns`, `usermod -aG sudo tv` (your user name), `systemctl enable --now ssh avahi-daemon` and `exit`. Log out and in again.

The rest is done from the other computer.

## 4. Install TVWCS from the other computer

1. Open a terminal: **PowerShell** on Windows, **Terminal** on macOS, any terminal on Linux.
2. Sign in to the TV computer. The `-t` lets the installer ask questions:

   ```bash
   ssh -t tv@livingroom.local
   ```

   Use your own user and hostname, or the IP address. The first time, answer `yes` to the fingerprint question, then type your password.
3. Run the installer:

   ```bash
   wget -qO- https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash
   ```

4. Answer its questions. It asks everything first, then shows what it will do and changes nothing until you say yes. For a TV computer:

   | Question | Answer |
   |---|---|
   | **Which version?** | Enter (the latest release). |
   | **Log … in automatically into TVWCS at startup?** | Enter (yes). On a fresh Debian with no desktop there is no login screen, so the first text console logs you in and starts TVWCS. |
   | **Go ahead?** | Enter (yes). sudo asks for your password. |

5. Restart (`sudo reboot`). The computer logs straight into TVWCS. To log in by hand instead, open **Settings › User** (channel 00) and turn off **Log in automatically after startup**; the text console then asks for your user name and password, and typing `tvwcs` starts TVWCS. Anyone who switches the computer on gets your session with the automatic login, which suits a TV.

Type channel 00 in the Quick Menu to open **Settings**.

## 5. Optional: sign in with a key instead of a password

1. On the other computer, make a key if you have none: `ssh-keygen -t ed25519` (press Enter for the defaults).
2. Copy it to the TV computer:
   - **macOS and Linux:** `ssh-copy-id tv@livingroom.local`
   - **Windows (PowerShell):** `type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh tv@livingroom.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"`
3. Check that `ssh tv@livingroom.local` no longer asks for a password.
4. On the TV, open **Settings › System information › Remote access (SSH)** and set **Sign in with** to **Keys only**. Settings refuses this until your user has a key, so you cannot lock yourself out.

## If something does not work

- **`Could not resolve hostname livingroom.local`:** use the IP address. Check that Avahi runs on the TV computer (`systemctl status avahi-daemon`). Some routers block these announcements between Wi-Fi and wired devices.
- **`Connection refused`:** the SSH server is not running. On the TV computer: `sudo systemctl enable --now ssh`.
- **The installer asks no questions:** you signed in without `-t`.
- **The TV still shows a text login:** log in and type `tvwcs`, or restart (`sudo reboot`): the automatic login starts from the next start.
- **No sound:** restart once (`sudo reboot`), then choose the output on the **Sound** page of Settings. HDMI outputs not in use yet are listed there too.
