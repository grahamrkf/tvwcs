"""Settings > Network: wired, Wi-Fi and IP settings. Back ends: settings/network.py (nmcli), settings/iwd.py."""

from __future__ import annotations
import os
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib

from tvwcs.settings import network
from tvwcs.settings.app import in_background
from tvwcs.settings.pages.base import Page, _on_off


# ====================================================================== Network
class NetworkPage(Page):
    key = "network"
    title = "Network"
    icon = "network-wired-symbolic"
    fallback = "⇄"
    poll = 6
    server_off = True
    scanning = False

    def read(self):
        return network.read_state(scan=self.scanning)

    def summary(self):
        s = self.state
        if not s:
            return ""
        return "NetworkManager" if s.managed else "Wi-Fi through iwd" if s.iwd else "Shown only (no NetworkManager)"

    def draw(self, s):
        if not s.managed:
            self.note(s.message)
        unmanaged = [i for i in s.interfaces if i.state.startswith("unmanaged")]
        if s.managed and unmanaged and network.unmanaged_reason(unmanaged[0].device) == "netplan":
            self.row(
                "Let NetworkManager manage the network",
                "",
                lambda: self.take_over(unmanaged[0]),
                icon="emblem-system-symbolic",
                fallback="⚙",
                ident="netplan",
                detail="netplan gives the network to systemd-networkd (as Ubuntu Server does), so it can only be shown here. "
                "Saved Wi-Fi networks and addresses set by hand are kept.",
            )
        self.section("ETHERNET")
        wired = s.of_kind("ethernet")
        if not wired:
            self.note("No Ethernet port was found.")
        for i in wired:
            self.ethernet_row(i, s.managed)
        self.section("WI-FI")
        wireless = s.of_kind("wifi")
        if s.iwd:
            wireless = [i for i in wireless if i.device in s.iwd_devices] or wireless  # not an access point's interface
        if not wireless:
            self.note("No Wi-Fi adapter was found.")
            return
        if s.iwd:
            self.draw_iwd(s, wireless)
            return
        if not s.managed or wireless[0].state.startswith("unmanaged"):
            for i in wireless:
                self.ethernet_row(i, s.managed)
            return
        self.row(
            "Wi-Fi",
            _on_off(s.wifi_enabled),
            lambda: self.act(
                lambda: network.set_wifi(not s.wifi_enabled),
                "Switching Wi-Fi " + ("off…" if s.wifi_enabled else "on…"),
                "Wi-Fi",
            ),
            icon="network-wireless-symbolic",
            fallback="📶",
            ident="wifi",
        )
        if not s.wifi_enabled:
            return
        device = wireless[0]
        if device.connected:
            self.ip_row(device)
        self.row(
            "Search for networks",
            "Searching…" if self.scanning else "",
            None if self.scanning else self.scan,
            icon="edit-find-symbolic",
            fallback="⌕",
            detail="Looks for Wi-Fi networks nearby. The list is not searched again until you choose this.",
            ident="scan",
        )
        if not s.networks:
            self.note(
                "Looking…" if self.scanning else "No networks listed. Choose Search for networks to look for them."
            )
        for n in s.networks:
            self.wifi_row(n, device)

    def draw_iwd(self, s, wireless):
        """Wi-Fi run by iwd (no NetworkManager): its adapter, then the networks it sees, to join or forget."""
        for i in wireless:
            self.ethernet_row(i, False)
        if not s.wifi_enabled:
            self.note(
                "The Wi-Fi adapter is off (iwd). Turn it on with: iwctl device "
                + wireless[0].device
                + " set-property Powered on"
            )
            return
        self.row(
            "Search for networks",
            "Searching…" if self.scanning else "",
            None if self.scanning else self.scan,
            icon="edit-find-symbolic",
            fallback="⌕",
            detail="Looks for Wi-Fi networks nearby. iwd also looks now and then by itself.",
            ident="scan",
        )
        if not s.networks:
            self.note(
                "Looking…" if self.scanning else "No networks listed. Choose Search for networks to look for them."
            )
        device = next((i for i in wireless if i.device == s.iwd_device), wireless[0])
        for n in s.networks:
            self.wifi_row(n, device)

    def iwd_do(self, work, args, label, status):
        """A change iwd may let this user make (work() -> problem); if it refuses, the same as root (args)."""

        def tried(problem):
            self.busy = False
            self.set_status("")
            if problem == network.iwd.DENIED:
                self.iwd_root(args, label, status)
                return
            if problem:
                self.win.notice("Wi-Fi", problem)
            self.refresh(quiet=True)

        self.set_status(status)
        self.busy = True
        in_background(work, tried, lambda exc: tried(str(exc)))

    def iwd_root(self, args, label, status, cleanup=""):
        """One of settings.iwd's root commands (it asks for the password), then the page is read again."""
        self.set_status(status)
        lines = []

        def done(code, tail):
            self.set_status("")
            if cleanup:
                try:
                    os.unlink(cleanup)
                except OSError:
                    pass
            if code:
                self.win.notice("Wi-Fi", ("\n".join(lines[-4:]) or tail or f"{label} did not work.").strip())
            self.refresh(quiet=True)

        self.win.run_as_root(network.iwd.root_argv(*args), label, lines.append, done)

    def plain_ip_row(self, i):
        """Without NetworkManager: whether DHCP gave the address, with a warning when it was set by hand."""
        if not i.addresses:
            return
        self.row(
            f"IP settings ({i.device})",
            "Automatic (DHCP)" if i.dynamic else "Set by hand",
            None,
            ident=f"ip:{i.device}",
            detail={"networkd": "Set up by systemd-networkd", "dhcpcd": "Set up by dhcpcd", "iwd": "Set up by iwd"}.get(
                i.set_by, ""
            ),
        )
        if not i.dynamic:
            self.note(network.hand_set_note(i), "error")

    @staticmethod
    def _details(i):
        return " · ".join(
            x
            for x in (
                ", ".join(i.addresses),
                f"Gateway {i.gateway}" if i.gateway else "",
                f"DNS {', '.join(i.dns)}" if i.dns else "",
                f"MAC {i.mac}" if i.mac else "",
            )
            if x
        )

    @staticmethod
    def _state_text(i):
        if i.connected:
            return "Connected"
        if i.kind == "wifi" and not i.state.startswith("unmanaged"):
            return "Not connected"
        return {"unavailable": "No cable", "disconnected": "Not connected", "unmanaged": "Not managed"}.get(
            i.state.split(" ")[0], i.state.capitalize() or "Unknown"
        )

    def ethernet_row(self, i, managed):
        go = None
        extras = []
        detail = self._details(i)
        if managed and i.state.startswith("unmanaged"):
            go = lambda i=i: self.take_over(i)
            detail = " · ".join(
                x
                for x in (
                    "Not set up through NetworkManager, so it cannot be changed here. Choose it to let Settings manage it",
                    detail,
                )
                if x
            )
        elif managed and i.state not in ("unavailable",):
            if i.connected:
                go = lambda i=i: self.win.confirm(
                    f"Disconnect {i.device}?",
                    f"Disconnect {i.connection or i.device}? Anything using the network will lose it until you connect again.",
                    "Disconnect",
                    lambda: self.act(
                        lambda: network.disconnect_device(i.device), f"Disconnecting {i.device}…", "Ethernet"
                    ),
                )
            else:
                go = lambda i=i: self.act(
                    lambda: network.connect_device(i.device), f"Connecting {i.device}…", "Ethernet"
                )
        label = ("Ethernet" if i.kind == "ethernet" else "Wi-Fi") + f" ({i.device})"
        self.row(
            label,
            self._state_text(i),
            go,
            detail=detail,
            icon="network-wired-symbolic" if i.kind == "ethernet" else "network-wireless-symbolic",
            fallback="⇄",
            ident=f"if:{i.device}",
            extras=extras,
            value_css="state-on" if i.connected else "setting-value",
        )
        if managed:
            self.ip_row(i)
        elif i.connected:
            self.plain_ip_row(i)

    def take_over(self, i):
        """Hand a port that NetworkManager leaves alone to it (settings.network: with ifupdown, a minimal Debian
        install's network, ifupdown is uninstalled)."""
        reason = network.unmanaged_reason(i.device)
        kind = "Wi-Fi" if i.kind == "wifi" else "Ethernet"
        if reason == "ifupdown":
            text = (
                f"{i.device} is set up by ifupdown (/etc/network/interfaces), as a minimal Debian install does, and NetworkManager (which "
                "Settings uses) will not touch it. Settings can hand the network to NetworkManager: ifupdown is uninstalled, /etc/network "
                "is removed and NetworkManager is restarted, so it manages every Ethernet port and Wi-Fi adapter from then on.\n\n"
                "The network drops for a moment. Ethernet connects again by itself, but you have to choose your Wi-Fi network and enter "
                "its password again here, and any IP address, gateway or DNS servers set by hand have to be set again. It asks for your password."
            )
            title, ok = "Hand the network to NetworkManager?", "Hand it over"
        elif reason == "netplan":
            text = (
                f"{i.device} is set up by netplan (/etc/netplan), which gives it to systemd-networkd, as Ubuntu Server does, so "
                "NetworkManager (which Settings uses) leaves it alone. Settings can set netplan to use NetworkManager instead: one "
                "file is added to /etc/netplan (the others are kept, and backed up in /var/backups) and the settings are applied, "
                "so NetworkManager manages every Ethernet port and Wi-Fi adapter from then on.\n\n"
                "Your saved Wi-Fi networks and any IP address, gateway or DNS servers set by hand are kept: netplan hands them to "
                "NetworkManager. The network drops for a moment while it switches. It asks for your password."
            )
            title, ok = "Hand the network to NetworkManager?", "Hand it over"
        else:
            text = (
                f"NetworkManager is set to leave {i.device} alone. Settings can ask it to manage it. "
                "If that does not last after a restart, a file in /etc/NetworkManager/conf.d lists it under unmanaged-devices."
            )
            title, ok = f"Manage {i.device} here?", "Manage it"

        def go():
            self.set_status(f"Handing {i.device} to NetworkManager…")
            lines = []

            def done(code, tail):
                self.set_status("")
                if code:
                    self.win.notice(kind, ("\n".join(lines[-6:]) or tail or "It did not work.").strip())
                else:
                    self.win.notice(
                        kind,
                        "NetworkManager manages the network now."
                        + (
                            " Choose your Wi-Fi network to connect again."
                            if any(w.kind == "wifi" for w in self.state.interfaces) and reason == "ifupdown"
                            else ""
                        ),
                    )
                self.refresh(quiet=True)

            self.win.run_as_root(
                network.take_over_argv(i.device, reason), f"Handing {i.device} to NetworkManager", lines.append, done
            )

        self.win.confirm(title, text, ok, go, danger=reason in ("ifupdown", "netplan"))

    def ip_row(self, i):
        """IP address, default gateway and DNS servers of the interface's connection: from DHCP, or set by hand."""
        if not i.connection_uuid:
            return
        value = (
            "Automatic (DHCP)"
            if i.method != "manual"
            else "Fixed" + (f": {i.addresses[0].split('/')[0]}" if i.addresses else "")
        )
        self.row(
            f"IP settings ({i.device})",
            value,
            lambda i=i: self.ip_settings(i),
            icon="preferences-system-network-symbolic",
            fallback="⚙",
            detail="IP address, default gateway and DNS servers, or back to automatic (DHCP)",
            ident=f"ip:{i.device}",
        )

    def wifi_row(self, n, device):
        detail = f"{network.signal_bars(n.signal)}  {n.signal} %" + (f" · {n.security}" if n.secured else " · Open")
        if n.in_use and device.addresses:
            detail += " · " + self._details(device)
        extras = []
        s = self.state
        if s.iwd:  # each change is a root command (it asks for the password)
            iw = network.iwd
            forget = lambda n=n: self.iwd_do(
                lambda: iw.forget(n.ssid), ["forget", n.ssid], f"Forgetting {n.ssid}", f"Forgetting {n.ssid}…"
            )
            disconnect = lambda n=n: self.iwd_do(
                lambda: iw.disconnect(s.iwd_station),
                ["disconnect", s.iwd_station],
                f"Disconnecting from {n.ssid}",
                f"Disconnecting from {n.ssid}…",
            )
            connect = lambda n=n: self.iwd_do(
                lambda: iw.join(n.ssid), ["join", n.ssid], f"Connecting to {n.ssid}", f"Connecting to {n.ssid}…"
            )
        else:
            forget = lambda n=n: self.act(lambda: network.forget(n.saved_uuid), f"Forgetting {n.ssid}…", "Wi-Fi")
            disconnect = lambda n=n: self.act(
                lambda: network.disconnect_device(device.device), f"Disconnecting from {n.ssid}…", "Wi-Fi"
            )
            connect = lambda n=n: self.act(
                lambda: network.activate(n.saved_uuid), f"Connecting to {n.ssid}…", f"Connect to {n.ssid}"
            )
        if n.saved_uuid:
            extras.append(
                self.button(
                    "user-trash-symbolic",
                    "✕",
                    f"Forget {n.ssid}",
                    lambda n=n, forget=forget: self.win.confirm(
                        f"Forget {n.ssid}?",
                        f"The saved password and settings for {n.ssid} are removed"
                        + (", and this computer leaves it." if n.in_use else "."),
                        "Forget",
                        forget,
                    ),
                    danger=True,
                )
            )
        if n.in_use:
            go = lambda n=n: self.win.confirm(
                f"Disconnect from {n.ssid}?",
                "Anything using the network will lose it until you connect again.",
                "Disconnect",
                disconnect,
            )
        elif n.saved_uuid:
            go = connect
        elif n.secured:
            go = lambda n=n: self.ask_password(n)
        elif s.iwd:
            go = connect
        else:
            go = lambda n=n: self.act(
                lambda: network.join_wifi(n.ssid), f"Connecting to {n.ssid}…", f"Connect to {n.ssid}"
            )
        locked = n.secured
        self.row(
            n.ssid,
            "Connected" if n.in_use else "Saved" if n.saved_uuid else "",
            go,
            detail=detail,
            icon="network-wireless-encrypted-symbolic" if locked else "network-wireless-symbolic",
            fallback="🔒" if locked else "📶",
            ident=f"wifi:{n.ssid}",
            extras=extras,
            value_css="state-on" if n.in_use else "setting-value",
        )

    def ask_password(self, n, error=""):
        def join(password):
            if not password:
                return
            if self.state.iwd:
                try:
                    secret = network.iwd.password_file(password)
                except (ValueError, OSError) as exc:
                    self.ask_password(n, str(exc))
                    return
                self.iwd_root(
                    ["join", n.ssid, secret], f"Connecting to {n.ssid}", f"Connecting to {n.ssid}…", cleanup=secret
                )
                return

            def work():
                problem = network.join_wifi(n.ssid, password)
                if problem != "The password was not accepted.":
                    return problem
                GLib.idle_add(
                    lambda: (self.ask_password(n, "The password was not accepted. Try again."), GLib.SOURCE_REMOVE)[1]
                )
                return ""

            self.act(work, f"Connecting to {n.ssid}…", f"Connect to {n.ssid}")

        keeper = (
            "iwd saves it (in /var/lib/iwd) for next time. Then Settings asks for your own password, since that needs administrator rights."
            if self.state.iwd
            else "NetworkManager saves the password for next time."
        )
        self.win.ask_text(
            f"Password for {n.ssid}",
            f"{n.security} network. {keeper}",
            join,
            secret=True,
            ok_label="Connect",
            error=error,
        )

    def scan(self):
        self.scanning = True
        self.redraw()
        self.set_status("Searching for networks…")

        def done(state):
            self.scanning = False
            self.busy = False
            self.set_status("")
            if state is not None:
                self.state = state
            self.redraw()

        self.busy = True
        in_background(lambda: network.read_state(scan=True), done, lambda _e: done(None))

    def ip_settings(self, i):
        uuid, name = i.connection_uuid, i.connection or i.device
        self.set_status("Reading IP settings…")
        in_background(
            lambda: network.read_ipv4(uuid), lambda s: (self.set_status(""), self.ip_form(uuid, name, s, iface=i))
        )

    def ip_form(self, uuid, name, s, error="", iface=None):
        again = lambda error="": self.ip_form(uuid, name, s, error, iface)

        def edit(field, title, message):
            def set_value(text):
                setattr(s, field, text.strip())
                again()

            self.win.ask_text(title, message, set_value, getattr(s, field), back=lambda: again())

        def flip():
            nonlocal s
            s = (
                network.Ipv4Settings("auto", s.address, s.gateway, s.dns)
                if not s.automatic
                else network.fixed_from(s, iface)
            )
            again()

        rows = [("Get the settings automatically (DHCP)", "Yes" if s.automatic else "No, set them here", flip)]
        if not s.automatic:
            rows += [
                (
                    "IP address",
                    s.address,
                    lambda: edit(
                        "address",
                        "IP address",
                        "With its prefix, for example 192.168.1.20/24 (without one, /24 is used).",
                    ),
                ),
                (
                    "Default gateway",
                    s.gateway,
                    lambda: edit(
                        "gateway",
                        "Default gateway",
                        "The router's address, for example 192.168.1.1. Can be left empty.",
                    ),
                ),
                (
                    "DNS servers",
                    s.dns,
                    lambda: edit(
                        "dns", "DNS servers", "One or more, separated by commas, for example 1.1.1.1, 9.9.9.9."
                    ),
                ),
            ]

        def save():
            problem, _args = network.validate_ipv4(s)
            if problem:
                again(problem)
                return
            self.win.close_modal()
            self.act(lambda: network.apply_ipv4(uuid, s), f"Applying the IP settings of {name}…", "IP settings")

        self.win.form(
            f"IP settings · {name}",
            rows,
            "Save",
            save,
            "Automatic (DHCP) asks the router for the address, gateway and DNS servers; choose the first row to switch. "
            "Saving reconnects, so the connection drops for a moment.",
            error,
        )
