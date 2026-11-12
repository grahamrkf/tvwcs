import re, unittest
from tvwcs import appearance, model, retro


class RetroIconTests(unittest.TestCase):
    def test_icon_names(self):
        self.assertEqual(retro.retro_icon_name("audio-volume-high-symbolic"), "tvwcs-retro-volume-high-symbolic")
        self.assertEqual(retro.retro_icon_name("view-more-symbolic"), "tvwcs-retro-dots-symbolic")
        self.assertEqual(retro.retro_icon_name("non-starred-symbolic"), "tvwcs-retro-star-off-symbolic")
        self.assertIsNone(retro.retro_icon_name("no-such-icon-symbolic"))
        self.assertIsNone(retro.retro_icon_name(None))

    def test_wifi_and_battery_levels(self):
        self.assertEqual(retro.retro_icon_name("network-wireless-signal-none-symbolic"), "tvwcs-retro-wifi-1-symbolic")
        self.assertEqual(
            retro.retro_icon_name("network-wireless-signal-excellent-symbolic"), "tvwcs-retro-wifi-5-symbolic"
        )
        self.assertEqual(retro.retro_icon_name("battery-level-10-symbolic"), "tvwcs-retro-battery-0-symbolic")
        self.assertEqual(retro.retro_icon_name("battery-level-50-symbolic"), "tvwcs-retro-battery-2-symbolic")
        self.assertEqual(retro.retro_icon_name("battery-level-100-charged-symbolic"), "tvwcs-retro-battery-3-symbolic")
        self.assertEqual(
            retro.retro_icon_name("battery-level-40-charging-symbolic"), "tvwcs-retro-battery-charging-symbolic"
        )

    def test_every_icon_named_is_drawn(self):
        names = (
            set(retro.ICONS.values())
            | {f"wifi-{n}" for n in range(1, 6)}
            | {f"battery-{n}" for n in range(4)}
            | {"battery-charging", "check"}
        )
        for name in names:
            for prefix in retro.ICON_SETS.values():
                self.assertTrue((retro.ICON_FILES / f"{prefix}-{name}-symbolic.svg").is_file(), (prefix, name))

    def test_icons_are_9_by_9_pixels(self):
        for path in retro.ICON_FILES.glob("*.svg"):
            self.assertIn('viewBox="0 0 9 9"', path.read_text(encoding="ascii"), path.name)

    def test_sizes_are_whole_multiples(self):
        self.assertEqual(retro.icon_pixel_size(22), 18)
        self.assertEqual(retro.icon_pixel_size(33), 36)
        self.assertEqual(retro.icon_pixel_size(4), 9)

    def test_fonts_and_static_are_there(self):
        for f in (*retro.FONT_FILES, retro.STATIC_PICTURE):
            self.assertGreater(f.stat().st_size, 1000, f.name)
        self.assertEqual(retro.STATIC_PICTURE.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class RetroSettingsTests(unittest.TestCase):
    def test_defaults_are_modern(self):
        s = model._clean_settings({})
        self.assertEqual(
            (s["style"], s["phosphor"], s["retro_wallpaper"], s["retro_font"]), ("modern", "green", "gray", "pixel")
        )
        self.assertEqual(model.wallpaper_of(s), model.DEFAULT_WALLPAPER)
        self.assertEqual(model._clean_settings({"retro_font": "vt323"})["retro_font"], "vt323")
        self.assertEqual(model._clean_settings({"retro_font": "comic"})["retro_font"], "pixel")

    def test_retro_choices_are_kept_and_bad_ones_dropped(self):
        s = model._clean_settings(
            {"style": "retro", "phosphor": "amber", "retro_wallpaper": "static", "theme": "light"}
        )
        self.assertEqual((s["style"], s["phosphor"], s["retro_wallpaper"]), ("retro", "amber", "static"))
        self.assertEqual(model.wallpaper_of(s), "static")
        self.assertTrue(model.dark_look(s))  # Retro is always dark
        s = model._clean_settings({"style": "neon", "phosphor": "pink", "retro_wallpaper": "#123456"})
        self.assertEqual((s["style"], s["phosphor"], s["retro_wallpaper"]), ("modern", "green", "gray"))

    def test_retro_backgrounds(self):
        self.assertEqual(model.wallpaper_of({"style": "retro", "retro_wallpaper": "blue"}), "#0000ff")
        self.assertEqual(appearance.wallpaper_argv("#0000ff"), ["swaymsg", "output * bg #0000ff solid_color"])
        self.assertEqual(appearance.wallpaper_argv("static"), ["swaymsg", f'output * bg "{retro.STATIC_PICTURE}" fill'])


from tvwcs import theme  # needs no GTK


class RetroThemeTests(unittest.TestCase):
    def test_retro_sizes_are_on_the_pixel_grid(self):
        for scale in (1.0, 1.5, 2.0, 3.0):
            css = theme.render_css("#0078d7", scale, style="retro", phosphor="green")
            for size in re.findall(r"font-size:\s*(\d+)px", css):
                self.assertEqual(int(size) % 8, 0, (scale, size))

    def test_large_text_uses_the_8x8_font(self):
        css = theme.render_css("#0078d7", style="retro")
        clock = next(l for l in css.splitlines() if l.startswith(".clock-time"))
        self.assertIn("TVWCS Pixel 8x8", clock)
        self.assertIn("TVWCS Pixel 5x7", css)
        self.assertNotIn("font-weight: 700", css)

    def test_list_and_button_text_uses_the_thinner_8x16_font(self):
        for scale in (0.6, 1.0, 1.6, 2.0):
            css = theme.render_css("#0078d7", scale, style="retro")
            button = next(l for l in css.splitlines() if l.startswith("button { "))
            self.assertIn("TVWCS Pixel 8x16", button)
            self.assertEqual(int(re.search(r"font-size:\s*(\d+)px", button).group(1)) % 16, 0, scale)
        badge = next(l for l in theme.render_css("#0078d7", style="retro").splitlines() if l.startswith(".badge {"))
        self.assertNotIn("8x16", badge)  # the smallest text keeps the 5 x 7 font
        self.assertEqual(
            (theme.snap_font_size(13, 1.6), theme.snap_font_size(15, 1.6)), (16, 32)
        )  # notes a step smaller

    def test_vt323_and_inter_replace_the_pixel_fonts(self):
        vt = theme.render_css("#0078d7", 1.0, style="retro", retro_font="vt323")
        self.assertIn('"VT323"', vt)
        self.assertNotIn("TVWCS Pixel", vt)
        button = next(l for l in vt.splitlines() if l.startswith("button { "))
        self.assertIn("font-size: 21px", button)  # 15 px, 40 % larger
        inter = theme.render_css("#0078d7", 1.6, style="retro", retro_font="readable")
        self.assertIn('"Inter"', inter)
        self.assertNotIn("TVWCS Pixel", inter)
        self.assertIn("font-weight: 200", inter)  # Modern's weights
        self.assertIn(
            "font-size: 24px", next(l for l in inter.splitlines() if l.startswith("button { "))
        )  # scaled, not snapped
        self.assertIn("tvwcs-vt-check-symbolic", vt)
        self.assertIn('"liga" 0', vt)
        self.assertNotIn('"liga" 0', inter)  # VT323 would draw "fi" as one cell
        self.assertEqual(retro.retro_icon_name("view-more-symbolic", "tvwcs-vt"), "tvwcs-vt-dots-symbolic")
        self.assertIn("TVWCS Pixel", theme.render_css("#0078d7", style="retro", retro_font="nonsense"))

    def test_phosphor_replaces_the_accent(self):
        css = theme.render_css("#e81123", style="retro", phosphor="amber")
        self.assertIn("#ffb000", css)
        self.assertNotIn("@", re.sub(r"@media", "", css))
        retro_rules = css.split('window.tvwcs-window, .tvwcs-root { font-family: "TVWCS Pixel 5x7"')[1]
        self.assertNotIn("#e81123", retro_rules.split(".tile-")[0])

    def test_modern_is_unchanged(self):
        self.assertNotIn("TVWCS Pixel", theme.render_css("#0078d7"))
        self.assertIn("#0078d7", theme.render_css("#0078d7"))


if __name__ == "__main__":
    unittest.main()
