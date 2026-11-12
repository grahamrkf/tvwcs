import tempfile, unittest
from pathlib import Path
from unittest import mock
from tvwcs.system import appearance


class AppearanceTests(unittest.TestCase):
    def test_dark_preference_is_added_to_an_empty_file(self):
        self.assertEqual(appearance.with_dark_preference("", True), "[Settings]\ngtk-application-prefer-dark-theme=1\n")

    def test_dark_preference_replaces_the_old_value_and_keeps_the_rest(self):
        text = "[Settings]\ngtk-theme-name=Adwaita\ngtk-application-prefer-dark-theme=1\n[Other]\nx=1\n"
        out = appearance.with_dark_preference(text, False)
        self.assertIn("gtk-theme-name=Adwaita", out)
        self.assertIn("[Other]\nx=1", out)
        self.assertEqual(out.count("gtk-application-prefer-dark-theme"), 1)
        self.assertFalse(appearance.gtk_prefers_dark(out))

    def test_dark_preference_goes_into_settings_not_another_section(self):
        out = appearance.with_dark_preference("[Settings]\na=1\n[Other]\nb=2\n", True)
        self.assertLess(out.index("gtk-application-prefer-dark-theme"), out.index("[Other]"))
        self.assertTrue(appearance.gtk_prefers_dark(out))

    def test_reading_the_preference(self):
        self.assertIsNone(appearance.gtk_prefers_dark(""))
        self.assertIsNone(appearance.gtk_prefers_dark("not ini at all ["))
        self.assertTrue(appearance.gtk_prefers_dark("[Settings]\ngtk-application-prefer-dark-theme=true\n"))

    def test_colour_scheme_and_wallpaper_commands(self):
        self.assertEqual(appearance.color_scheme("dark"), "prefer-dark")
        self.assertEqual(appearance.color_scheme("light"), "default")
        self.assertEqual(appearance.wallpaper_argv("#323232"), ["swaymsg", "output * bg #323232 solid_color"])

    def test_apply_theme_writes_both_gtk_files(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(appearance, "have", return_value=False):
            self.assertEqual(appearance.apply_theme("light", env={"XDG_CONFIG_HOME": d}), "")
            for v in ("gtk-3.0", "gtk-4.0"):
                self.assertFalse(appearance.gtk_prefers_dark((Path(d) / v / "settings.ini").read_text()))

    def test_portal_missing(self):
        self.assertTrue(appearance.portal_missing(which=lambda n: None, exists=lambda p: False))
        self.assertFalse(
            appearance.portal_missing(which=lambda n: None, exists=lambda p: p == "/usr/libexec/xdg-desktop-portal-gtk")
        )


if __name__ == "__main__":
    unittest.main()
