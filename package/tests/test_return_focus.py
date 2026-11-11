import json, tempfile, unittest
from pathlib import Path
from tvwcs import return_focus
from tvwcs.window_manager import WindowManager

def win(i,cls,focused=False,fullscreen=False):
    return {"con_id":i,"class":cls,"title":cls,"focused":focused,"fullscreen":fullscreen}

class FakeWM(WindowManager):
    def __init__(self,wins):
        super().__init__(); self.binary="/usr/bin/swaymsg"; self.wins=wins; self.sent=[]
    def windows(self): return self.wins
    def _call(self,*args,timeout=2):
        self.sent.append(" ".join(args)); return '[{"success":true}]'

class ReturnFocusTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory(); self.path=Path(self.dir.name)/"return.json"
    def tearDown(self): self.dir.cleanup()

    def test_note_then_take_once(self):
        return_focus.note({"con_id":7,"fullscreen":True},self.path,now=100)
        self.assertEqual(return_focus.take(self.path,now=110),{"con_id":7,"fullscreen":True})
        self.assertIs(return_focus.take(self.path,now=111),return_focus.MISSING)   # used up
    def test_nothing_to_go_back_to_is_noted_too(self):
        return_focus.note(None,self.path,now=100)
        self.assertIsNone(return_focus.take(self.path,now=101))
    def test_old_or_broken_notes_are_ignored(self):
        return_focus.note({"con_id":7,"fullscreen":False},self.path,now=100)
        self.assertIs(return_focus.take(self.path,now=100+return_focus.FRESH_SECONDS+1),return_focus.MISSING)
        self.path.write_text("not json"); self.assertIs(return_focus.take(self.path),return_focus.MISSING)
        self.path.write_text(json.dumps([1])); self.assertIs(return_focus.take(self.path),return_focus.MISSING)
        self.assertIs(return_focus.take(self.path),return_focus.MISSING)   # no file
    def test_settings_is_never_a_target(self):
        self.assertIsNone(return_focus.target_of(win(3,return_focus.SETTINGS_APP_ID)))
        self.assertIsNone(return_focus.target_of(None))
        self.assertEqual(return_focus.target_of(win(4,"firefox",fullscreen=True)),{"con_id":4,"fullscreen":True})
        self.assertEqual(return_focus.target_of(win(4,"firefox"),fullscreen=True),{"con_id":4,"fullscreen":True})
    def test_focused_app(self):
        wm=FakeWM([win(1,"kodi"),win(2,"firefox",focused=True)])
        self.assertEqual(return_focus.focused_app(wm),{"con_id":2,"fullscreen":False})
        self.assertIsNone(return_focus.focused_app(FakeWM([win(1,"kodi"),win(3,return_focus.SETTINGS_APP_ID,focused=True)])))
    def test_go_back_focuses_and_restores_full_screen(self):
        wm=FakeWM([win(1,"kodi"),win(3,return_focus.SETTINGS_APP_ID,focused=True)])
        self.assertTrue(return_focus.go_back(wm,{"con_id":1,"fullscreen":True}))
        self.assertEqual(wm.sent,["[con_id=1] focus","[con_id=1] fullscreen enable"])
    def test_go_back_leaves_a_full_screen_window_alone(self):
        wm=FakeWM([win(1,"kodi",fullscreen=True)])
        return_focus.go_back(wm,{"con_id":1,"fullscreen":True}); self.assertEqual(wm.sent,["[con_id=1] focus"])
    def test_go_back_to_a_closed_window_does_nothing(self):
        wm=FakeWM([win(3,return_focus.SETTINGS_APP_ID,focused=True)])
        self.assertFalse(return_focus.go_back(wm,{"con_id":1,"fullscreen":False})); self.assertEqual(wm.sent,[])
        self.assertFalse(return_focus.go_back(wm,None))

if __name__=="__main__": unittest.main()
