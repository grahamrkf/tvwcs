import unittest
from tvwcs.system.system_actions import (
    SYSTEM_ACTIONS,
    command_for,
    lock_command,
    login_manager_installed,
    logout_command,
    can_log_out,
    power_menu,
    unavailable_message,
)

from unittest import mock as _mock
from tvwcs.system import servermode as _servermode

# These tests are about a computer without server mode, whatever the one running them has in /etc/tvwcs/server-mode.
_not_server = _mock.patch.object(_servermode, "server_user", lambda: "")


def setUpModule():
    _not_server.start()


def tearDownModule():
    _not_server.stop()


class SystemActionTests(unittest.TestCase):
    def test_dialog_contents(self):
        ids = [a.id for a in SYSTEM_ACTIONS]
        self.assertIn("lock", ids)
        self.assertIn("refresh", ids)

    def test_confirmation_only_for_logout_reboot_shutdown(self):
        self.assertEqual({a.id for a in SYSTEM_ACTIONS if a.confirm}, {"logout", "reboot", "shutdown"})

    def test_lock_prefers_configured_command(self):
        self.assertEqual(lock_command("slock -x", {}, lambda c: None), ["slock", "-x"])

    def test_lock_autodetect_and_fallback(self):
        have = lambda names: (lambda c: "/usr/bin/" + c if c in names else None)
        self.assertEqual(lock_command("", {}, have({"swaylock", "loginctl"})), ["swaylock", "-f", "-c", "000000"])
        self.assertEqual(lock_command("", {}, have({"loginctl"})), ["loginctl", "lock-session"])
        self.assertIsNone(lock_command("", {}, have(set())))  # nothing to lock with: Settings says so

    def test_logout_command(self):
        self.assertIsNone(logout_command({}, lambda c: None))
        self.assertEqual(logout_command({"SWAYSOCK": "/s"}, lambda c: "/x"), ["swaymsg", "exit"])

    def test_command_for(self):
        have = lambda names: (lambda c: "/usr/bin/" + c if c in names else None)
        systemd = have({"systemctl", "loginctl"})
        self.assertEqual(command_for("shutdown", which=systemd, systemd=True), ["systemctl", "poweroff"])
        self.assertEqual(command_for("reboot", which=systemd, systemd=True), ["systemctl", "reboot"])
        self.assertEqual(command_for("sleep", which=systemd, systemd=True), ["systemctl", "suspend"])
        self.assertIsNone(command_for("refresh"))

    def test_power_without_systemd(self):
        have = lambda names: (lambda c: "/usr/bin/" + c if c in names else None)
        # only systemd is supported: systemctl installed but not in charge, or plain commands, do nothing
        self.assertIsNone(
            command_for("shutdown", which=have({"systemctl", "loginctl", "reboot", "poweroff"}), systemd=False)
        )
        self.assertIsNone(command_for("sleep", which=have(set()), systemd=True))
        self.assertIn("systemd", unavailable_message("reboot"))
        self.assertIn("lock_command", unavailable_message("lock"))

    def test_power_menu_offers_lock_and_log_out_with_a_login_screen(self):
        ids = lambda settings, dm: [a.id for a in power_menu(settings, dm)]
        self.assertEqual(ids({}, False), ["lock", "sleep", "reboot", "shutdown"])
        self.assertEqual(ids({"quick_lock_button": False}, True), ["lock", "sleep", "reboot", "shutdown", "logout"])

    def test_finds_a_login_screen(self):
        self.assertTrue(
            login_manager_installed(lambda p: p == "/etc/systemd/system/display-manager.service", lambda n: None)
        )
        self.assertFalse(
            login_manager_installed(lambda p: False, lambda n: "/usr/sbin/lightdm" if n == "lightdm" else None)
        )  # installed, not started
        stale = lambda p: p in ("/run/systemd/system", "/etc/X11/default-display-manager")
        self.assertFalse(
            login_manager_installed(stale)
        )  # disabled under systemd: its default-display-manager stays behind

    def test_log_out_follows_how_this_login_started(self):
        class Out:
            def __init__(self, text, code=0):
                self.stdout = text
                self.returncode = code

        dm = lambda p: p == "/etc/systemd/system/display-manager.service"
        env = {"XDG_SESSION_ID": "3"}
        self.assertFalse(
            can_log_out(env, lambda *a, **k: Out("login\n"), dm)
        )  # a text console, though a login screen is set up
        self.assertTrue(can_log_out(env, lambda *a, **k: Out("greetd\n"), lambda p: False))
        self.assertTrue(can_log_out(env, lambda *a, **k: Out("", 1), dm))  # logind cannot say: the login screen decides
        self.assertFalse(can_log_out({}, lambda *a, **k: Out("greetd"), lambda p: False))


if __name__ == "__main__":
    unittest.main()
