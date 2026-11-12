import unittest
from tvwcs.window_manager import WindowManager
from tvwcs.model import LAUNCH_NEW_WORKSPACE, LAUNCH_SAME


def con(i, title, cls, urgent=False):
    return {
        "type": "con",
        "id": i,
        "window": 100 + i,
        "name": title,
        "urgent": urgent,
        "window_properties": {"title": title, "class": cls, "instance": cls},
        "nodes": [],
        "floating_nodes": [],
    }


TREE = {
    "type": "root",
    "nodes": [
        {
            "type": "output",
            "name": "HDMI-1",
            "nodes": [
                {
                    "type": "workspace",
                    "name": "1: main",
                    "visible": True,
                    "nodes": [
                        con(10, "Firefox — Video", "firefox"),
                        con(11, "i3bar for output HDMI-1", "i3bar"),
                        con(12, "(4) Inbox", "thunderbird", True),
                    ],
                    "floating_nodes": [],
                },
                {
                    "type": "workspace",
                    "name": "2",
                    "visible": False,
                    "nodes": [con(13, "Terminal", "xterm")],
                    "floating_nodes": [],
                },
                {
                    "type": "workspace",
                    "name": "3",
                    "visible": False,
                    "nodes": [con(14, "A", "a"), con(15, "B", "b")],
                    "floating_nodes": [con(16, "TVWCS", "tvwcs"), con(17, "TVWCS · Launch Profile", "tvwcs")],
                },
            ],
            "floating_nodes": [],
        },
        {
            "type": "output",
            "name": "__i3",
            "nodes": [
                {
                    "type": "workspace",
                    "name": "__i3_scratch",
                    "nodes": [],
                    "floating_nodes": [con(18, "Hidden 1", "h"), con(19, "Hidden 2", "h")],
                }
            ],
            "floating_nodes": [],
        },
    ],
    "floating_nodes": [],
}


class FakeWM(WindowManager):
    """sway adapter whose IPC is replaced by a recorder."""

    def __init__(self, workspaces=(), outputs=()):
        super().__init__()
        self.binary = "/usr/bin/swaymsg"
        self.sent = []
        self._ws = list(workspaces)
        self._out = list(outputs)

    def _tree(self):
        return TREE

    def workspaces(self):
        return self._ws

    def outputs(self):
        return self._out

    def _call(self, *args, timeout=2):
        self.sent.append(" ".join(args))
        return '[{"success":true}]'


class WindowManagerTests(unittest.TestCase):
    def test_windows_exclude_bars_and_tvwcs(self):
        wm = FakeWM()
        titles = {w["title"] for w in wm.windows()}
        self.assertIn("Firefox — Video", titles)
        self.assertNotIn("i3bar for output HDMI-1", titles)
        self.assertFalse({"TVWCS", "TVWCS · Launch Profile"} & titles)

    def test_document_named_like_tvwcs_is_not_hidden(self):
        tree = TREE["nodes"][0]["nodes"][1]["nodes"]
        tree.append(con(30, "tvwcs.conf - Text Editor", "gedit"))
        tree.append(con(31, "TVWCS_notes.txt - Mousepad", "mousepad"))
        try:
            titles = {w["title"] for w in FakeWM().windows()}
        finally:
            del tree[-2:]
        self.assertIn("tvwcs.conf - Text Editor", titles)
        self.assertIn("TVWCS_notes.txt - Mousepad", titles)

    def test_untitled_window_is_listed_by_class(self):
        tree = TREE["nodes"][0]["nodes"][1]["nodes"]
        tree.append(con(32, "", "gedit"))
        try:
            found = [w for w in FakeWM().windows() if w["con_id"] == 32]
        finally:
            del tree[-1]
        self.assertEqual(found[0]["title"], "gedit")

    def test_windows_know_whether_their_workspace_is_on_screen(self):
        wm = FakeWM(
            workspaces=[
                {"name": "1: main", "visible": True},
                {"name": "2", "visible": False},
                {"name": "3", "visible": False},
            ]
        )
        by_id = {x["con_id"]: x for x in wm.windows()}
        self.assertTrue(by_id[10]["workspace_visible"])
        self.assertFalse(by_id[13]["workspace_visible"])
        self.assertFalse(by_id[18]["workspace_visible"])  # 18: parked

    def test_find_matching_returns_the_window_without_focusing_it(self):
        from tvwcs.model import LaunchProfile

        wm = FakeWM()
        found = wm.find_matching(LaunchProfile("p", "xterm.desktop", "Terminal"), None)
        self.assertEqual(found["con_id"], 13)
        self.assertEqual(wm.sent, [])
        self.assertIsNone(wm.find_matching(LaunchProfile("p", "nothing.desktop", "Nope"), None))

    def test_window_fields(self):
        w = next(w for w in FakeWM().windows() if w["con_id"] == 12)
        self.assertEqual((w["workspace"], w["output"], w["urgent"]), ("1: main", "HDMI-1", True))

    def test_new_workspace_number_is_lowest_free(self):
        wm = FakeWM(
            workspaces=[
                {"name": "1: main", "num": 1},
                {"name": "2", "num": 2},
                {"name": "4", "num": 4},
                {"name": "misc", "num": -1},
            ]
        )
        self.assertEqual(wm.new_workspace_number(), 3)

    def test_prepare_for_launch_modes(self):
        wm = FakeWM(workspaces=[{"name": "1", "num": 1, "focused": True}])
        self.assertIsNone(wm.prepare_for_launch(LAUNCH_SAME))
        self.assertFalse(any(c.startswith("workspace number") for c in wm.sent))
        self.assertEqual(wm.prepare_for_launch(LAUNCH_NEW_WORKSPACE), "2")
        self.assertIn("workspace number 2", wm.sent)

    def test_focus_same_pulls_window_to_current_workspace(self):
        wm = FakeWM()
        self.assertTrue(wm.focus(13, LAUNCH_SAME))
        self.assertIn("[con_id=13] move container to workspace current", wm.sent)

    def test_focus_new_workspace_mode_just_shows_a_lone_window(self):
        wm = FakeWM()
        self.assertTrue(wm.focus(13, LAUNCH_NEW_WORKSPACE))  # alone on workspace "2"
        self.assertFalse(any("move container" in c for c in wm.sent))
        self.assertIn("[con_id=13] focus", wm.sent)

    def test_focus_new_workspace_mode_splits_a_shared_window_off(self):
        wm = FakeWM(workspaces=[{"name": "1: main", "num": 1}, {"name": "2", "num": 2}, {"name": "3", "num": 3}])
        self.assertTrue(wm.focus(14, LAUNCH_NEW_WORKSPACE))  # shares "3"
        self.assertIn("[con_id=14] move container to workspace number 4", wm.sent)

    def test_close_workspace_kills_each_window(self):
        wm = FakeWM()
        self.assertTrue(wm.close_workspace("3"))
        self.assertEqual(sorted(c for c in wm.sent if c.endswith("kill")), ["[con_id=14] kill", "[con_id=15] kill"])
        self.assertFalse(FakeWM().close_workspace("nope"))

    def test_focus_parked_window_gets_its_own_workspace(self):
        wm = FakeWM(workspaces=[{"name": "1", "num": 1}])
        wm.focus(18, LAUNCH_NEW_WORKSPACE)
        self.assertIn("[con_id=18] move container to workspace number 2", wm.sent)

    def test_place_tvwcs_command(self):
        wm = FakeWM()
        wm.place_tvwcs(20, 50, 460, 1010)
        self.assertEqual(
            wm.sent[-1],
            '[title="^TVWCS$"] floating enable, border pixel 0, resize set 460 1010, move absolute position 20 50, opacity 1',
        )

    def test_focus_workspace_brings_it_to_pointer_output(self):
        wm = FakeWM(
            workspaces=[
                {"name": "3", "output": "HDMI-2", "num": 3},
                {"name": "1", "output": "HDMI-1", "num": 1, "focused": True},
            ],
            outputs=[{"name": "HDMI-1"}, {"name": "HDMI-2"}],
        )
        wm.focus_output_under_mouse = lambda: "HDMI-1"
        wm.focus_workspace("3")
        self.assertEqual(wm.sent, ['workspace "3"', "move workspace to output HDMI-1"])

    def test_move_workspace_to_chosen_output(self):
        wm = FakeWM(outputs=[{"name": "HDMI-1"}, {"name": "HDMI-2"}])
        self.assertTrue(wm.move_workspace_to_output("3", "HDMI-2"))
        self.assertEqual(wm.sent, ['workspace "3"', "move workspace to output HDMI-2"])
        self.assertFalse(wm.move_workspace_to_output("3", "DP-9"))

    def test_restore_fullscreen(self):
        tree = TREE["nodes"][0]["nodes"]
        tree[0]["nodes"][0]["focused"] = True
        try:
            wm = FakeWM(workspaces=[{"name": "1: main", "focused": True}])
            self.assertEqual({w["con_id"]: w["fullscreen"] for w in wm.windows()}[10], False)
            wm.restore_fullscreen(
                {10, 12, 13, 99}
            )  # 12 shares the current workspace with the focused 10; 99 has closed
            self.assertEqual(wm.sent, ["[con_id=10] fullscreen enable", "[con_id=13] fullscreen enable"])
            wm = FakeWM(workspaces=[{"name": "1: main", "focused": True}])
            wm.restore_fullscreen({10, 13}, skip_current=True)  # just launched an app here
            self.assertEqual(wm.sent, ["[con_id=13] fullscreen enable"])
            tree[1]["nodes"][0]["fullscreen_mode"] = 1  # 13 still is: nothing to do
            wm = FakeWM(workspaces=[{"name": "1: main", "focused": True}])
            self.assertEqual(wm.fullscreen_windows(), {13})
            wm.restore_fullscreen({13})
            self.assertEqual(wm.sent, [])
            tree[0]["nodes"][0][
                "fullscreen_mode"
            ] = 1  # 10, on the current workspace, and 13 elsewhere are both fullscreen
            wm = FakeWM(workspaces=[{"name": "1: main", "focused": True}])
            wm.leave_fullscreen()
            self.assertEqual(wm.sent, ["[con_id=10] fullscreen disable"])  # only the one TVWCS opens over
        finally:
            tree[0]["nodes"][0].pop("focused", None)
            tree[0]["nodes"][0].pop("fullscreen_mode", None)
            tree[1]["nodes"][0].pop("fullscreen_mode", None)

    def test_sway_uses_swaymsg_and_lists_wayland_windows(self):
        from unittest import mock

        with mock.patch("tvwcs.window_manager.shutil.which", lambda name: f"/usr/bin/{name}"):
            sway = WindowManager()
        self.assertEqual(sway.binary, "/usr/bin/swaymsg")
        tree = TREE["nodes"][0]["nodes"][1]["nodes"]
        tree.append(
            {
                "type": "con",
                "id": 40,
                "window": None,
                "app_id": "org.gnome.Nautilus",
                "name": "Files",
                "nodes": [],
                "floating_nodes": [],
            }
        )
        tree.append(
            {
                "type": "con",
                "id": 41,
                "window": None,
                "app_id": None,
                "name": "split container",
                "nodes": [],
                "floating_nodes": [],
            }
        )
        try:
            found = {w["con_id"]: w for w in FakeWM().windows()}
        finally:
            del tree[-2:]
        self.assertEqual((found[40]["class"], found[40]["title"]), ("org.gnome.Nautilus", "Files"))
        self.assertNotIn(41, found)

    def test_workspace_name_is_quoted(self):
        wm = FakeWM(workspaces=[{"name": 'we"ird', "output": "A", "num": -1, "focused": True}], outputs=[{"name": "A"}])
        wm.focus_output_under_mouse = lambda: "A"
        wm.focus_workspace('we"ird')
        self.assertEqual(wm.sent[0], 'workspace "we\\"ird"')


class ScreenTests(unittest.TestCase):
    def test_only_windows_on_a_shown_workspace_count(self):
        shown = FakeWM(workspaces=[{"name": "1: main", "visible": True}])
        self.assertTrue(shown.screen_has_windows())
        hidden = FakeWM(workspaces=[{"name": "1: main", "visible": False}, {"name": "2", "visible": False}])
        self.assertFalse(hidden.screen_has_windows())
        self.assertTrue(FakeWM(workspaces=[{"name": "2", "visible": True}]).screen_has_windows())

    def test_where_tvwcs_is(self):
        self.assertFalse(FakeWM(workspaces=[{"name": "1: main", "visible": True}]).tvwcs_on_screen())
        self.assertTrue(FakeWM(workspaces=[{"name": "3", "visible": True}]).tvwcs_on_screen())

    def test_urgent_windows(self):
        self.assertEqual(FakeWM().urgent_ids(), {12})


if __name__ == "__main__":
    unittest.main()
