"""The Quick Menu's bottom row (clock, status icons, ⚙, ⊞ and ⏻) and the panels a status icon unfolds. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import sys, threading, types
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from tvwcs.settings import bluetooth, network, sound
from tvwcs.system import power, quick_status, servermode
from tvwcs.settings.date_time import clock_text, short_date_text
from tvwcs.system.system_actions import power_menu
from tvwcs.core.workspaces import quick_list
from tvwcs.ui.widgets import KEEP_LTR, NavGroup, S, clear_box, glyph, muted_label
from tvwcs.ui.widgets import pointer_only


class StatusPanelsMixin:
    """The bottom of the Quick Menu (clock, status icons, ⚙, ⊞ and ⏻) and the panels a status icon unfolds."""

    # ---------------------------------------------------------- the bottom: clock, status icons and power
    STATUS_KEYS = ("updates", "network", "volume", "bluetooth", "battery")

    def _build_status_bar(self):
        """Two rows. Above: icons for waiting updates, the network, the volume, Bluetooth and the battery (with its
        charge, and whether it is charging; only on a computer with a battery), and ⏻ at the far right. Below: the time
        and date, and ⊞ Applications in the corner. Each row keeps its width whatever the icons show (an update count).
        The clock and the updates icon open their page of the Settings app; the others, and ⏻, unfold a panel above the
        rows (toggle_status_panel).
        The icons are refreshed by main.StatusWatcher."""
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        bar.add_css_class("quick-status")
        icons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        bar.append(icons)
        self._status_buttons = {}
        self.search_button = None
        if self.search_folds:  # first, nearest the corner: it stays put while the others come and go
            b = Gtk.Button()
            b.add_css_class("square")
            b.add_css_class("status-icon")
            b.set_valign(Gtk.Align.CENTER)
            b.set_child(glyph("edit-find-symbolic", "⌕", 22))
            b.set_tooltip_text("Search, or type a channel number")
            b.connect("clicked", lambda *_: self.toggle_search())
            icons.append(b)
            self.search_button = b
        for key in self.STATUS_KEYS:
            b = Gtk.Button()
            b.add_css_class("square")
            b.add_css_class("status-icon")
            b.set_valign(Gtk.Align.CENTER)
            if key == "updates":
                b.connect("clicked", lambda *_: self.app.open_settings("updates"))
            else:
                b.connect("clicked", lambda _b, k=key: self.toggle_status_panel(k))
            icons.append(b)
            self._status_buttons[key] = b
        gap = Gtk.Box()
        gap.set_hexpand(True)
        icons.append(gap)
        power = Gtk.Button()
        power.set_child(glyph("system-shutdown-symbolic", "⏻", 22))
        power.set_tooltip_text("Lock, sleep, reboot or shut down")
        power.add_css_class("square")
        power.add_css_class("status-icon")
        power.set_valign(Gtk.Align.CENTER)
        power.connect("clicked", lambda *_: self.toggle_status_panel("power"))
        icons.append(power)
        self._status_buttons["power"] = power
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        bar.append(line)
        clock = Gtk.Button()
        clock.add_css_class("clock-button")
        clock.set_hexpand(True)
        clock.set_tooltip_text("Date and time")
        # one line: the time, then the date to its right, on the same baseline
        text = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
        text.set_halign(Gtk.Align.START)
        self.clock_time = Gtk.Label()
        self.clock_time.add_css_class("clock-time")
        self.clock_time.set_valign(Gtk.Align.BASELINE)
        text.append(self.clock_time)
        self.clock_date = Gtk.Label()
        self.clock_date.add_css_class("clock-date")
        self.clock_date.set_valign(Gtk.Align.BASELINE)
        text.append(self.clock_date)
        clock.set_child(text)
        clock.connect("clicked", lambda *_: self.app.open_settings("datetime"))
        line.append(clock)
        # ⚙ beside ⊞: the Settings app (channel 0), one click from anywhere
        gear = Gtk.Button()
        gear.set_child(glyph("emblem-system-symbolic", "⚙", 22))
        gear.add_css_class("square")
        gear.add_css_class("status-icon")
        gear.set_valign(Gtk.Align.CENTER)
        gear.set_tooltip_text("Settings")
        gear.connect("clicked", lambda *_: self.app.open_settings())
        line.append(gear)
        self.settings_button = gear
        guide = Gtk.Button()
        guide.set_child(glyph("view-grid-symbolic", "⊞", 22))
        guide.add_css_class("square")
        guide.add_css_class("status-icon")
        guide.set_valign(Gtk.Align.CENTER)
        # ⊞ is on screen when it is clicked: open or close Applications here and now (show_mode would first ask the
        # window manager where TVWCS is, and an answer from before the click showed it again instead of closing it)
        guide.connect(
            "clicked",
            lambda *_: self.app.show_panels(
                not self.guide_open, False, focus="guide" if not self.guide_open else "quick"
            ),
        )
        line.append(guide)
        self.guide_button = guide
        self._status_group = NavGroup(
            ([self.search_button] if self.search_button else []) + list(self._status_buttons.values())
        )
        self._clock_group = NavGroup([clock, gear, guide])
        pointer_only(*self._status_group, *self._clock_group)
        self._status_shown = None
        self.tick_clock()
        self.show_status(self.app.status)
        self._flip(bar)  # the clock's row is nearest the corner
        return bar

    def tick_clock(self):
        if getattr(self, "clock_time", None) is None:
            return
        t = clock_text(None, self.app.store.settings.get("clock_24h", False))
        d = short_date_text()
        if self.clock_time.get_text() != t:
            self.clock_time.set_text(t)
        if self.clock_date.get_text() != d:
            self.clock_date.set_text(d)

    def show_status(self, status):
        buttons = getattr(self, "_status_buttons", None)
        if not buttons or status == self._status_shown:
            return
        self._status_shown = status
        looks = {
            "network": quick_status.network_icon(status),
            "volume": quick_status.volume_icon(status),
            "bluetooth": quick_status.bluetooth_icon(status),
            "updates": quick_status.updates_icon(status),
            "battery": quick_status.battery_icon(status),
        }
        shown = {
            "network": True,
            "volume": status.volume is not None,
            "bluetooth": bool(status.bluetooth),
            "updates": quick_status.updates_shown(status),
            "battery": status.battery is not None,
        }
        for key, (icon, fallback, tip) in looks.items():
            b = buttons[key]
            if key in ("updates", "battery"):  # an icon and a number: how many updates, the battery's percent
                child = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
                child.set_halign(Gtk.Align.CENTER)
                child.append(glyph(icon, fallback, 22))
                n = Gtk.Label(label=str(status.updates) if key == "updates" else f"{status.battery or 0}%")
                n.add_css_class("status-count")
                if key != "updates" or status.updates:
                    child.append(n)  # a restart alone: just its icon
                b.add_css_class("status-wide")
            else:
                child = glyph(icon, fallback, 22)
            if key == "bluetooth":
                (b.add_css_class if status.bluetooth == "off" else b.remove_css_class)("status-off")
            b.set_child(child)
            b.set_tooltip_text(tip)
            b.set_visible(shown[key])
            self._mirror(child)
            if not shown[key] and self._panel_key == key:
                self._close_open()

    # ---------------------------------------------------------- status panels: what a status icon (or ⏻) unfolds
    # A panel opens above the status row, like a row's options. One is open at a time; it folds away once the selection
    # leaves it (and its icon), with Back, or with its icon again. Details that take a command to read (network,
    # Bluetooth, sound) are read on a worker thread: the panel says "Loading…" until they arrive, and the selection
    # moves into it then, if it is still on the icon.
    def toggle_status_panel(self, key):
        opener = self._status_buttons[key]
        if self._panel_key == key:
            self._close_open()
            opener.grab_focus()
            return
        self._close_open()
        self._panel_key = key
        self._panel_token += 1
        opener.add_css_class("active")
        self._open_row = types.SimpleNamespace(
            opener=opener,
            expanded=lambda k=key: self._panel_key == k,
            collapse=self._collapse_status_panel,
            owns=lambda w, o=opener: w is o or self._contains(self.status_panel, w),
        )
        self.status_panel.set_visible(True)
        getattr(self, f"_panel_{key}")()

    def _collapse_status_panel(self):
        key = self._panel_key
        self._panel_key = None
        self._panel_token += 1
        self._panel_groups = []
        self._panel_placeholder = False
        b = self._status_buttons.get(key) if key else None
        if b is not None:
            b.remove_css_class("active")
        self.status_panel.set_visible(False)
        clear_box(self.status_panel)
        self.app.fit_quick_menu()

    def _fill_panel(self, build):
        """(Re)draw the open panel: build() adds its lines (_panel_line). A line that was selected stays selected; with
        the selection still on the panel's icon, it moves to the line build() prefers (_panel_prefer), else the last."""
        focused = self.get_focus()
        at = None
        placeholder = self._panel_placeholder
        self._panel_placeholder = False
        for g in (
            self._panel_groups if not placeholder else ()
        ):  # "Loading…" moved the selection in; the real lines choose again
            for k, w in enumerate(g):
                if w is focused:
                    at = (g.ident, k)
        self._keep_panel = True
        try:
            clear_box(self.status_panel)
            self._panel_groups = []
            self._panel_prefer = None
            build()
            self._flip(self.status_panel)
            self._mirror(self.status_panel)  # its first line nearest its icon, as below it
        finally:
            self._keep_panel = False
        groups = self._panel_groups
        target = None
        if at is not None:
            g = next((g for g in groups if g.ident == at[0]), None)
            if g is not None:
                target = g[min(at[1], len(g) - 1)]
        opener = self._status_buttons.get(self._panel_key)
        if target is None and groups and (placeholder or at is not None or focused is None or focused is opener):
            g = next((g for g in groups if g.ident == self._panel_prefer), groups[-1])
            target = self._landing(g) or g[0]
        if target is not None:
            target.grab_focus()
        self.app.fit_quick_menu()

    def _panel_line(self, widget, ident=None, *focusable, column=False):
        """Add a line to the open panel; its buttons (focusable) are one navigation row, known as `ident` across redraws."""
        self.status_panel.append(widget)
        if focusable:
            pointer_only(*focusable)
            g = NavGroup(list(focusable))
            g.ident = ident
            g.column = column
            self._panel_groups.append(g)
        return widget

    def _panel_text(self, text, css="muted"):
        l = Gtk.Label(label=text)
        l.set_xalign(0)
        l.set_wrap(True)
        l.add_css_class(css)
        return self._panel_line(l)

    def _panel_button(self, ident, icon, fallback, label, action, danger=False):
        b = self.dialog_button(icon, fallback, label)
        b.add_css_class("menu-item")
        if danger:
            b.add_css_class("danger")
        b.connect("clicked", lambda *_: action())
        self._panel_line(b, ident, b)
        return b

    def _panel_settings(self, page, label):
        if page == "network" and servermode.active():
            return  # turned off in server mode
        self._panel_button("settings", "emblem-system-symbolic", "⚙", label, lambda: self.app.open_settings(page))

    def _panel_read(self, read, build):
        """Read in the background, then draw build(result) if the same panel is still open (result is None when the read failed)."""
        token = self._panel_token

        def work():
            try:
                result = read()
            except Exception as exc:  # a panel must never break the menu
                print(f"Cannot read the status details: {exc}", file=sys.stderr)
                result = None
            GLib.idle_add(
                lambda: (token == self._panel_token and self._fill_panel(lambda: build(result)), GLib.SOURCE_REMOVE)[1]
            )

        threading.Thread(target=work, daemon=True).start()

    def _panel_do(self, work, reload):
        """Run a change (Wi-Fi off, disconnect a device, ...) in the background: work() -> "" when done, else why not.
        Then the panel is read again and the status icons refreshed."""
        if self._panel_busy:
            return
        self._panel_busy = True
        token = self._panel_token

        def run():
            try:
                problem = work() or ""
            except Exception as exc:
                problem = str(exc)
            GLib.idle_add(lambda: (done(problem), GLib.SOURCE_REMOVE)[1])

        def done(problem):
            self._panel_busy = False
            self.app.watch.read_now()
            if problem:
                self.show_message(problem, "That didn't work")
            if token == self._panel_token:
                reload()

        threading.Thread(target=run, daemon=True).start()

    def _panel_loading(self, page, label):
        def build():
            self._panel_text("Loading…")
            self._panel_settings(page, label)

        self._fill_panel(build)
        self._panel_placeholder = True

    def _panel_power(self):
        """Lock, Sleep, Reboot, Shut down and (with a login screen) Log out, the first nearest ⏻."""

        def run(action):
            self._close_open()
            self._status_buttons["power"].grab_focus()
            self.system_action(action)

        def build():
            for action in reversed(power_menu()):
                self._panel_button(
                    action.id,
                    action.icon,
                    action.fallback,
                    action.label,
                    lambda a=action: run(a),
                    danger=bool(action.confirm),
                )

        self._fill_panel(build)

    def _panel_network(self):
        """The connection in use (Wi-Fi network and signal, or the wired connection, with its address), Wi-Fi on or off,
        and Network settings."""
        self._panel_loading("network", "Network settings")

        def build(state):
            if state is None:
                self._panel_text("The network details could not be read.")
            else:
                connected = [i for i in state.interfaces if i.connected]
                if not connected:
                    self._panel_text("Not connected to a network", "panel-title")
                for i in connected:
                    net = next((n for n in state.networks if n.in_use), None) if i.kind == "wifi" else None
                    if i.kind == "wifi":
                        head = f"Wi-Fi · {net.ssid if net else i.connection or i.device}"
                    else:
                        head = f"Wired · {i.connection or i.device}"
                    self._panel_text(head, "panel-title")
                    details = [
                        f"Signal {net.signal}%" if net else "",
                        ", ".join(a.split("/")[0] for a in i.addresses),
                        f"gateway {i.gateway}" if i.gateway else "",
                        i.device,
                    ]
                    self._panel_text(" · ".join(d for d in details if d))
                if state.message:
                    self._panel_text(state.message)
                if state.managed and state.of_kind("wifi"):
                    on = state.wifi_enabled
                    if on:
                        self._panel_button(
                            "scan", "view-refresh-symbolic", "⟳", "Find Wi-Fi networks", self._panel_wifi_scan
                        )
                    self._panel_button(
                        "wifi",
                        "network-wireless-symbolic" if not on else "network-wireless-offline-symbolic",
                        "⌔",
                        "Turn Wi-Fi off" if on else "Turn Wi-Fi on",
                        lambda: self._panel_do(lambda: network.set_wifi(not on), self._panel_network),
                    )
                    self._panel_prefer = "scan" if on else "wifi"
            self._panel_settings("network", "Network settings")

        self._panel_read(network.read_details, build)

    def _panel_wifi_scan(self):
        """The Wi-Fi networks in range, strongest first: choose one to connect (a password is asked when it needs one)."""
        self._fill_panel(
            lambda: (
                self._panel_text("Looking for Wi-Fi networks…"),
                self._panel_settings("network", "Network settings"),
            )
        )
        self._panel_placeholder = True

        def build(state):
            networks = [n for n in (state.networks if state else []) if n.ssid and not n.in_use]
            seen = set()
            networks = [
                n for n in sorted(networks, key=lambda n: -n.signal) if not (n.ssid in seen or seen.add(n.ssid))
            ]
            self._panel_text("Wi-Fi networks" if networks else "No other Wi-Fi networks were found", "panel-title")
            for n in networks[:12]:
                label = f"{n.ssid}  ·  {n.signal}%" + ("  🔒" if n.secured and not n.saved_uuid else "")
                self._panel_button(
                    f"net:{n.ssid}", "network-wireless-symbolic", "⌔", label, lambda n=n: self._join_wifi(n)
                )
                if self._panel_prefer is None:
                    self._panel_prefer = f"net:{n.ssid}"
            self._panel_button("back", "go-previous-symbolic", "←", "Back", self._panel_network)
            self._panel_settings("network", "Network settings")

        self._panel_read(lambda: network.read_state(scan=True), build)

    def _join_wifi(self, n, error=""):
        if n.saved_uuid:
            self._panel_do(lambda: network.activate(n.saved_uuid), self._panel_network)
            return
        if not n.secured:
            self._panel_do(lambda: network.join_wifi(n.ssid), self._panel_network)
            return

        def got(password):
            if password:
                self._panel_do(lambda: network.join_wifi(n.ssid, password), self._panel_network)

        self.ask_text(
            f"Password for {n.ssid}",
            got,
            "",
            f"{n.security} network. NetworkManager saves the password for next time.",
            secret=True,
            ok_label="Connect",
            error=error,
        )

    def _panel_bluetooth(self):
        """The devices that are connected, each with Disconnect; Bluetooth on or off; Bluetooth settings."""
        self._panel_loading("bluetooth", "Bluetooth settings")

        def build(state):
            if state is None or not state.available:
                self._panel_text(state.message if state else "The Bluetooth details could not be read.")
            else:
                if not state.powered:
                    self._panel_text(
                        "Bluetooth is off" + (" (blocked, as in airplane mode)" if state.blocked else ""), "panel-title"
                    )
                else:
                    connected = [d for d in state.devices if d.connected]
                    self._panel_text("Connected" if connected else "No devices are connected", "panel-title")
                    for d in connected:
                        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
                        icon, fallback, _kind = d.kind
                        g = glyph(icon, fallback, 22)
                        g.set_size_request(S(28), -1)
                        line.append(g)
                        name = Gtk.Label(label=d.name + (f" · {d.battery}%" if d.battery is not None else ""))
                        name.set_xalign(0)
                        name.set_hexpand(True)
                        name.set_ellipsize(3)
                        line.append(name)
                        off = Gtk.Button(label="Disconnect")
                        off.connect(
                            "clicked",
                            lambda _b, a=d.address: self._panel_do(
                                lambda: bluetooth.disconnect(a), self._panel_bluetooth
                            ),
                        )
                        line.append(off)
                        self._panel_line(line, f"device:{d.address}", off)
                        if self._panel_prefer is None:
                            self._panel_prefer = f"device:{d.address}"
                on = state.powered
                if on:
                    self._panel_button(
                        "scan", "view-refresh-symbolic", "⟳", "Find Bluetooth devices", self._panel_bluetooth_scan
                    )
                self._panel_button(
                    "power",
                    "bluetooth-disabled-symbolic" if on else "bluetooth-active-symbolic",
                    "ᛒ",
                    "Turn Bluetooth off" if on else "Turn Bluetooth on",
                    lambda: self._panel_do(lambda: bluetooth.set_powered(not on), self._panel_bluetooth),
                )
                if self._panel_prefer is None:
                    self._panel_prefer = "power"
            self._panel_settings("bluetooth", "Bluetooth settings")

        self._panel_read(bluetooth.read_state, build)

    def _panel_bluetooth_scan(self):
        """Look for devices for a few seconds, then list the ones not connected: choose one to pair (or connect)."""
        self._fill_panel(
            lambda: (
                self._panel_text("Looking for Bluetooth devices… Put the device in pairing mode."),
                self._panel_settings("bluetooth", "Bluetooth settings"),
            )
        )
        self._panel_placeholder = True

        def read():
            bluetooth.scan(8)
            return bluetooth.read_state()

        def build(state):
            found = [d for d in (state.devices if state and state.available else []) if not d.connected]
            self._panel_text("Bluetooth devices" if found else "No devices were found", "panel-title")
            for d in found[:12]:
                icon, fallback, _kind = d.kind
                self._panel_button(
                    f"dev:{d.address}",
                    icon,
                    fallback,
                    ("Connect " if d.paired else "Pair ") + d.name,
                    lambda d=d: self._panel_do(
                        lambda: bluetooth.connect(d.address) if d.paired else bluetooth.pair(d.address),
                        self._panel_bluetooth,
                    ),
                )
                if self._panel_prefer is None:
                    self._panel_prefer = f"dev:{d.address}"
            self._panel_button("back", "go-previous-symbolic", "←", "Back", self._panel_bluetooth)
            self._panel_settings("bluetooth", "Bluetooth settings")

        self._panel_read(read, build)

    def _panel_battery(self):
        """The charge, and about how long until the battery is empty (or charged)."""

        def build():
            b = power.read_battery()
            seconds, _direction = power.battery_time()
            if not b.present:
                self._panel_text("No battery was found.")
            else:
                self._panel_text(
                    f"Battery {b.percent}%"
                    + (", on battery" if b.on_battery else ", charging" if b.charging else ", plugged in"),
                    "panel-title",
                )
                if b.on_battery:
                    text = f"About {power.time_text(seconds)} left" if seconds else "Working out how long it will last…"
                elif b.charging:
                    text = (
                        f"About {power.time_text(seconds)} until it is fully charged"
                        if seconds
                        else "Working out how long it will take to charge…"
                    )
                else:
                    text = "Fully charged" if b.percent >= 95 else "Not charging"
                self._panel_text(text)
            self._panel_settings("power", "Power settings")

        self._fill_panel(build)

    def _panel_volume(self):
        """The output and the input: mute, − and + (and a slider for the mouse); Sound settings."""
        self._panel_loading("sound", "Sound settings")

        def build(state):
            if state is None or not state.available:
                self._panel_text(state.message if state else "The sound details could not be read.")
            else:
                for kind, device in (("Output", state.output()), ("Input", state.input())):
                    if device is not None:
                        self._volume_line(kind, device)
                if not state.outputs:
                    self._panel_text("No sound output was found.")
            self._panel_settings("sound", "Sound settings")

        self._panel_read(sound.read_state, build)

    def _volume_line(self, kind, device):
        self._panel_text(f"{kind} · {device.label}", "panel-title")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        output = kind == "Output"

        def mute_look():
            if output:
                icon, fallback = (
                    ("audio-volume-muted-symbolic", "🔇") if device.muted else ("audio-volume-high-symbolic", "🔊")
                )
            else:
                icon, fallback = (
                    ("microphone-sensitivity-muted-symbolic", "🎙")
                    if device.muted
                    else ("audio-input-microphone-symbolic", "🎙")
                )
            mute.set_child(glyph(icon, fallback, 22))
            mute.set_tooltip_text(f"Unmute the {kind.lower()}" if device.muted else f"Mute the {kind.lower()}")
            (mute.add_css_class if device.muted else mute.remove_css_class)("active")

        mute = Gtk.Button()
        mute.add_css_class("square")
        mute_look()

        def toggle_mute():
            device.muted = not device.muted
            mute_look()
            muted = device.muted

            def work():
                result = sound.set_muted(device, muted)
                return "" if result.ok else result.message

            self._panel_do(work, lambda: None)

        mute.connect("clicked", lambda *_: toggle_mute())
        less = Gtk.Button(label="−")
        less.add_css_class("square")
        less.set_tooltip_text(f"{kind} volume down")
        more = Gtk.Button(label="+")
        more.add_css_class("square")
        more.set_tooltip_text(f"{kind} volume up")
        boost = bool(self.app.store.settings.get("audio_boost"))
        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, sound.top(boost), 1)
        slider.set_draw_value(False)
        slider.set_hexpand(True)
        slider.set_focusable(False)
        slider.add_css_class(KEEP_LTR)
        percent = Gtk.Label()
        percent.set_width_chars(5)
        percent.set_xalign(1)
        percent.add_css_class("status-count")

        def show(value):
            percent.set_text(f"{value}%")
            slider.set_value(min(sound.top(boost), value))

        def apply(value):
            device.volume = max(0, min(sound.top(boost), int(value)))
            show(device.volume)
            self._volume_target[device.name] = device.volume
            if device.name not in self._volume_busy:
                self._send_volume(device)

        less.connect("clicked", lambda *_: apply(sound.stepped(device.volume, -1, boost)))
        more.connect("clicked", lambda *_: apply(sound.stepped(device.volume, 1, boost)))
        slider.connect("change-value", lambda _s, _scroll, value: (apply(round(value)), False)[1])
        show(device.volume)
        for w in (mute, less, slider, more, percent):
            line.append(w)
        self._panel_line(line, kind, mute, less, more, column=True)
        if self._panel_prefer is None:
            self._panel_prefer = kind

    def _send_volume(self, device):
        """Set the volume on a worker thread, one change at a time per device: presses that come quicker than pactl
        answers are merged into the last one."""
        self._volume_busy.add(device.name)
        target = self._volume_target[device.name]

        def run():
            try:
                sound.set_volume(device, target, bool(self.app.store.settings.get("audio_boost")))
            except Exception:
                pass
            GLib.idle_add(lambda: (done(), GLib.SOURCE_REMOVE)[1])

        def done():
            self._volume_busy.discard(device.name)
            if self._volume_target.get(device.name) != target:
                self._send_volume(device)
            else:
                self.app.watch.read_now()

        threading.Thread(target=run, daemon=True).start()

    def _build_quick_content(self, content):
        """One list: favorites in their order, then the other open applications (nearest the search field), with no
        headings. An open favorite shows once, as the open application (with ★). With neither, a note says where the
        installed applications are."""
        entries = self.app.workspace_entries()
        outputs = self.app.wm.outputs()
        opened = self.app.open_favorites([w for e in entries for w in e.windows])
        # an app that is uninstalled stays a favorite, hidden, and comes back if it is installed again
        installed = self.app.catalogue.by_id()
        favorites = [p for p in self.app.store.favorites() if p.desktop_id in installed]
        rows, self._starred = quick_list(favorites, entries, opened)
        for kind, item in rows:
            if kind == "favorite":
                content.append(self._favorite_row(item))
            else:
                content.append(
                    self._window_row(item.windows[0]) if len(item.windows) == 1 else self._workspace_row(item, outputs)
                )
        if not self.app.wm.available:
            content.append(muted_label("TVWCS can't see open apps here: it needs the sway window manager."))
        if not rows:
            content.append(
                muted_label(
                    f"Nothing is open and there are no favorites yet. {self.guide_hint()} to see your installed applications."
                )
            )
        self._flip(content)
        self._mirror(content)  # the open applications stay nearest the search field

    def _keep_at_bottom(self, adj):
        """The Quick Menu's lists grow upwards from the search field: when they overflow, show their bottom (in a top
        corner they grow downwards, and show their top). "changed"
        comes while GTK is sizing the list, when a new value would not move it yet, so it is set just after. Not while
        a row's options are open: they unfold upwards, and the list scrolls to show them instead."""
        if self._open_row is not None and getattr(self._open_row, "opener", None) is None:
            return
        GLib.idle_add(
            lambda: (
                adj.set_value(adj.get_lower() if self.top else adj.get_upper() - adj.get_page_size()),
                GLib.SOURCE_REMOVE,
            )[1]
        )
