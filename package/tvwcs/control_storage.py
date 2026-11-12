"""Storage for Settings: the drives inside or plugged into the computer. No GTK dependency.

Drives are read with lsblk and mounted, unmounted and switched off with udisksctl (UDisks), which lets the user at
the screen do that for USB drives without a password."""

from __future__ import annotations
import json
from dataclasses import dataclass, field

from tvwcs.control_cmd import have, run

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def size_text(n):
    """1500000000 -> '1.5 GB' (powers of 1000, as drives are sold)."""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ""
    i = 0
    while n >= 1000 and i < len(_SIZE_UNITS) - 1:
        n /= 1000
        i += 1
    return f"{n:.0f} {_SIZE_UNITS[i]}" if n >= 100 or i == 0 else f"{n:.1f} {_SIZE_UNITS[i]}"


@dataclass
class Volume:
    path: str  # /dev/sdb1
    name: str  # sdb1
    fstype: str = ""
    label: str = ""
    size: int = 0
    mountpoints: list = field(default_factory=list)
    used: int = 0
    avail: int = 0

    @property
    def mounted(self):
        return bool(self.mountpoints)

    @property
    def system(self):
        """Holds the running system (/, /boot, /home, swap...): shown, never unmounted from here."""
        return (
            any(m in ("/", "/boot", "/boot/efi", "/home", "/usr", "/var", "[SWAP]") for m in self.mountpoints)
            or self.fstype == "swap"
        )

    @property
    def title(self):
        """Its label; a system partition without one is named for what it holds ("System", "Home", "Boot")."""
        if self.label:
            return self.label
        for m in self.mountpoints:
            if m in _SYSTEM_NAMES:
                return f"{_SYSTEM_NAMES[m]} ({self.name})"
        return self.name


_SYSTEM_NAMES = {
    "/": "System",
    "/home": "Home",
    "/boot": "Boot",
    "/boot/efi": "Boot",
    "/usr": "Programs",
    "/var": "System data",
}


@dataclass
class Drive:
    path: str
    name: str
    model: str = ""
    size: int = 0
    removable: bool = False  # plugged in (USB, SD card): can be switched off before unplugging
    transport: str = ""
    volumes: list = field(default_factory=list)

    @property
    def system(self):
        return any(v.system for v in self.volumes)

    @property
    def title(self):
        return self.model or self.name


@dataclass
class StorageState:
    drives: list = field(default_factory=list)
    udisks: bool = False
    message: str = ""


# ---------------------------------------------------------------------- reading drives
LSBLK = ["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS,RM,HOTPLUG,MODEL,TRAN,FSUSED,FSAVAIL"]


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def parse_lsblk(text):
    """`lsblk -J -b -o ...` -> [Drive]. Loop devices, RAM disks and CD drives without media are left out; a drive with
    a file system written straight on it (no partitions) is one volume."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    drives = []

    def volumes(node):
        out = []
        for child in node.get("children") or []:
            if child.get("fstype") or child.get("mountpoints") and any(child.get("mountpoints")):
                mps = [m for m in (child.get("mountpoints") or []) if m]
                out.append(
                    Volume(
                        child.get("path") or f"/dev/{child.get('name')}",
                        child.get("name", ""),
                        child.get("fstype") or "",
                        (child.get("label") or "").strip(),
                        _int(child.get("size")),
                        mps,
                        _int(child.get("fsused")),
                        _int(child.get("fsavail")),
                    )
                )
            out += volumes(child)  # LVM and encrypted volumes sit under their partition
        return out

    for node in data.get("blockdevices", []):
        if node.get("type") not in ("disk",) or node.get("name", "").startswith(("loop", "ram", "zram")):
            continue
        d = Drive(
            node.get("path") or f"/dev/{node.get('name')}",
            node.get("name", ""),
            (node.get("model") or "").strip(),
            _int(node.get("size")),
            bool(node.get("rm")) or bool(node.get("hotplug")),
            node.get("tran") or "",
        )
        d.volumes = volumes(node)
        if node.get("fstype"):
            mps = [m for m in (node.get("mountpoints") or []) if m]
            d.volumes.insert(
                0,
                Volume(
                    d.path,
                    d.name,
                    node.get("fstype"),
                    (node.get("label") or "").strip(),
                    d.size,
                    mps,
                    _int(node.get("fsused")),
                    _int(node.get("fsavail")),
                ),
            )
        if d.size:
            drives.append(d)
    return sorted(drives, key=lambda d: (not d.system, d.removable, d.name))


def read_state():
    s = StorageState(udisks=have("udisksctl"))
    if have("lsblk"):
        r = run(LSBLK, timeout=10)
        s.drives = parse_lsblk(r.out) if r.ok else []
        if not r.ok:
            s.message = r.message
    else:
        s.message = "lsblk was not found (util-linux)."
    return s


# ---------------------------------------------------------------------- changing (each -> "" when it worked, else why not)
def _outcome(r, otherwise):
    if r.ok:
        return ""
    text = (r.err or r.out or "").strip()
    if "NotAuthorized" in text or "not authorized" in text.lower():
        return "This user may not do that without an administrator's password (polkit)."
    return text.splitlines()[-1] if text else otherwise


def mount(volume):
    return _outcome(
        run(["udisksctl", "mount", "--no-user-interaction", "-b", volume], timeout=30), "The drive could not be opened."
    )


def unmount(volume):
    return _outcome(
        run(["udisksctl", "unmount", "--no-user-interaction", "-b", volume], timeout=30),
        "The drive is still in use. Close what uses it, then try again.",
    )


def power_off(drive):
    return _outcome(
        run(["udisksctl", "power-off", "--no-user-interaction", "-b", drive], timeout=30),
        "The drive could not be switched off.",
    )
