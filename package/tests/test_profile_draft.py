"""The profile editor's draft: what is stored when Save is pressed (no display needed)."""

import unittest
from types import SimpleNamespace

from tvwcs.model import LAUNCH_NEW_WORKSPACE, LAUNCH_SAME, LaunchProfile
from tvwcs.pinlock import check_pin
from tvwcs.profile_draft import ProfileDraft


class ProfileDraftTests(unittest.TestCase):
    def test_round_trip(self):
        p = LaunchProfile(
            id="a",
            desktop_id="x.desktop",
            name="X",
            channel=7,
            launch_mode=LAUNCH_NEW_WORKSPACE,
            hotkey="F5",
            favorite=True,
        )
        d = ProfileDraft.of(p)
        self.assertEqual(d.channel, "7")
        self.assertTrue(d.new_workspace)
        self.assertEqual(d.profile(), p)

    def test_new_profile(self):
        d = ProfileDraft.new("x.desktop", "X profile 2")
        d.channel = " 12 "
        p = d.profile()
        self.assertEqual((p.channel, p.launch_mode, p.name), (12, LAUNCH_SAME, "X profile 2"))
        self.assertTrue(p.id)
        d.channel = ""
        self.assertIsNone(d.profile().channel)
        d.channel = "1a"
        self.assertRaises(ValueError, d.profile)

    def test_pin(self):
        d = ProfileDraft.new("x.desktop", "X")
        self.assertRaises(ValueError, d.set_pin, "12", "12")
        self.assertRaises(ValueError, d.set_pin, "1234", "1235")
        self.assertEqual(d.pin_hash, "")
        d.set_pin("1234", "1234")
        self.assertTrue(check_pin("1234", d.profile().pin_hash))

    def test_profile_names_follow_the_application_name(self):
        from tvwcs.model import LaunchProfile, display_name, next_label, profile_label, default_of

        main = LaunchProfile("a", "kodi.desktop", "Kodi")
        old = LaunchProfile("b", "kodi.desktop", "Kodi profile 2")
        new = LaunchProfile("c", "kodi.desktop", "3")
        self.assertIs(default_of([new, old, main], "Kodi"), main)
        self.assertEqual(
            [display_name(p, "Kodi", p is main) for p in (main, old, new)], ["Kodi", "Kodi profile 2", "Kodi 3"]
        )
        self.assertEqual([profile_label(p, "Kodi", p is main) for p in (main, old, new)], ["Default", "profile 2", "3"])
        self.assertEqual(next_label(["Default", "3"]), "2")
        self.assertEqual(next_label(["Default", "2", "3"]), "4")


if __name__ == "__main__":
    unittest.main()
