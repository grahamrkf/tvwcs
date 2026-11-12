"""Settings > Storage: disks and USB drives. Back end: settings/storage.py (udisksctl)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from tvwcs.settings import storage
from tvwcs.settings.pages.base import Page


# ====================================================================== Storage
class StoragePage(Page):
    """The drives in the computer and plugged into it (open, close, switch off before unplugging). See settings.storage."""

    key = "storage"
    title = "Storage"
    icon = "drive-harddisk-symbolic"
    fallback = "🖴"
    poll = 5

    def read(self):
        return storage.read_state()

    def summary(self):
        s = self.state
        return f"{len(s.drives)} drive{'s' if len(s.drives)!=1 else ''}" if s else ""

    def draw(self, s):
        self.section("DRIVES")
        if s.message:
            self.note(s.message, "error")
        if not s.drives:
            self.note("No drives were found.")
        for d in s.drives:
            self.drive_rows(d, s)
        if not s.udisks:
            self.note("Install udisks2 to open and close drives here.", "error")
        self.note(
            "Each drive's partitions are listed under it. Mounting a partition makes its files readable, in the folder shown "
            "under it. Unmount it, or switch the drive off with ⏏, before unplugging it."
        )

    def drive_rows(self, d, s):
        kind = (
            "Inside the computer" if not d.removable else ("USB drive" if d.transport == "usb" else "Removable drive")
        )
        extras = []
        if d.removable and not d.system and s.udisks:
            extras.append(
                self.button(
                    "media-eject-symbolic",
                    "⏏",
                    f"Switch off {d.title} so it can be unplugged",
                    lambda d=d: self.eject(d),
                )
            )
        self.row(
            d.title,
            storage.size_text(d.size),
            None,
            detail=kind + (" · holds this system" if d.system else ""),
            icon="drive-removable-media-symbolic" if d.removable else "drive-harddisk-symbolic",
            fallback="🖴",
            ident=f"drive:{d.name}",
            extras=extras,
        )
        for v in d.volumes:
            if v.fstype == "swap":
                continue
            space = (
                f"{storage.size_text(v.used)} used, {storage.size_text(v.avail)} free"
                if v.mounted and (v.used or v.avail)
                else storage.size_text(v.size)
            )
            where = ", ".join(v.mountpoints)
            go = None
            if v.system:  # /, /home, /boot...: always in use, never unmounted from here
                value, detail = "Part of the system", (
                    f"Always in use · its files are in {where}" if where else "Always in use"
                )
            elif v.mounted:
                value, detail = "Mounted", f"Its files are in {where}"
            else:
                value, detail = "Not mounted", "Mount it to see its files"
            if not v.system and s.udisks and v.fstype not in ("crypto_LUKS", "LVM2_member"):
                go = (
                    (lambda v=v: self.act(lambda: storage.unmount(v.path), f"Unmounting {v.title}…", "Storage"))
                    if v.mounted
                    else (lambda v=v: self.act(lambda: storage.mount(v.path), f"Mounting {v.title}…", "Storage"))
                )
                if not v.mounted:
                    detail = "Select to mount it and see its files"
                else:
                    detail += " · select to unmount"
            detail = " · ".join(x for x in (v.fstype, detail, space) if x)
            self.row(
                v.title,
                value,
                go,
                detail=detail,
                ident=f"vol:{v.name}",
                indent=44,
                value_css="state-on" if v.mounted and not v.system else "setting-value",
            )

    def eject(self, d):
        def work():
            for v in d.volumes:
                if v.mounted:
                    problem = storage.unmount(v.path)
                    if problem:
                        return problem
            return storage.power_off(d.path)

        self.act(work, f"Switching off {d.title}…", "Storage", after=lambda: None)
