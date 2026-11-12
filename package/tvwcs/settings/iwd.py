"""Wi-Fi through iwd, for computers whose network NetworkManager does not run (Arch with systemd-networkd and iwd,
or iwd alone). No GTK dependency.

Settings reads iwd's state over D-Bus with `busctl` (systemd's), as the user. Connecting to a saved or open network,
leaving and forgetting one are tried as the user too (Arch's iwd lets the wheel group); when iwd refuses (DENIED) they
go through `python3 -m tvwcs.settings.iwd` as root. A new password always does: it is written the way iwd keeps it
(/var/lib/iwd/<name>.psk), which iwd sees at once, and the network is then connected. A network that fails to connect the first time is forgotten again, so a mistyped password is not kept.

IP addresses are not iwd's business here: systemd-networkd, dhcpcd or iwd's own network configuration give them, and
Settings only says which (settings.network.address_source)."""

from __future__ import annotations
import json, os, re, sys, time
from dataclasses import dataclass

from tvwcs import LIB_DIR
from tvwcs.settings.cmd import have, run

SERVICE = "net.connman.iwd"
STORAGE = "/var/lib/iwd"
# iwd's network types, as Settings shows them
SECURITY = {"psk": "WPA", "open": "", "8021x": "802.1X", "wep": "WEP", "hotspot": "Hotspot"}


@dataclass
class IwdNetwork:
    path: str  # its D-Bus object
    ssid: str
    kind: str  # psk, open, 8021x...
    signal: int  # 0-100 %
    connected: bool = False
    known: str = ""  # its KnownNetwork object ("" = not saved)
    device: str = ""  # the Device object it was seen by


@dataclass
class IwdDevice:
    path: str
    name: str  # wlan0
    powered: bool
    state: str  # the station's state: connected, disconnected, connecting, roaming...
    station: bool  # in station mode (not an access point)


# ------------------------------------------------------------------ reading (busctl's JSON; pure parsing)
def _value(v):
    """busctl --json gives each variant as {"type":..., "data":...}."""
    return v.get("data") if isinstance(v, dict) and "type" in v and "data" in v else v


def parse_objects(text):
    """`busctl --json=short call net.connman.iwd / org.freedesktop.DBus.ObjectManager GetManagedObjects` ->
    ({path: {interface: {property: value}}})."""
    try:
        data = json.loads(text or "{}").get("data")
    except (ValueError, AttributeError):
        return {}
    objects = data[0] if isinstance(data, list) and data else data
    if not isinstance(objects, dict):
        return {}
    return {
        path: {iface: {k: _value(v) for k, v in (props or {}).items()} for iface, props in (ifaces or {}).items()}
        for path, ifaces in objects.items()
    }


def devices(objects):
    found = []
    for path, ifaces in sorted(objects.items()):
        d = ifaces.get(f"{SERVICE}.Device")
        if d is None:
            continue
        st = ifaces.get(f"{SERVICE}.Station")
        found.append(
            IwdDevice(
                path, str(d.get("Name", "")), bool(d.get("Powered")), str((st or {}).get("State", "")), st is not None
            )
        )
    return found


def parse_ordered(text):
    """`... Station GetOrderedNetworks` -> [(network path, signal in 1/100 dBm)], strongest first."""
    try:
        data = json.loads(text or "{}").get("data")
    except (ValueError, AttributeError):
        return []
    rows = (
        data[0]
        if isinstance(data, list)
        and data
        and isinstance(data[0], list)
        and (not data[0] or isinstance(data[0][0], list))
        else data
    )
    out = []
    for row in rows or []:
        if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str):
            out.append((row[0], int(row[1])))
    return out


def percent(strength):
    """iwd's signal (1/100 dBm) as 0-100 %: -100 dBm and below is 0, -50 dBm and above is 100."""
    return max(0, min(100, 2 * (strength // 100 + 100)))


def networks(objects, ordered):
    """The networks a station sees, strongest first, one per name (the connected one wins)."""
    best = {}
    for path, strength in ordered:
        n = objects.get(path, {}).get(f"{SERVICE}.Network")
        if n is None or not n.get("Name"):
            continue
        known = str(n.get("KnownNetwork", "") or "")
        net = IwdNetwork(
            path,
            str(n["Name"]),
            str(n.get("Type", "")),
            percent(strength),
            bool(n.get("Connected")),
            "" if known in ("", "/") else known,
            str(n.get("Device", "")),
        )
        old = best.get(net.ssid)
        if old is None or (net.connected and not old.connected):
            best[net.ssid] = net
    return sorted(best.values(), key=lambda n: (not n.connected, -n.signal, n.ssid.casefold()))


def known_networks(objects):
    """{ssid: KnownNetwork path} of the saved networks, seen now or not."""
    return {
        str(k["Name"]): path
        for path, ifaces in objects.items()
        for k in [ifaces.get(f"{SERVICE}.KnownNetwork")]
        if k and k.get("Name")
    }


def _busctl(*args, timeout=10):
    return run(["busctl", "--system", "--json=short", *args], timeout=timeout)


def running():
    """iwd is running and busctl is there to ask it."""
    return have("busctl") and run(["systemctl", "is-active", "--quiet", "iwd.service"], timeout=5).ok


@dataclass
class IwdState:
    devices: list
    networks: list
    known: dict
    problem: str = ""


def read_state(scan=False):
    got = _busctl("call", SERVICE, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
    if not got.ok:
        denied = "AccessDenied" in got.err or "Access denied" in got.err
        return IwdState(
            [],
            [],
            {},
            (
                "iwd does not let this user see its Wi-Fi networks (its D-Bus policy). Add the user to the wheel group."
                if denied
                else f"iwd did not answer: {(got.err or got.out).strip()}"
            ),
        )
    objects = parse_objects(got.out)
    devs = devices(objects)
    found = []
    station = next((d for d in devs if d.station and d.powered), None)
    if station is not None:
        if scan:  # iwd also scans by itself now and then; a search asks for one now (as the user: ignored if refused)
            _busctl("call", SERVICE, station.path, f"{SERVICE}.Station", "Scan", timeout=10)
            for _ in range(20):
                time.sleep(0.5)
                st = _busctl("get-property", SERVICE, station.path, f"{SERVICE}.Station", "Scanning", timeout=5)
                if not st.ok or '"data":true' not in st.out.replace(" ", ""):
                    break
            objects = (
                parse_objects(
                    _busctl("call", SERVICE, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects").out
                )
                or objects
            )
        ordered = parse_ordered(_busctl("call", SERVICE, station.path, f"{SERVICE}.Station", "GetOrderedNetworks").out)
        found = networks(objects, ordered)
    return IwdState(devs, found, known_networks(objects))


# ------------------------------------------------------------------ iwd's files (as root)
_PLAIN = re.compile(r"[A-Za-z0-9 _-]+")


def storage_name(ssid, kind="psk"):
    """iwd's file name for a network: its name when it only has letters, digits, spaces, _ and -; otherwise = and
    its bytes in hex."""
    base = ssid if _PLAIN.fullmatch(ssid) else "=" + ssid.encode("utf-8").hex()
    return f"{base}.{kind}"


def escape(value):
    """A value as iwd's settings files read it back: backslashes doubled, spaces at either end as \\s."""
    value = value.replace("\\", "\\\\")
    lead = len(value) - len(value.lstrip(" "))
    trail = len(value) - len(value.rstrip(" ")) if value.strip(" ") else 0
    return "\\s" * lead + value[lead : len(value) - trail] + "\\s" * trail


def psk_text(passphrase):
    if not 8 <= len(passphrase.encode("utf-8")) <= 63:
        raise ValueError("A WPA password has 8 to 63 characters.")
    if any(c in passphrase for c in "\r\n\0"):
        raise ValueError("Unexpected character in the password.")
    return f"[Security]\nPassphrase={escape(passphrase)}\n"


# ------------------------------------------------------------------ changing: the root commands Settings runs
def root_argv(*args) -> list:
    """`python3 -m tvwcs.settings.iwd args` from this copy of TVWCS, for sudo."""
    here = str(LIB_DIR)
    return ["env", "PYTHONDONTWRITEBYTECODE=1", f"PYTHONPATH={here}", "python3", "-m", "tvwcs.settings.iwd", *args]


def password_file(passphrase):
    """The password in a file only this user can read, for the root command to take (never in a command line)."""
    psk_text(passphrase)  # checked here, so a bad one is said before the password prompt
    folder = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(folder, f"tvwcs-wifi-{os.getpid()}-{time.time_ns()}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(passphrase)
    return path


DENIED = (
    "iwd did not let this user do that."  # its D-Bus policy: then Settings asks for the password and does it as root
)
# busctl prints a failed call's message, not its error name: both are matched
_ERRORS = (
    (("net.connman.iwd.Failed", "Operation failed"), "It could not connect. Check the password."),
    (("InvalidFormat", "Invalid format"), "The password was not accepted."),
    (("NotFound", "Not found"), "The network is no longer in range."),
    (("Aborted", "Operation aborted"), "Connecting was cancelled."),
    (("Busy", "Operation already in progress"), "Wi-Fi is busy. Try again in a moment."),
    (("NoAgent", "No Agent"), "The network needs a password."),
    (("AccessDenied", "Access denied", "not allowed", "NotAuthorized"), DENIED),
)


def explain(err):
    err = (err or "").strip()
    for keys, text in _ERRORS:
        if any(k in err for k in keys):
            return text
    return re.sub(r"^Call failed:\s*", "", err) or "It did not work."


def _call(path, iface, method, timeout=60):
    """A D-Bus call to iwd -> "" or why it failed, in words."""
    r = run(["busctl", "--system", f"--timeout={timeout}", "call", SERVICE, path, iface, method], timeout=timeout + 5)
    return "" if r.ok else explain(r.err or r.out)


def _find(ssid):
    objects = parse_objects(
        _busctl("call", SERVICE, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects").out
    )
    net = next(
        (p for p, i in sorted(objects.items()) for n in [i.get(f"{SERVICE}.Network")] if n and n.get("Name") == ssid),
        None,
    )
    known = known_networks(objects).get(ssid)
    return net, known


def _wait(ssid, known, seconds=6):
    """Until iwd lists `ssid` as a known network (known=True) or no longer does: it reads and drops its files a moment
    after they change (inotify), and a file written before it has finished dropping the old one fails to load."""
    for _ in range(int(seconds / 0.25)):
        if bool(_find(ssid)[1]) == known:
            return True
        time.sleep(0.25)
    return False


def _forget_quietly(ssid, written=""):
    known = _find(ssid)[1]
    if known:
        _call(known, f"{SERVICE}.KnownNetwork", "Forget", timeout=10)
    if written:
        try:
            os.unlink(written)
        except OSError:
            pass
    _wait(ssid, False)


def _write_psk(path, passphrase):
    tmp = path + ".tvwcs-new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(psk_text(passphrase))
    os.replace(tmp, path)


def join(ssid, secret_file=""):
    """Connect to `ssid` (as root with secret_file: first saving the password in it, which is removed, the way iwd
    keeps it). A network saved here that fails to connect is forgotten again, and waited for until iwd has let it go,
    so a retry with the right password straight away loads cleanly."""
    written = ""
    if secret_file:
        try:
            with open(secret_file, encoding="utf-8") as f:
                passphrase = f.read()
        finally:
            try:
                os.unlink(secret_file)
            except OSError:
                pass
        if _find(ssid)[1]:
            _forget_quietly(ssid)  # an old password for it (a new one is being typed)
        written = os.path.join(STORAGE, storage_name(ssid, "psk"))
        os.makedirs(STORAGE, mode=0o700, exist_ok=True)
        _write_psk(written, passphrase)
        _wait(ssid, True)
    net, _known = _find(ssid)
    if net is None:
        problem = "The network is no longer in range."
    else:
        problem = _call(net, f"{SERVICE}.Network", "Connect")
        if problem == "The network needs a password." and written:  # iwd had not loaded the file yet: once more
            time.sleep(1)
            _write_psk(written, passphrase)
            _wait(ssid, True)
            problem = _call(net, f"{SERVICE}.Network", "Connect")
    if problem and written:
        _forget_quietly(ssid, written)  # a wrong password is not kept, so it is not tried again by itself
    return problem


def forget(ssid):
    _net, known = _find(ssid)
    if known:
        problem = _call(known, f"{SERVICE}.KnownNetwork", "Forget", timeout=10)
        if not problem:
            _wait(ssid, False)
        return problem
    for kind in ("psk", "open", "8021x"):  # saved, but iwd has not read it
        try:
            os.unlink(os.path.join(STORAGE, storage_name(ssid, kind)))
        except OSError:
            pass
    return ""


def disconnect(device_path):
    if not re.fullmatch(r"/net/connman/iwd/[A-Za-z0-9_/]+", device_path):
        return "Unexpected device."
    return _call(device_path, f"{SERVICE}.Station", "Disconnect", timeout=15)


USAGE = """Usage (as root): python3 -m tvwcs.settings.iwd <command>
  join SSID [PASSWORD-FILE]   connect (saving the password in the file, which is removed, the way iwd keeps it)
  forget SSID                 forget a saved network
  disconnect DEVICE-PATH      leave the network"""


def main(argv):
    args = list(argv)
    if not args:
        print(USAGE, file=sys.stderr)
        return 2
    cmd = args.pop(0)
    if cmd == "join" and len(args) in (1, 2):
        problem = join(args[0], args[1] if len(args) == 2 else "")
    elif cmd == "forget" and len(args) == 1:
        problem = forget(args[0])
    elif cmd == "disconnect" and len(args) == 1:
        problem = disconnect(args[0])
    else:
        print(USAGE, file=sys.stderr)
        return 2
    if problem:
        print(problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
