import contextlib, io, subprocess, unittest
from unittest import mock
from tvwcs import control_ubuntu as ubuntu
from tvwcs.control_cmd import Result

SIMULATION = """NOTE: This is only a simulation!
Reading package lists...
The following packages will be REMOVED:
  firefox* snapd* ubuntu-desktop-minimal*
Purg firefox [1:1snap1-0ubuntu5]
Remv ubuntu-desktop-minimal [1.539]
Purg snapd [2.66]
"""
SNAP_LIST = """Name      Version  Rev    Tracking       Publisher   Notes
bare      1.0      5      latest/stable  canonical✓  base
core22    20240111 1122   latest/stable  canonical✓  base
firefox   131.0    5134   latest/stable  mozilla✓    -
gnome-42-2204 0+git 176   latest/stable  canonical✓  -
snapd     2.65     23258  latest/stable  canonical✓  snapd
thunderbird 128.0  500    latest/stable  canonical✓  -
"""


class UbuntuTests(unittest.TestCase):
    def test_ubuntu_and_its_family_only(self):
        self.assertTrue(ubuntu.is_ubuntu("ID=ubuntu\nID_LIKE=debian\n"))
        self.assertTrue(ubuntu.is_ubuntu('ID=linuxmint\nID_LIKE="ubuntu debian"\n'))
        self.assertFalse(ubuntu.is_ubuntu("ID=debian\n"))
        self.assertFalse(ubuntu.is_ubuntu('ID=elementary\nNAME="ubuntu-like"\n'))

    def test_removals_from_a_simulation(self):
        self.assertEqual(ubuntu.parse_removals(SIMULATION), ["firefox", "ubuntu-desktop-minimal", "snapd"])
        with mock.patch.object(ubuntu, "run", lambda argv, timeout=0: Result(True, 0, SIMULATION, "")):
            self.assertEqual(ubuntu.would_remove(["snapd"], run=ubuntu.run), ["firefox", "ubuntu-desktop-minimal"])

    def test_snap_apps_leave_out_bases_and_support_snaps(self):
        self.assertEqual(ubuntu.parse_snap_list(SNAP_LIST), ["firefox", "thunderbird"])

    def test_installed_extras_lists_only_whats_installed(self):
        def fake(argv, timeout=0):
            return Result(
                True, 0, "snapd\tii \ncloud-init\trc \nubuntu-pro-client\tii \nubuntu-advantage-tools\tii \n", ""
            )

        with mock.patch.object(ubuntu, "is_ubuntu", lambda: True), mock.patch.object(ubuntu, "have", lambda c: True):
            found = [(e.key, p) for e, p in ubuntu.installed_extras(run=fake)]
        self.assertEqual(found, [("snap", ["snapd"]), ("pro", ["ubuntu-pro-client", "ubuntu-advantage-tools"])])
        with mock.patch.object(ubuntu, "is_ubuntu", lambda: False):
            self.assertEqual(ubuntu.installed_extras(run=fake), [])

    def test_purge_keeps_what_metapackages_brought_in(self):
        argv = ubuntu.purge_argv(["snap", "pro"])
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertEqual(argv[4:], ["snapd", *ubuntu.BY_KEY["pro"].packages])
        script = argv[2]
        self.assertLess(script.index("apt-mark manual"), script.index("apt-get purge -y"))
        self.assertNotIn("pin", script.lower())
        subprocess.run(["sh", "-n", "-c", script], check=True)
        with self.assertRaises(KeyError):
            ubuntu.purge_argv(["bogus"])

    def test_command_line_takes_only_known_extras(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ubuntu.main(["purge", "bogus"]), 2)
            self.assertEqual(ubuntu.main([]), 2)


if __name__ == "__main__":
    unittest.main()
