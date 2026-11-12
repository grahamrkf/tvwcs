"""Bluetooth for Settings, through BlueZ's `bluetoothctl`. No GTK dependency.

bluetoothctl runs one command per call (non-interactive mode). Pairing registers a NoInputNoOutput agent, which
pairs headphones, speakers, gamepads and remotes ("just works"); a device that insists on typing a code (some
keyboards) has to be paired once with a full Bluetooth tool."""

from __future__ import annotations
import os, re
from dataclasses import dataclass, field

from tvwcs.control_cmd import have, key_values, run

SCAN_SECONDS = 10
_MAC = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"
_DEVICE_LINE = re.compile(rf"^Device ({_MAC})\s?(.*)$")

# bluetoothctl's Icon: value -> (symbolic icon, text glyph, what to call it)
DEVICE_ICONS = {
    "audio-headset": ("audio-headset-symbolic", "🎧", "Headset"),
    "audio-headphones": ("audio-headphones-symbolic", "🎧", "Headphones"),
    "audio-card": ("audio-speakers-symbolic", "🔊", "Speaker"),
    "input-gaming": ("input-gaming-symbolic", "🎮", "Game controller"),
    "input-keyboard": ("input-keyboard-symbolic", "⌨", "Keyboard"),
    "input-mouse": ("input-mouse-symbolic", "🖱", "Mouse"),
    "input-tablet": ("input-tablet-symbolic", "✎", "Tablet"),
    "phone": ("phone-symbolic", "📱", "Phone"),
    "computer": ("computer-symbolic", "🖥", "Computer"),
    "video-display": ("video-display-symbolic", "▭", "Display"),
    "multimedia-player": ("multimedia-player-symbolic", "♫", "Media player"),
}
DEFAULT_ICON = ("bluetooth-symbolic", "ᛒ", "Device")


@dataclass
class BtDevice:
    address: str
    name: str
    icon: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    battery: int | None = None

    @property
    def kind(self):
        return DEVICE_ICONS.get(self.icon, DEFAULT_ICON)


@dataclass
class BtState:
    available: bool
    message: str = ""
    controller: str = ""
    powered: bool = False
    blocked: bool = False
    devices: list = field(default_factory=list)

    @property
    def paired(self):
        return [d for d in self.devices if d.paired]

    @property
    def nearby(self):
        return [d for d in self.devices if not d.paired]


def parse_devices(text):
    """`bluetoothctl devices` -> [(address, name)]; status lines ([CHG], Agent registered) are skipped."""
    found = []
    for line in text.splitlines():
        m = _DEVICE_LINE.match(line.strip())
        if m:
            found.append((m.group(1).upper(), m.group(2).strip()))
    return found


def _yes(value):
    return (value or "").strip().lower() == "yes"


def parse_info(address, text):
    """`bluetoothctl info <address>` -> BtDevice (None when bluetoothctl does not know it)."""
    if f"DEVICE {address.upper()}" not in text.upper() or "not available" in text:
        return None
    info = key_values(text)
    battery = None
    m = re.search(r"\((\d+)\)", info.get("Battery Percentage", ""))
    if m:
        battery = int(m.group(1))
    name = info.get("Alias") or info.get("Name") or address
    return BtDevice(
        address,
        name,
        info.get("Icon", ""),
        _yes(info.get("Paired")),
        _yes(info.get("Trusted")),
        _yes(info.get("Connected")),
        battery,
    )


def parse_show(text):
    """`bluetoothctl show` -> (controller address or "", powered, blocked by rfkill)."""
    m = re.search(rf"Controller ({_MAC})", text)
    info = key_values(text)
    blocked = info.get("PowerState", "").lower() == "off-blocked"
    return (m.group(1).upper() if m else ""), _yes(info.get("Powered")), blocked


def _sort_key(d):
    return (not d.connected, not d.paired, d.name == d.address, d.name.casefold())


def read_state():
    if not have("bluetoothctl"):
        return BtState(False, "Bluetooth needs BlueZ (the bluez package), which provides bluetoothctl.")
    show = run(["bluetoothctl", "show"], timeout=8)
    controller, powered, blocked = parse_show(show.out)
    if not controller:
        # bluetooth.service only starts with an adapter (ConditionPathIsDirectory=/sys/class/bluetooth)
        if show.ok or "No default controller" in show.out + show.err or not os.path.isdir("/sys/class/bluetooth"):
            return BtState(False, "No Bluetooth adapter was found.")
        return BtState(
            False, "The Bluetooth service is not answering. Start it (bluetooth.service, or bluetoothd) and try again."
        )
    devices = []
    for address, name in parse_devices(run(["bluetoothctl", "devices"], timeout=8).out):
        d = parse_info(address, run(["bluetoothctl", "info", address], timeout=8).out) or BtDevice(address, name)
        if d.name == d.address and name and name.replace("-", ":").upper() != address:
            d.name = name
        devices.append(d)
    devices.sort(key=_sort_key)
    return BtState(True, "", controller, powered, blocked, devices)


def set_powered(on):
    """Switch the adapter on or off. -> "" on success, else why not."""
    result = run(["bluetoothctl", "power", "on" if on else "off"], timeout=10)
    if on and failure(result) and have("rfkill"):  # switched off by rfkill (airplane mode): lift that, then try again
        run(["rfkill", "unblock", "bluetooth"], timeout=5)
        result = run(["bluetoothctl", "power", "on"], timeout=10)
    return failure(result)


def scan(seconds=SCAN_SECONDS):
    """Look for devices for a while; they are then listed by read_state()."""
    return run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], timeout=seconds + 10)


def failure(result):
    """bluetoothctl often exits 0 on failure; the outcome is in its text."""
    text = result.out + "\n" + result.err
    m = re.search(r"Failed to \w+:?\s*(.*)", text)
    if m:
        return _explain(m.group(1).strip() or m.group(0))
    if "not available" in text:
        return "That device is no longer in range."
    if not result.ok:
        return _explain(result.message)
    return ""


_REASONS = {
    "org.bluez.Error.AuthenticationFailed": "The device refused to pair. Put it in pairing mode and try again.",
    "org.bluez.Error.AuthenticationCanceled": "Pairing was cancelled.",
    "org.bluez.Error.ConnectionAttemptFailed": "The device did not answer. Is it switched on and in range?",
    "org.bluez.Error.AlreadyExists": "",
    "org.bluez.Error.Blocked": "Bluetooth is switched off by rfkill (airplane mode).",
    "org.bluez.Error.NotReady": "Bluetooth is switched off.",
    "br-connection-page-timeout": "The device did not answer. Is it switched on and in range?",
    "br-connection-profile-unavailable": "This device offers nothing this computer can use (no matching profile).",
}


def _explain(reason):
    for key, text in _REASONS.items():
        if key in reason:
            return text
    return reason


def pair(address):
    """Pair, trust (so it can reconnect by itself) and connect. -> "" on success, else why not."""
    paired = run(["bluetoothctl", "--agent", "NoInputNoOutput", "--timeout", "30", "pair", address], timeout=40)
    problem = failure(paired)
    if problem:
        return problem
    run(["bluetoothctl", "trust", address], timeout=8)
    return connect(address)


def connect(address):
    return failure(run(["bluetoothctl", "--timeout", "20", "connect", address], timeout=30))


def disconnect(address):
    return failure(run(["bluetoothctl", "disconnect", address], timeout=15))


def forget(address):
    return failure(run(["bluetoothctl", "remove", address], timeout=15))
