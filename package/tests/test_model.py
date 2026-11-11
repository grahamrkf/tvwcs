import copy, json, tempfile, unittest
from pathlib import Path
from tvwcs.model import (ACCENT_NAMES, DEFAULT_SETTINGS, MARGIN_RANGE, ConfigStore, accent_name, key_hints, scale_key, tv_mode, LaunchProfile, LAUNCH_SAME, LAUNCH_NEW_WORKSPACE, compute_layout, extract_badge, is_tvwcs_title, profile_detail, row_description, search_items, startup_choices, PIN_LAUNCH, PIN_LAUNCH_AND_SHOW)
from tvwcs.applications import Application

class ModelTests(unittest.TestCase):
    def test_channel_uniqueness_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"config.json")
            store.set_profile(LaunchProfile("1","firefox.desktop","Firefox",channel=42))
            with self.assertRaises(ValueError): store.set_profile(LaunchProfile("2","chromium.desktop","Chromium",channel=42))
            self.assertEqual(ConfigStore(Path(d)/"config.json").assigned()[0].channel,42)
    def test_channel_digits(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"; store=ConfigStore(path)
            self.assertEqual((store.channel_digits(),store.channel_text(7)),(2,"07"))   # two digits by default
            with self.assertRaises(ValueError): store.set_profile(LaunchProfile("1","a.desktop","A",channel=100))
            store.set_profile(LaunchProfile("1","a.desktop","A",channel=99)); store.set_profile(LaunchProfile("2","b.desktop","B",channel=5))
            self.assertEqual([p.id for p in store.too_long_channels(1)],["1"])
            store.set_channel_digits(1); store.save(); store=ConfigStore(path)
            self.assertEqual((store.channel_digits(),store.get("1").channel,store.get("2").channel,store.channel_text(5)),(1,None,5,"5"))
            store.set_channel_digits(4); store.set_profile(LaunchProfile("1","a.desktop","A",channel=9999)); store.save()
            self.assertEqual((ConfigStore(path).channel_digits(),ConfigStore(path).channel_text(42)),(4,"0042"))
            with self.assertRaises(ValueError): store.set_channel_digits(5)
    def test_channel_digits_from_before_the_setting(self):
        # before 5.12 channels had three digits: a config with one over 99 keeps three, one without goes to two
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"
            for channels,digits in (([150,3],3),([42,0],2),([],2)):
                path.write_text(json.dumps({"settings":{},"profiles":[{"id":str(i),"desktop_id":f"{i}.desktop","name":"A","channel":c} for i,c in enumerate(channels)]}))
                store=ConfigStore(path)
                self.assertEqual((store.channel_digits(),[p.channel for p in store.profiles]),(digits,channels))
            path.write_text(json.dumps({"settings":{"channel_digits":2},"profiles":[{"id":"x","desktop_id":"a.desktop","name":"A","channel":150}]}))
            self.assertIsNone(ConfigStore(path).get("x").channel)   # too long for the digits chosen
    def test_numeric_search_labels(self):
        p=LaunchProfile("1","firefox.desktop","Stream",channel=7)
        app=Application("firefox.desktop","Firefox",None,None,None,("Internet",),"/fake","firefox")
        self.assertEqual(search_items("7",[p],{app.desktop_id:app},[])[0]["label"],"07  Stream")
        self.assertEqual(search_items("007",[p],{app.desktop_id:app},[],3)[0]["label"],"007  Stream")
    def test_launch_mode_defaults_to_same_workspace(self):
        self.assertEqual(LaunchProfile("1","a.desktop","A").launch_mode,LAUNCH_SAME)
    def test_launch_mode_persists_and_toggles(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"; store=ConfigStore(path)
            store.set_profile(LaunchProfile("p","firefox.desktop","Firefox",launch_mode=LAUNCH_NEW_WORKSPACE))
            self.assertEqual(ConfigStore(path).get("p").launch_mode,LAUNCH_NEW_WORKSPACE)
            self.assertEqual(store.toggle_launch_mode("p"),LAUNCH_SAME)
            self.assertEqual(ConfigStore(path).get("p").launch_mode,LAUNCH_SAME)
            self.assertEqual(store.toggle_launch_mode("p"),LAUNCH_NEW_WORKSPACE)
            self.assertIsNone(store.toggle_launch_mode("missing"))
    def test_invalid_launch_mode_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): ConfigStore(Path(d)/"c.json").set_profile(LaunchProfile("p","a.desktop","A",launch_mode="bogus"))
    def test_legacy_config_loads(self):
        # 2.2 files have "tile" and no launch_mode or settings block.
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"
            path.write_text(json.dumps({"version":1,"profiles":[{"id":"x","desktop_id":"a.desktop","name":"A","tile":False,"favorite":True,"channel":7}]}))
            store=ConfigStore(path); p=store.get("x")
            self.assertEqual((p.launch_mode,p.favorite,p.channel),(LAUNCH_SAME,True,7))
            self.assertEqual(store.settings["margin"],0)
    def test_settings_validated(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"
            path.write_text(json.dumps({"settings":{"margin":9999,"quick_width":500,"accent":"red","lock_command":" i3lock "},"profiles":[]}))
            s=ConfigStore(path).settings
            self.assertEqual((s["margin"],s["quick_width"],s["accent"],s["lock_command"]),(0,500,"#0078d7","i3lock"))
    def test_desktop_action_persists(self):
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"config.json")
            store.set_profile(LaunchProfile("a","browser.desktop","Private Window",desktop_action="Private"))
            self.assertEqual(ConfigStore(Path(d)/"config.json").get("a").desktop_action,"Private")
    def test_numeric_search(self):
        p=LaunchProfile("1","firefox.desktop","Stream",channel=12)
        app=Application("firefox.desktop","Firefox",None,None,None,("Internet",),"/fake","firefox")
        self.assertEqual([r["id"] for r in search_items("12",[p],{app.desktop_id:app},[])],["1"])
    def test_favorite_independent_of_channel(self):
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"config.json"); store.set_profile(LaunchProfile("1","firefox.desktop","Stream",favorite=True))
            self.assertIsNone(store.favorites()[0].channel); self.assertEqual(store.assigned(),[])

class SettingsAndProfileTests(unittest.TestCase):
    def test_new_settings_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"
            s=ConfigStore(path).settings
            self.assertEqual((s["scale"],s["close_on_click_outside"],s["hotkeys"],s["startup"]["mode"],s["margin"],s["keyboard"]),
                             ("",True,{"keyboard":{"menu":"Mod4","last":"Mod4+Tab"},"remote":{"menu":"F2","last":""},"gamepad":{"menu":"","last":""}},"none",0,"hidden"))
            path.write_text(json.dumps({"settings":{"scale":"huge","close_on_click_outside":False,"keyboard":"tiny","hotkeys":{"keyboard":{"menu":"Mod1","guide":"F3"},"gamepad":{"menu":"F7"}},"startup":{"mode":"app","profile_id":"p1"}}}))
            s=ConfigStore(path).settings
            self.assertEqual((s["scale"],s["close_on_click_outside"],s["keyboard"]),("",False,"hidden"))
            self.assertEqual(s["hotkeys"],{"keyboard":{"menu":"Mod1","last":"Mod4+Tab"},"remote":{"menu":"F2","last":""},"gamepad":{"menu":"F7","last":""}}); self.assertEqual((s["startup"]["mode"],s["startup"]["profile_id"]),("app","p1"))
    def test_quick_menu_corner_and_options_buttons(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"
            s=ConfigStore(path).settings; self.assertEqual((s["quick_corner"],s["hide_options_buttons"]),("bottom-left",False))
            path.write_text(json.dumps({"settings":{"quick_corner":"top-right","hide_options_buttons":True}}))
            s=ConfigStore(path).settings; self.assertEqual((s["quick_corner"],s["hide_options_buttons"]),("top-right",True))
            path.write_text(json.dumps({"settings":{"quick_corner":"middle","hide_options_buttons":"yes"}}))
            s=ConfigStore(path).settings; self.assertEqual((s["quick_corner"],s["hide_options_buttons"]),("bottom-left",False))
    def test_open_at_login_is_one_choice(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"
            self.assertEqual(ConfigStore(path).settings["startup"],{"mode":"none","profile_id":"","last_profile_id":""})
            path.write_text(json.dumps({"settings":{"startup":{"mode":"menu"}}}))   # the Quick Menu at login is gone in 4.0
            self.assertEqual(ConfigStore(path).settings["startup"]["mode"],"none")
            path.write_text(json.dumps({"settings":{"startup":{"mode":"last","show_menu":True}}}))
            self.assertEqual(ConfigStore(path).settings["startup"]["mode"],"last")
            store=ConfigStore(path); store.save()
            self.assertNotIn("show_menu",json.loads(path.read_text())["settings"]["startup"])
    def test_the_mode_is_the_session(self):
        self.assertTrue(tv_mode({"TVWCS_SESSION":"sway"})); self.assertFalse(tv_mode({}))
        self.assertFalse(tv_mode({"TVWCS_SESSION":"i3","TVWCS_MODE":"desktop"})); self.assertTrue(tv_mode({"TVWCS_MODE":"tv"}))
        self.assertEqual((scale_key({"scale":""},True),scale_key({"scale":""},False),scale_key({"scale":"4","scale_4k":True},False)),((4,False),(3,False),(4,True)))
    def test_settings_removed_in_4_0_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"
            path.write_text(json.dumps({"settings":{"use":"tv","scale":"tenfoot","apps_open":"side","reduce_motion":True,"tvwcs_lock_screen":False,
                                                    "button_hints":True,"quick_close_button":False,"password_keyboard":"digits"}}))
            store=ConfigStore(path); store.save(); saved=json.loads(path.read_text())["settings"]
            for key in ("use","apps_open","reduce_motion","tvwcs_lock_screen","button_hints","quick_close_button","password_keyboard"): self.assertNotIn(key,saved)
            self.assertEqual(saved["scale"],"")   # the size the old "Used on: A TV" chose: automatic now, by the mode
    def test_accent_names_and_key_hints(self):
        self.assertEqual(accent_name("#E81123"),"Red"); self.assertEqual(accent_name("#123456"),"#123456")
        self.assertIn(DEFAULT_SETTINGS["accent"],ACCENT_NAMES); self.assertTrue(MARGIN_RANGE[0]<=DEFAULT_SETTINGS["margin"]<=MARGIN_RANGE[1])
        self.assertIn("Back  Go back",key_hints(True)); self.assertIn("Esc  Go back",key_hints(False))
    def test_a_key_used_twice_keeps_only_its_first_use(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; path.write_text(json.dumps({"settings":{"hotkeys":{"remote":{"menu":"F5","guide":"F5"},"gamepad":{"menu":"Mod4"}}}}))
            hk=ConfigStore(path).settings["hotkeys"]
            self.assertEqual((hk["remote"],hk["gamepad"]["menu"]),({"menu":"F5","last":""},""))   # Mod4 is already the keyboard's
    def test_old_single_hotkey_set_becomes_the_remote_set(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; path.write_text(json.dumps({"settings":{"hotkeys":{"menu":"F9","guide":"Shift+F9"}}}))
            hk=ConfigStore(path).settings["hotkeys"]
            self.assertEqual((hk["remote"],hk["keyboard"]["menu"]),({"menu":"F9","last":""},"Mod4"))
    def test_the_new_last_app_key_gives_way_to_an_app_that_has_it(self):
        with tempfile.TemporaryDirectory() as d:   # a config from before 5.21, where an app already has Super+Tab
            path=Path(d)/"c.json"; path.write_text(json.dumps({"settings":{"hotkeys":{"keyboard":{"menu":"Mod4"}}},
                "profiles":[{"id":"p1","desktop_id":"kodi.desktop","name":"Kodi","hotkey":"Mod4+Tab"}]}))
            store=ConfigStore(path)
            self.assertEqual((store.settings["hotkeys"]["keyboard"]["last"],store.get("p1").hotkey),("","Mod4+Tab"))
            store.settings["hotkeys"]["keyboard"]["last"]="Mod4+Tab"; store.get("p1").hotkey=""; store.save()   # saved as chosen
            self.assertEqual(ConfigStore(path).settings["hotkeys"]["keyboard"]["last"],"Mod4+Tab")
            path.write_text(json.dumps({"settings":{"hotkeys":{"keyboard":{"menu":"Mod4","last":"Mod4+Tab"}}},
                "profiles":[{"id":"p1","desktop_id":"kodi.desktop","name":"Kodi","hotkey":"Mod4+Tab"}]}))
            store=ConfigStore(path)   # set by hand on both: the slot keeps it, as before
            self.assertEqual((store.settings["hotkeys"]["keyboard"]["last"],store.get("p1").hotkey),("Mod4+Tab",""))
    def test_defaults_are_not_shared_between_stores(self):
        with tempfile.TemporaryDirectory() as d:
            a=ConfigStore(Path(d)/"a.json"); a.settings["hotkeys"]["remote"]["menu"]="F9"
            self.assertEqual(ConfigStore(Path(d)/"b.json").settings["hotkeys"]["remote"]["menu"],"F2")
    def test_pin_fields_persist_and_are_validated(self):
        from tvwcs.pinlock import make_hash
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path); h=make_hash("1234")
            store.set_profile(LaunchProfile("p","a.desktop","A",pin_hash=h,pin_scope=PIN_LAUNCH_AND_SHOW))
            p=ConfigStore(path).get("p"); self.assertEqual((p.pin_hash,p.pin_scope),(h,PIN_LAUNCH_AND_SHOW))
            with self.assertRaises(ValueError): store.set_profile(LaunchProfile("q","a.desktop","A",pin_scope="nope"))
            with self.assertRaises(ValueError): store.set_profile(LaunchProfile("q","a.desktop","A",pin_hash="1234"))   # a plaintext PIN is refused
    def test_hand_edited_bad_pin_data_is_dropped_on_load(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; path.write_text(json.dumps({"profiles":[{"id":"x","desktop_id":"a.desktop","name":"A","pin_hash":"1234","pin_scope":"weird"}]}))
            p=ConfigStore(path).get("x"); self.assertEqual((p.pin_hash,p.pin_scope),("",PIN_LAUNCH))
    def test_old_run_as_user_key_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; path.write_text(json.dumps({"profiles":[{"id":"x","desktop_id":"a.desktop","name":"A","run_as_user":"bob"}]}))
            store=ConfigStore(path); self.assertEqual(store.get("x").name,"A"); self.assertFalse(hasattr(store.get("x"),"run_as_user"))
    def test_profile_description_override_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path)
            store.set_profile(LaunchProfile("p","a.desktop","A",description="  Kids   profile "))
            self.assertEqual(ConfigStore(path).get("p").description,"Kids profile")
    def test_app_description_override_persists_and_clears(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path)
            store.set_app_description("a.desktop","My own words"); self.assertEqual(ConfigStore(path).app_descriptions,{"a.desktop":"My own words"})
            store.set_app_description("a.desktop","   "); self.assertEqual(ConfigStore(path).app_descriptions,{})
    def test_an_application_description_moves_to_its_default_profile(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path)
            store.set_profile(LaunchProfile("p","b.desktop","B")); store.set_profile(LaunchProfile("q","b.desktop","B 2"))
            store.set_app_description("b.desktop","Before 4.0")
            app=Application("b.desktop","B","Generic","Comment",None,("Internet",),"/x","b")
            store.ensure_defaults([app]); again=ConfigStore(path)
            self.assertEqual((again.get("p").description,again.get("q").description,again.app_descriptions),("Before 4.0","",{}))
    def test_row_description_defaults_and_overrides(self):
        app=Application("b.desktop","B","Generic","The .desktop comment",None,("Internet",),"/x","b",(("Private","Private Window"),))
        main=LaunchProfile("1","b.desktop","B"); sec=LaunchProfile("2","b.desktop","P",command="b --kiosk",desktop_action="Private")
        self.assertEqual(row_description(main,app,True),"The .desktop comment")                      # main: the .desktop description
        self.assertEqual(row_description(main,app,True,"Override"),"Override")                        # ... or the one from before 4.0
        main.description="Its own"; self.assertEqual(row_description(main,app,True,"Override"),"Its own")   # 4.0: each profile has its own
        main.description=""
        self.assertEqual(row_description(sec,app,False),"Private Window  ·  b --kiosk")             # secondary: its launch options
        sec.description="Just for me"; self.assertEqual(row_description(sec,app,False),"Just for me")
    def test_startup_choices_order(self):
        ps=[LaunchProfile("a","a.desktop","Zed"),LaunchProfile("b","b.desktop","Alpha",channel=9),LaunchProfile("c","c.desktop","Mid",favorite=True,channel=5),
            LaunchProfile("d","d.desktop","Beta",favorite=True),LaunchProfile("e","e.desktop","Chan",channel=2)]
        got=[(t,[p.name for p in g]) for t,g in startup_choices(ps)]
        self.assertEqual(got,[("FAVORITES",["Mid","Beta"]),("CHANNELS",["Chan","Alpha"]),("ALL OTHER APPS",["Zed"])])   # a favorite with a channel is listed once
        self.assertEqual([t for t,_ in startup_choices([LaunchProfile("a","a.desktop","Only")])],["ALL OTHER APPS"])
    def test_last_profile_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path); store.record_last_profile("x")
            self.assertEqual(ConfigStore(path).settings["startup"]["last_profile_id"],"x")
    def test_tvwcs_title_is_exact_not_prefix(self):
        self.assertTrue(is_tvwcs_title("TVWCS")); self.assertTrue(is_tvwcs_title("TVWCS · Launch Profile"))
        for t in ("tvwcs.conf - Text Editor","TVWCS_notes.txt","TVWCS notes","TVWCS Launch Profile"): self.assertFalse(is_tvwcs_title(t),t)
    def test_profile_detail_lists_action_and_command(self):
        app=Application("b.desktop","B",None,"A browser",None,("Internet",),"/x","b",(("Private","Private Window"),))
        self.assertEqual(profile_detail(LaunchProfile("1","b.desktop","P",desktop_action="Private"),app),"Private Window")
        self.assertEqual(profile_detail(LaunchProfile("1","b.desktop","P",command="b --kiosk"),app),"b --kiosk")
        self.assertEqual(profile_detail(LaunchProfile("1","b.desktop","P",desktop_action="Private",command="b --x"),app),"Private Window  ·  b --x")
        self.assertEqual(profile_detail(LaunchProfile("1","b.desktop","P"),app),"")

class ProfileHotkeyTests(unittest.TestCase):
    def test_profile_hotkey_persists_and_bad_ones_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path)
            store.set_profile(LaunchProfile("a","firefox.desktop","Firefox",hotkey="Mod4+f"))
            self.assertEqual(ConfigStore(path).get("a").hotkey,"Mod4+f")
            with self.assertRaises(ValueError): store.set_profile(LaunchProfile("b","x.desktop","X",hotkey="a;rm"))
            path.write_text(json.dumps({"profiles":[{"id":"a","desktop_id":"a.desktop","name":"A","hotkey":"bad key"}]}))
            self.assertEqual(ConfigStore(path).get("a").hotkey,"")
    def test_a_hand_edited_duplicate_keeps_the_device_slot(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"
            path.write_text(json.dumps({"profiles":[{"id":"a","desktop_id":"a.desktop","name":"A","hotkey":"F2"},
                                                    {"id":"b","desktop_id":"b.desktop","name":"B","hotkey":"F8"},{"id":"c","desktop_id":"c.desktop","name":"C","hotkey":"F8"}]}))
            store=ConfigStore(path)
            self.assertEqual([store.get(i).hotkey for i in "abc"],["","F8",""])   # F2 is the remote's Quick Menu
    def test_owner_lookup_and_taking_a_key(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json"; store=ConfigStore(path)
            store.set_profile(LaunchProfile("a","firefox.desktop","Firefox",hotkey="F8"))
            self.assertEqual(store.hotkey_owner("F2"),("slot","remote","menu")); self.assertEqual(store.owner_label(("slot","remote","menu")),"Remote: Quick Menu")
            self.assertEqual(store.hotkey_owner("F8"),("profile","a")); self.assertEqual(store.owner_label(("profile","a")),"Firefox")
            self.assertIsNone(store.hotkey_owner("F8",("profile","a"))); self.assertIsNone(store.hotkey_owner("F9")); self.assertIsNone(store.hotkey_owner(""))
            store.set_slot_hotkey("remote","fullscreen","F8")   # taken from Firefox
            self.assertEqual((store.get("a").hotkey,store.settings["hotkeys"]["remote"]["fullscreen"]),("","F8"))
            store.set_profile_hotkey("a","F2")                  # taken from the remote's Quick Menu
            self.assertEqual((store.get("a").hotkey,store.settings["hotkeys"]["remote"]["menu"]),("F2",""))
            store.set_profile(LaunchProfile("b","x.desktop","X",hotkey="F2"))   # saving a profile takes it too
            reloaded=ConfigStore(path)
            self.assertEqual((reloaded.get("a").hotkey,reloaded.get("b").hotkey),("","F2"))
            self.assertEqual([p.id for p in reloaded.hotkey_profiles()],["b"]); self.assertEqual(reloaded.app_hotkeys(),[("F2","b","X")])
            store.set_profile_hotkey("b",""); self.assertEqual(store.hotkey_profiles(),[])

class ScaleTests(unittest.TestCase):
    def test_sizes_1_to_5_and_the_automatic_ones(self):
        from tvwcs.model import SIZES, size_of, size_label
        self.assertEqual((SIZES[3],SIZES[4]),(1.0,1.6))   # the desktop and TV sizes of before 5.8
        self.assertEqual((size_of({},True),size_of({},False)),(4,3))
        self.assertEqual((size_of({"style":"retro"},True),size_of({"style":"retro"},False)),(3,2))   # Retro: a size smaller
        self.assertEqual(size_of({"scale":"5","style":"retro"},True),5); self.assertEqual(size_of({"scale":"9"},False),3)
        self.assertEqual((size_label(3),size_label(4),size_label(1)),("3 (desktop size)","4 (TV size)","1"))
    def test_old_size_names_become_numbers(self):
        from tvwcs.model import _clean_settings, is_4k
        self.assertEqual([(_clean_settings({"scale":k})["scale"],_clean_settings({"scale":k})["scale_4k"]) for k in ("desktop","tenfoot","tenfoot_4k")],
                         [("3",False),("4",False),("4",True)])
        self.assertEqual((_clean_settings({"scale":"2","scale_4k":True})["scale"],_clean_settings({"scale":"2","scale_4k":True})["scale_4k"]),("2",True))
        self.assertEqual(_clean_settings({"scale":"0"})["scale"],"")
        self.assertTrue(is_4k(3840,2160)); self.assertTrue(is_4k(2160,3840)); self.assertFalse(is_4k(1920,1080)); self.assertFalse(is_4k(5120,1440))
    def test_large_sizes_shrink_on_a_smaller_screen(self):
        from tvwcs.model import effective_scale
        self.assertEqual(effective_scale((4,False),1080),1.6); self.assertEqual(effective_scale((4,False),0),1.6)
        self.assertAlmostEqual(effective_scale((4,False),720),1.067,places=3)
        self.assertEqual(effective_scale((4,False),480),1.0)                      # never smaller than the desktop size
        self.assertEqual(effective_scale((4,True),2160),3.0); self.assertEqual(effective_scale((4,True),1080),1.6)   # 4K TV Mode before 5.8
        self.assertEqual(effective_scale((3,False),720),1.0); self.assertEqual(effective_scale((4,False),2160),1.6)
        self.assertEqual((effective_scale((1,False),720),effective_scale((2,False),1080),effective_scale((5,False),1080)),(0.6,0.8,2.0))
        self.assertEqual(effective_scale((3,True),2160),1.875)

class AppNameTests(unittest.TestCase):
    def test_plain_profiles_follow_a_renamed_application(self):
        from types import SimpleNamespace as NS
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"c.json")
            store.ensure_defaults([NS(desktop_id="k.desktop",name="Kodi")])
            store.profiles.append(LaunchProfile("x","k.desktop","My Kodi")); store.profiles.append(LaunchProfile("y","k.desktop","Kodi",command="kodi --x"))
            store.ensure_defaults([NS(desktop_id="k.desktop",name="Kodi Media Center")])
            self.assertEqual(sorted(p.name for p in store.profiles),["Kodi","Kodi Media Center","My Kodi"])
            self.assertEqual(ConfigStore(Path(d)/"c.json").app_names,{"k.desktop":"Kodi Media Center"})
    def test_the_old_control_panel_name(self):
        from types import SimpleNamespace as NS
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"c.json"); store.profiles.append(LaunchProfile("x","com.tvwcs.ControlPanel.desktop","Control Panel"))
            store.ensure_defaults([NS(desktop_id="com.tvwcs.ControlPanel.desktop",name="TVWCS Settings")])
            self.assertEqual([p.name for p in store.profiles],["TVWCS Settings"])

class LayoutTests(unittest.TestCase):
    AREA={"x":0,"y":30,"width":1920,"height":1050}   # y offset = a 30 px bar on top
    def test_quick_menu_only(self):
        l=compute_layout(self.AREA,20,460,False)
        self.assertEqual((l.x,l.y,l.width,l.height),(20,50,460,1010))
        self.assertEqual(l.guide_width,0)
    def test_margin_is_equal_on_all_sides_with_guide(self):
        l=compute_layout(self.AREA,20,460,True)
        self.assertEqual(l.x-self.AREA["x"],20)                                            # left
        self.assertEqual(l.y-self.AREA["y"],20)                                            # top
        self.assertEqual(self.AREA["y"]+self.AREA["height"]-(l.y+l.height),20)             # bottom
        self.assertEqual(self.AREA["x"]+self.AREA["width"]-(l.x+l.width),20)               # right
        self.assertEqual(l.quick_width+l.margin+l.guide_width,l.width)                     # same gap between the two
    def test_three_panels(self):
        # Settings is a tab of the Applications window now: the extra argument is accepted and ignored.
        l=compute_layout(self.AREA,20,460,True,True)
        self.assertEqual(l.guide_width,l.width-l.quick_width-l.margin)                       # full middle, no third panel
        self.assertEqual(self.AREA["x"]+self.AREA["width"]-(l.x+l.width),20)                 # same margin at the right edge
        self.assertGreater(l.guide_width,l.quick_width)                                      # the guide still gets the middle
    def test_settings_panel_needs_the_guide(self):
        l=compute_layout(self.AREA,20,460,False,True)
        self.assertFalse(l.guide_open); self.assertEqual(l.width,460)
    def test_three_panels_on_a_small_screen(self):
        l=compute_layout({"x":0,"y":0,"width":1280,"height":720},20,460,True,True)
        self.assertGreaterEqual(l.guide_width,300)
    def test_second_monitor_offset(self):
        l=compute_layout({"x":1920,"y":0,"width":1920,"height":1080},20,460,False)
        self.assertEqual(l.x,1940)
    def test_desktop_quick_menu_fits_its_contents_in_the_bottom_left_corner(self):
        l=compute_layout(self.AREA,20,460,False,quick_height=400)
        self.assertEqual((l.x,l.y,l.width,l.height),(20,30+1050-20-400,460,400))
        self.assertEqual(compute_layout(self.AREA,20,460,False,quick_height=5000).height,1010)   # never taller than the screen
        l=compute_layout(self.AREA,20,460,True,quick_height=400)   # Applications open: the full height
        self.assertEqual((l.y,l.height),(50,1010))
    def test_quick_menu_in_each_corner(self):
        area=self.AREA; right=area["x"]+area["width"]; bottom=area["y"]+area["height"]
        for corner,(x,y) in {"bottom-left":(20,bottom-20-400),"bottom-right":(right-20-460,bottom-20-400),
                             "top-left":(20,50),"top-right":(right-20-460,50)}.items():
            l=compute_layout(area,20,460,False,quick_height=400,corner=corner)
            self.assertEqual((l.x,l.y,l.width,l.height),(x,y,460,400),corner)
    def test_applications_open_to_the_left_of_a_right_hand_quick_menu(self):
        l=compute_layout(self.AREA,20,460,True,guide_width=800,corner="bottom-right")
        self.assertEqual(l.x+l.width,1920-20)   # the Quick Menu (at the right of the window) keeps its margin
        self.assertEqual(l.width,460+20+800); self.assertEqual((l.y,l.height),(50,1010))
    def test_small_screen_is_clamped(self):
        l=compute_layout({"x":0,"y":0,"width":800,"height":600},20,460,True)
        self.assertLessEqual(l.quick_width,int((800-40)*0.45)); self.assertGreater(l.guide_width,0)

class BadgeTests(unittest.TestCase):
    def test_count_in_title(self):
        self.assertEqual(extract_badge("(3) Inbox - Mail"),("Inbox - Mail","3"))
        self.assertEqual(extract_badge("[12] Chat"),("Chat","12"))
        self.assertEqual(extract_badge("(250) Feed")[1],"99+")
    def test_urgent_without_count(self):
        self.assertEqual(extract_badge("Terminal",True),("Terminal","!"))
        self.assertEqual(extract_badge("Terminal"),("Terminal",None))
    def test_not_a_badge(self):
        self.assertEqual(extract_badge("Report (draft 2)"),("Report (draft 2)",None))
    def test_window_search_result_carries_badge(self):
        r=search_items("inbox",[],{},[{"con_id":5,"title":"(2) Inbox","class":"mail","instance":"mail"}])[0]
        self.assertEqual((r["label"],r["badge"]),("Inbox","2"))

class SearchDetailTests(unittest.TestCase):
    def test_a_profile_named_like_its_app_does_not_repeat_the_name(self):
        app=Application("s.desktop","TVWCS Settings","Settings",None,None,("Settings",),"/x","s")
        apps={"s.desktop":app}
        same=LaunchProfile("p","s.desktop","TVWCS Settings",channel=0); other=LaunchProfile("q","s.desktop","Network",channel=5)
        for q in ("0","000"): self.assertEqual(search_items(q,[same],apps,[])[0]["detail"],"Settings")
        self.assertEqual(search_items("5",[other],apps,[])[0]["detail"],"TVWCS Settings")
        self.assertEqual(search_items("tvwcs",[other],apps,[])[0]["id"],"q")   # still found by its app's name

class ChannelZeroTests(unittest.TestCase):
    def test_channel_000_is_allowed_and_100_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"config.json")
            store.set_profile(LaunchProfile("z","a.desktop","A",channel=0))
            self.assertEqual(ConfigStore(Path(d)/"config.json").get("z").channel,0)
            with self.assertRaisesRegex(ValueError,"00 to 99"): store.set_profile(LaunchProfile("y","b.desktop","B",channel=100))
            with self.assertRaises(ValueError): store.set_profile(LaunchProfile("x","c.desktop","C",channel=-1))
    def test_settings_gets_channel_000_once(self):
        from tvwcs.model import SETTINGS_DESKTOP_ID
        settings=Application(SETTINGS_DESKTOP_ID,"TVWCS Settings",None,None,None,("Settings",),"/x","tvwcs settings")
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"; store=ConfigStore(path)
            store.set_profile(LaunchProfile("s",SETTINGS_DESKTOP_ID,"TVWCS Settings",channel=99))
            store.ensure_defaults([settings])
            self.assertEqual(store.get("s").channel,0)                 # moved from 99 the first time
            store.get("s").channel=7; store.save(); store=ConfigStore(path); store.ensure_defaults([settings])
            self.assertEqual(store.get("s").channel,7)                 # the user's later choice stays
    def test_channel_000_already_taken_is_left_alone(self):
        from tvwcs.model import SETTINGS_DESKTOP_ID
        settings=Application(SETTINGS_DESKTOP_ID,"TVWCS Settings",None,None,None,("Settings",),"/x","tvwcs settings")
        with tempfile.TemporaryDirectory() as d:
            store=ConfigStore(Path(d)/"config.json")
            store.set_profile(LaunchProfile("a","a.desktop","A",channel=0))
            store.set_profile(LaunchProfile("s",SETTINGS_DESKTOP_ID,"TVWCS Settings",channel=99))
            store.ensure_defaults([settings])
            self.assertEqual(store.get("s").channel,99); self.assertTrue(store.settings["channel_zero_done"])
    def test_new_settings_are_cleaned(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.json"
            path.write_text(json.dumps({"profiles":[],"settings":{"theme":"purple","wallpaper":"#123456","password_keyboard":"digits","screensaver_logo":"nope","flatpak_unverified":True}}))
            s=ConfigStore(path).settings
            self.assertEqual(s["theme"],"dark"); self.assertEqual(s["wallpaper"],DEFAULT_SETTINGS["wallpaper"])
            self.assertEqual(s["keyboard"],"hidden"); self.assertNotIn("screensaver_logo",s); self.assertNotIn("flatpak_unverified",s)
    def test_wallpaper_choices(self):
        from tvwcs.model import WALLPAPERS, DEFAULT_WALLPAPER
        self.assertEqual(len(WALLPAPERS),18); self.assertIn(DEFAULT_WALLPAPER,WALLPAPERS); self.assertEqual(DEFAULT_SETTINGS["theme"],"dark")

if __name__=="__main__": unittest.main()
