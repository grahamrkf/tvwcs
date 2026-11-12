"""Hiding the mouse pointer (cursor.py): when, for how long, and what runs."""

import unittest

from tvwcs.system import cursor


class CursorTests(unittest.TestCase):
    def test_only_in_tv_mode(self):
        self.assertTrue(cursor.hide_enabled({}, {"TVWCS_SESSION": "sway"}))
        self.assertFalse(cursor.hide_enabled({}, {}))
        self.assertEqual(cursor.hide_seconds({}), 3)

    def test_sway_command(self):
        self.assertEqual(cursor.sway_command(True, 3), "seat * hide_cursor 3000")
        self.assertEqual(cursor.sway_command(False, 3), "seat * hide_cursor 0")

    def test_hider_tells_sway_once(self):
        ran = []
        h = cursor.CursorHider(run=lambda argv, **k: ran.append(argv))
        h.apply({}, {"SWAYSOCK": "/run/sway", "TVWCS_SESSION": "sway"})
        h.apply({}, {"SWAYSOCK": "/run/sway", "TVWCS_SESSION": "sway"})
        self.assertEqual(ran, [["swaymsg", "seat * hide_cursor 3000"]])
        h.apply({}, {})
        self.assertEqual(ran[-1], ["swaymsg", "seat * hide_cursor 0"])


if __name__ == "__main__":
    unittest.main()
