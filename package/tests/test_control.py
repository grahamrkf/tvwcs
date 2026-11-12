"""The Settings app's readers: the output of pactl, bluetoothctl, nmcli, ip, the package managers and /proc, parsed
from saved samples. No display, sound server, adapter or network needed."""

import os, tempfile, unittest
from unittest import mock
from pathlib import Path

from tvwcs import (
    control_bluetooth as bt,
    control_network as net,
    control_sound as sound,
    control_sysinfo as info,
    control_updates as upd,
)
from tvwcs.control_cmd import Result, key_values, split_terse


class SessionTypeTests(unittest.TestCase):
    def test_startx_from_a_console_is_x11(self):
        self.assertEqual(info.session_type({"XDG_SESSION_TYPE": "tty", "DISPLAY": ":0"}), "X11")
        self.assertEqual(
            info.session_type({"XDG_SESSION_TYPE": "tty", "WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"}), "Wayland"
        )
        self.assertEqual(info.session_type({"XDG_SESSION_TYPE": "tty"}), "tty")


SINKS = """Sink #52
\tState: RUNNING
\tName: alsa_output.pci-0000_00_1f.3.analog-stereo
\tDescription: Built-in Audio Analog Stereo
\tDriver: PipeWire
\tMute: no
\tVolume: front-left: 26214 /  40% / -23.88 dB,   front-right: 32768 /  50% / -18.06 dB
\t        balance 0.10
\tProperties:
\t\tdevice.icon_name = "audio-card-analog"
\tPorts:
\t\tanalog-output-speaker: Speakers (type: Speaker, priority: 10000, availability group: Legacy 1, availability unknown)
\t\tanalog-output-headphones: Headphones (type: Headphones, priority: 9900, availability group: Legacy 2, not available)
\tActive Port: analog-output-speaker
\tFormats:
\t\tpcm

Sink #60
\tName: alsa_output.pci-0000_01_00.1.hdmi-stereo
\tDescription: TU106 HDMI / DisplayPort
\tMute: yes
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
"""
SOURCES = """Source #53
\tName: alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
\tDescription: Monitor of Built-in Audio Analog Stereo
\tMute: no
\tVolume: front-left: 65536 / 100% / 0.00 dB
\tMonitor of Sink: alsa_output.pci-0000_00_1f.3.analog-stereo
Source #54
\tName: alsa_input.usb-Blue_Yeti-00.analog-stereo
\tDescription: Yeti Stereo Microphone
\tMute: no
\tVolume: front-left: 45875 /  70% / -9.29 dB,   front-right: 45875 /  70% / -9.29 dB
\tMonitor of Sink: n/a
\tProperties:
\t\tdevice.class = "sound"
"""


class CommandTests(unittest.TestCase):
    def test_split_terse_unescapes_colons_and_backslashes(self):
        self.assertEqual(split_terse(r"*:Home\:5G:78:WPA2"), ["*", "Home:5G", "78", "WPA2"])
        self.assertEqual(split_terse(r"GENERAL.HWADDR:AA\:BB\:CC", 1), ["GENERAL.HWADDR", "AA:BB:CC"])
        self.assertEqual(split_terse(r"a\\b:c"), ["a\\b", "c"])

    def test_key_values_and_message(self):
        self.assertEqual(key_values("\tName: tv\n\tPowered: yes\n")["Powered"], "yes")
        self.assertEqual(Result(False, 1, "", "first\nError: the reason\n").message, "Error: the reason")


CARDS = """Card #42
\tName: alsa_card.pci-0000_00_1f.3
\tDriver: alsa
\tProperties:
\t\tdevice.description = "Built-in Audio"
\tProfiles:
\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)
\t\toutput:analog-stereo: Analog Stereo Output (sinks: 1, sources: 0, priority: 6500, available: yes)
\t\toutput:analog-stereo+input:analog-stereo: Analog Stereo Duplex (sinks: 1, sources: 1, priority: 6565, available: yes)
\t\toutput:hdmi-stereo: Digital Stereo (HDMI) Output (sinks: 1, sources: 0, priority: 5900, available: yes)
\t\toutput:hdmi-stereo+input:analog-stereo: Digital Stereo (HDMI) Output + Analog Stereo Input (sinks: 1, sources: 1, priority: 5965, available: yes)
\t\toutput:hdmi-stereo-extra1: Digital Stereo (HDMI 2) Output (sinks: 1, sources: 0, priority: 5700, available: no)
\tActive Profile: output:analog-stereo+input:analog-stereo
\tPorts:
\t\thdmi-output-0: HDMI / DisplayPort (type: HDMI, priority: 5900, availability unknown)
Card #43
\tName: alsa_card.pci-0000_01_00.1
\tProperties:
\t\tdevice.description = "GA104 High Definition Audio Controller"
\tProfiles:
\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)
\t\toutput:hdmi-stereo: Digital Stereo (HDMI) Output (sinks: 1, sources: 0, priority: 5900, available: yes)
\tActive Profile: off
"""


class SoundTests(unittest.TestCase):
    def test_outputs_of_other_card_profiles_hdmi_first(self):
        cards = sound.parse_cards(CARDS)
        self.assertEqual(
            [(c.name, c.description, c.active) for c in cards],
            [
                ("alsa_card.pci-0000_00_1f.3", "Built-in Audio", "output:analog-stereo+input:analog-stereo"),
                ("alsa_card.pci-0000_01_00.1", "GA104 High Definition Audio Controller", "off"),
            ],
        )
        found = [(o.card_label, o.label, o.available, o.profile) for o in sound.other_outputs(cards)]
        self.assertEqual(
            found,
            [
                (
                    "Built-in Audio",
                    "Digital Stereo (HDMI) Output",
                    True,
                    "output:hdmi-stereo+input:analog-stereo",
                ),  # keeps the microphone
                (
                    "GA104 High Definition Audio Controller",
                    "Digital Stereo (HDMI) Output",
                    True,
                    "output:hdmi-stereo",
                ),  # a card that was off
                ("Built-in Audio", "Digital Stereo (HDMI 2) Output", False, "output:hdmi-stereo-extra1"),
            ],
        )
        self.assertEqual(
            sound.sink_for("alsa_card.pci-0000_00_1f.3", "output:hdmi-stereo"),
            "alsa_output.pci-0000_00_1f.3.hdmi-stereo",
        )

    def test_counts_the_kernels_sound_cards(self):
        with tempfile.NamedTemporaryFile("w", suffix="cards", delete=False) as f:
            f.write(
                " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n                      HDA Intel PCH at 0x6001120000 irq 147\n 1 [NVidia         ]: HDA-Intel - HDA NVidia\n"
            )
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(sound.count_alsa_cards(f.name), 2)
        self.assertEqual(sound.count_alsa_cards("/nonexistent"), -1)

    def test_outputs_with_ports_volume_and_mute(self):
        a, b = sound.parse_devices(SINKS, "sink")
        self.assertEqual(
            (a.index, a.label, a.volume, a.muted, a.active_port),
            (52, "Built-in Audio Analog Stereo", 45, False, "analog-output-speaker"),
        )
        self.assertEqual(
            [(p.name, p.label, p.available) for p in a.ports],
            [("analog-output-speaker", "Speakers", True), ("analog-output-headphones", "Headphones", False)],
        )
        self.assertEqual((b.muted, b.volume, b.ports), (True, 100, []))

    def test_devices_with_nothing_plugged_in_fold_away_unless_in_use(self):
        P = sound.Port
        speakers = sound.Device(
            "sink", 1, "speakers", "", 0, False, [P("spk", "Speakers"), P("hp", "Headphones", False)]
        )
        hdmi = sound.Device("sink", 2, "hdmi", "", 0, False, [P("hdmi", "HDMI", False)])
        virtual = sound.Device("sink", 3, "null", "", 0, False)  # no ports: nothing to say it is unplugged
        self.assertEqual([d.unplugged for d in (speakers, hdmi, virtual)], [False, True, False])
        self.assertEqual(sound.split_unplugged([speakers, hdmi, virtual], "speakers"), ([speakers, virtual], [hdmi]))
        self.assertEqual(sound.split_unplugged([speakers, hdmi], "hdmi"), ([speakers, hdmi], []))

    def test_inputs_leave_out_monitors(self):
        sources = sound.parse_devices(SOURCES, "source")
        self.assertEqual([s.is_monitor for s in sources], [True, False])
        self.assertEqual(sources[1].volume, 70)

    def test_info_and_server_name(self):
        sink, source, server = sound.parse_info(
            "Server Name: PulseAudio (on PipeWire 1.0.5)\nDefault Sink: hdmi\nDefault Source: mic\n"
        )
        self.assertEqual((sink, source, sound.server_label(server)), ("hdmi", "mic", "PipeWire 1.0.5"))
        self.assertEqual(sound.server_label("pulseaudio"), "PulseAudio")

    def test_volume_steps_land_on_multiples_and_stay_in_range(self):
        self.assertEqual([sound.stepped(v, 1) for v in (0, 47, 45, 98, 100)], [5, 50, 50, 100, 100])
        self.assertEqual([sound.stepped(v, -1) for v in (0, 3, 47, 45, 100)], [0, 0, 45, 40, 95])
        self.assertEqual(
            [sound.stepped(110, -1), sound.stepped(110, 1), sound.stepped(160, 1, boost=True)], [100, 100, 150]
        )  # above the top: down to it
        self.assertEqual(
            [sound.stepped(100, 1, boost=True), sound.stepped(150, 1, boost=True)], [105, 150]
        )  # over-amplification: up to 150 %
        self.assertEqual(sound.top(), 100)
        self.assertEqual(sound.top(True), 150)

    def test_volume_keys_stop_at_the_top(self):
        def press(volume, step, boost=False):
            calls = []

            def fake_run(cmd, timeout=None):
                calls.append(cmd)
                return Result(
                    True,
                    0,
                    (
                        f"Volume: front-left: 1 / {volume}% / -3 dB,   front-right: 1 / {volume}% / -3 dB\n"
                        if cmd[1] == "get-sink-volume"
                        else ""
                    ),
                    "",
                )

            shown = []
            with mock.patch.object(sound, "run", fake_run), mock.patch.object(sound, "_indicate", shown.append):
                sound.volume_key(step, boost)
            self.assertEqual(shown, [int(calls[-1][-1][:-1])])  # the indicator shows the volume just set
            return calls[-1][-1] if calls[-1][1] == "set-sink-volume" else None

        self.assertEqual(
            [press(95, 1), press(100, 1), press(100, 1, boost=True), press(150, 1, boost=True), press(100, -1)],
            ["100%", "100%", "105%", "150%", "95%"],
        )
        self.assertEqual(
            [press(120, 1), press(170, 1, boost=True)], ["100%", "150%"]
        )  # set louder elsewhere: back to the top
        self.assertEqual(sound.main(["volume", "sideways"]), 2)

    def test_the_mute_key_toggles_and_shows_the_indicator(self):
        calls = []
        shown = []

        def fake_run(cmd, timeout=None):
            calls.append(cmd)
            return Result(True, 0, "", "")

        with mock.patch.object(sound, "run", fake_run), mock.patch.object(sound, "_indicate", shown.append):
            self.assertEqual(sound.main(["volume", "mute"]), 0)
        self.assertEqual(calls, [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]])
        self.assertEqual(shown, [None])

    def test_the_indicator_reads_the_level_when_it_is_not_known(self):
        def fake_run(cmd, timeout=None):
            return Result(
                True, 0, "Volume: front-left: 1 / 35% / -3 dB\n" if cmd[1] == "get-sink-volume" else "Mute: yes\n", ""
            )

        with (
            mock.patch.object(sound, "run", fake_run),
            mock.patch("tvwcs.osd.can_show", return_value=True),
            mock.patch("tvwcs.osd.show") as show,
        ):
            sound._indicate(None)
        show.assert_called_once_with(35, True)
        with (
            mock.patch("tvwcs.osd.can_show", return_value=False),
            mock.patch.object(sound, "run") as run,
            mock.patch("tvwcs.osd.show") as show,
        ):
            sound._indicate(40)  # no graphical session (over SSH): pactl is not even asked
        run.assert_not_called()
        show.assert_not_called()

    def test_tvwcs_conf_binds_the_volume_keys(self):
        conf = (Path(__file__).resolve().parents[2] / "data" / "tvwcs.conf").read_text().splitlines()
        for flag in ("--locked ", ""):
            for key, word in (("Raise", "up"), ("Lower", "down")):
                self.assertIn(f"bindsym {flag}--no-warn XF86Audio{key}Volume exec /usr/bin/tvwcs volume {word}", conf)
            self.assertIn(f"bindsym {flag}--no-warn XF86AudioMute exec /usr/bin/tvwcs volume mute", conf)
        self.assertIn(
            'no_focus [app_id="^com\\.tvwcs\\.Osd$"]', conf
        )  # the indicator's fallback window never takes the keys

    def test_loud_outputs_are_brought_down_to_the_top(self):
        listing = (
            "Sink #1\n\tName: hdmi\n\tVolume: front-left: 1 / 100% / 0 dB,   front-right: 1 / 155% / 11 dB\n\t        balance 0.00\n"
            '\tBase Volume: 65536 / 100% / 0.00 dB\n\tProperties:\n\t\tdevice.description = "Volume: 900%"\n'
            "Sink #2\n\tName: analog\n\tVolume: mono: 1 / 120% / 4 dB\n"
        )
        self.assertEqual(sound.loud_outputs(listing, 100), ["hdmi", "analog"])
        self.assertEqual(sound.loud_outputs(listing, 150), ["hdmi"])
        calls = []

        def fake_run(cmd, timeout=None):
            calls.append(cmd)
            return Result(True, 0, listing if cmd[1] == "list" else "", "")

        with mock.patch.object(sound, "run", fake_run):
            self.assertEqual(sound.keep_under_top(boost=True), ["hdmi"])
        self.assertEqual(calls[-1], ["pactl", "set-sink-volume", "hdmi", "150%"])

    def test_volume_guard_checks_at_start_and_on_output_changes(self):
        class Proc:
            def __init__(self):
                self.stdout = iter(
                    [
                        "Event 'change' on sink-input #7\n",
                        "Event 'change' on sink #56\n",
                        "Event 'new' on sink #57\n",
                        "Event 'change' on source #3\n",
                    ]
                )

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        checks = []
        guard = None

        def popen(*a, **k):
            if len(checks) > 3:
                guard.stopping.set()
            return Proc()

        guard = sound.VolumeGuard(lambda: True, popen=popen, check=checks.append)
        guard.RETRY = 0
        with mock.patch.object(sound, "have", lambda name: True):
            guard.start()
            guard.thread.join(5)
        self.assertFalse(guard.thread.is_alive())
        self.assertEqual(
            checks[:3], [True, True, True]
        )  # at start, then the two output events (not a stream's, not an input's)

    def test_stream_indexes(self):
        self.assertEqual(sound.parse_short_streams("12\t52\t83\tPipeWire\ts16le\n15\t52\t90\n"), [12, 15])


BT_INFO = """Device 00:1B:66:AA:BB:CC (public)
\tName: MOMENTUM 4
\tAlias: Living room headphones
\tIcon: audio-headset
\tPaired: yes
\tTrusted: yes
\tConnected: yes
\tUUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)
\tBattery Percentage: 0x50 (80)
"""


class BluetoothTests(unittest.TestCase):
    def test_controller(self):
        text = "Controller 5C:F3:70:11:22:33 (public)\n\tName: tv\n\tPowered: no\n\tPowerState: off-blocked\n"
        self.assertEqual(bt.parse_show(text), ("5C:F3:70:11:22:33", False, True))
        self.assertEqual(bt.parse_show("No default controller available\n"), ("", False, False))

    def test_no_adapter_is_not_a_stopped_service(self):
        # bluetoothctl waits for a service that never starts without an adapter (ConditionPathIsDirectory=/sys/class/bluetooth)
        failed = Result(False, 1, "", "Waiting to connect to bluetoothd...")
        with mock.patch.object(bt, "have", lambda _n: True), mock.patch.object(bt, "run", lambda *_a, **_k: failed):
            for adapter, message in (
                (False, "No Bluetooth adapter was found."),
                (True, "The Bluetooth service is not answering"),
            ):
                with mock.patch.object(bt.os.path, "isdir", lambda _p, a=adapter: a):
                    self.assertTrue(bt.read_state().message.startswith(message))

    def test_device_list_skips_status_lines(self):
        text = "Agent registered\n[CHG] Controller 5C:F3:70:11:22:33 Discovering: yes\nDevice 00:1B:66:AA:BB:CC MOMENTUM 4\nDevice 4C:B9:9B:01:02:03 4C-B9-9B-01-02-03\n"
        self.assertEqual(
            bt.parse_devices(text), [("00:1B:66:AA:BB:CC", "MOMENTUM 4"), ("4C:B9:9B:01:02:03", "4C-B9-9B-01-02-03")]
        )

    def test_device_info(self):
        d = bt.parse_info("00:1B:66:AA:BB:CC", BT_INFO)
        self.assertEqual(
            (d.name, d.paired, d.trusted, d.connected, d.battery, d.kind[2]),
            ("Living room headphones", True, True, True, 80, "Headset"),
        )
        self.assertIsNone(bt.parse_info("00:1B:66:AA:BB:CC", "Device 00:1B:66:AA:BB:CC not available\n"))

    def test_failures_are_explained(self):
        self.assertEqual(bt.failure(Result(True, 0, "Attempting to pair with X\nPairing successful\n", "")), "")
        self.assertIn(
            "did not answer",
            bt.failure(Result(True, 0, "Failed to connect: org.bluez.Error.Failed br-connection-page-timeout\n", "")),
        )
        self.assertIn(
            "pairing mode", bt.failure(Result(False, 1, "Failed to pair: org.bluez.Error.AuthenticationFailed\n", ""))
        )
        self.assertIn(
            "no longer in range", bt.failure(Result(False, 1, "Device 00:1B:66:AA:BB:CC not available\n", ""))
        )


class NetworkTests(unittest.TestCase):
    def test_devices(self):
        text = "eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:disconnected:--\nlo:loopback:connected (externally):lo\np2p-dev-wlan0:wifi-p2p:disconnected:--\n"
        found = net.parse_device_list(text)
        self.assertEqual(
            [(i.device, i.kind, i.connection, i.connected) for i in found],
            [("eth0", "ethernet", "Wired connection 1", True), ("wlan0", "wifi", "", False)],
        )

    def test_device_details(self):
        text = (
            "GENERAL.HWADDR:AA\\:BB\\:CC\\:DD\\:EE\\:FF\nGENERAL.STATE:100 (connected)\nIP4.ADDRESS[1]:192.168.1.20/24\n"
            "IP4.GATEWAY:192.168.1.1\nIP4.ROUTE[1]:dst = 0.0.0.0/0, nh = 192.168.1.1, mt = 100\nIP4.DNS[1]:192.168.1.1\nIP4.DNS[2]:1.1.1.1\n"
        )
        i = net.parse_device_show(text, net.Interface("eth0", "ethernet"))
        self.assertEqual(
            (i.mac, i.state, i.addresses, i.gateway, i.dns),
            ("AA:BB:CC:DD:EE:FF", "connected", ["192.168.1.20/24"], "192.168.1.1", ["192.168.1.1", "1.1.1.1"]),
        )

    def test_wifi_list_merges_access_points_and_skips_hidden(self):
        text = "*:Home\\:5G:40:WPA2\n :Home\\:5G:78:WPA2\n :Cafe:90:\n :Office:65:WPA1 WPA2\n ::30:WPA2\n"
        nets = net.parse_wifi_list(text)
        self.assertEqual(
            [(n.ssid, n.signal, n.in_use, n.secured) for n in nets],
            [("Home:5G", 40, True, True), ("Cafe", 90, False, False), ("Office", 65, False, True)],
        )

    def test_ip_json_without_networkmanager(self):
        addr = (
            '[{"ifname":"lo","link_type":"loopback","flags":["UP","LOWER_UP"],"addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8}]},'
            '{"ifname":"enp3s0","link_type":"ether","address":"aa:bb:cc:dd:ee:ff","flags":["BROADCAST","UP","LOWER_UP"],'
            '"addr_info":[{"family":"inet","local":"10.0.0.5","prefixlen":24},{"family":"inet6","local":"fe80::1","prefixlen":64}]},'
            '{"ifname":"docker0","link_type":"ether","flags":["UP"],"addr_info":[]}]'
        )
        route = '[{"dst":"default","gateway":"10.0.0.1","dev":"enp3s0"},{"dst":"10.0.0.0/24","dev":"enp3s0"}]'
        found = net.parse_ip_json(addr, route, physical=lambda name: name == "enp3s0")
        self.assertEqual(
            [(i.device, i.state, i.addresses, i.gateway, i.mac) for i in found],
            [("enp3s0", "connected", ["10.0.0.5/24"], "10.0.0.1", "aa:bb:cc:dd:ee:ff")],
        )
        self.assertEqual(net.parse_ip_json("not json", ""), [])

    def test_unmanaged_wired_connection_shows_in_the_panel(self):
        # Debian's ifupdown port: NetworkManager calls it unmanaged, but it is up and carries the default route
        listed = [
            net.Interface("wlp2s0", "wifi", "connected", "WIFI-EF04"),
            net.Interface("enp1s0", "ethernet", "unmanaged"),
            net.Interface("enp9s0", "ethernet", "unmanaged"),
        ]
        addr = (
            '[{"ifname":"enp1s0","link_type":"ether","flags":["UP","LOWER_UP"],"addr_info":[{"family":"inet","local":"192.168.0.174","prefixlen":24}]},'
            '{"ifname":"enp9s0","link_type":"ether","flags":["UP"],"addr_info":[]}]'
        )
        route = '[{"dst":"default","gateway":"192.168.0.1","dev":"wlp2s0","metric":2000},{"dst":"default","gateway":"192.168.0.1","dev":"enp1s0","metric":1002}]'
        found = net.with_unmanaged(listed, addr, route, physical=lambda name: True)
        self.assertEqual(
            [(i.device, i.connected) for i in found], [("enp1s0", True), ("wlp2s0", True), ("enp9s0", False)]
        )
        self.assertEqual((found[0].addresses, found[0].gateway), (["192.168.0.174/24"], "192.168.0.1"))

    def test_wifi_stays_behind_a_wired_connection(self):
        wireless = lambda name: name.startswith("wl")
        ifupdown = '[{"dst":"default","gateway":"192.168.0.1","dev":"enp1s0","metric":1002},{"dst":"default","gateway":"192.168.0.1","dev":"wlp2s0","metric":600}]'
        self.assertEqual(net.wifi_metric(ifupdown, "wlp2s0", wireless), 1102)
        managed = '[{"dst":"default","dev":"enp1s0","metric":100},{"dst":"default","dev":"wlp2s0","metric":600}]'
        self.assertIsNone(net.wifi_metric(managed, "wlp2s0", wireless))  # wired already first
        self.assertIsNone(
            net.wifi_metric('[{"dst":"default","dev":"wlp2s0","metric":600}]', "wlp2s0", wireless)
        )  # Wi-Fi only
        self.assertIsNone(
            net.wifi_metric('[{"dst":"default","dev":"enp1s0"}]', "wlp2s0", wireless)
        )  # Wi-Fi has no route
        self.assertEqual(
            net.wifi_metric('[{"dst":"default","dev":"eth0"},{"dst":"default","dev":"wlan0"}]', "wlan0", wireless), 100
        )  # both 0
        self.assertIsNone(net.wifi_metric("not json", "wlp2s0", wireless))

    def test_ipv4_settings(self):
        s = net.parse_ipv4(
            "ipv4.method:manual\nipv4.addresses:192.168.1.20/24\nipv4.gateway:192.168.1.1\nipv4.dns:1.1.1.1,9.9.9.9\n"
        )
        self.assertEqual(
            (s.automatic, s.address, s.gateway, s.dns), (False, "192.168.1.20/24", "192.168.1.1", "1.1.1.1,9.9.9.9")
        )
        self.assertTrue(net.parse_ipv4("ipv4.method:auto\nipv4.addresses:\nipv4.gateway:--\n").automatic)

    def test_ipv4_validation(self):
        self.assertEqual(net.validate_ipv4(net.Ipv4Settings("auto"))[0], "")
        problem, args = net.validate_ipv4(net.Ipv4Settings("manual", "192.168.1.20", "192.168.1.1", "1.1.1.1 9.9.9.9"))
        self.assertEqual((problem, args[3], args[7]), ("", "192.168.1.20/24", "1.1.1.1,9.9.9.9"))
        self.assertIn("not an IPv4 address", net.validate_ipv4(net.Ipv4Settings("manual", "192.168.1"))[0])
        self.assertIn(
            "not on the network", net.validate_ipv4(net.Ipv4Settings("manual", "192.168.1.20/24", "10.0.0.1"))[0]
        )
        self.assertIn("DNS server", net.validate_ipv4(net.Ipv4Settings("manual", "192.168.1.20/24", "", "one.one"))[0])

    def test_signal_bars(self):
        self.assertEqual([net.signal_bars(s) for s in (0, 30, 60, 100)], ["▂", "▂▄", "▂▄▆", "▂▄▆█"])

    def test_a_fixed_address_starts_from_the_one_in_use(self):
        now = net.Interface(
            "eth0", "ethernet", addresses=["192.168.1.37/24"], gateway="192.168.1.1", dns=["192.168.1.1", "1.1.1.1"]
        )
        s = net.fixed_from(net.Ipv4Settings("auto"), now)
        self.assertEqual(
            (s.automatic, s.address, s.gateway, s.dns),
            (False, "192.168.1.37/24", "192.168.1.1", "192.168.1.1, 1.1.1.1"),
        )
        self.assertEqual(
            net.fixed_from(net.Ipv4Settings("auto", "10.0.0.5/24"), now).address, "10.0.0.5/24"
        )  # one already typed is kept

    def test_wifi_is_scanned_only_when_asked_and_the_ip_method_is_read(self):
        calls = []
        answers = {
            "RUNNING": "running",
            "DEVICE,TYPE,STATE,CONNECTION": "eth0:ethernet:connected:Wired\nwlan0:wifi:disconnected:--\n",
            "NAME,UUID,TYPE,DEVICE": "Wired:u-1:802-3-ethernet:eth0\n",
            "ipv4.method": "manual",
            "radio": "enabled",
            "IN-USE,SSID,SIGNAL,SECURITY": " :Cafe:90:\n",
        }

        def fake_run(argv, timeout=None):
            calls.append(argv)
            return Result(True, 0, next((v for k, v in answers.items() if k in argv), ""), "")

        from unittest import mock

        with mock.patch.object(net, "run", fake_run), mock.patch.object(net, "have", lambda _n: True):
            state = net.read_state()
            self.assertEqual([a[a.index("--rescan") + 1] for a in calls if "--rescan" in a], ["no"])
            self.assertEqual(state.of_kind("ethernet")[0].method, "manual")
            self.assertEqual(state.of_kind("wifi")[0].method, "")
            calls.clear()
            net.read_state(scan=True)
            self.assertEqual([a[a.index("--rescan") + 1] for a in calls if "--rescan" in a], ["yes"])


class UpdatesTests(unittest.TestCase):
    def test_apt(self):
        text = "Listing...\nbash/noble-updates,noble-security 5.2.21-2ubuntu4.1 amd64 [upgradable from: 5.2.21-2ubuntu4]\nfirefox/noble 129.0 amd64\n"
        self.assertEqual(
            upd.parse_apt(text),
            [
                upd.Update("bash", "5.2.21-2ubuntu4.1", "5.2.21-2ubuntu4", "noble-updates"),
                upd.Update("firefox", "129.0", "", "noble"),
            ],
        )

    def test_pacman(self):
        self.assertEqual(
            upd.parse_pacman("linux 6.9.7.arch1-1 -> 6.9.8.arch1-1\nmesa 1 -> 2 [ignored]\n"),
            [upd.Update("linux", "6.9.8.arch1-1", "6.9.7.arch1-1")],
        )
        m = next(m for m in upd.MANAGERS if m.id == "pacman")
        self.assertEqual(m.install_argv, ("pacman", "-Syu", "--noconfirm"))
        self.assertIn(2, m.ok_codes)  # 2: nothing to update
        self.assertTrue(m.fresh_lists)
        self.assertEqual(m.refresh_argv, ())  # never pacman -Sy alone (a partial upgrade)

    def test_pacman_questions_become_buttons(self):
        p = upd.parse_prompt(":: Proceed with installation? [Y/n] ")
        self.assertEqual(
            (p.question, p.answers, p.back), ("Proceed with installation?", (("Yes", "y"), ("No", "n")), "n")
        )
        p = upd.parse_prompt(":: python-a and python-b are in conflict. Remove python-b? [y/N] ")
        self.assertEqual(p.answers[0], ("No", "n"))
        self.assertEqual(p.back, "n")  # the default first; Back never says yes
        p = upd.parse_prompt(
            "Enter a number (default=2): ",
            [
                ":: There are 3 providers available for ttf-font:",
                ":: Repository extra",
                "   1) gnu-free-fonts  2) noto-fonts  3) ttf-dejavu",
            ],
        )
        self.assertIn("ttf-font", p.question)
        self.assertEqual(p.answers[0], ("noto-fonts (default)", "2"))
        self.assertEqual(len(p.answers), 3)
        self.assertEqual(
            upd.parse_prompt(
                "Enter a selection (default=all): ", [":: There are 2 members in group xorg-apps:"]
            ).answers,
            (("All (default)", ""),),
        )
        self.assertIsNone(upd.parse_prompt("downloading linux..."))
        self.assertTrue(upd.is_prompt(":: Import PGP key 1234? [Y/n] "))
        self.assertFalse(upd.is_prompt("checking keys in keyring"))

    def test_aur_helper_updates(self):
        self.assertEqual(upd.aur_helper(which=lambda n: "/usr/bin/paru" if n == "paru" else None), "paru")
        self.assertEqual(upd.aur_helper(which=lambda n: None), "")
        with mock.patch.object(
            upd, "run", lambda argv, timeout=0: Result(False, 1, "tvwcs 5.11.0-1 -> 5.12.0-1\n", "")
        ):
            self.assertEqual(upd._list_aur("yay"), ([upd.Update("tvwcs", "5.12.0-1", "5.11.0-1")], ""))
        with mock.patch.object(upd, "run", lambda argv, timeout=0: Result(False, 1, "", "")):
            self.assertEqual(upd._list_aur("paru"), ([], ""))  # 1: nothing to update
        with mock.patch.object(
            upd, "run", lambda argv, timeout=0: Result(False, 1, "", "error: failed to reach the AUR")
        ):
            self.assertEqual(upd._list_aur("yay")[1], "error: failed to reach the AUR")
        self.assertEqual(
            upd.aur_update_argv("yay"), ["yay", "-Sua", "--sudoflags=-S"]
        )  # as the user; sudo reads the password from Settings

    def test_aur_helper_questions(self):
        p = upd.parse_prompt("[sudo] password for tv: ")
        self.assertEqual(p.kind, "password")
        self.assertTrue(upd.is_prompt("[sudo] password for tv: "))
        menu = "==> [N]one [A]ll [Ab]ort [I]nstalled [No]tInstalled or (1 2 3, 1-3, ^4)"
        p = upd.parse_prompt("==> ", ["  1 tvwcs  (Installed)", "==> Diffs to show?", menu])
        self.assertEqual(
            (p.question, p.answers[0], p.back), ("Diffs to show?", ("Show all", "A"), "Ab")
        )  # reviewing comes first
        self.assertEqual(upd.parse_prompt("==> ", ["==> Packages to cleanBuild?", menu]).answers[0], ("None", "N"))
        p = upd.parse_prompt("==> ", ['==> Packages to exclude: (eg: "1 2 3", "1-3", "^4" or repo name)'])
        self.assertEqual((p.question, p.answers), ("Packages to exclude:", (("None, update them all", ""),)))
        p = upd.parse_prompt(
            "==> ",
            [
                '==> Packages to exclude: (eg: "1 2 3", "1-3", "^4" or repo name)',
                " -> Excluding packages may cause partial upgrades and break systems",
            ],
        )
        self.assertEqual(p.question, "Packages to exclude:")  # not yay's warning under it
        self.assertFalse(upd.is_prompt("==> Making package: tvwcs 5.12.0-1"))

    def test_arch_news_since_the_last_upgrade(self):
        rss = (
            "<rss><channel><item><title>Manual step for foo</title><link>https://archlinux.org/news/foo/</link>"
            "<pubDate>Wed, 29 Oct 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;Run &lt;code&gt;pacman -Syu&lt;/code&gt; first.&lt;/p&gt;</description></item>"
            "<item><title>Old</title><link>https://archlinux.org/news/old/</link><pubDate>Mon, 01 Sep 2026 10:00:00 +0000</pubDate>"
            "<description>x</description></item></channel></rss>"
        )
        items = upd.parse_news(rss)
        self.assertEqual([n.title for n in items], ["Manual step for foo", "Old"])
        self.assertEqual(items[0].text, "Run pacman -Syu first.")
        with tempfile.TemporaryDirectory() as d:
            log = Path(d, "pacman.log")
            log.write_text(
                "[2026-10-01T09:00:00+0000] [PACMAN] starting full system upgrade\n[2026-10-01T09:01:00+0000] [ALPM] upgraded x\n"
            )
            since = upd.last_upgrade(str(log))
            self.assertEqual([n.title for n in upd.news_since(items, since)], ["Manual step for foo"])
            self.assertIsNone(upd.last_upgrade(str(Path(d, "missing.log"))))
            Path(d, "etc", "pacman.d").mkdir(parents=True)
            Path(d, "etc", "pacman.d", "mirrorlist.pacnew").write_text("")
            self.assertEqual(
                upd.pacnew_files(str(Path(d, "etc"))), [str(Path(d, "etc", "pacman.d", "mirrorlist.pacnew"))]
            )
        self.assertEqual(len(upd.news_since(items, None)), 1)
        self.assertEqual(upd.news_since(None, 0), [])
        self.assertIsNone(upd.read_news(now=1e12, fetch=lambda _u: (_ for _ in ()).throw(OSError("offline"))))

    def test_detect_uses_the_first_manager_found(self):
        self.assertEqual(upd.detect(which=lambda c: "/usr/bin/" + c if c in ("apt-get", "flatpak") else None).id, "apt")
        self.assertEqual(
            upd.detect(which=lambda c: "/usr/bin/" + c if c in ("pacman", "checkupdates") else None).id, "pacman"
        )
        self.assertEqual(upd.detect(which=lambda c: "/usr/bin/" + c if c in ("dnf",) else None).id, "dnf")
        self.assertIsNone(
            upd.detect(which=lambda c: "/usr/bin/" + c if c in ("zypper", "xbps-install", "apk") else None)
        )  # not supported
        self.assertIsNone(upd.detect(which=lambda c: None))

    def test_age_and_reboot(self):
        self.assertEqual(
            [upd.age_text(t, 1000000) for t in (999990, 1000000 - 300, 1000000 - 7200, 1000000 - 86400 * 3)],
            ["just now", "5 minutes ago", "2 hours ago", "3 days ago"],
        )
        self.assertEqual(upd.age_text(None), "")
        self.assertTrue(upd.reboot_needed("6.9", exists=lambda p: p == "/run/reboot-required"))
        self.assertTrue(
            upd.reboot_needed("6.9", exists=lambda p: p == "/usr/lib/modules")
        )  # the running kernel's modules are gone
        self.assertFalse(
            upd.reboot_needed(
                "6.9", exists=lambda p: p in ("/usr/lib/modules", "/usr/lib/modules/6.9"), listdir=lambda d: ["6.9"]
            )
        )

    def test_a_newer_kernel_needs_a_restart(self):
        # Debian 13 after an update: no /run/reboot-required, and the running kernel stays installed beside the new one
        run = "6.12.115+deb13-amd64"
        new = "6.12.116+deb13-amd64"
        files = {"/usr/lib/modules", f"/usr/lib/modules/{run}", f"/boot/vmlinuz-{run}", f"/boot/vmlinuz-{new}"}
        mods = lambda extra: (lambda d: [run] + extra if d == "/usr/lib/modules" else (_ for _ in ()).throw(OSError()))
        self.assertTrue(upd.reboot_needed(run, exists=files.__contains__, dnf=False, listdir=mods([new])))
        self.assertFalse(upd.reboot_needed(run, exists=files.__contains__, dnf=False, listdir=mods([])))
        self.assertFalse(
            upd.reboot_needed(
                new, exists=lambda p: p in files or p == f"/usr/lib/modules/{new}", dnf=False, listdir=mods([new])
            )
        )  # restarted
        old = "6.12.110+deb13-amd64"  # an older kernel kept, or a removed one's folder: no restart
        self.assertFalse(upd.newer_kernel_installed(run, mods([old]), files.__contains__))
        self.assertFalse(
            upd.newer_kernel_installed(run, mods(["6.12.120+deb13-amd64"]), files.__contains__)
        )  # folder left, no image
        self.assertFalse(
            upd.newer_kernel_installed(run, mods(["6.12.120+deb13-rt-amd64"]), lambda p: True)
        )  # another kind
        # Ubuntu, and Fedora's vmlinuz beside the modules
        self.assertTrue(
            upd.newer_kernel_installed(
                "6.8.0-48-generic",
                lambda d: ["6.8.0-48-generic", "6.8.0-49-generic"],
                lambda p: p == "/boot/vmlinuz-6.8.0-49-generic",
            )
        )
        self.assertTrue(
            upd.newer_kernel_installed(
                "6.11.4-301.fc41.x86_64",
                lambda d: ["6.11.10-300.fc41.x86_64"],
                lambda p: p.endswith("6.11.10-300.fc41.x86_64/vmlinuz"),
            )
        )


class SysinfoTests(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(
            info.parse_os_release('NAME="Linux Mint"\nVERSION="22 (Wilma)"\nPRETTY_NAME="Linux Mint 22"\n'),
            "Linux Mint 22",
        )
        self.assertEqual(
            info.parse_os_release('NAME="Debian GNU/Linux"\nVERSION="13 (trixie)"\n'), "Debian GNU/Linux 13 (trixie)"
        )
        self.assertEqual(
            info.parse_cpu("processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz\n"),
            "Intel Core i5-8250U CPU @ 1.60GHz",
        )
        self.assertEqual(
            info.parse_cpu("processor\t: 0\nBogoMIPS\t: 108.00\n\nHardware\t: BCM2835\nModel\t: Raspberry Pi 4\n"),
            "Raspberry Pi 4",
        )
        self.assertEqual(
            info.parse_meminfo("MemTotal:  8000000 kB\nMemFree: 100 kB\nMemAvailable:  4000000 kB\n"),
            (8192000000, 4096000000),
        )
        self.assertEqual(
            info.parse_lspci_gpus(
                "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics 620 (rev 07)\n01:00.0 3D controller: NVIDIA Corporation GP108M\n00:1f.3 Audio device: Intel\n"
            ),
            ["Intel Corporation UHD Graphics 620", "NVIDIA Corporation GP108M"],
        )

    def test_formatting(self):
        self.assertEqual([info.size_text(n) for n in (512, 1500, 7.6e9)], ["512 B", "1.5 kB", "7.6 GB"])
        self.assertEqual(
            [info.duration_text(s) for s in (59, 3660, 7200, 90061)],
            ["0 minutes", "1 hour, 1 minute", "2 hours", "1 day, 1 hour"],
        )

    def test_battery_and_temperature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "BAT0").mkdir()
            (root / "BAT0" / "capacity").write_text("85\n")
            (root / "BAT0" / "status").write_text("Charging\n")
            self.assertEqual(info.battery(str(root)), "85 %, charging")
            for name, kind, temp in (("thermal_zone0", "acpitz", "30000"), ("thermal_zone1", "x86_pkg_temp", "48500")):
                (root / name).mkdir()
                (root / name / "type").write_text(kind)
                (root / name / "temp").write_text(temp)
            self.assertEqual(info.cpu_temperature(str(root)), "48 °C")
            self.assertEqual(info.battery(str(root / "none")), "")


if __name__ == "__main__":
    unittest.main()
