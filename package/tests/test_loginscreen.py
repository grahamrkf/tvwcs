"""The login screen and automatic login without GTK, in a pretend root folder (TVWCS_ROOT): greetd, LightDM and SDDM,
and changing a password."""

import os, tempfile, unittest
from pathlib import Path
from unittest import mock
from tvwcs.settings import account
from tvwcs.system import loginscreen


class RootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"TVWCS_ROOT": str(self.root)})
        self.env.start()
        ws = self.root / "usr" / "share" / "wayland-sessions"
        ws.mkdir(parents=True)
        (ws / "tvwcs-sway.desktop").write_text("[Desktop Entry]\nName=TVWCS\nExec=/usr/bin/tvwcs-session\n")
        self.units = self.root / "lib" / "systemd" / "system"
        self.units.mkdir(parents=True)
        (self.units / "greetd.service").write_text("[Unit]\n")
        self.etc = self.root / "etc"
        (self.etc / "systemd" / "system").mkdir(parents=True)
        (self.etc / "greetd").mkdir()
        self.out = []
        self.c = loginscreen.Changer(out=self.out.append)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def use(self, unit):
        link = self.etc / "systemd" / "system" / "display-manager.service"
        if link.is_symlink():
            link.unlink()
        link.symlink_to(f"/lib/systemd/system/{unit}.service")

    def test_a_disabled_login_screen_does_not_count(self):
        (self.etc / "X11").mkdir()
        (self.etc / "X11" / "default-display-manager").write_text("/usr/sbin/greetd\n")
        self.assertEqual(loginscreen.active_unit(), "greetd")  # no systemd: the file decides
        (self.root / "run" / "systemd" / "system").mkdir(parents=True)
        self.assertEqual(loginscreen.active_unit(), "")  # systemd: only display-manager.service does
        self.use("lightdm")
        self.assertEqual(loginscreen.active_unit(), "lightdm")

    def test_greeter_names(self):
        self.assertEqual(
            loginscreen.current_greeter({"default_session": {"command": "agreety --cmd /bin/sh"}}), "agreety"
        )
        self.assertEqual(
            loginscreen.current_greeter({"default_session": {"command": "cage -s -- gtkgreet"}}), "gtkgreet"
        )
        self.assertEqual(loginscreen.current_greeter({}), "")

    def test_without_a_login_screen_greetd_logs_in_to_tvwcs(self):
        self.assertEqual(loginscreen.active_unit(), "")
        self.c.use_greetd("tv")
        cfg = loginscreen.greetd_config()
        self.assertEqual(cfg["initial_session"], {"command": "/usr/bin/tvwcs-session", "user": "tv"})
        self.assertEqual(cfg["default_session"]["command"], "/usr/sbin/agreety --cmd /usr/bin/tvwcs-session")
        self.assertEqual(loginscreen.active_unit(), "greetd")
        self.assertEqual(loginscreen.autologin(), ("tv", "tvwcs-sway"))
        self.assertIn(["systemctl", "set-default", "graphical.target"], self.c.calls)
        self.assertEqual(loginscreen.name("greetd"), "greetd (text login)")

    def test_without_a_login_screen_the_console_logs_in(self):
        self.assertTrue(loginscreen.autologin_supported(""))
        self.c.set_autologin("tv", unit="")
        dropin = self.etc / "systemd" / "system" / "getty@tty1.service.d" / "tvwcs-autologin.conf"
        self.assertIn(
            "ExecStart=\nExecStart=-/sbin/agetty -o '-p -f -- \\\\u' --noclear --autologin tv %I $TERM",
            dropin.read_text(),
        )
        self.assertEqual(loginscreen.autologin(""), ("tv", "tvwcs-sway"))
        self.assertIn(["systemctl", "daemon-reload"], self.c.calls)
        self.c.set_autologin("", unit="")
        self.assertFalse(dropin.parent.exists())
        self.assertEqual(loginscreen.autologin(""), ("", ""))
        with self.assertRaises(SystemExit):
            self.c.set_autologin("tv; rm -rf /", unit="")

    def test_the_consoles_own_automatic_login_is_read_and_kept(self):
        d = self.etc / "systemd" / "system" / "getty@tty1.service.d"
        d.mkdir(parents=True)
        (d / "autologin.conf").write_text(
            "[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin=sam --noclear %I $TERM\n"
        )
        self.assertEqual(loginscreen.console_autologin(), "sam")
        with self.assertRaises(SystemExit):
            self.c.set_autologin("", unit="")  # not TVWCS's file: it says where to change it
        (d / "zz.conf").write_text(
            "[Service]\nExecStart=\nExecStart=-/sbin/agetty --noclear %I $TERM\n"
        )  # a later drop-in wins
        self.assertEqual(loginscreen.console_autologin(), "")

    def test_switching_to_lightdm_makes_the_link_systemctl_enable_cannot(self):
        units = self.root / "usr" / "lib" / "systemd" / "system"
        units.mkdir(parents=True)
        (units / "lightdm.service").write_text("[Unit]\n")
        link = self.etc / "systemd" / "system" / "display-manager.service"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to("/usr/lib/systemd/system/sddm.service")
        self.c.switch_to("lightdm")
        self.assertEqual(os.readlink(link), "/usr/lib/systemd/system/lightdm.service")
        self.assertIn(["systemctl", "disable", "sddm.service"], self.c.calls)

    def test_switching_to_a_login_screen_ends_the_consoles_automatic_login(self):
        self.c.set_autologin("tv", unit="")
        self.c.switch_to("greetd")
        self.assertFalse((self.etc / "systemd" / "system" / "getty@tty1.service.d" / "tvwcs-autologin.conf").exists())

    def test_the_shell_profile_starts_the_session_once(self):
        home = self.root / "home"
        home.mkdir()
        (home / ".profile").write_text("# mine\nPATH=$HOME/bin:$PATH")
        with mock.patch.dict(os.environ, {"ZDOTDIR": ""}):
            self.assertFalse(loginscreen.profile_starts(home))
            self.assertEqual(loginscreen.set_profile(True, home, "/bin/bash"), "")
            self.assertEqual(loginscreen.set_profile(True, home, "/bin/bash"), "")
            text = (home / ".profile").read_text()
            self.assertTrue(text.startswith("# mine\nPATH=$HOME/bin:$PATH\n\n"))
            self.assertEqual(text.count(loginscreen.PROFILE_BEGIN), 1)
            self.assertIn("/dev/tty1", text)
            self.assertTrue(loginscreen.profile_starts(home))
            self.assertEqual(loginscreen.set_profile(False, home, "/bin/bash"), "")
            self.assertEqual((home / ".profile").read_text(), "# mine\nPATH=$HOME/bin:$PATH\n")
            self.assertFalse(loginscreen.profile_starts(home))
            (home / ".bash_profile").write_text("")  # bash reads it in place of .profile
            self.assertEqual(loginscreen.profile_file(home, "/bin/bash"), home / ".bash_profile")
            self.assertEqual(loginscreen.profile_file(home, "/usr/bin/zsh"), home / ".zprofile")
            self.assertIsNone(loginscreen.profile_file(home, "/usr/bin/fish"))
            self.assertNotEqual(loginscreen.set_profile(True, home, "/usr/bin/fish"), "")

    def test_the_profiles_lines_run_in_sh(self):
        import subprocess

        body = loginscreen.PROFILE_BODY.replace("/dev/tty1", "/dev/not-a-tty")  # not the first console: nothing starts
        self.assertEqual(subprocess.run(["sh", "-n", "-c", loginscreen.PROFILE_BODY]).returncode, 0)
        self.assertEqual(
            subprocess.run(
                ["sh", "-c", body + "\necho done"], capture_output=True, text=True, stdin=subprocess.DEVNULL
            ).stdout,
            "done\n",
        )

    def test_another_greetd_greeter_is_kept(self):
        (self.etc / "greetd" / "config.toml").write_text(
            '[terminal]\nvt = 1\n\n[default_session]\ncommand = "tuigreet --cmd sway"\nuser = "greeter"\n'
        )
        self.use("greetd")
        self.c.set_autologin("tv")
        cfg = loginscreen.greetd_config()
        self.assertEqual(
            (cfg["default_session"], cfg["terminal"]["vt"]), ({"command": "tuigreet --cmd sway", "user": "greeter"}, 1)
        )
        self.assertEqual(loginscreen.autologin(), ("tv", "tvwcs-sway"))
        self.c.set_autologin("")
        self.assertNotIn("initial_session", loginscreen.greetd_config())
        self.assertEqual(loginscreen.autologin(), ("", ""))

    def test_automatic_login_where_each_login_screen_keeps_it(self):
        for u in ("lightdm", "sddm"):
            (self.units / f"{u}.service").write_text("")
        self.use("lightdm")
        self.c.set_autologin("tv")
        self.assertIn(
            "autologin-session=tvwcs-sway",
            (self.etc / "lightdm" / "lightdm.conf.d" / "50-tvwcs-autologin.conf").read_text(),
        )
        self.assertEqual(loginscreen.autologin(), ("tv", "tvwcs-sway"))
        self.c.set_autologin("")
        self.assertEqual(loginscreen.autologin(), ("", ""))
        self.use("sddm")
        self.c.set_autologin("tv", "sway")
        self.assertEqual(loginscreen.autologin(), ("tv", "sway"))
        self.use("gdm3")
        with self.assertRaises(SystemExit):
            self.c.set_autologin("tv")
        self.assertFalse(loginscreen.autologin_supported())

    def test_command_line(self):
        self.assertEqual(loginscreen.main(["greetd", "tv"]), 0)
        self.assertEqual(loginscreen.autologin(), ("tv", "tvwcs-sway"))
        self.assertEqual(loginscreen.main(["autologin", "--off"]), 0)
        self.assertEqual(loginscreen.autologin(), ("", ""))
        self.assertEqual(loginscreen.main(["switch", "lightdm"]), 1)  # not installed
        self.assertEqual(loginscreen.main(["bogus"]), 2)

    def test_root_command_installs_packages_first(self):
        argv = loginscreen.root_command(["greetd", "tv"], ("greetd",))
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertEqual(argv[3:6], ["sh", "1", "greetd"])
        self.assertEqual(argv[6:8], ["env", "PYTHONDONTWRITEBYTECODE=1"])
        self.assertEqual(argv[-4:], ["-m", "tvwcs.system.loginscreen", "greetd", "tv"])
        with self.assertRaises(ValueError):
            loginscreen.root_command(["greetd"], ("bad name",))


class AccountTests(unittest.TestCase):
    def fake_passwd(self, d, accept_new=True):
        """A passwd that asks the usual three questions; "old" is the current password, a short new one is refused."""
        f = Path(d) / "passwd"
        f.write_text(
            "#!/bin/sh\nprintf 'Changing password for tv.\\nCurrent password: '; read -r cur\n"
            "[ \"$cur\" = old ] || { echo 'passwd: Authentication token manipulation error'; exit 10; }\n"
            "while :; do printf 'New password: '; read -r new; printf 'Retype new password: '; read -r again\n"
            "  [ ${#new} -ge 6 ] && break; echo 'BAD PASSWORD: The password is shorter than 6 characters'; done\n"
            "echo 'passwd: password updated successfully'\n"
        )
        f.chmod(0o755)
        return str(f)

    def test_changes_the_password_answering_passwd(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.fake_passwd(d)
            self.assertEqual(account.change_password("old", "long-enough", argv=(p,)), "")
            self.assertEqual(
                account.change_password("nope", "long-enough", argv=(p,)), "Your current password is not right."
            )
            self.assertEqual(
                account.change_password("old", "short", argv=(p,)),
                "BAD PASSWORD: The password is shorter than 6 characters",
            )
            self.assertEqual(account.change_password("old", "", argv=(p,)), "The new password is empty.")

    def test_full_name(self):
        self.assertEqual(account.valid_full_name("Living Room"), "")
        self.assertTrue(account.valid_full_name("a:b"))
        self.assertEqual(account.full_name_argv("tv", "Living Room"), ["chfn", "-f", "Living Room", "tv"])
        self.assertTrue(account.read().login)


if __name__ == "__main__":
    unittest.main()
