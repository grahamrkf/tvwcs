"""Where plain `tvwcs` runs and TVWCS's include line in the usual sway config, without GTK or sway."""

import json, tempfile, unittest, unittest.mock
from pathlib import Path
from tvwcs.system import sway_include as si


class Out:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class WhereTests(unittest.TestCase):
    def test_places(self):
        self.assertEqual(si.where({}), "console")
        self.assertEqual(si.where({"SWAYSOCK": "/run/user/1000/sway.sock", "TVWCS_SESSION": "sway"}), "tvwcs")
        self.assertEqual(
            si.where({"SWAYSOCK": "/run/user/1000/sway.sock", "WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"}), "sway"
        )
        self.assertEqual(si.where({"WAYLAND_DISPLAY": "wayland-0"}), "other")  # GNOME, KDE...
        self.assertEqual(si.where({"DISPLAY": ":0"}), "other")  # X11
        self.assertTrue(si.in_sway({"SWAYSOCK": "x"}))
        self.assertFalse(si.in_sway({"WAYLAND_DISPLAY": "wayland-0"}))


class IncludeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = {"HOME": str(self.home), "SWAYSOCK": "x"}
        self.std = self.home / "etc-sway-config"
        self.std.write_text("set $mod Mod4\nbar {\n}\n")
        self.no_sway = lambda *a, **k: Out(returncode=1)

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self):
        return self.home / ".config" / "sway" / "config"

    def test_without_a_config_it_is_made_from_the_standard_one(self):
        self.assertFalse(si.active(self.env, self.no_sway))
        path = si.add(self.env, standard=self.std)
        self.assertEqual(path, self.cfg())
        text = path.read_text()
        self.assertTrue(text.startswith("set $mod Mod4\nbar {"))
        self.assertTrue(text.endswith(f"{si.COMMENT}\n{si.INCLUDE}\n"))
        self.assertFalse(path.with_name("config.tvwcs-backup").exists())  # there was nothing to keep
        self.assertTrue(si.active(self.env, self.no_sway))

    def test_an_own_config_is_kept_with_a_backup_and_added_once(self):
        self.cfg().parent.mkdir(parents=True)
        self.cfg().write_text("# mine")
        si.add(self.env, standard=self.std)
        si.add(self.env, standard=self.std)
        text = self.cfg().read_text()
        self.assertTrue(text.startswith("# mine\n\n"))
        self.assertEqual(text.count(si.INCLUDE), 1)
        self.assertEqual(self.cfg().with_name("config.tvwcs-backup").read_text(), "# mine")

    def test_the_old_sway_folder_is_used_when_it_is_the_only_one(self):
        old = self.home / ".sway" / "config"
        old.parent.mkdir()
        old.write_text("# old\n")
        self.assertEqual(si.user_config(self.env), old)

    def test_the_running_config_counts_too(self):
        run = lambda *a, **k: Out(json.dumps({"config": "  include   /usr/share/tvwcs/tvwcs.conf\n"}))
        self.assertTrue(si.active(self.env, run))
        self.assertFalse(si.has_include("# include /usr/share/tvwcs/tvwcs.conf"))  # commented out
        self.assertTrue(si.active({"SWAYSOCK": "x", "TVWCS_SESSION": "sway", "HOME": str(self.home)}, self.no_sway))


if __name__ == "__main__":
    unittest.main()


class ReloadAfterUpdateTests(unittest.TestCase):
    def test_conf_newer_than_what_sway_read(self):
        from tvwcs.system import sway_include as S

        self.assertTrue(S.conf_is_newer(200, 100))  # installed while sway ran
        self.assertFalse(S.conf_is_newer(50, 100))  # sway started after the install: it read it
        self.assertFalse(S.conf_is_newer(200, 100, 300))  # TVWCS already had sway reload it

    def test_it_reloads_once_after_an_update(self):
        import os, tempfile
        from pathlib import Path
        from tvwcs.system import sway_include as S

        with tempfile.TemporaryDirectory() as d:
            sock = Path(d, "sway-ipc.sock")
            sock.touch()
            conf = Path(d, "tvwcs.conf")
            conf.touch()
            calls = []

            class R:
                returncode = 0

            def run(argv, **k):
                calls.append(argv)
                return R()

            real_stat = os.stat

            def stat(p, *a, **k):  # sway started at 100, tvwcs.conf installed at 200
                st = real_stat(p, *a, **k)
                t = 200 if str(p) == str(conf) else 100
                return os.stat_result(
                    (st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid, st.st_size, t, t, t)
                )

            env = {"SWAYSOCK": str(sock)}
            with unittest.mock.patch("os.stat", stat):
                self.assertTrue(S.reload_if_updated(d, env, conf=str(conf), run=run, now=250))
                self.assertFalse(S.reload_if_updated(d, env, conf=str(conf), run=run, now=260))  # already reloaded
                self.assertFalse(S.reload_if_updated(d, {}, conf=str(conf), run=run))  # not under sway
            self.assertEqual(calls, [["swaymsg", "reload"]])
