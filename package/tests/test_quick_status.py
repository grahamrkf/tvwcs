"""The Quick Menu's clock and status icons, the Date and time page's backend, and TV mode's bar hiding, from saved
samples (no display, no timedatectl, no sway needed)."""

import os, tempfile, time, unittest
from pathlib import Path

from tvwcs.settings import date_time as dt
from tvwcs.system import quick_status as qs, tv_mode

ROUTE = """Iface	Destination	Gateway 	Flags	RefCnt	Use	Metric	Mask		MTU	Window	IRTT
wlp2s0	00000000	0101A8C0	0003	0	0	2000	00000000	0	0	0
enp1s0	00000000	0101A8C0	0003	0	0	100	00000000	0	0	0
enp1s0	0001A8C0	00000000	0001	0	0	100	00FFFFFF	0	0	0
"""
WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlp2s0: 0000   49.  -61.  -256        0      0      0      0     12        0
"""
SHOW = """timezone=x
Timezone=America/New_York
LocalRTC=no
CanNTP=yes
NTP=yes
NTPSynchronized=no
"""


class NetworkTests(unittest.TestCase):
    def test_the_default_route_with_the_lowest_metric_wins(self):
        self.assertEqual(qs.default_interface(ROUTE), "enp1s0")
        self.assertEqual(qs.default_interface(ROUTE.splitlines()[0]), "")

    def test_wired_wifi_and_offline(self):
        self.assertEqual(qs.read_network(ROUTE, WIRELESS, lambda i: i.startswith("wl")), ("wired", 0))
        wifi_only = "\n".join(ROUTE.splitlines()[:2])
        self.assertEqual(qs.read_network(wifi_only, WIRELESS, lambda i: i.startswith("wl")), ("wifi", 70))
        self.assertEqual(qs.read_network("", WIRELESS, lambda i: True), ("offline", 0))

    def test_icons(self):
        self.assertEqual(qs.network_icon(qs.Status("wifi", 70))[0], "network-wireless-signal-good-symbolic")
        self.assertEqual(qs.updates_icon(qs.Status(updates=3))[2], "3 updates available")
        self.assertFalse(qs.updates_shown(qs.Status()))
        self.assertEqual(
            qs.updates_icon(qs.Status(reboot=True))[::2], ("system-reboot-symbolic", "Restart to finish updating")
        )
        self.assertEqual(
            qs.updates_icon(qs.Status(updates=1, reboot=True))[2], "Restart to finish updating (1 update available)"
        )
        self.assertTrue(qs.updates_shown(qs.Status(reboot=True)))
        self.assertEqual(qs.network_icon(qs.Status("wifi", 100))[0], "network-wireless-signal-excellent-symbolic")
        self.assertEqual(qs.network_icon(qs.Status("wifi", 5))[0], "network-wireless-signal-none-symbolic")
        self.assertIn("70%", qs.network_icon(qs.Status("wifi", 70))[2])
        self.assertEqual(qs.network_icon(qs.Status())[0], "network-offline-symbolic")


class VolumeAndBluetoothTests(unittest.TestCase):
    def test_volume(self):
        out = (
            "Volume: front-left: 72089 / 110% / 2.48 dB,   front-right: 72089 / 110% / 2.48 dB\n        balance 0.00\n"
        )
        self.assertEqual(qs.parse_volume(out, "Mute: no\n"), (110, False))
        self.assertEqual(qs.parse_volume(out, "Mute: yes\n"), (110, True))
        self.assertEqual(qs.volume_icon(qs.Status(volume=110))[0], "audio-volume-high-symbolic")
        self.assertEqual(qs.volume_icon(qs.Status(volume=20))[0], "audio-volume-low-symbolic")
        self.assertEqual(qs.volume_icon(qs.Status(volume=50, muted=True))[0], "audio-volume-muted-symbolic")

    def test_bluetooth(self):
        show = "Controller AA:BB:CC:DD:EE:FF (public)\n\tName: htpc\n\tPowered: yes\n"
        self.assertEqual(qs.parse_bluetooth(show, ""), "on")
        self.assertEqual(qs.parse_bluetooth(show, "Device 11:22:33:44:55:66 Pad\n"), "connected")
        self.assertEqual(qs.parse_bluetooth(show.replace("yes", "no"), ""), "off")
        self.assertEqual(qs.parse_bluetooth("No default controller available\n", ""), "")


class BatteryTests(unittest.TestCase):
    def supply(self, files):
        root = tempfile.mkdtemp()
        for name, values in files.items():
            os.makedirs(os.path.join(root, name))
            for k, v in values.items():
                Path(root, name, k).write_text(v + "\n")
        return root

    def test_reads_the_charge_and_whether_it_charges(self):
        self.assertEqual(
            qs.read_battery(self.supply({"AC": {"type": "Mains", "online": "1"}})), (None, "")
        )  # a desktop: no icon
        self.assertEqual(
            qs.read_battery(
                self.supply(
                    {
                        "AC": {"type": "Mains", "online": "0"},
                        "BAT0": {"type": "Battery", "status": "Discharging", "capacity": "64"},
                    }
                )
            ),
            (64, "battery"),
        )
        self.assertEqual(
            qs.read_battery(
                self.supply(
                    {
                        "AC": {"type": "Mains", "online": "1"},
                        "BAT0": {"type": "Battery", "status": "Charging", "capacity": "41"},
                    }
                )
            ),
            (41, "charging"),
        )
        self.assertEqual(
            qs.read_battery(
                self.supply(
                    {
                        "AC": {"type": "Mains", "online": "1"},
                        "BAT0": {"type": "Battery", "status": "Full", "capacity": "100"},
                    }
                )
            ),
            (100, "plugged"),
        )

    def test_icons(self):
        self.assertEqual(
            qs.battery_icon(qs.Status(battery=64, power="battery"))[::2],
            ("battery-level-60-symbolic", "Battery 64%, on battery"),
        )
        self.assertEqual(
            qs.battery_icon(qs.Status(battery=41, power="charging"))[::2],
            ("battery-level-40-charging-symbolic", "Battery 41%, charging"),
        )
        self.assertEqual(
            qs.battery_icon(qs.Status(battery=100, power="plugged"))[0], "battery-level-100-charged-symbolic"
        )


class DateTimeTests(unittest.TestCase):
    def test_reads_timedatectl(self):
        self.assertEqual(dt.parse_show(SHOW), ("America/New_York", True, False, True))

    def test_zone_from_the_localtime_link(self):
        self.assertEqual(dt.zone_from_link("../usr/share/zoneinfo/Europe/Paris"), "Europe/Paris")
        self.assertEqual(dt.zone_from_link("/etc/foo"), "")

    def test_one_list_of_zones(self):
        zones = [
            "America/New_York",
            "America/Argentina/Buenos_Aires",
            "Europe/Paris",
            "UTC",
            "Etc/GMT+5",
            "Africa/Abidjan",
        ]
        self.assertEqual(
            dt.zone_choices(zones),
            [
                ("Africa/Abidjan", "Abidjan (Africa)"),
                ("America/Argentina/Buenos_Aires", "Buenos Aires, Argentina (America)"),
                ("America/New_York", "New York (America)"),
                ("Europe/Paris", "Paris (Europe)"),
                ("UTC", "UTC"),
            ],
        )
        self.assertEqual(dt.zone_label("America/New_York"), "New York (America)")
        self.assertEqual(dt.zone_label("UTC"), "UTC")
        self.assertEqual(dt.split_zone("Etc/UTC"), ("Other", "UTC"))

    def test_commands(self):
        self.assertEqual(dt.ntp_argv(True), ["timedatectl", "set-ntp", "true"])
        self.assertEqual(dt.timezone_argv("Europe/Paris"), ["timedatectl", "set-timezone", "Europe/Paris"])
        self.assertEqual(
            dt.timezone_argv("Europe/Paris", False),
            ["ln", "-sfn", "/usr/share/zoneinfo/Europe/Paris", "/etc/localtime"],
        )
        self.assertTrue(dt.valid_zone("Europe/Paris", ["Europe/Paris"]))
        self.assertFalse(dt.valid_zone("../etc/passwd", ["../etc/passwd"]))

    def test_zones_from_the_tree(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("Europe/Paris", "posix/Europe/Paris", "UTC"):
                p = Path(d) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"TZif2...")
            (Path(d) / "zone.tab").write_text("not a zone")
            self.assertEqual(dt.zones_from_tree(d), ["Europe/Paris", "UTC"])

    def test_clock(self):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        try:
            when = 1760533500  # 2025-10-15 13:05 UTC, a Wednesday
            self.assertEqual(dt.clock_text(when, True), "13:05")
            self.assertEqual(dt.clock_text(when, False), "1:05 PM")
            self.assertEqual(dt.clock_text(when - 13 * 3600, False), "12:05 AM")
            self.assertEqual(dt.date_text(when), "Wednesday, October 15")
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()


class FakeWM:
    def __init__(self, modes):
        self.modes = dict(modes)
        self.calls = []

    def bar_modes(self):
        return dict(self.modes)

    def set_bar_mode(self, bar_id, mode):
        self.calls.append((bar_id, mode))
        self.modes[bar_id] = mode
        return True


class TVModeTests(unittest.TestCase):
    def test_hides_the_bars_and_restores_their_modes(self):
        with tempfile.TemporaryDirectory() as d:
            saved = Path(d) / "bars.json"
            wm = FakeWM({"bar-0": "dock", "bar-1": "hide"})
            self.assertEqual(tv_mode.hide_bars(wm, saved), 2)
            self.assertEqual(wm.modes, {"bar-0": "invisible", "bar-1": "invisible"})
            self.assertEqual(tv_mode.hide_bars(wm, saved), 0)  # already hidden: nothing to do
            wm.modes["bar-0"] = "dock"  # sway reloaded its config
            tv_mode.hide_bars(wm, saved)
            self.assertEqual(wm.modes["bar-0"], "invisible")
            self.assertEqual(tv_mode.restore_bars(wm, saved), 2)
            self.assertEqual(wm.modes, {"bar-0": "dock", "bar-1": "hide"})
            self.assertFalse(saved.exists())
            self.assertEqual(tv_mode.restore_bars(wm, saved), 0)

    def test_a_bar_hidden_by_its_config_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            wm = FakeWM({"bar-0": "invisible"})
            self.assertEqual(tv_mode.hide_bars(wm, Path(d) / "b.json"), 0)
            self.assertEqual(wm.calls, [])

    def test_the_kept_open_menu_steps_aside_for_a_window_opened_elsewhere(self):
        self.assertTrue(tv_mode.should_step_aside(True, False, True, False))
        self.assertFalse(tv_mode.should_step_aside(True, True, True, False))  # the menu still has the focus
        self.assertFalse(tv_mode.should_step_aside(True, False, False, False))  # nothing opened
        self.assertFalse(tv_mode.should_step_aside(True, False, True, True))  # its own popover or dialog

    def test_when_the_menu_comes_back(self):
        self.assertTrue(tv_mode.should_show_menu(True, False, False, 100, 50))
        self.assertFalse(tv_mode.should_show_menu(True, False, False, 100, 150))  # an app was just launched
        self.assertFalse(tv_mode.should_show_menu(True, False, True, 100, 0))  # an app is open
        self.assertFalse(tv_mode.should_show_menu(True, True, False, 100, 0))  # already shown
        self.assertFalse(tv_mode.should_show_menu(False, False, False, 100, 0))  # the option is off


if __name__ == "__main__":
    unittest.main()
