import unittest
from tvwcs.applications import Application
from tvwcs.model import LaunchProfile
from tvwcs.workspaces import build_entries, quick_list, short_app_name, workspace_label


def app(name, wm_class):
    return Application(wm_class + ".desktop", name, None, None, None, ("Other",), "/x", "x", (), wm_class)


APPS = [app("Brave Web Browser", "brave-browser"), app("Text Editor", "gedit"), app("Files", "nautilus")]


def match(w):
    return next((a for a in APPS if a.wm_class in (w.get("class"), w.get("instance"))), None)


def win(i, cls, ws, title="t", urgent=False):
    return {
        "con_id": i,
        "class": cls,
        "instance": cls,
        "title": title,
        "workspace": ws,
        "output": "HDMI-1",
        "urgent": urgent,
    }


class WorkspaceTests(unittest.TestCase):
    def test_label_is_named_by_contents(self):
        self.assertEqual(
            workspace_label([win(1, "brave-browser", "1"), win(2, "gedit", "1")], match), "Brave + Text Editor"
        )

    def test_label_dedupes_and_truncates(self):
        wins = [
            win(1, "gedit", "1"),
            win(2, "gedit", "1"),
            win(3, "nautilus", "1"),
            win(4, "brave-browser", "1"),
            win(5, "mystery-app", "1"),
        ]
        self.assertEqual(workspace_label(wins, match), "Text Editor + Files + Brave + 1 more")

    def test_unknown_app_uses_its_class(self):
        self.assertEqual(workspace_label([win(1, "mystery-app", "1")], match), "Mystery app")

    def test_short_name(self):
        self.assertEqual(short_app_name("Brave Web Browser"), "Brave")
        self.assertEqual(short_app_name("Browser"), "Browser")

    def test_entries_lone_apps_and_shared_workspaces(self):
        wins = [
            win(1, "brave-browser", "1: web"),
            win(2, "gedit", "1: web"),
            win(3, "nautilus", "2"),
            win(4, "gedit", "__i3_scratch"),
        ]
        entries = build_entries(
            wins,
            [{"name": "1: web", "output": "DP-1", "visible": True, "focused": True}, {"name": "2", "output": "HDMI-1"}],
            match,
        )
        self.assertEqual(
            [(e.name, e.label, len(e.windows), e.shared) for e in entries],
            [
                ("1: web", "Brave + Text Editor", 2, True),
                ("2", "Files", 1, False),
                ("__i3_scratch", "Text Editor", 1, False),
            ],
        )
        self.assertEqual((entries[0].output, entries[0].visible, entries[0].focused), ("DP-1", True, True))

    def test_urgent_propagates(self):
        e = build_entries([win(1, "gedit", "1", urgent=True), win(2, "nautilus", "1")], [], match)[0]
        self.assertTrue(e.urgent)

    def test_numeric_workspace_order(self):
        names = [
            e.name
            for e in build_entries([win(1, "gedit", "10"), win(2, "gedit", "2"), win(3, "gedit", "web")], [], match)
        ]
        self.assertEqual(names, ["2", "10", "web"])


if __name__ == "__main__":
    unittest.main()


class QuickListTests(unittest.TestCase):
    def test_one_list_open_favorites_in_their_place(self):
        wins = [win(1, "gedit", "2"), win(2, "nautilus", "3"), win(3, "mystery-app", "3"), win(4, "vlc", "4")]
        entries = build_entries(wins, [], match)
        fav = [
            LaunchProfile("b", "brave-browser.desktop", "Brave"),
            LaunchProfile("g", "gedit.desktop", "Editor"),
            LaunchProfile("n", "nautilus.desktop", "Files"),
            LaunchProfile("c", "brave-browser.desktop", "Private", desktop_action="new-private-window"),
        ]
        opened = {"gedit.desktop": wins[0], "nautilus.desktop": wins[1], "brave-browser.desktop": {"con_id": 99}}
        rows, starred = quick_list(fav, entries, opened)
        got = [(k, x.name if k == "favorite" else x.name) for k, x in rows]
        # Brave's window is not in any entry: listed as the favorite. The editor, open alone, stands in its place.
        # Files shares workspace 3, so that workspace's row (in the open list) has it. A desktop action is always listed.
        self.assertEqual(
            got, [("favorite", "Brave"), ("entry", "2"), ("favorite", "Private"), ("entry", "3"), ("entry", "4")]
        )
        self.assertEqual(starred, {1, 2, 99})
