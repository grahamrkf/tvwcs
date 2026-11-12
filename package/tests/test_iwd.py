"""control_iwd and the Network page without NetworkManager: iwd's networks from busctl's JSON, its files, and whether
DHCP gave an address."""

import json, os, tempfile, unittest
from unittest import mock

from tvwcs import control_iwd as iwd, control_network as net
from tvwcs.control_cmd import Result


def v(t, d):
    return {"type": t, "data": d}


DEV = "/net/connman/iwd/0/4"
HOME = f"{DEV}/486f6d65_psk"
CAFE = f"{DEV}/436166c3a9_open"
WORK = f"{DEV}/576f726b_8021x"
OBJECTS = {
    "type": "a{oa{sa{sv}}}",
    "data": [
        {
            "/net/connman/iwd": {"net.connman.iwd.Daemon": {}},
            "/net/connman/iwd/0": {"net.connman.iwd.Adapter": {"Powered": v("b", True)}},
            DEV: {
                "net.connman.iwd.Device": {
                    "Name": v("s", "wlan0"),
                    "Powered": v("b", True),
                    "Mode": v("s", "station"),
                    "Adapter": v("o", "/net/connman/iwd/0"),
                },
                "net.connman.iwd.Station": {
                    "State": v("s", "connected"),
                    "Scanning": v("b", False),
                    "ConnectedNetwork": v("o", HOME),
                },
            },
            HOME: {
                "net.connman.iwd.Network": {
                    "Name": v("s", "Home"),
                    "Connected": v("b", True),
                    "Device": v("o", DEV),
                    "Type": v("s", "psk"),
                    "KnownNetwork": v("o", "/net/connman/iwd/486f6d65_psk"),
                }
            },
            CAFE: {
                "net.connman.iwd.Network": {
                    "Name": v("s", "Café"),
                    "Connected": v("b", False),
                    "Device": v("o", DEV),
                    "Type": v("s", "open"),
                }
            },
            WORK: {
                "net.connman.iwd.Network": {
                    "Name": v("s", "Work"),
                    "Connected": v("b", False),
                    "Device": v("o", DEV),
                    "Type": v("s", "8021x"),
                }
            },
            "/net/connman/iwd/486f6d65_psk": {
                "net.connman.iwd.KnownNetwork": {"Name": v("s", "Home"), "Type": v("s", "psk")}
            },
            "/net/connman/iwd/4f6c64_psk": {
                "net.connman.iwd.KnownNetwork": {"Name": v("s", "Old"), "Type": v("s", "psk")}
            },
        }
    ],
}
ORDERED = {"type": "a(on)", "data": [[[CAFE, -4500], [HOME, -6000], [WORK, -9900]]]}


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.objects = iwd.parse_objects(json.dumps(OBJECTS))

    def test_devices(self):
        (d,) = iwd.devices(self.objects)
        self.assertEqual((d.name, d.powered, d.state, d.station), ("wlan0", True, "connected", True))

    def test_networks_connected_first(self):
        found = iwd.networks(self.objects, iwd.parse_ordered(json.dumps(ORDERED)))
        self.assertEqual(
            [(n.ssid, n.kind, n.signal, n.connected, bool(n.known)) for n in found],
            [("Home", "psk", 80, True, True), ("Café", "open", 100, False, False), ("Work", "8021x", 2, False, False)],
        )
        self.assertEqual(
            iwd.known_networks(self.objects),
            {"Home": "/net/connman/iwd/486f6d65_psk", "Old": "/net/connman/iwd/4f6c64_psk"},
        )

    def test_bad_output(self):
        self.assertEqual(iwd.parse_objects("not json"), {})
        self.assertEqual(iwd.parse_ordered(""), [])
        self.assertEqual(iwd.parse_ordered(json.dumps({"type": "a(on)", "data": [[]]})), [])

    def test_percent(self):
        self.assertEqual([iwd.percent(x) for x in (-3000, -5000, -7500, -10000, -12000)], [100, 100, 50, 0, 0])


class FileTests(unittest.TestCase):
    def test_storage_name(self):
        self.assertEqual(iwd.storage_name("My Home-5G_2"), "My Home-5G_2.psk")
        self.assertEqual(iwd.storage_name("Café", "open"), "=436166c3a9.open")
        self.assertEqual(iwd.storage_name("a.b"), "=612e62.psk")

    def test_psk_text(self):
        self.assertEqual(iwd.psk_text("pass word"), "[Security]\nPassphrase=pass word\n")
        self.assertEqual(iwd.psk_text("  back\\slash "), "[Security]\nPassphrase=\\s\\sback\\\\slash\\s\n")
        for bad in ("short", "x" * 64, "line\nbreak!"):
            with self.assertRaises(ValueError):
                iwd.psk_text(bad)

    def test_password_file_is_private(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": d}):
            path = iwd.password_file("correct horse")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(open(path).read(), "correct horse")
            with self.assertRaises(ValueError):
                iwd.password_file("short")

    def test_join_saves_then_connects_and_forgets_a_wrong_password(self):
        calls = []

        def fake(argv, timeout=15, **_k):
            calls.append(argv)
            if "GetManagedObjects" in argv:
                objs = json.loads(json.dumps(OBJECTS))
                objs["data"][0]["/net/connman/iwd/4e6577_psk"] = {
                    "net.connman.iwd.KnownNetwork": {"Name": v("s", "New"), "Type": v("s", "psk")}
                }
                objs["data"][0][f"{DEV}/4e6577_psk"] = {
                    "net.connman.iwd.Network": {"Name": v("s", "New"), "Type": v("s", "psk"), "Device": v("o", DEV)}
                }
                return Result(True, 0, json.dumps(objs), "")
            if "Connect" in argv:
                return Result(False, 1, "", "Call failed: net.connman.iwd.Failed: Operation failed")
            return Result(True, 0, "", "")

        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(iwd, "STORAGE", d),
            mock.patch.object(iwd, "run", fake),
            mock.patch.object(iwd.time, "sleep", lambda _s: None),
        ):
            secret = os.path.join(d, "secret")
            open(secret, "w").write("wrong password")
            self.assertEqual(iwd.join("New", secret), "It could not connect. Check the password.")
            self.assertFalse(os.path.exists(secret))
            self.assertEqual(os.listdir(d), [])  # neither the secret nor New.psk is left
            self.assertIn(
                [
                    "busctl",
                    "--system",
                    "--timeout=10",
                    "call",
                    "net.connman.iwd",
                    "/net/connman/iwd/4e6577_psk",
                    "net.connman.iwd.KnownNetwork",
                    "Forget",
                ],
                calls,
            )
            self.assertTrue(any(a[-1] == "Connect" and a[-3] == f"{DEV}/4e6577_psk" for a in calls))

    def test_busctl_messages_in_words(self):
        self.assertEqual(iwd.explain("Call failed: Operation failed"), "It could not connect. Check the password.")
        self.assertEqual(iwd.explain("Call failed: No Agent registered"), "The network needs a password.")
        self.assertEqual(iwd.explain("Call failed: Access denied"), iwd.DENIED)
        self.assertEqual(iwd.explain("Call failed: Something new"), "Something new")

    def test_a_password_iwd_has_not_loaded_yet_is_tried_again(self):
        connects = []

        def fake(argv, timeout=15, **_k):
            if "GetManagedObjects" in argv:
                objs = json.loads(json.dumps(OBJECTS))
                if connects or os.path.exists(os.path.join(d, "New.psk")):
                    objs["data"][0]["/net/connman/iwd/4e6577_psk"] = {
                        "net.connman.iwd.KnownNetwork": {"Name": v("s", "New"), "Type": v("s", "psk")}
                    }
                objs["data"][0][f"{DEV}/4e6577_psk"] = {
                    "net.connman.iwd.Network": {"Name": v("s", "New"), "Type": v("s", "psk"), "Device": v("o", DEV)}
                }
                return Result(True, 0, json.dumps(objs), "")
            if argv[-1] == "Connect":
                connects.append(1)
                return Result(len(connects) > 1, 1, "", "" if len(connects) > 1 else "Call failed: No Agent registered")
            return Result(True, 0, "", "")

        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(iwd, "STORAGE", d),
            mock.patch.object(iwd, "run", fake),
            mock.patch.object(iwd.time, "sleep", lambda _s: None),
        ):
            secret = os.path.join(d, "secret")
            open(secret, "w").write("right password")
            self.assertEqual(iwd.join("New", secret), "")
            self.assertEqual(len(connects), 2)
            self.assertEqual(open(os.path.join(d, "New.psk")).read(), "[Security]\nPassphrase=right password\n")

    def test_root_argv_and_usage(self):
        argv = iwd.root_argv("forget", "Home")
        self.assertEqual(argv[-4:], ["-m", "tvwcs.control_iwd", "forget", "Home"])
        self.assertEqual(iwd.main([]), 2)
        self.assertEqual(iwd.main(["join"]), 2)
        self.assertEqual(iwd.disconnect("/etc/passwd"), "Unexpected device.")


class AddressTests(unittest.TestCase):
    ADDR = [
        {
            "ifname": "enp1s0",
            "link_type": "ether",
            "flags": ["UP", "LOWER_UP"],
            "address": "52:54:00:12:34:56",
            "addr_info": [
                {"family": "inet", "local": "192.168.1.20", "prefixlen": 24, "dynamic": True, "valid_life_time": 3500}
            ],
        },
        {
            "ifname": "wlan0",
            "link_type": "ether",
            "flags": ["UP", "LOWER_UP"],
            "address": "52:54:00:ab:cd:ef",
            "addr_info": [{"family": "inet", "local": "10.0.0.5", "prefixlen": 24, "valid_life_time": 4294967295}],
        },
    ]

    def test_dhcp_or_by_hand(self):
        found = net.parse_ip_json(json.dumps(self.ADDR), "[]", physical=lambda _n: True)
        self.assertEqual([(i.device, i.dynamic) for i in found], [("enp1s0", True), ("wlan0", False)])

    def test_who_sets_and_the_warning(self):
        self.assertEqual(
            net.parse_networkctl("  2 enp1s0 ether routable configured\n  3 wlan0 wlan routable unmanaged\n"),
            {"enp1s0"},
        )
        self.assertTrue(net.iwd_configures("[General]\nEnableNetworkConfiguration=true\n"))
        self.assertFalse(net.iwd_configures("[Network]\nEnableNetworkConfiguration=true\n"))
        i = net.Interface("wlan0", "wifi", "connected", addresses=["10.0.0.5/24"], set_by="iwd")
        self.assertIn("10.0.0.5", net.hand_set_note(i))
        self.assertIn("/var/lib/iwd", net.hand_set_note(i))
        i.set_by = "networkd"
        self.assertIn("networkctl reload", net.hand_set_note(i))
        i.set_by = ""
        self.assertIn("command line", net.hand_set_note(i))


class ReadStateTests(unittest.TestCase):
    def test_without_networkmanager_iwd_runs_wifi(self):
        def fake(argv, timeout=15, **_k):
            if argv[:2] == ["ip", "-j"]:
                return Result(True, 0, json.dumps(AddressTests.ADDR) if argv[2] == "addr" else "[]", "")
            if "GetManagedObjects" in argv:
                return Result(True, 0, json.dumps(OBJECTS), "")
            if "GetOrderedNetworks" in argv:
                return Result(True, 0, json.dumps(ORDERED), "")
            if argv[:2] == ["systemctl", "is-active"]:
                return Result(argv[-1] == "iwd.service", 0, "", "")
            return Result(False, 1, "", "")

        have = lambda n: n in ("busctl", "ip", "systemctl")
        with (
            mock.patch.object(net, "run", fake),
            mock.patch.object(iwd, "run", fake),
            mock.patch.object(net, "have", have),
            mock.patch.object(iwd, "have", have),
            mock.patch.object(net, "_physical", lambda _n: True),
            mock.patch.object(net, "_read", lambda _p: ""),
        ):
            s = net.read_state()
        self.assertTrue(s.iwd)
        self.assertFalse(s.managed)
        self.assertEqual(s.iwd_station, DEV)
        self.assertTrue(s.wifi_enabled)
        self.assertEqual(
            [(n.ssid, n.security, n.in_use, bool(n.saved_uuid), n.secured) for n in s.networks],
            [
                ("Home", "WPA", True, True, True),
                ("Café", "", False, False, False),
                ("Work", "802.1X", False, False, True),
            ],
        )

    def test_access_denied(self):
        with mock.patch.object(iwd, "run", lambda *_a, **_k: Result(False, 1, "", "Call failed: Access denied")):
            self.assertIn("wheel", iwd.read_state().problem)


if __name__ == "__main__":
    unittest.main()
