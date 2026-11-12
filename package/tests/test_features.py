"""features.py: the software each Settings page needs, and how it is installed."""

import unittest
from unittest import mock

from tvwcs.system import features as F


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.which = mock.patch.object(F.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}")
        self.which.start()

    def tearDown(self):
        self.which.stop()

    def test_each_page_knows_the_software_it_needs(self):
        self.assertEqual(F.PAGE_FEATURE["sound"], "sound")
        self.assertNotIn("apps", F.PAGE_FEATURE)
        self.assertNotIn("storage", F.BY_KEY)
        self.assertNotIn("network", F.BY_KEY)
        self.assertFalse(hasattr(F, "enabled"))  # 4.0: no on/off switch, what is installed is used

    def test_5_0_drops_the_screen_saver_terminal_and_network_shares(self):
        for gone in ("screensaver", "sway_saver", "lock_saver", "cursor", "terminal", "samba"):
            self.assertNotIn(gone, F.BY_KEY)

    def test_package_names_are_checked(self):
        with self.assertRaises(ValueError):
            F.install_argv(["bluez; rm -rf /"])
        self.assertEqual(F.install_argv(["bluez"])[-1], "bluez")
        self.assertEqual(F.remove_argv(["cloud-init"])[-3:], ["remove", "-y", "cloud-init"])
        with self.assertRaises(ValueError):
            F.remove_argv(["cloud-init; reboot"])


if __name__ == "__main__":
    unittest.main()
