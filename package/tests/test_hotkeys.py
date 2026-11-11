import unittest
from tvwcs.hotkeys import DEFAULT_HOTKEYS, HotkeyCapture, binding, clean_hotkeys, defaulted, describe, is_modifier_only, normalize_spec, render_bindings, used_by, valid_spec

class HotkeyTests(unittest.TestCase):
    def test_validation(self):
        for ok in ("F2","Shift+F2","Mod4+space","Mod4","Mod4+Shift+Return"): self.assertTrue(valid_spec(ok),ok)
        for bad in ("","Mod4+Shift","F2+F3","Shift+Shift+a","Mod4+a b","a;rm"): self.assertFalse(valid_spec(bad),bad)
    def test_describe(self):
        self.assertEqual(describe("F2"),"F2"); self.assertEqual(describe("Shift+F2"),"Shift + F2")
        self.assertEqual(describe("Mod4"),"Super (tap)"); self.assertEqual(describe("Mod4+Shift+a"),"Super + Shift + A"); self.assertEqual(describe(""),"Not set")
    def test_normalize_orders_modifiers(self):
        self.assertEqual(normalize_spec(["Shift","Mod4","a"]),"Mod4+Shift+a")
    def test_defaults_tap_super_on_the_keyboard_and_f2_on_the_remote(self):
        hk=clean_hotkeys(None); self.assertEqual(hk,DEFAULT_HOTKEYS)
        self.assertTrue(is_modifier_only("Mod4")); self.assertEqual(binding("Mod4"),"bindcode --release 133")
        conf=render_bindings(hk,"/opt/t v/tvwcs")
        self.assertIn("bindcode --release 133 exec --no-startup-id '/opt/t v/tvwcs' toggle",conf)
        self.assertIn("bindsym F2 exec --no-startup-id '/opt/t v/tvwcs' toggle",conf)
        self.assertIn("bindsym Mod4+Tab exec --no-startup-id '/opt/t v/tvwcs' last-app",conf)
        self.assertEqual(conf.count("exec"),3)   # unset keys (the remote's and gamepad's Last app, the gamepad's Quick Menu) bind nothing
        self.assertNotIn("bindsym Mod4 ",conf)   # binding Super itself would steal Super+Enter etc.
        for line in conf.splitlines():   # sway has no end-of-line comments; one would become arguments to tvwcs
            if line.startswith("bind"): self.assertNotIn("#",line)
    def test_on_a_tv_a_lone_window_has_no_border(self):
        hk=clean_hotkeys(None)
        self.assertNotIn("border",render_bindings(hk,"t"))
        conf=render_bindings(hk,"t",tv=True).splitlines()
        self.assertIn("hide_edge_borders smart",conf); self.assertIn("default_border pixel 2",conf)
        self.assertTrue(all(l.startswith(("#","bind","default_border","hide_edge_borders")) for l in conf))
    def test_lone_modifiers_bind_their_own_keycode_on_release(self):
        hk=clean_hotkeys({"keyboard":{"menu":"Mod4"},"remote":{"menu":"Mod1"},"gamepad":{"menu":"Control"}})
        conf=render_bindings(hk,"t",{"Mod4":134})   # the keyboard's real keycode wins over the default
        self.assertIn("bindcode --release 134 exec --no-startup-id t toggle",conf)
        self.assertIn("bindcode --release 64 exec --no-startup-id t toggle",conf); self.assertIn("bindcode --release 37 exec --no-startup-id t toggle",conf)
        self.assertEqual(binding("Mod4+space"),"bindsym Mod4+space")
        # GTK names a remote's multimedia keys without XF86; sway rejects them that way
        self.assertEqual(binding("Mail"),"bindsym XF86Mail"); self.assertEqual(binding("Shift+Search"),"bindsym Shift+XF86Search")
        self.assertEqual(binding("XF86Tools"),"bindsym XF86Tools"); self.assertEqual(binding("F2"),"bindsym F2")
    def test_only_the_quick_menu_and_last_app_have_device_hotkeys(self):
        hk=clean_hotkeys({"remote":{"menu":"F2","fullscreen":"F11","guide":"F3"}})   # the Applications and Fullscreen keys before 4.0
        self.assertEqual(hk["remote"],{"menu":"F2","last":""}); conf=render_bindings(hk,"t")
        self.assertNotIn("F11",conf); self.assertNotIn("F3",conf)
    def test_application_hotkeys_launch_their_profile(self):
        conf=render_bindings(clean_hotkeys(None),"/opt/tvwcs",app_keys=[("Mod4+f","3f2a-b1","Fire\nfox"),("F2","x","Taken"),("F9","bad id","Odd"),("F7","ok","")])
        self.assertIn("bindsym Mod4+f exec --no-startup-id /opt/tvwcs launch 3f2a-b1",conf); self.assertIn("# Application: Fire fox (Super + F)",conf)
        self.assertEqual(conf.count("bindsym F2 "),1)   # the remote's Quick Menu keeps it
        self.assertNotIn("bad id",conf); self.assertIn("launch ok",conf)
    def test_a_remote_key_for_the_last_app(self):
        hk=clean_hotkeys({"keyboard":{"menu":"Mod4","last":""},"remote":{"menu":"F2","last":"Red"}})
        conf=render_bindings(hk,"t")
        self.assertIn("# Remote: Last app (Red)\nbindsym XF86Red exec --no-startup-id t last-app",conf); self.assertNotIn("Tab",conf)
        self.assertEqual(clean_hotkeys({"keyboard":{"menu":"Mod4+Tab"}})["keyboard"]["last"],"")   # the Quick Menu keeps a key both have
    def test_defaulted_slots(self):
        self.assertEqual(defaulted({"keyboard":{"menu":"Mod4"},"remote":{"menu":"F2","last":""},"gamepad":{"menu":""}}),[("keyboard","last"),("gamepad","last")])
        self.assertEqual(defaulted(None),[]); self.assertIn(("keyboard","menu"),defaulted({"menu":"F9"}))
    def test_used_by_finds_the_slot_holding_a_key(self):
        self.assertEqual(used_by(DEFAULT_HOTKEYS,"F2"),("remote","menu")); self.assertIsNone(used_by(DEFAULT_HOTKEYS,"F2",("remote","menu")))
        self.assertIsNone(used_by(DEFAULT_HOTKEYS,"F9"))
    def test_capture_plain_key_and_chord(self):
        c=HotkeyCapture(); self.assertEqual(c.press("F2",()),"F2")
        c=HotkeyCapture(); self.assertEqual(c.press("a",("Shift","Mod4")),"Mod4+Shift+a")
    def test_capture_lone_modifier_on_release(self):
        c=HotkeyCapture(); self.assertIsNone(c.press("Super_L",())); self.assertEqual(c.release("Super_L"),"Mod4")
    def test_modifier_used_in_a_chord_is_not_a_lone_modifier(self):
        c=HotkeyCapture(); c.press("Super_L",()); self.assertEqual(c.press("space",("Mod4",)),"Mod4+space"); self.assertIsNone(c.release("Super_L"))
class NavigationKeyTests(unittest.TestCase):
    def test_d_pad_ok_and_back_navigate_the_dialog(self):
        from tvwcs.hotkeys import is_navigation
        for k in ("Up","Down","Left","Right","Return","KP_Enter","Escape","Back","Tab"): self.assertTrue(is_navigation(k),k)
        for k in ("XF86Tools","XF86Mail","F5","a"): self.assertFalse(is_navigation(k),k)
        self.assertFalse(is_navigation("Up",held=("Super_L",)))   # Super+Up is a hotkey

if __name__=="__main__": unittest.main()
