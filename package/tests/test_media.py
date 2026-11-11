import re, unittest
from tvwcs import lockscreen, model, theme

class MediaSettingsTests(unittest.TestCase):
    def test_media_look_is_kept_and_bad_ones_dropped(self):
        s=model._clean_settings({})
        self.assertEqual(s["media_look"],"jellyfin")
        s=model._clean_settings({"style":"media","media_look":"plex","theme":"light"})
        self.assertEqual((s["style"],s["media_look"]),("media","plex"))
        self.assertTrue(model.dark_look(s))   # Media is always dark
        self.assertEqual(model.wallpaper_of(s),model.MEDIA_WALLPAPERS["plex"])
        self.assertEqual(model._clean_settings({"style":"media","media_look":"kodi"})["media_look"],"jellyfin")
    def test_each_look_has_a_background(self):
        self.assertEqual(set(model.MEDIA_WALLPAPERS),set(model.MEDIA_LOOKS))
        for colour in model.MEDIA_WALLPAPERS.values(): self.assertRegex(colour,r"^#[0-9a-f]{6}$")

class MediaThemeTests(unittest.TestCase):
    def test_every_token_is_filled_in(self):
        for look in model.MEDIA_LOOKS:
            css=theme.render_css("#0078d7",1.6,style="media",media=look)
            self.assertNotIn("@",css,look)
            self.assertIn(theme.MEDIA_PALETTES[look]["ACCENT"],css)
            self.assertNotIn("#0078d7",css.split(".tile-0")[0])   # the look's accent replaces the Modern one (the tiles keep theirs)
    def test_corners_are_rounded_and_selections_filled(self):
        css=theme.render_css("#0078d7",style="media",media="jellyfin")
        self.assertNotIn("border-radius: 0;",css.split("window.tvwcs-window, .tvwcs-root { font-family")[0])
        self.assertIn("background: linear-gradient(100deg, #9b5de5, #2a9fe0)",css)
    def test_plex_selection_text_is_dark_on_gold(self):
        css=theme.render_css("#0078d7",style="media",media="plex")
        rule=re.search(r"button:focus, button:focus-visible, button:active \{([^}]*)\}",css).group(1)
        self.assertIn("background: #e8a90f",rule); self.assertIn("color: #1a1a1a",rule)
        self.assertIn(".icon-tile, .icon-tile label { color: #ffffff;",css)   # application tiles keep white letters
    def test_radius_is_scaled(self):
        self.assertIn("border-radius: 10px",theme.render_css("#0078d7",1.6,style="media",media="jellyfin"))   # 6 px x 1.6
    def test_modern_and_retro_are_unchanged(self):
        self.assertIn("border-radius: 0;",theme.render_css("#0078d7"))
        self.assertNotIn("@FILL@",theme.render_css("#0078d7",style="retro"))

class MediaLockScreenTests(unittest.TestCase):
    def test_lock_screen_uses_the_look(self):
        look=lockscreen.look_of({"style":"media","media_look":"emby"})
        self.assertFalse(look.retro); self.assertEqual(look.accent,"#4caf50"); self.assertEqual(look.ring_font,"Roboto")
        self.assertIn("#4caf50",lockscreen.picture(1920,1080,look))

if __name__=="__main__": unittest.main()
