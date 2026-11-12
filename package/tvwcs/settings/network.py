"""Ethernet and Wi-Fi for Settings. No GTK dependency.

Changes go through NetworkManager's `nmcli`, which polkit lets the user at the screen use without a password.
Without NetworkManager the panel still shows every interface, its addresses and the gateway (from `ip`), and whether
DHCP gave the address or it was set by hand. With iwd running (Arch's systemd-networkd and iwd), Wi-Fi networks can be
joined and forgotten through it (settings.iwd)."""

from __future__ import annotations
import ipaddress, json, os, re
from dataclasses import dataclass, field

from tvwcs.settings import iwd
from tvwcs.system import distro
from tvwcs.settings.cmd import have, run, split_terse


@dataclass
class Interface:
    device: str
    kind: str  # "ethernet" or "wifi"
    state: str = ""  # connected, disconnected, unavailable (no cable), connecting, ...
    connection: str = ""  # the active NetworkManager connection's name
    connection_uuid: str = ""
    mac: str = ""
    addresses: list = field(default_factory=list)  # "192.168.1.20/24"
    gateway: str = ""
    dns: list = field(default_factory=list)
    method: str = ""  # the connection's IPv4 method: "auto" (DHCP) or "manual"; "" when there is no connection
    dynamic: bool = False  # without NetworkManager: its IPv4 address has a lease (DHCP) rather than being set by hand
    set_by: str = ""  # without NetworkManager: what gives it its address (networkd, dhcpcd, iwd), "" when unknown

    @property
    def connected(self):
        return self.state.startswith("connected")


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    security: str
    in_use: bool = False
    saved_uuid: str = ""  # a saved connection for it ("" = none)

    @property
    def secured(self):
        return bool(self.security.strip()) and self.security.strip() != "--"


@dataclass
class NetState:
    managed: bool  # NetworkManager is there to change things
    message: str = ""
    interfaces: list = field(default_factory=list)
    wifi_enabled: bool = False
    networks: list = field(default_factory=list)
    iwd: bool = False  # without NetworkManager, iwd runs Wi-Fi: networks are joined and forgotten through it
    iwd_station: str = ""  # then: the D-Bus object of the adapter that joins networks
    iwd_devices: list = field(default_factory=list)  # and the interfaces iwd runs (not, say, an access point's)
    iwd_device: str = ""  # the one that joins networks (wlan0)

    def of_kind(self, kind):
        return [i for i in self.interfaces if i.kind == kind]


@dataclass
class Ipv4Settings:
    method: str = "auto"  # "auto" (DHCP) or "manual"
    address: str = ""  # "192.168.1.20/24"
    gateway: str = ""
    dns: str = ""  # comma separated

    @property
    def automatic(self):
        return self.method != "manual"


# ------------------------------------------------------------------ parsing (pure)
_STATE = re.compile(r"^\d+\s*\((.*)\)$")


def parse_device_list(text):
    """`nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device` -> [Interface] (Ethernet and Wi-Fi only)."""
    found = []
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) >= 3 and f[1] in ("ethernet", "wifi"):
            found.append(Interface(f[0], f[1], f[2], f[3] if len(f) > 3 and f[3] != "--" else ""))
    return found


def parse_device_show(text, iface):
    """`nmcli -t -f GENERAL.HWADDR,GENERAL.STATE,GENERAL.CONNECTION,IP4 device show <dev>` into `iface`."""
    for line in text.splitlines():
        key, value = (split_terse(line, 1) + [""])[:2]
        key = key.split("[")[0]
        if not value or value == "--":
            continue
        if key == "GENERAL.HWADDR":
            iface.mac = value
        elif key == "GENERAL.STATE":
            m = _STATE.match(value)
            iface.state = m.group(1) if m else value
        elif key == "IP4.ADDRESS":
            iface.addresses.append(value)
        elif key == "IP4.GATEWAY":
            iface.gateway = value
        elif key == "IP4.DNS":
            iface.dns.append(value)
    return iface


def parse_connections(text):
    """`nmcli -t -f NAME,UUID,TYPE,DEVICE connection show` -> [(name, uuid, type, device)]."""
    rows = []
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) >= 4:
            rows.append((f[0], f[1], f[2], "" if f[3] == "--" else f[3]))
    return rows


def parse_wifi_list(text):
    """`nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list` -> [WifiNetwork], one per name, strongest first.
    Hidden networks (no name) are left out."""
    best = {}
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1]:
            continue
        try:
            signal = max(0, min(100, int(f[2] or 0)))
        except ValueError:
            signal = 0
        net = WifiNetwork(f[1], signal, f[3], f[0].strip() == "*")
        old = best.get(net.ssid)
        if old is None or (net.in_use and not old.in_use) or (net.in_use == old.in_use and signal > old.signal):
            best[net.ssid] = net
    return sorted(best.values(), key=lambda n: (not n.in_use, -n.signal, n.ssid.casefold()))


_FOREVER = 4294967295  # ip's valid_life_time for an address without a lease


def _physical(name):
    return os.path.exists(f"/sys/class/net/{name}/device")


def parse_ip_json(addr_json, route_json, physical=_physical):
    """`ip -j addr` and `ip -j route` -> [Interface], for systems without NetworkManager. Loopback and virtual
    interfaces (bridges, containers, tunnels) are left out."""
    try:
        links = json.loads(addr_json or "[]")
    except ValueError:
        links = []
    try:
        routes = json.loads(route_json or "[]")
    except ValueError:
        routes = []
    gateways = {r.get("dev"): r.get("gateway", "") for r in routes if r.get("dst") == "default" and r.get("gateway")}
    found = []
    for link in links:
        name = link.get("ifname", "")
        if not name or not physical(name):
            continue
        if link.get("link_type") not in (None, "ether"):
            continue  # loopback, tunnels, …
        kind = "wifi" if os.path.isdir(f"/sys/class/net/{name}/wireless") else "ethernet"
        up = "UP" in link.get("flags", []) and "LOWER_UP" in link.get("flags", [])
        v4 = [a for a in link.get("addr_info", []) if a.get("family") == "inet" and a.get("local")]
        addresses = [f"{a['local']}/{a.get('prefixlen',32)}" for a in v4]
        found.append(
            Interface(
                name,
                kind,
                "connected" if up and addresses else "disconnected" if up else "unavailable",
                "",
                "",
                link.get("address", ""),
                addresses,
                gateways.get(name, ""),
                dynamic=bool(v4) and all(a.get("dynamic") or _FOREVER > a.get("valid_life_time", _FOREVER) for a in v4),
            )
        )
    return found


def with_unmanaged(interfaces, addr_json, route_json, physical=_physical):
    """NetworkManager's interfaces, with the ones it leaves alone (an ifupdown port on Debian is "unmanaged") but that
    are up with an address shown as connected, from `ip`; then ordered by default route, the one in use first."""
    seen = {i.device: i for i in parse_ip_json(addr_json, route_json, physical)}
    for iface in interfaces:
        live = seen.get(iface.device)
        if iface.state.startswith("unmanaged") and live is not None and live.connected:
            iface.state = "connected (not managed by NetworkManager)"
            iface.addresses = live.addresses
            iface.gateway = live.gateway
    try:
        routes = json.loads(route_json or "[]")
    except ValueError:
        routes = []
    metric = {}
    for r in routes:
        if r.get("dst") == "default" and r.get("dev"):
            metric[r["dev"]] = min(metric.get(r["dev"], 1 << 31), r.get("metric", 0))
    return sorted(interfaces, key=lambda i: metric.get(i.device, 1 << 32))


def parse_ipv4(text):
    """`nmcli -t -f ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns connection show <uuid>` -> Ipv4Settings."""
    s = Ipv4Settings()
    for line in text.splitlines():
        key, value = (split_terse(line, 1) + [""])[:2]
        value = "" if value == "--" else value
        if key == "ipv4.method":
            s.method = "manual" if value == "manual" else "auto"
        elif key == "ipv4.addresses":
            s.address = value.split(",")[0].strip()
        elif key == "ipv4.gateway":
            s.gateway = value
        elif key == "ipv4.dns":
            s.dns = value
    return s


def signal_bars(signal):
    """0-100 -> a four-step bar glyph, for the Wi-Fi list."""
    return "▂▄▆█"[: max(1, min(4, (signal + 24) // 25))]


def validate_ipv4(settings):
    """-> (problem or "", nmcli arguments for `connection modify`)."""
    if settings.automatic:
        return "", ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]
    text = settings.address.strip()
    try:
        iface = ipaddress.IPv4Interface(text if "/" in text else text + "/24")
    except ValueError:
        return f"“{text or 'nothing'}” is not an IPv4 address (for example 192.168.1.20/24).", []
    gateway = settings.gateway.strip()
    if gateway:
        try:
            if ipaddress.IPv4Address(gateway) not in iface.network:
                return f"The gateway {gateway} is not on the network {iface.network}.", []
        except ValueError:
            return f"“{gateway}” is not an IPv4 address.", []
    servers = [s for s in re.split(r"[,\s]+", settings.dns.strip()) if s]
    for s in servers:
        try:
            ipaddress.ip_address(s)
        except ValueError:
            return f"The DNS server “{s}” is not an IP address.", []
    return "", [
        "ipv4.method",
        "manual",
        "ipv4.addresses",
        iface.with_prefixlen,
        "ipv4.gateway",
        gateway,
        "ipv4.dns",
        ",".join(servers),
    ]


def fixed_from(settings, iface):
    """Switching from DHCP to a fixed address: start from the address, gateway and DNS servers in use now."""
    out = Ipv4Settings("manual", settings.address, settings.gateway, settings.dns)
    if not out.address and iface is not None and iface.addresses:
        out.address = iface.addresses[0]
    if not out.gateway and iface is not None:
        out.gateway = iface.gateway
    if not out.dns and iface is not None:
        out.dns = ", ".join(iface.dns)
    return out


def parse_networkctl(text):
    """`networkctl list --no-legend --no-pager` -> the links systemd-networkd has configured."""
    out = set()
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[4] in ("configured", "configuring"):
            out.add(parts[1])
    return out


def iwd_configures(conf_text):
    """iwd gives addresses itself ([General] EnableNetworkConfiguration=true in /etc/iwd/main.conf)."""
    section = ""
    for line in (conf_text or "").splitlines():
        t = line.strip()
        if t.startswith("["):
            section = t.strip("[]").strip()
            continue
        if section == "General" and "=" in t:
            key, value = (x.strip() for x in t.split("=", 1))
            if key == "EnableNetworkConfiguration":
                return value.lower() in ("true", "yes", "1")
    return False


def _active(unit):
    return run(["systemctl", "is-active", "--quiet", unit], timeout=5).ok


def who_sets(interfaces):
    """Fill in what gives each interface its address: systemd-networkd (when it has configured it), iwd's own network
    configuration (Wi-Fi), or dhcpcd."""
    networkd = (
        parse_networkctl(run(["networkctl", "list", "--no-legend", "--no-pager"], timeout=5).out)
        if have("networkctl") and _active("systemd-networkd.service")
        else set()
    )
    iwd_ip = _active("iwd.service") and iwd_configures(_read("/etc/iwd/main.conf"))
    dhcpcd = _active("dhcpcd.service") or any(_active(f"dhcpcd@{i.device}.service") for i in interfaces)
    for i in interfaces:
        i.set_by = (
            "networkd" if i.device in networkd else "iwd" if iwd_ip and i.kind == "wifi" else "dhcpcd" if dhcpcd else ""
        )
    return interfaces


# Where an address set by hand is changed, by what set it
HAND_SET = {
    "networkd": "in its .network file in /etc/systemd/network (DHCP=yes, or Address= and Gateway=), then run sudo networkctl reload",
    "dhcpcd": "in /etc/dhcpcd.conf (remove its static ip_address= lines for DHCP), then run sudo systemctl restart dhcpcd",
    "iwd": "in the [IPv4] section of the network's file in /var/lib/iwd (remove it for DHCP), then reconnect",
}


def hand_set_note(i):
    """The warning for an address set by hand, which Settings cannot change without NetworkManager."""
    where = HAND_SET.get(i.set_by, "with the tool that set it up (systemd-networkd, dhcpcd or iwd)")
    return (
        f"{i.device}'s IP address ({i.addresses[0].split('/')[0]}) is set by hand, not by DHCP. Settings cannot change it here: "
        f"change it from the command line, {where}."
    )


# ------------------------------------------------------------------ reading
def read_state(scan=False):
    if not have("nmcli") or not run(["nmcli", "-t", "-f", "RUNNING", "general"], timeout=5).out.strip() == "running":
        addr = run(["ip", "-j", "addr"], timeout=5)
        route = run(["ip", "-j", "route"], timeout=5)
        interfaces = who_sets(parse_ip_json(addr.out, route.out))
        if iwd.running():
            st = iwd.read_state(scan=scan)
            nets = [
                WifiNetwork(
                    n.ssid, n.signal, iwd.SECURITY.get(n.kind, n.kind), n.connected, n.known or st.known.get(n.ssid, "")
                )
                for n in st.networks
            ]
            why = st.problem or (
                "iwd runs Wi-Fi here: networks can be joined and forgotten (saving a new password asks for yours). Ethernet and IP "
                "addresses are only shown (Settings changes those through NetworkManager)."
            )
            station = next((d for d in st.devices if d.station and d.powered), None)
            return NetState(
                False,
                why,
                interfaces,
                any(d.powered for d in st.devices),
                nets,
                iwd=True,
                iwd_station=station.path if station else "",
                iwd_devices=[d.name for d in st.devices],
                iwd_device=station.name if station else "",
            )
        why = (
            "NetworkManager is not running, so these settings can only be shown here. Start NetworkManager to change them."
            if have("nmcli")
            else "Changing these settings needs NetworkManager (nmcli). Without it they can only be shown here."
        )
        if (
            distro.is_arch()
        ):  # Arch starts no network manager by itself: the installer picks systemd-networkd, iwd or NetworkManager
            why += (
                " On Arch: install networkmanager, turn off what runs the network now (systemd-networkd and iwd, or dhcpcd), then "
                "turn on NetworkManager: sudo systemctl disable --now systemd-networkd iwd; sudo systemctl enable --now NetworkManager"
            )
        return NetState(False, why, interfaces)
    interfaces = parse_device_list(run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=8).out)
    connections = parse_connections(
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"], timeout=8).out
    )
    for iface in interfaces:
        parse_device_show(
            run(
                ["nmcli", "-t", "-f", "GENERAL.HWADDR,GENERAL.STATE,IP4", "device", "show", iface.device], timeout=8
            ).out,
            iface,
        )
        iface.connection_uuid = next((u for _n, u, _t, d in connections if d == iface.device), "")
        if iface.connection_uuid:
            method = run(
                ["nmcli", "-g", "ipv4.method", "connection", "show", iface.connection_uuid], timeout=5
            ).out.strip()
            iface.method = "manual" if method == "manual" else "auto"
    wifi_on = run(["nmcli", "-t", "radio", "wifi"], timeout=5).out.strip() == "enabled"
    networks = []
    if wifi_on and any(i.kind == "wifi" for i in interfaces):
        # only a search asks the adapter to scan; otherwise this lists what NetworkManager already knows
        listing = run(
            [
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes" if scan else "no",
            ],
            timeout=30,
        )
        networks = parse_wifi_list(listing.out)
        saved = saved_wifi(connections)
        for n in networks:
            n.saved_uuid = saved.get(n.ssid, "")
    return NetState(True, "", interfaces, wifi_on, networks)


def read_details():
    """read_state() for the Quick Menu's network panel: what is connected, the connection in use first."""
    state = read_state(scan=False)
    state.interfaces = with_unmanaged(
        state.interfaces, run(["ip", "-j", "addr"], timeout=5).out, run(["ip", "-j", "route"], timeout=5).out
    )
    return state


def saved_wifi(connections):
    """{ssid: uuid} of the saved Wi-Fi connections (a connection's name is not always its network's name)."""
    found = {}
    for name, uuid, kind, _dev in connections:
        if kind not in ("802-11-wireless", "wifi"):
            continue
        ssid = run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", uuid], timeout=5).out.strip() or name
        found.setdefault(ssid, uuid)
    return found


def read_ipv4(uuid):
    return parse_ipv4(
        run(
            ["nmcli", "-t", "-f", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns", "connection", "show", uuid],
            timeout=8,
        ).out
    )


# ------------------------------------------------------------------ changing (each -> "" on success, else why not)
def _outcome(result):
    if result.ok:
        return ""
    m = re.search(r"Error: (.*)", result.err or result.out)
    reason = m.group(1).strip() if m else result.message
    if "Secrets were required" in reason or "802-1x" in reason:
        return "The password was not accepted."
    if "Not authorized" in reason or "not authorized" in reason:
        return "NetworkManager did not allow this user to change that (polkit)."
    return reason


def set_wifi(on):
    return _outcome(run(["nmcli", "radio", "wifi", "on" if on else "off"], timeout=10))


def connect_device(device):
    return _outcome(run(["nmcli", "device", "connect", device], timeout=45))


def disconnect_device(device):
    return _outcome(run(["nmcli", "device", "disconnect", device], timeout=20))


def activate(uuid):
    problem = _outcome(run(["nmcli", "connection", "up", uuid], timeout=45))
    if not problem:
        keep_wired_first()
    return problem


def forget(uuid):
    return _outcome(run(["nmcli", "connection", "delete", uuid], timeout=15))


def join_wifi(ssid, password=None):
    """Join a network not saved yet. A failed attempt leaves no half-made connection behind to fail again next time.
    The password is passed as an argument, as `nmcli device wifi connect` documents."""
    before = {
        u
        for _n, u, _t, _d in parse_connections(
            run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"], timeout=8).out
        )
    }
    argv = ["nmcli", "device", "wifi", "connect", ssid] + (["password", password] if password else [])
    problem = _outcome(run(argv, timeout=60))
    if problem:
        for _n, u, _t, _d in parse_connections(
            run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"], timeout=8).out
        ):
            if u not in before:
                run(["nmcli", "connection", "delete", u], timeout=15)
    else:
        keep_wired_first()
    return problem


def _wireless(name):
    return os.path.isdir(f"/sys/class/net/{name}/wireless")


def wifi_metric(route_json, wifi_device, wireless=_wireless):
    """The route metric that keeps a wired connection first when Wi-Fi joins the same computer, or None when nothing
    needs changing. NetworkManager gives Wi-Fi metric 600, but a wired connection it does not manage (ifupdown on
    Debian, metric 1002 for a second one…) can have a higher one, and then Wi-Fi quietly takes over all traffic."""
    try:
        routes = json.loads(route_json or "[]")
    except ValueError:
        return None
    defaults = [r for r in routes if r.get("dst") == "default" and r.get("dev")]
    wired = [r.get("metric", 0) for r in defaults if not wireless(r["dev"])]
    wifi = [r.get("metric", 0) for r in defaults if r["dev"] == wifi_device]
    if not wired or not wifi or min(wifi) > min(wired):
        return None
    return min(wired) + 100


def keep_wired_first():
    """After Wi-Fi connects: if its default route beats a wired one, raise the Wi-Fi connection's route metric so
    the wired connection stays in use (Wi-Fi remains as a backup) and re-apply it without dropping the connection."""
    for _name, uuid, kind, device in parse_connections(
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"], timeout=8).out
    ):
        if "wireless" not in kind or not device:
            continue
        metric = wifi_metric(run(["ip", "-j", "route", "show", "default"], timeout=5).out, device)
        if metric is None:
            continue
        if run(
            ["nmcli", "connection", "modify", uuid, "ipv4.route-metric", str(metric), "ipv6.route-metric", str(metric)],
            timeout=15,
        ).ok:
            run(["nmcli", "device", "reapply", device], timeout=15)


def apply_ipv4(uuid, settings):
    """Save the IPv4 settings on a connection and re-activate it so they take effect."""
    problem, args = validate_ipv4(settings)
    if problem:
        return problem
    problem = _outcome(run(["nmcli", "connection", "modify", uuid, *args], timeout=15))
    return problem or activate(uuid)


# ------------------------------------------------------------------ ports ifupdown has, which NetworkManager leaves alone
# A minimal Debian install (and any install over Wi-Fi) sets up its network port in /etc/network/interfaces, run by
# ifupdown. NetworkManager's ifupdown plugin, with Debian's default "managed=false", then leaves that port unmanaged,
# so Settings could only show it. Handing the network to NetworkManager uninstalls ifupdown and removes /etc/network,
# then restarts NetworkManager, which manages every port from then on: Ethernet connects again with DHCP, and the
# Wi-Fi network is chosen again here (a fixed address set in the installer has to be set again too).
INTERFACES = "/etc/network/interfaces"
NM_CONF = "/etc/NetworkManager/NetworkManager.conf"


def ifupdown_ignored(conf_text):
    """NetworkManager.conf says to leave interfaces in /etc/network/interfaces alone ([ifupdown] managed=false, Debian's default)."""
    section = None
    managed = None
    plugin = False
    for line in conf_text.splitlines():
        t = line.strip()
        if t.startswith("["):
            section = t.strip("[]").strip().lower()
            continue
        if "=" not in t or t.startswith("#"):
            continue
        key, value = (x.strip().lower() for x in t.split("=", 1))
        if section == "main" and key == "plugins":
            plugin = "ifupdown" in value
        if section == "ifupdown" and key == "managed":
            managed = value in ("true", "1", "yes")
    return plugin and managed is not True


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ------------------------------------------------------------------ ports netplan gives to systemd-networkd (Ubuntu)
# Ubuntu Server (and an Ubuntu cloud image) describes its network in /etc/netplan, and netplan hands it to
# systemd-networkd, telling NetworkManager to leave those ports alone. Handing the network to NetworkManager sets
# netplan's renderer to NetworkManager (one more file in /etc/netplan; the others are kept, backed up first) and
# applies it: netplan turns every port and Wi-Fi network it describes into a NetworkManager connection, so saved
# Wi-Fi networks and fixed addresses are kept. Ubuntu Desktop already uses NetworkManager.
NETWORKD_RUN = "/run/systemd/network"
NETPLAN_NM_FILE = "/etc/netplan/90-tvwcs-network-manager.yaml"


def netplan_networkd(folder=None):
    """netplan hands at least one port to systemd-networkd (it wrote a 10-netplan-*.network file for it)."""
    try:
        return any(n.startswith("10-netplan-") and n.endswith(".network") for n in os.listdir(folder or NETWORKD_RUN))
    except OSError:
        return False


def unmanaged_reason(device):
    """Why NetworkManager leaves `device` alone: "ifupdown" (ifupdown is installed, with /etc/network/interfaces, and
    NetworkManager is set to leave what it lists alone; the installer makes that file readable by root only when it
    holds a Wi-Fi password, so it is not read here), "netplan" (netplan gives it to systemd-networkd), or "config"
    (another setting; Settings can still ask NetworkManager to manage it)."""
    if (
        os.path.exists(INTERFACES)
        and (have("ifup") or os.path.exists("/sbin/ifup"))
        and ifupdown_ignored(_read(NM_CONF))
    ):
        return "ifupdown"
    if have("netplan") and netplan_networkd():
        return "netplan"
    return "config"


# Run as root. The ports ifupdown has up are taken down first, so no DHCP client or wpa_supplicant of its own is
# left running beside NetworkManager's.
DROP_IFUPDOWN_SCRIPT = r"""set -u
devs=""
if command -v ifquery >/dev/null 2>&1; then devs=$(ifquery --state 2>/dev/null | cut -d= -f1 | grep -vx lo); fi
for d in $devs; do ifdown --force "$d" 2>/dev/null || true; done
if dpkg-query -W -f='${Status}' ifupdown 2>/dev/null | grep -q installed; then
  if ! DEBIAN_FRONTEND=noninteractive apt-get purge -y ifupdown; then
    for d in $devs; do ifup "$d" 2>/dev/null || true; done   # back as it was, so the computer stays online
    exit 1
  fi
fi
rm -rf /etc/network
for d in $devs; do ip addr flush dev "$d" 2>/dev/null || true; done
systemctl restart NetworkManager
for i in 1 2 3 4 5 6 7 8 9 10; do nmcli -t general >/dev/null 2>&1 && break; sleep 1; done
for d in $devs "$@"; do nmcli device set "$d" managed yes 2>/dev/null || true; done
echo "NetworkManager manages the network now."
"""
SET_MANAGED_SCRIPT = r"""set -u
nmcli device set "$1" managed yes
sleep 1
nmcli device connect "$1" || true
"""

# Run as root. On a failure the old files are put back and applied again, so the computer stays online. systemd-networkd
# is turned off afterwards when nothing is left for it: otherwise start-up waits up to two minutes for it
# (systemd-networkd-wait-online). It is masked, not only disabled: its other sockets (resolve-hook, varlink) and D-Bus
# start it again within a second, and it would then take every port with DHCP through the catch-all
# zzzz-dracut-default.network that dracut leaves in /run, beside NetworkManager.
NETPLAN_SCRIPT = r"""set -u
backup=/var/backups/tvwcs-netplan-$(date +%Y%m%d-%H%M%S)
mkdir -p "$backup" && cp -a /etc/netplan/. "$backup"/ || exit 1
undo() { echo "Putting the old network settings back."; rm -f /etc/netplan/*.yaml; cp -a "$backup"/. /etc/netplan/; netplan apply; exit 1; }
for f in /etc/netplan/*.yaml; do [ -f "$f" ] && sed -i '/^[[:space:]]*renderer:[[:space:]]*networkd[[:space:]]*$/d' "$f"; done
printf '# Added by TVWCS Settings > Network: NetworkManager manages the network.\nnetwork:\n  version: 2\n  renderer: NetworkManager\n' > @FILE@
chmod 600 /etc/netplan/*.yaml
netplan generate || undo
systemctl enable NetworkManager.service >/dev/null 2>&1 || true
netplan apply || undo
for i in 1 2 3 4 5 6 7 8 9 10; do nmcli -t general >/dev/null 2>&1 && break; sleep 1; done
if ! ls /run/systemd/network/10-netplan-*.network >/dev/null 2>&1; then
  rm -f /run/systemd/network/zzzz-dracut-default.network
  systemctl disable --now systemd-networkd-wait-online.service systemd-networkd.socket systemd-networkd-resolve-hook.socket \
    systemd-networkd-varlink.socket >/dev/null 2>&1 || true
  systemctl mask --now systemd-networkd.service >/dev/null 2>&1 || true
fi
echo "NetworkManager manages the network now. The old settings are in $backup."
""".replace("@FILE@", NETPLAN_NM_FILE)


def take_over_argv(device, reason):
    """The root command that hands `device` to NetworkManager: with "ifupdown", ifupdown is uninstalled and
    /etc/network removed (every port goes to NetworkManager); with "netplan", netplan's renderer becomes
    NetworkManager (every port it describes goes to it); otherwise NetworkManager is only asked to manage it."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", device):
        raise ValueError("Unexpected device name.")
    script = {"ifupdown": DROP_IFUPDOWN_SCRIPT, "netplan": NETPLAN_SCRIPT}.get(reason, SET_MANAGED_SCRIPT)
    return ["sh", "-c", script, "sh", device]
