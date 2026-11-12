import unittest
from tvwcs.system.privilege import absolute, doas_command, needs_root, polkit_refused, sudo_command, sudo_outcome

have = lambda names: (lambda c: f"/usr/sbin/{c}" if c in names else None)


class PrivilegeTests(unittest.TestCase):
    def test_which_commands_need_root(self):
        self.assertTrue(needs_root(["reboot"], euid=1000))
        self.assertTrue(needs_root(["/usr/sbin/poweroff"], euid=1000))
        self.assertFalse(needs_root(["reboot"], euid=0))
        self.assertFalse(needs_root(["systemctl", "reboot"], euid=1000))  # polkit decides

    def test_polkit_refusals(self):
        self.assertTrue(polkit_refused("Failed to reboot system via logind: Interactive authentication required."))
        self.assertTrue(polkit_refused("Failed to power off system via logind: Access denied"))
        self.assertFalse(polkit_refused("Failed to connect to bus: No such file or directory"))
        self.assertFalse(polkit_refused(""))

    def test_commands_name_programs_by_full_path(self):
        which = have({"sudo", "doas", "reboot"})
        self.assertEqual(absolute(["reboot"], which), ["/usr/sbin/reboot"])
        self.assertEqual(sudo_command(["reboot"], which=which), ["sudo", "-n", "--", "/usr/sbin/reboot"])
        self.assertEqual(sudo_command(["reboot"], True, which), ["sudo", "-S", "-p", "", "--", "/usr/sbin/reboot"])
        self.assertEqual(
            doas_command(["systemctl", "poweroff"], have({"doas"})), ["doas", "-n", "systemctl", "poweroff"]
        )
        self.assertIsNone(sudo_command(["reboot"], which=have(set())))
        self.assertIsNone(doas_command(["reboot"], have(set())))

    def test_sudo_outcomes_from_real_sudo_messages(self):  # captured from sudo 1.9 with LC_ALL=C
        self.assertEqual(sudo_outcome(0, ""), "ok")
        self.assertEqual(sudo_outcome(1, "sudo: a password is required"), "password")
        self.assertEqual(
            sudo_outcome(1, "Sorry, try again.\n\nsudo: no password was provided\nsudo: 1 incorrect password attempt"),
            "wrong",
        )
        self.assertEqual(sudo_outcome(1, "tvnobody is not in the sudoers file."), "denied")
        self.assertEqual(
            sudo_outcome(1, "Sorry, user tv is not allowed to execute '/usr/sbin/reboot' as root on box."), "denied"
        )
        self.assertEqual(sudo_outcome(1, "sudo: sorry, you must have a tty to run sudo"), "tty")
        self.assertEqual(sudo_outcome(1, "Failed to reboot: something else"), "error")


if __name__ == "__main__":
    unittest.main()
