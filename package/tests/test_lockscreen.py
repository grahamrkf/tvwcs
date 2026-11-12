"""TVWCS's lock screen: when it is used, and the swaylock command it runs (no display needed)."""

import re, tempfile, unittest
from pathlib import Path

from tvwcs.system import lockscreen, system_actions


def which_of(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


class LockScreenTests(unittest.TestCase):
    def test_used_in_tv_mode_when_swaylock_is_installed(self):
        tv = {
            "TVWCS_SESSION": "sway"
        }  # TV mode always locks with TVWCS's lock screen; a desktop session keeps its own locker
        self.assertEqual(lockscreen.command({}, tv, which_of("swaylock"))[1:], ["lock"])
        self.assertIsNone(lockscreen.command({}, {}, which_of("swaylock")))
        self.assertIsNone(lockscreen.command({}, tv, which_of("loginctl")))

    def test_the_power_menu_lock_uses_it(self):
        self.assertEqual(
            system_actions.command_for("lock", {}, {"TVWCS_SESSION": "sway"}, which_of("swaylock"))[-1], "lock"
        )
        self.assertEqual(
            system_actions.command_for("lock", {}, {}, which_of("swaylock")), ["swaylock", "-f", "-c", "000000"]
        )
        self.assertEqual(system_actions.command_for("lock", {}, {}, which_of("loginctl")), ["loginctl", "lock-session"])
        self.assertIsNone(system_actions.command_for("lock", {}, {}, which_of()))

    def test_locker_arguments_follow_the_theme(self):
        argv = lockscreen.locker_argv({"accent": "#107C10"}, [("HDMI-A-1", "/run/x/lock-HDMI-A-1.svg")])
        self.assertEqual(argv[:6], ["swaylock", "-f", "-e", "-F", "-c", "1b1b1b"])
        self.assertEqual(argv[argv.index("--ring-color") + 1], "107c10")
        self.assertEqual(argv[argv.index("-i") + 1], "HDMI-A-1:/run/x/lock-HDMI-A-1.svg")
        self.assertIn("--indicator-idle-visible", argv)
        self.assertEqual(
            lockscreen.locker_argv({"accent": "nonsense"})[lockscreen.locker_argv().index("--ring-color") + 1], "0078d7"
        )
        self.assertNotIn("-i", lockscreen.locker_argv({}))  # no pictures (sway could not be asked): a plain colour
        retro = lockscreen.locker_argv({"style": "retro", "phosphor": "amber", "retro_wallpaper": "static"})
        self.assertEqual(retro[retro.index("--ring-color") + 1], "ffb000")
        self.assertEqual(retro[retro.index("--font") + 1], "TVWCS Pixel 5x7")

    def test_pictures_say_it_is_locked_in_the_theme(self):
        dark = lockscreen.picture(1920, 1080, lockscreen.look_of({}), "")
        self.assertIn('width="1920" height="1080"', dark)
        self.assertIn(">Locked<", dark)
        self.assertIn("password", dark)
        self.assertIn("#0078d7", dark)
        self.assertIn("#1b1b1b", dark)
        light = lockscreen.picture(1280, 720, lockscreen.look_of({"theme": "light", "accent": "#E81123"}), "")
        self.assertIn("#e81123", light)
        self.assertIn("#f2f2f2", light)
        retro = lockscreen.picture(
            3840,
            2160,
            lockscreen.look_of({"style": "retro", "retro_wallpaper": "static"}),
            "data:image/png;base64,AA==",
        )
        self.assertIn("&#x27;TVWCS Pixel 8x8&#x27;", retro)
        self.assertIn("#39ff6a", retro)
        self.assertIn("data:image/png;base64,AA==", retro)
        sizes = [int(m) for m in re.findall(r'font-size="(\d+)"', retro)]
        self.assertEqual(sizes[0] % 8, 0)
        self.assertEqual(sizes[1] % 7, 0)  # whole pixels of the pixel fonts

    def test_outputs_and_pictures(self):
        text = '[{"name":"HDMI-A-1","active":true,"current_mode":{"width":3840,"height":2160}},{"name":"DP-1","active":false,"current_mode":{}}]'
        self.assertEqual(lockscreen.outputs(lambda _a: text), [("HDMI-A-1", 3840, 2160)])
        self.assertEqual(lockscreen.outputs(lambda _a: "not json"), [])
        with tempfile.TemporaryDirectory() as d:
            made = lockscreen.make_pictures({}, Path(d), [("HDMI-A-1", 1920, 1080)])
            self.assertEqual(made, [("HDMI-A-1", f"{d}/lock-HDMI-A-1.svg")])
            self.assertIn("<svg", Path(made[0][1]).read_text())
            self.assertIn("/etc/fonts/fonts.conf", lockscreen.fonts_conf(Path(d)))

    def test_colours_match_the_theme(self):
        from tvwcs.ui import theme

        for name, (bg, fg, muted) in lockscreen.MODERN.items():
            p = theme.PALETTES[name]
            self.assertEqual((p["PANE"], p["FG"], p["MUTED"]), (bg, fg, muted))
        for name, (bg, fg, muted, line) in lockscreen.RETRO.items():
            p = theme.RETRO_PALETTES[name]
            self.assertEqual((p["BG"], p["FG"], p["MUTED"], p["LINE"]), (bg, fg, muted, line))
        for name, (bg, fg, muted, accent, _font, ring) in lockscreen.MEDIA.items():
            p = theme.MEDIA_PALETTES[name]
            self.assertEqual((p["PANE"], p["FG"], p["MUTED"], p["ACCENT"]), (bg, fg, muted, accent))
            self.assertTrue(p["FONT"].startswith(f'"{ring}"'))
        from tvwcs.core.model import MEDIA_LOOKS, RETRO_WALLPAPERS

        self.assertEqual(lockscreen.RETRO_BACKGROUNDS, RETRO_WALLPAPERS)
        self.assertEqual(set(lockscreen.MEDIA), set(MEDIA_LOOKS))
        self.assertEqual(set(theme.MEDIA_PALETTES), set(MEDIA_LOOKS))

    def test_lock_at_start_only_when_on_in_tv_mode_with_a_password(self):
        tv = {"TVWCS_SESSION": "sway"}
        on = {"lock_at_start": True}
        sw = which_of("swaylock")
        self.assertEqual(lockscreen.lock_at_start(on, tv, sw, "P"), "")
        self.assertEqual(lockscreen.lock_at_start({}, tv, sw, "P"), "off")
        self.assertIn(
            "TVWCS session", lockscreen.lock_at_start(on, {}, sw, "P")
        )  # desktop mode: its own login, no lock
        self.assertIn("TVWCS session", lockscreen.lock_at_start(on, tv, which_of(), "P"))
        for status in ("NP", "L"):
            self.assertIn("password", lockscreen.lock_at_start(on, tv, sw, status))
        self.assertEqual(lockscreen.lock_at_start(on, tv, sw, ""), "")  # passwd -S could not tell: lock

    def test_password_status(self):
        from tvwcs.settings.account import password_status

        self.assertEqual(password_status(lambda _a: "htpc P 2026-10-01 0 99999 7 -1\n"), "P")
        self.assertEqual(password_status(lambda _a: "tv L 2026-10-01 0 99999 7 -1\n"), "L")
        self.assertEqual(password_status(lambda _a: ""), "")

        def fails(_a):
            raise OSError("no passwd")

        self.assertEqual(password_status(fails), "")

    def test_the_session_config_runs_it_before_tvwcs(self):
        from pathlib import Path

        conf = (Path(__file__).resolve().parents[2] / "data" / "tvwcs.conf").read_text().splitlines()
        self.assertLess(conf.index("exec /usr/bin/tvwcs lock-at-start"), conf.index("exec /usr/bin/tvwcs launcher"))


if __name__ == "__main__":
    unittest.main()
