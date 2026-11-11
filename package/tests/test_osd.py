import os, signal, tempfile, unittest
from pathlib import Path
from unittest import mock

from tvwcs import osd

class LevelTests(unittest.TestCase):
    def test_the_level_file_round_trips(self):
        self.assertEqual(osd.parse_level(osd.format_level(45,False)),(45,False))
        self.assertEqual(osd.parse_level(osd.format_level(120,True)),(120,True))
        self.assertEqual(osd.parse_level(""),(None,False)); self.assertEqual(osd.parse_level("loud"),(None,False))
    def test_the_bar_is_measured_against_the_keys_top(self):
        self.assertEqual(osd.fraction(50,100),0.5); self.assertEqual(osd.fraction(75,150),0.5)
        self.assertEqual(osd.fraction(130,100),1.0)   # set louder elsewhere: full, never past it
        self.assertEqual(osd.fraction(0,100),0.0)
    def test_it_says_muted_or_the_percent(self):
        self.assertEqual(osd.describe(80,False),("audio-volume-high-symbolic","🔊","80%"))
        self.assertEqual(osd.describe(20,False)[0],"audio-volume-low-symbolic")
        self.assertEqual(osd.describe(80,True),("audio-volume-muted-symbolic","🔇","Muted"))
        self.assertEqual(osd.describe(0,False)[0],"audio-volume-muted-symbolic")

class LayerShellTests(unittest.TestCase):
    def test_it_needs_both_the_library_and_its_introspection_data(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("glob.glob",return_value=[]):
            self.assertFalse(osd.layer_shell_found(dirs=(d,)))
            Path(d,osd.LAYER_SHELL_LIB).touch(); self.assertFalse(osd.layer_shell_found(dirs=(d,)))   # Debian's gir package alone is not enough, nor the library alone
            os.makedirs(Path(d,"girepository-1.0")); Path(d,"girepository-1.0",osd.LAYER_SHELL_TYPELIB).touch()
            self.assertTrue(osd.layer_shell_found(dirs=(d,)))
    def test_it_is_preloaded_on_sway_only(self):
        self.assertEqual(osd.launch_env({"SWAYSOCK":"s","LD_PRELOAD":"libx.so"},found=True)["LD_PRELOAD"],"libgtk4-layer-shell.so.0 libx.so")
        self.assertEqual(osd.launch_env({"SWAYSOCK":"s","LD_PRELOAD":"libgtk4-layer-shell.so.0"},found=True)["LD_PRELOAD"],"libgtk4-layer-shell.so.0")
        self.assertNotIn("LD_PRELOAD",osd.launch_env({"SWAYSOCK":"s"},found=False))   # not installed: the floating window
        self.assertNotIn("LD_PRELOAD",osd.launch_env({"WAYLAND_DISPLAY":"wayland-1"},found=True))
        self.assertEqual(osd.launch_env({},found=False)["GSK_RENDERER"],"cairo")
        self.assertEqual(osd.launch_env({"GSK_RENDERER":"gl"},found=False)["GSK_RENDERER"],"gl")   # the user's choice stays

class ShowTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.env={"XDG_RUNTIME_DIR":self.dir.name,"SWAYSOCK":"/run/sway","WAYLAND_DISPLAY":"wayland-1"}
    def test_nothing_without_a_graphical_session(self):
        with mock.patch("subprocess.Popen") as popen:
            self.assertFalse(osd.show(50,False,{"XDG_RUNTIME_DIR":self.dir.name}))
            self.assertFalse(osd.show(None,False,self.env))
        popen.assert_not_called()
    def test_it_starts_the_indicator_once_and_then_signals_it(self):
        with mock.patch("subprocess.Popen") as popen, mock.patch.object(osd,"layer_shell_found",return_value=True):
            self.assertTrue(osd.show(55,True,self.env))
        self.assertEqual(Path(self.dir.name,osd.LEVEL_NAME).read_text(),"55 1\n")
        argv=popen.call_args.args[0]; self.assertEqual(argv[1:],["-m","tvwcs.osd"])
        self.assertIn(osd.LAYER_SHELL_LIB,popen.call_args.kwargs["env"]["LD_PRELOAD"])
        Path(self.dir.name,osd.PID_NAME).write_text(f"{os.getpid()}\n")
        with mock.patch("subprocess.Popen") as popen, mock.patch("os.kill") as kill, mock.patch.object(osd,"running_pid",return_value=os.getpid()):
            self.assertTrue(osd.show(60,False,self.env))
        popen.assert_not_called(); kill.assert_called_with(os.getpid(),signal.SIGUSR1)
        self.assertEqual(Path(self.dir.name,osd.LEVEL_NAME).read_text(),"60 0\n")
    def test_only_a_live_indicator_counts_as_running(self):
        proc=Path(self.dir.name,"proc"); Path(self.dir.name,osd.PID_NAME).write_text("4242\n")
        def fake(cmdline, state):
            (proc/"4242").mkdir(parents=True,exist_ok=True)
            (proc/"4242"/"cmdline").write_bytes(cmdline); (proc/"4242"/"stat").write_bytes(f"4242 (python3) {state} 1 2 3".encode())
            return osd.running_pid(self.env,proc=str(proc))
        self.assertEqual(fake(b"python3\0-m\0tvwcs.osd\0","S"),4242)
        self.assertIsNone(fake(b"python3\0-m\0tvwcs.osd\0","Z"))   # ended, not yet reaped
        self.assertIsNone(fake(b"bash\0","S"))                       # the id now belongs to another program
        self.assertIsNone(osd.running_pid(self.env,proc=str(Path(self.dir.name,"none"))))
    def test_a_burst_of_keys_starts_it_once(self):
        with mock.patch("subprocess.Popen") as popen:
            for v in (50,45,40): osd.show(v,False,self.env)
        self.assertEqual(popen.call_count,1)
        self.assertEqual(Path(self.dir.name,osd.LEVEL_NAME).read_text(),"40 0\n")   # it shows the newest once up
        rt=Path(self.dir.name); mark=rt/osd.STARTING_NAME
        self.assertTrue(osd._claim_start(rt,now=mark.stat().st_mtime+10))   # it never came up: the next key tries again

if __name__=="__main__": unittest.main()
