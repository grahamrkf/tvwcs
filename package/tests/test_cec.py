import errno, struct, tempfile, unittest
from pathlib import Path

from tvwcs.system import cec
from tvwcs.core.model import _clean_settings


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def claimed(menu="red", pa=0x2000, la=4):
    logic = cec.CecLogic(menu, clock=Clock())
    logic.address_changed(pa, 1 << la)
    return logic


class MessageTests(unittest.TestCase):
    def test_builders(self):
        self.assertEqual(cec.image_view_on(4), bytes([0x40, 0x04]))
        self.assertEqual(cec.active_source(4, 0x2100), bytes([0x4F, 0x82, 0x21, 0x00]))
        self.assertEqual(cec.inactive_source(4, 0x2000), bytes([0x40, 0x9D, 0x20, 0x00]))
        self.assertEqual(cec.standby(4), bytes([0x40, 0x36]))
        self.assertEqual(cec.feature_abort(4, 0, 0x9F), bytes([0x40, 0x00, 0x9F, 0x00]))
        self.assertEqual(cec.phys_text(0x2100), "2.1.0.0")
        self.assertEqual(cec.phys_text(cec.PHYS_ADDR_INVALID), "")

    def test_buttons_press_keys(self):
        logic = claimed()
        a = logic.message(bytes([0x04, 0x44, 0x00]))  # TV -> playback 1: OK
        self.assertEqual(a.keys, [cec.KEY_ENTER])
        self.assertEqual(a.button, "select")
        self.assertEqual(
            logic.message(bytes([0x04, 0x44, 0x0D])).keys, [cec.KEY_ESC]
        )  # Exit is Esc, which TVWCS takes as Back
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x25])).keys, [cec.KEY_1 + 4])  # 5
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x20])).keys, [cec.KEY_0])
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x71])).keys, [])  # Blue: no key of its own
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x7E])).button, "")  # unknown

    def test_held_arrow_repeats_but_menu_button_does_not(self):
        logic = claimed()
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x02])).keys, [cec.KEY_DOWN])
        logic.clock.t += 0.5
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x02])).keys, [cec.KEY_DOWN])
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x72])).hotkey, "menu")
        logic.clock.t += 0.5
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x72])).hotkey, "")  # still held
        logic.message(bytes([0x04, 0x45]))  # released
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x72])).hotkey, "menu")
        logic.clock.t += 2
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x72])).hotkey, "menu")  # the Released was lost

    def test_previous_channel_switches_to_the_last_app(self):
        logic = claimed()
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x32])).hotkey, "last")
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x32])).hotkey, "")  # still held
        logic.last_button = ""
        logic.message(bytes([0x04, 0x45]))
        a = logic.message(bytes([0x04, 0x44, 0x32]))
        self.assertEqual((a.hotkey, a.keys), ("", []))

    def test_menu_button_none(self):
        logic = claimed(menu="")
        self.assertEqual(logic.message(bytes([0x04, 0x44, 0x72])).hotkey, "")

    def test_answers(self):
        logic = claimed()
        self.assertEqual(logic.message(bytes([0x04, 0x8F])).send, [bytes([0x40, 0x90, 0x00])])
        self.assertEqual(logic.message(bytes([0x04, 0x8D, 0x00])).send, [bytes([0x40, 0x8E, 0x00])])
        self.assertEqual(
            logic.message(bytes([0x04, 0x9F])).send, [bytes([0x40, 0x00, 0x9F, 0x00])]
        )  # Get CEC Version: not ours to answer, abort
        self.assertEqual(logic.message(bytes([0x04, 0xFF])).send, [bytes([0x40, 0x00, 0xFF, 0x04])])  # Abort: refused
        self.assertEqual(logic.message(bytes([0x04, 0x00, 0x44, 0x00])).send, [])  # never abort a Feature Abort
        self.assertEqual(logic.message(bytes([0x0F, 0x87, 0, 0, 0])).send, [])  # a broadcast for someone else
        self.assertEqual(logic.message(bytes([0x08, 0x8F])).send, [])  # sent to another device
        self.assertEqual(logic.message(bytes([0x40, 0x8F])).send, [])  # our own

    def test_active_source(self):
        logic = claimed()
        self.assertEqual(logic.message(bytes([0x0F, 0x85])).send, [])  # not active yet
        self.assertEqual(logic.become_active(), [bytes([0x40, 0x04]), bytes([0x4F, 0x82, 0x20, 0x00])])
        self.assertEqual(logic.message(bytes([0x0F, 0x85])).send, [bytes([0x4F, 0x82, 0x20, 0x00])])
        logic.message(bytes([0x8F, 0x82, 0x30, 0x00]))  # another device became the source
        self.assertFalse(logic.active)
        self.assertEqual(
            logic.message(bytes([0x0F, 0x86, 0x20, 0x00])).send, [bytes([0x4F, 0x82, 0x20, 0x00])]
        )  # TV picks us
        self.assertTrue(logic.active)
        logic.message(bytes([0x0F, 0x80, 0x20, 0x00, 0x30, 0x00]))  # routing change away
        self.assertFalse(logic.active)

    def test_standby(self):
        logic = claimed()
        logic.become_active()
        self.assertTrue(logic.message(bytes([0x0F, 0x36])).tv_off)
        self.assertFalse(logic.active)
        self.assertFalse(logic.message(bytes([0x8F, 0x36])).tv_off)  # not from the TV
        self.assertEqual(logic.going_away(tv_standby=True), [bytes([0x40, 0x36])])
        logic.become_active()
        self.assertEqual(logic.going_away(tv_standby=False), [bytes([0x40, 0x9D, 0x20, 0x00])])
        self.assertEqual(logic.going_away(tv_standby=False), [])  # no longer the source

    def test_not_ready(self):
        logic = cec.CecLogic()
        self.assertEqual(logic.become_active(), [])
        self.assertEqual(logic.going_away(True), [])
        logic.address_changed(cec.PHYS_ADDR_INVALID, 0)
        self.assertFalse(logic.ready)

    def test_keys_have_names(self):
        self.assertTrue(all(k < 248 for k in cec.KEYS))  # xkb has names for these
        self.assertFalse(any(b.id in cec.NAVIGATION for b in cec.HOTKEY_CHOICES))
        self.assertIn(cec.DEFAULT_MENU_BUTTON, {b.id for b in cec.HOTKEY_CHOICES})


class SettingsTests(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(cec.clean_settings(None), cec.DEFAULTS)
        s = cec.clean_settings({"enabled": False, "follow_tv": True, "menu": "root_menu", "wake_tv": "yes"})
        self.assertEqual((s["enabled"], s["follow_tv"], s["menu"], s["wake_tv"]), (False, True, "root_menu", True))
        self.assertEqual(
            cec.clean_settings({"menu": "select"})["menu"], cec.DEFAULT_MENU_BUTTON
        )  # OK can't be a hotkey
        self.assertEqual(cec.clean_settings({"menu": "digit_1"})["menu"], cec.DEFAULT_MENU_BUTTON)
        self.assertEqual(cec.clean_settings({"menu": ""})["menu"], "")
        self.assertEqual(cec.clean_settings({})["last"], "previous_channel")
        self.assertEqual(cec.clean_settings({"last": "blue"})["last"], "blue")
        self.assertEqual(cec.clean_settings({"last": "up"})["last"], "previous_channel")
        self.assertEqual(
            cec.clean_settings({"menu": "blue", "last": "blue"})["last"], ""
        )  # one button, one job: the Quick Menu's

    def test_in_config(self):
        self.assertEqual(_clean_settings({})["cec"], cec.DEFAULTS)
        self.assertEqual(_clean_settings({"cec": {"menu": "blue"}})["cec"]["menu"], "blue")
        a = _clean_settings({})
        a["cec"]["menu"] = "x"
        self.assertEqual(_clean_settings({})["cec"]["menu"], cec.DEFAULT_MENU_BUTTON)  # defaults are copied

    def test_status_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertIsNone(cec.read_status(d))
            cec.write_status(
                cec.Status(state="connected", phys_addr="2.0.0.0", keys=True, last_button="Red", seen=["red"]), d
            )
            s = cec.read_status(d)
            self.assertEqual((s.state, s.last_button, s.seen), ("connected", "Red", ["red"]))
            self.assertEqual(cec.describe(s), "Connected to the TV on input HDMI 2")
            s.keys = False
            self.assertIn("can't press keys", cec.describe(s))
            self.assertEqual(cec.describe(None), "TVWCS is not running")

    def test_adapters(self):
        self.assertEqual(
            cec.adapters(globber=lambda p: ["/dev/cec10", "/dev/cec1", "/dev/cec0"]),
            ["/dev/cec0", "/dev/cec1", "/dev/cec10"],
        )


class FakeKernel:
    """Enough of a CEC adapter's ioctls for Adapter."""

    def __init__(self, configured=None):
        self.calls = []
        self.queue = []
        self.events = []
        self.configured = configured

    def ioctl(self, fd, req, arg=0):
        self.calls.append((req, arg))
        if req == cec.CEC_ADAP_G_CAPS:
            return cec.CAPS.pack(b"vc4_hdmi", b"vc4-hdmi-0", 1, 0x7E, 0)
        if req == cec.CEC_ADAP_G_PHYS_ADDR:
            return struct.pack("=H", 0x1000)
        if req == cec.CEC_ADAP_G_LOG_ADDRS:
            name, num = self.configured or (b"", 0)
            return cec.LOG_ADDRS.pack(bytes(4), 0, 5, num, 0, 0, name, bytes(4), bytes(4), bytes(4), bytes(48))
        if req == cec.CEC_RECEIVE:
            if not self.queue:
                raise OSError(errno.EAGAIN, "empty")
            m, rx, tx = self.queue.pop(0)
            return cec.MSG.pack(0, 0, len(m), 0, 0, 0, m.ljust(16, b"\0"), 0, rx, tx, 0, 0, 0, 0)
        if req == cec.CEC_DQEVENT:
            if not self.events:
                raise OSError(errno.EAGAIN, "empty")
            return cec.EVENT.pack(
                0, cec.CEC_EVENT_STATE_CHANGE, 0, cec.STATE_CHANGE.pack(*self.events.pop(0)).ljust(64, b"\0")
            )
        return arg


class AdapterTests(unittest.TestCase):
    def adapter(self, k):
        return cec.Adapter("/dev/cec0", ioctl=k.ioctl, opener=lambda *a: 7, closer=lambda fd: None)

    def test_claim_and_messages(self):
        k = FakeKernel()
        a = self.adapter(k)
        self.assertEqual((a.driver, a.name), ("vc4_hdmi", "vc4-hdmi-0"))
        self.assertEqual(a.phys_addr(), 0x1000)
        a.claim()
        req, data = k.calls[-2]
        self.assertEqual(req, cec.CEC_ADAP_S_LOG_ADDRS)
        f = cec.LOG_ADDRS.unpack(data)
        self.assertEqual(
            (f[3], f[6].rstrip(b"\0"), f[8][0], f[7][0]),
            (1, b"TVWCS", cec.LOG_ADDR_TYPE_PLAYBACK, cec.PRIM_DEVTYPE_PLAYBACK),
        )
        self.assertEqual(k.calls[-1], (cec.CEC_S_MODE, struct.pack("=I", 0x11)))
        a.transmit(cec.image_view_on(4))
        f = cec.MSG.unpack(k.calls[-1][1])
        self.assertEqual((f[2], f[6][:2]), (2, b"\x40\x04"))
        k.queue = [(b"\x04\x44\x00", cec.CEC_RX_STATUS_OK, 0), (b"\x40\x04", 0, cec.CEC_TX_STATUS_OK)]
        self.assertEqual(a.receive(), b"\x04\x44\x00")
        self.assertEqual(a.receive(), b"")
        self.assertIsNone(a.receive())
        k.events = [(0x1000, 1 << 4, 0)]
        self.assertEqual(a.event(), (0x1000, 16))
        self.assertIsNone(a.event())

    def test_ours_reclaimed_others_left(self):
        k = FakeKernel(configured=(b"TVWCS", 1))
        a = self.adapter(k)
        a.claim()
        self.assertEqual([r for r, _ in k.calls].count(cec.CEC_ADAP_S_LOG_ADDRS), 2)  # let go, then claimed again
        k = FakeKernel(configured=(b"Kodi", 1))
        a = self.adapter(k)
        with self.assertRaises(PermissionError):
            a.claim()
        self.assertNotIn(cec.CEC_ADAP_S_LOG_ADDRS, [r for r, _ in k.calls])


class KeyboardTests(unittest.TestCase):
    def test_tap(self):
        calls = []
        written = []
        kb = cec.VirtualKeyboard(
            keys=[28],
            ioctl=lambda fd, req, arg=0: calls.append(req),
            opener=lambda *a: 3,
            writer=lambda fd, data: written.append(data),
            closer=lambda fd: None,
        )
        self.assertEqual(calls, [cec.UI_SET_EVBIT, cec.UI_SET_KEYBIT, cec.UI_DEV_SETUP, cec.UI_DEV_CREATE])
        kb.tap(28)
        events = [cec.INPUT_EVENT.unpack_from(written[0], i * cec.INPUT_EVENT.size)[2:] for i in range(4)]
        self.assertEqual(events, [(1, 28, 1), (0, 0, 0), (1, 28, 0), (0, 0, 0)])
        kb.close()
        self.assertEqual(calls[-1], cec.UI_DEV_DESTROY)


class FakeAdapter:
    def __init__(self, path):
        import os

        self.path = path
        self.driver = "vc4_hdmi"
        self.r, self.fd = os.pipe()
        self.sent = []
        self.released = False
        self.closed = False

    def phys_addr(self):
        return 0x2000

    def claim(self):
        pass

    def release(self):
        self.released = True

    def transmit(self, m):
        self.sent.append(bytes(m))
        return True

    def receive(self):
        return None

    def event(self):
        return None

    def close(self):
        import os

        if not self.closed:
            os.close(self.r)
            os.close(self.fd)
            self.closed = True


class FakeKeyboard:
    def __init__(self):
        self.taps = []

    def tap(self, k):
        self.taps.append(k)

    def close(self):
        pass


class _Params:
    def __init__(self, *v):
        self.v = v

    def unpack(self):
        return self.v


def _fake_glib():
    """CecService's GLib calls, without GLib (the tests run without python3-gi)."""
    import types
    from unittest import mock

    GLib = types.SimpleNamespace(
        PRIORITY_DEFAULT=0,
        SOURCE_REMOVE=False,
        SOURCE_CONTINUE=True,
        IOCondition=types.SimpleNamespace(IN=1, PRI=2, ERR=8, HUP=16),
        io_add_watch=lambda *a: 1,
        timeout_add_seconds=lambda *a: 2,
        timeout_add=lambda ms, f: f(),
        source_remove=lambda s: None,
    )
    gi = types.ModuleType("gi")
    repo = types.ModuleType("gi.repository")
    repo.GLib = GLib
    gi.repository = repo
    return mock.patch.dict("sys.modules", {"gi": gi, "gi.repository": repo})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock

        p = _fake_glib()
        p.start()
        self.addCleanup(p.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for name, value in (
            ("adapters", lambda: ["/dev/cec0"]),
            ("Adapter", FakeAdapter),
            ("VirtualKeyboard", FakeKeyboard),
        ):
            p = mock.patch.object(cec, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(cec.CecService, "_watch_power", lambda self: None)
        p.start()
        self.addCleanup(p.stop)
        self.hotkeys = []
        self.tv_off = []
        self.s = cec.CecService(Path(self.dir.name), self.hotkeys.append, lambda: self.tv_off.append(1))

    def test_flow(self):
        opts = dict(cec.DEFAULTS, follow_tv=True)
        self.assertTrue(self.s.start(opts))
        a = self.s.adapter
        self.assertEqual(cec.read_status(Path(self.dir.name)).state, "starting")
        self.s._address(0x2000, 1 << 4)
        self.assertEqual(a.sent, [bytes([0x40, 0x04]), bytes([0x4F, 0x82, 0x20, 0x00])])  # the TV is switched to us
        self.s._address(0x2000, 1 << 4)
        self.assertEqual(len(a.sent), 2)  # once
        st = cec.read_status(Path(self.dir.name))
        self.assertEqual((st.state, st.phys_addr, st.keys), ("connected", "2.0.0.0", True))
        self.s._handle(self.s.logic.message(bytes([0x04, 0x44, 0x01])))
        self.s._handle(self.s.logic.message(bytes([0x04, 0x44, 0x72])))
        self.assertEqual(self.s.keyboard.taps, [cec.KEY_UP])
        self.assertEqual(self.hotkeys, ["menu"])
        self.assertEqual(cec.read_status(Path(self.dir.name)).seen, ["up", "red"])
        self.s._handle(self.s.logic.message(bytes([0x0F, 0x36])))
        self.assertEqual(self.tv_off, [1])
        self.s.logic.become_active()
        a.sent.clear()
        self.s._power_signal(None, None, None, None, "PrepareForSleep", _Params(True))
        self.assertEqual(a.sent, [bytes([0x40, 0x36])])
        self.s._power_signal(None, None, None, None, "PrepareForSleep", _Params(False))
        self.assertEqual(a.sent[1:], [bytes([0x40, 0x04]), bytes([0x4F, 0x82, 0x20, 0x00])])
        self.s.update(dict(opts, menu="blue"))
        self.assertEqual(self.s.logic.menu_button, "blue")
        self.s.stop(release=True)
        self.assertTrue(a.released)
        self.assertEqual(a.sent[-1], bytes([0x40, 0x9D, 0x20, 0x00]))
        self.assertEqual(cec.read_status(Path(self.dir.name)).state, "off")

    def test_busy(self):
        from unittest import mock

        def taken(self):
            raise PermissionError('another program uses HDMI-CEC here (as "Kodi")')

        with mock.patch.object(FakeAdapter, "claim", taken):
            self.assertFalse(self.s.start(dict(cec.DEFAULTS)))
        st = cec.read_status(Path(self.dir.name))
        self.assertEqual(st.state, "busy")
        self.assertIn("Kodi", cec.describe(st))


if __name__ == "__main__":
    unittest.main()
