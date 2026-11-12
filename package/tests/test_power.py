"""Power and sleep without a display: the idle times, what is due when, swayidle's command, and reading logind, pactl
and systemd-inhibit from saved samples."""

import os, tempfile, unittest

from tvwcs.system import power

from unittest import mock as _mock
from tvwcs.system import servermode as _servermode

# These tests are about a computer without server mode, whatever the one running them has in /etc/tvwcs/server-mode.
_not_server = _mock.patch.object(_servermode, "server_user", lambda: "")


def setUpModule():
    _not_server.start()


def tearDownModule():
    _not_server.stop()


class PowerTests(unittest.TestCase):
    def test_idle_option_is_cleaned(self):
        self.assertEqual(power.clean_idle(None), {"screen_off": 0, "lock": 0, "sleep": 0})
        self.assertEqual(
            power.clean_idle({"screen_off": None, "lock": 300, "sleep": "x", "screensaver": 60}),
            {"screen_off": 0, "lock": 300, "sleep": 0},
        )
        self.assertEqual(power.clean_idle({"lock": True, "sleep": -5})["lock"], 0)

    def test_what_is_due_runs_once_per_idle_period_in_time_order(self):
        times = {"screen_off": 600, "lock": 300, "sleep": 1800}
        self.assertEqual(power.due(times, 299, set()), [])
        self.assertEqual(power.due(times, 700, set()), ["lock", "screen_off"])
        self.assertEqual(power.due(times, 700, {"lock"}), ["screen_off"])
        self.assertEqual(power.due({"screen_off": 0, "lock": 0, "sleep": 60}, 120, set()), ["sleep"])

    def test_durations(self):
        self.assertEqual(
            [power.duration_text(v) for v in (0, 60, 300, 3600, 5400, 7200)],
            ["Never", "1 minute", "5 minutes", "1 hour", "90 minutes", "2 hours"],
        )

    def test_logind(self):
        l = power.parse_logind(
            {"IdleAction": 's "suspend"', "IdleActionUSec": "t 1800000000", "HandleLidSwitch": 's "suspend"'}
        )
        self.assertEqual((l.available, l.idle_action, l.idle_seconds, l.lid), (True, "suspend", 1800, "suspend"))
        self.assertFalse(power.parse_logind({}).available)

    def test_lid_only_where_there_is_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, acpi = os.path.join(tmp, "lid"), os.path.join(tmp, "acpi")
            self.assertFalse(power.has_lid((proc, acpi)))  # neither folder
            os.makedirs(proc)
            os.makedirs(os.path.join(acpi, "PNP0C0A:00"))
            self.assertFalse(power.has_lid((proc, acpi)))  # a desktop: no lid button, a battery-less ACPI
            os.makedirs(os.path.join(acpi, "PNP0C0D:00"))
            self.assertTrue(power.has_lid((proc, acpi)))
            os.makedirs(os.path.join(proc, "LID0"))
            self.assertTrue(power.has_lid((proc, os.path.join(tmp, "none"))))

    def test_sound_and_inhibitors_keep_it_awake(self):
        self.assertTrue(power.parse_playing("Sink Input #12\n\tDriver: protocol-native.c\n\tCorked: no\n"))
        self.assertFalse(power.parse_playing("Sink Input #12\n\tCorked: yes\n"))
        text = (
            "firefox 1000 tv 2345 firefox idle Playing video block\n"
            "NetworkManager 0 root 800 NetworkManager sleep NetworkManager needs to turn off networks delay\n"
        )
        self.assertEqual(power.parse_inhibitors(text), ["firefox"])

    def test_swayidle_command(self):
        argv = power.swayidle_argv({"screen_off": 600, "lock": 0, "sleep": 1800}, "/opt/tv wcs/bin/tvwcs")
        self.assertEqual(
            argv,
            [
                "swayidle",
                "-w",
                "timeout",
                "600",
                "'/opt/tv wcs/bin/tvwcs' idle screen_off",
                "resume",
                "'/opt/tv wcs/bin/tvwcs' idle resume",
                "timeout",
                "1800",
                "'/opt/tv wcs/bin/tvwcs' idle sleep",
            ],
        )
        self.assertIsNone(power.swayidle_argv({"screen_off": 0, "lock": 0, "sleep": 0}, "tvwcs"))
        self.assertEqual(
            power.swayidle_argv({"screen_off": 0, "lock": 300, "sleep": 0}, "tvwcs"),
            ["swayidle", "-w", "timeout", "300", "'tvwcs' idle lock"],
        )


class BatteryTests(unittest.TestCase):
    def supply(self, files):
        root = tempfile.mkdtemp()
        for name, values in files.items():
            os.makedirs(os.path.join(root, name))
            for k, v in values.items():
                with open(os.path.join(root, name, k), "w") as f:
                    f.write(v + "\n")
        return root

    def test_no_battery(self):
        self.assertFalse(power.read_battery(self.supply({"AC": {"type": "Mains", "online": "1"}})).present)
        self.assertFalse(power.read_battery("/nonexistent").present)

    def test_laptop_on_battery_and_plugged_in(self):
        b = power.read_battery(
            self.supply(
                {
                    "AC": {"type": "Mains", "online": "0"},
                    "BAT0": {"type": "Battery", "status": "Discharging", "energy_now": "30", "energy_full": "60"},
                }
            )
        )
        self.assertEqual((b.present, b.percent, b.on_battery), (True, 50, True))
        b = power.read_battery(
            self.supply(
                {
                    "AC": {"type": "Mains", "online": "1"},
                    "BAT0": {"type": "Battery", "status": "Charging", "capacity": "77"},
                }
            )
        )
        self.assertEqual((b.present, b.percent, b.on_battery, b.charging), (True, 77, False, True))
        b = power.read_battery(
            self.supply(
                {
                    "AC": {"type": "Mains", "online": "1"},
                    "BAT0": {"type": "Battery", "status": "Full", "capacity": "100"},
                }
            )
        )
        self.assertEqual((b.on_battery, b.charging), (False, False))

    def test_time_left_and_time_to_full(self):
        bat = lambda **v: self.supply({"BAT0": {"type": "Battery", **v}})
        # 30 Wh left, drawing 10 W: 3 hours; 30 Wh to go at 20 W: an hour and a half
        self.assertEqual(
            power.battery_time(
                bat(status="Discharging", energy_now="30000000", energy_full="60000000", power_now="10000000")
            ),
            (10800, "empty"),
        )
        self.assertEqual(
            power.battery_time(
                bat(status="Charging", energy_now="30000000", energy_full="60000000", power_now="20000000")
            ),
            (5400, "full"),
        )
        self.assertEqual(
            power.battery_time(
                bat(status="Discharging", charge_now="2000000", charge_full="4000000", current_now="-1000000")
            ),
            (7200, "empty"),
        )
        self.assertEqual(
            power.battery_time(
                bat(status="Discharging", time_to_empty_now="600", energy_now="1", energy_full="2", power_now="1")
            ),
            (600, "empty"),
        )
        self.assertEqual(
            power.battery_time(bat(status="Discharging", energy_now="30", energy_full="60", power_now="0")),
            (None, "empty"),
        )  # no rate yet
        self.assertEqual(power.battery_time(bat(status="Full", capacity="100")), (None, ""))
        self.assertEqual(power.battery_time("/nonexistent"), (None, ""))
        self.assertEqual(
            [power.time_text(s) for s in (10800, 12000, 2700, 20)], ["3 h", "3 h 20 min", "45 min", "1 min"]
        )

    def test_a_mouse_battery_is_not_the_computers(self):
        self.assertFalse(
            power.read_battery(
                self.supply(
                    {
                        "hidpp_battery_0": {
                            "type": "Battery",
                            "scope": "Device",
                            "capacity": "20",
                            "status": "Discharging",
                        }
                    }
                )
            ).present
        )

    def test_times_and_critical_action(self):
        settings = {
            "idle": {"sleep": 0},
            "idle_battery": {"sleep": 600},
            "battery_critical": power.clean_critical(None),
        }
        low = power.Battery(True, 4, True)
        plugged = power.Battery(True, 4, False)
        self.assertEqual(power.active_idle(settings, low)["sleep"], 600)
        self.assertEqual(power.active_idle(settings, plugged)["sleep"], 0)
        self.assertEqual(power.critical(settings, low), "shutdown")
        self.assertEqual(power.critical(settings, plugged), "")
        self.assertEqual(power.critical(settings, power.Battery(True, 6, True)), "")
        settings["battery_critical"] = power.clean_critical({"action": "nothing", "percent": 90})
        self.assertEqual(power.critical(settings, low), "")
        self.assertEqual(
            power.clean_critical({"action": "explode", "percent": 0}), {"action": "shutdown", "percent": 5}
        )


if __name__ == "__main__":
    unittest.main()
