"""Settings > Bluetooth: pairing and connecting devices. Back end: settings/bluetooth.py."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from tvwcs.settings import bluetooth
from tvwcs.settings.app import in_background
from tvwcs.settings.pages.base import Page, _on_off


# ====================================================================== Bluetooth
class BluetoothPage(Page):
    key = "bluetooth"
    title = "Bluetooth"
    icon = "bluetooth-active-symbolic"
    fallback = "ᛒ"
    poll = 4
    scanning = False

    def read(self):
        return bluetooth.read_state()

    def summary(self):
        s = self.state
        if not s or not s.available:
            return ""
        return "Searching for devices…" if self.scanning else f"Adapter {s.controller}"

    def draw(self, s):
        if not s.available:
            self.note(s.message)
            return
        self.row(
            "Bluetooth",
            _on_off(s.powered),
            lambda: self.act(
                lambda: bluetooth.set_powered(not s.powered),
                "Switching Bluetooth " + ("off…" if s.powered else "on…"),
                "Bluetooth",
            ),
            ident="power",
        )
        if s.blocked:
            self.note("Bluetooth is switched off by rfkill (airplane mode); turning it on here lifts that.")
        if not s.powered:
            self.note("Turn Bluetooth on to connect headphones, speakers, game controllers and remotes.")
            return
        self.row(
            "Search for devices",
            "Searching…" if self.scanning else "",
            None if self.scanning else self.scan,
            detail="Put the device in pairing mode first.",
            icon="edit-find-symbolic",
            fallback="⌕",
            ident="scan",
        )
        self.section("MY DEVICES")
        if not s.paired:
            self.note("No device is paired yet. Search for devices, then choose one to pair it.")
        for d in s.paired:
            self.device_row(d)
        self.section("OTHER DEVICES")
        named = [d for d in s.nearby if d.name and d.name.replace("-", ":").upper() != d.address]
        if not named:
            self.note("None found yet. Choose Search for devices." if not self.scanning else "Looking…")
        for d in named:
            self.device_row(d)
        if len(named) < len(s.nearby):
            self.note(f"{len(s.nearby)-len(named)} unnamed devices nearby are not listed.")

    def device_row(self, d):
        icon, fallback, kind = d.kind
        detail = " · ".join(
            x for x in (kind, f"Battery {d.battery} %" if d.battery is not None else "", d.address) if x
        )
        if not d.paired:
            self.row(
                d.name,
                "Pair",
                lambda d=d: self.act(lambda: bluetooth.pair(d.address), f"Pairing with {d.name}…", f"Pair {d.name}"),
                detail=detail,
                icon=icon,
                fallback=fallback,
                ident=f"bt:{d.address}",
            )
            return
        forget = self.button(
            "user-trash-symbolic",
            "✕",
            f"Forget {d.name}",
            lambda d=d: self.win.confirm(
                f"Forget {d.name}?",
                f"{d.name} will be disconnected and unpaired. To use it again, pair it again.",
                "Forget",
                lambda: self.act(lambda: bluetooth.forget(d.address), f"Forgetting {d.name}…", "Bluetooth"),
            ),
            danger=True,
        )
        if d.connected:
            go = lambda d=d: self.act(lambda: bluetooth.disconnect(d.address), f"Disconnecting {d.name}…", "Bluetooth")
        else:
            go = lambda d=d: self.act(
                lambda: bluetooth.connect(d.address), f"Connecting to {d.name}…", f"Connect {d.name}"
            )
        self.row(
            d.name,
            "Connected" if d.connected else "Not connected",
            go,
            detail=detail,
            icon=icon,
            fallback=fallback,
            ident=f"bt:{d.address}",
            extras=[forget],
            value_css="state-on" if d.connected else "setting-value",
        )

    def scan(self):
        self.scanning = True
        self.redraw()
        self.set_status("Searching for devices…")

        def done(_result):
            self.scanning = False
            self.set_status("")
            self.busy = False
            self.refresh(quiet=True)

        in_background(lambda: bluetooth.scan(), done, lambda _e: done(None))
