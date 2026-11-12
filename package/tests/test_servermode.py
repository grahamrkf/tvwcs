"""Server mode without root or GTK, in a pretend root folder (TVWCS_ROOT): turning it on and off, the polkit rule,
the server user's automatic login, starting TVWCS on the screen, the command line, and what it takes away."""

import os, pwd, tempfile, unittest
from pathlib import Path
from unittest import mock
from tvwcs import account, power, servermode, system_actions


class Done:
    def __init__(self, code=0, out=""):
        self.returncode = code
        self.stdout = out
        self.stderr = ""


class ServerModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"TVWCS_ROOT": str(self.root), "ZDOTDIR": ""})
        self.env.start()
        ws = self.root / "usr" / "share" / "wayland-sessions"
        ws.mkdir(parents=True)
        (ws / "tvwcs-sway.desktop").write_text("[Desktop Entry]\nName=TVWCS\nExec=/usr/bin/tvwcs-session\n")
        (self.root / "etc" / "systemd" / "system").mkdir(parents=True)
        self.home = self.root / "home" / "bob"
        self.home.mkdir(parents=True)
        bob = pwd.struct_passwd(("bob", "x", 1001, 1001, "Bob", "/home/bob", "/bin/bash"))
        self.users = mock.patch.object(
            servermode.pwd, "getpwnam", lambda n: bob if n == "bob" else (_ for _ in ()).throw(KeyError(n))
        )
        self.users.start()
        self.out = []
        self.c = servermode.Changer(out=self.out.append)

    def tearDown(self):
        self.users.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_on_and_off(self):
        self.assertFalse(servermode.active())
        self.c.turn_on("bob")
        self.assertEqual(servermode.server_user(), "bob")
        self.assertTrue(servermode.active())
        rule = (self.root / "etc" / "polkit-1" / "rules.d" / "50-tvwcs-server-mode.rules").read_text()
        self.assertIn('subject.user != "bob"', rule)
        self.assertIn("login1", rule)
        self.assertIn("power-off-drive", rule)
        # no login screen: the first console logs bob in, and his profile starts TVWCS's session
        self.assertIn(
            "--autologin bob ",
            (self.root / "etc" / "systemd" / "system" / "getty@tty1.service.d" / "tvwcs-autologin.conf").read_text(),
        )
        self.assertIn("/usr/bin/tvwcs-session", (self.home / ".profile").read_text())
        self.c.turn_off()
        self.assertFalse(servermode.active())
        self.assertFalse((self.root / "etc" / "tvwcs").exists())
        self.assertFalse((self.root / "etc" / "polkit-1" / "rules.d" / "50-tvwcs-server-mode.rules").exists())
        self.assertTrue(
            (self.root / "etc" / "systemd" / "system" / "getty@tty1.service.d" / "tvwcs-autologin.conf").exists()
        )  # the automatic login stays

    def test_refuses_unknown_accounts_and_root(self):
        for name in ("nobody-here", "bad name"):
            with self.assertRaises(SystemExit):
                self.c.turn_on(name)
        with mock.patch.object(
            servermode.pwd, "getpwnam", lambda n: pwd.struct_passwd(("root", "x", 0, 0, "", "/root", "/bin/sh"))
        ):
            with self.assertRaises(SystemExit):
                self.c.turn_on("root")
        self.assertFalse(servermode.active())

    def test_start_on_a_free_console(self):
        sessions = {"1": "7 tty7", "2": "0 pts/0"}  # greetd's on console 7, an SSH login

        def run(argv, **k):
            if argv[0] == "pgrep":
                return Done(1)
            if argv[:2] == ["loginctl", "list-sessions"]:
                return Done(0, "".join(f"{s} 1000 tv seat0\n" for s in sessions))
            if argv[:2] == ["loginctl", "show-session"]:
                return Done(0, sessions[argv[2]].replace(" ", "\n"))
            return Done()

        self.c.start("bob", run=run)
        argv = self.c.calls[-1]
        self.assertEqual(argv[0], "systemd-run")
        self.assertIn("PAMName=login", argv)
        self.assertIn("TTYPath=/dev/tty1", argv)
        self.assertIn("User=bob", argv)
        self.assertEqual(argv[-1], "/usr/bin/tvwcs-session")
        self.assertIn(
            "ExecStopPost=+/bin/systemctl --no-block start getty@tty1.service", argv
        )  # as root: bob may not start a getty
        sessions["3"] = "1 tty1"
        self.assertEqual(servermode.free_console(run), 2)
        with self.assertRaises(SystemExit):
            self.c.start("bob", run=lambda argv, **k: Done(0))  # bob's sway runs already

    def test_switching_console_without_one_is_not_an_error(self):
        def opener(*a):
            raise PermissionError("no /dev/tty0")

        self.assertFalse(servermode.switch_console(1, opener))

    def test_command_line(self):
        self.assertEqual(servermode.parse(["-s"]), ("on", ""))
        self.assertEqual(servermode.parse(["--server-mode", "--user=bob"]), ("on", "bob"))
        self.assertEqual(servermode.parse(["--start", "--user=bob"]), ("start", "bob"))
        self.assertEqual(servermode.parse(["--no-server-mode"]), ("off", ""))
        self.assertEqual(servermode.parse(["--no-server-mode", "--user=bob"]), ("", ""))
        self.assertEqual(servermode.parse(["-s", "--bogus"]), ("", ""))
        self.assertEqual(servermode.parse(["server-mode", "on"]), ("on", ""))
        self.assertEqual(servermode.parse(["server-mode", "on", "--user=bob"]), ("on", "bob"))
        self.assertEqual(servermode.parse(["server-mode", "off"]), ("off", ""))
        self.assertEqual(servermode.parse(["server-mode", "status"]), ("status", ""))
        self.assertEqual(servermode.parse(["start-session", "--user=bob"]), ("start", "bob"))
        self.assertEqual(servermode.parse(["start-session"]), ("start", ""))
        for wrong in (
            ["server-mode"],
            ["server-mode", "maybe"],
            ["server-mode", "off", "--user=bob"],
            ["server-mode", "on", "-s"],
            ["start-session", "bob"],
            ["-s", "--no-server-mode"],
        ):
            self.assertEqual(servermode.parse(wrong), ("", ""), wrong)
        with mock.patch.object(servermode, "server_user", lambda: "bob"):
            self.assertEqual(servermode.status_text(), "Server mode is on for bob.")
        with mock.patch.object(servermode, "server_user", lambda: ""):
            self.assertEqual(servermode.status_text(), "Server mode is off.")
        answers = iter(["2", "bob"])
        ran = []
        with mock.patch.object(servermode, "as_root", lambda args: ran.append(args) or 0):
            self.assertEqual(servermode.menu(ask=lambda _p: next(answers), out=lambda *_a: None), 0)
        self.assertEqual(ran, [["on", "bob"]])

    def test_what_it_takes_away(self):
        ids = lambda server, dm: [a.id for a in system_actions.power_menu({}, dm, server)]
        self.assertEqual(ids(True, True), ["lock", "logout"])
        self.assertEqual(ids(True, False), ["lock"])
        self.assertEqual(ids(False, False), ["lock", "sleep", "reboot", "shutdown"])
        self.assertFalse(system_actions.allowed("sleep", True))
        self.assertTrue(system_actions.allowed("lock", True))
        self.assertTrue(system_actions.allowed("shutdown", False))
        settings = {
            "idle": {"screen_off": 600, "lock": 0, "sleep": 1800},
            "idle_battery": {"screen_off": 60, "lock": 0, "sleep": 600},
            "battery_critical": {"action": "shutdown", "percent": 5},
        }
        battery = mock.Mock(present=True, on_battery=True, percent=3)
        self.assertEqual(power.active_idle(settings, battery, True)["sleep"], 0)
        self.assertEqual(power.active_idle(settings, battery, True)["screen_off"], 60)
        self.assertEqual(power.active_idle(settings, battery, False)["sleep"], 600)
        self.assertEqual(power.critical(settings, battery, True), "")
        self.assertEqual(power.critical(settings, battery, False), "shutdown")


class AdminTests(unittest.TestCase):
    def test_a_standard_account_asks_an_administrator(self):
        seen = []

        def converse(argv, answers, timeout=30):
            seen.append((argv, answers))
            return 0, "", 2

        self.assertEqual(
            account.run_as_admin("alice", "pw", ["env", "python3", "-m", "tvwcs.servermode", "off"], run=converse),
            (0, ""),
        )
        argv, answers = seen[0]
        self.assertEqual(argv[:3], ["su", "alice", "-c"])
        self.assertIn("sudo -S -k -p Password: -- env python3", argv[3])
        self.assertEqual(answers, ["pw", "pw"])
        self.assertEqual(
            account.run_as_admin("alice", "no", ["true"], run=lambda *a, **k: (1, "su: Authentication failure", 1)),
            (1, "That is not alice's password."),
        )
        self.assertEqual(account.run_as_admin("x; rm", "pw", ["true"], run=converse)[0], 1)


if __name__ == "__main__":
    unittest.main()
