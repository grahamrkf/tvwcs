import os, tempfile, unittest
from unittest import mock
from pathlib import Path
from tvwcs.applications import _application_directories, _parse_desktop_file, match_window, Application


def app(desktop_id, name, wm_class=None, icon=None):
    return Application(desktop_id, name, None, None, icon, ("Other",), "/x", name.lower(), (), wm_class)


class ApplicationTests(unittest.TestCase):
    def _parse(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.desktop"
            p.write_text(text, encoding="utf-8")
            return _parse_desktop_file("test.desktop", p)

    def test_parse_desktop_entry(self):
        a = self._parse(
            "[Desktop Entry]\nType=Application\nName=Test App\nExec=test-app\nCategories=AudioVideo;Player;\nIcon=test-icon\n"
        )
        self.assertEqual((a.name, a.primary_category, a.icon), ("Test App", "Media", "test-icon"))

    def test_parses_desktop_actions(self):
        a = self._parse(
            "[Desktop Entry]\nType=Application\nName=Test App\nExec=test-app\nActions=NewWindow;Private;\n\n[Desktop Action NewWindow]\nName=New Window\nExec=test-app --new-window\n\n[Desktop Action Private]\nName=Private Window\nExec=test-app --private\n"
        )
        self.assertEqual(a.desktop_actions, (("NewWindow", "New Window"), ("Private", "Private Window")))

    def test_ignores_hidden(self):
        self.assertIsNone(self._parse("[Desktop Entry]\nType=Application\nName=Hidden\nHidden=true\nExec=hidden\n"))

    def test_startup_wm_class_is_parsed(self):
        self.assertEqual(
            self._parse("[Desktop Entry]\nType=Application\nName=Code\nExec=code\nStartupWMClass=Code\n").wm_class,
            "Code",
        )

    def test_match_prefers_wm_class(self):
        apps = [app("files.desktop", "Files"), app("org.gnome.Nautilus.desktop", "Nautilus", "org.gnome.Nautilus")]
        self.assertEqual(
            match_window({"class": "org.gnome.Nautilus", "instance": "x", "title": "Documents - profiles"}, apps).name,
            "Nautilus",
        )

    def test_match_by_class_and_none(self):
        apps = [app("firefox.desktop", "Firefox Web Browser")]
        self.assertEqual(
            match_window({"class": "firefox", "instance": "Navigator", "title": "x"}, apps).desktop_id,
            "firefox.desktop",
        )
        self.assertIsNone(match_window({"class": "zzz", "instance": "zzz", "title": "nothing"}, apps))


if __name__ == "__main__":
    unittest.main()
