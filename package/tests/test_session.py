import os, subprocess, tempfile, time, unittest
from pathlib import Path
from tvwcs.session import first_time_this_login, is_tvwcs_process, runtime_dir, session_key

class SessionTests(unittest.TestCase):
    def test_runtime_dir_falls_back_to_the_users_cache(self):
        self.assertEqual(runtime_dir({"XDG_RUNTIME_DIR":"/run/user/7"}),Path("/run/user/7"))
        self.assertEqual(runtime_dir({"HOME":"/home/a"}),Path("/home/a/.cache/tvwcs"))
        self.assertEqual(runtime_dir({"HOME":"/home/a","XDG_CACHE_HOME":"/c"}),Path("/c/tvwcs"))
    def test_once_per_login_without_a_runtime_dir_that_empties(self):
        with tempfile.TemporaryDirectory() as d:
            boot=Path(d)/"boot_id"; boot.write_text("boot-1\n"); sock=Path(d)/"ipc-socket.100"; sock.write_text("")
            marker=Path(d)/"cache"/"tvwcs-startup-done"; env={"SWAYSOCK":str(sock)}
            self.assertTrue(first_time_this_login(marker,env,boot)); self.assertFalse(first_time_this_login(marker,env,boot))   # TVWCS restarted
            sock.unlink(); time.sleep(0.01); sock.write_text("")   # the next login: sway makes its socket again
            self.assertTrue(first_time_this_login(marker,env,boot)); self.assertFalse(first_time_this_login(marker,env,boot))
            boot.write_text("boot-2\n"); self.assertTrue(first_time_this_login(marker,env,boot))   # a reboot
            self.assertNotEqual(session_key({"SWAYSOCK":"/run/a.1.sock"},boot),session_key({"SWAYSOCK":"/run/a.2.sock"},boot))
    def test_a_stale_pid_naming_another_program_is_not_tvwcs(self):
        with tempfile.TemporaryDirectory() as d:
            proc=Path(d); (proc/str(os.getpid())).mkdir(); cmd=proc/str(os.getpid())/"cmdline"
            cmd.write_bytes(b"python3\0-m\0tvwcs.main\0"); self.assertTrue(is_tvwcs_process(os.getpid(),proc))
            cmd.write_bytes(b"/usr/bin/firefox\0"); self.assertFalse(is_tvwcs_process(os.getpid(),proc))
            self.assertFalse(is_tvwcs_process(2**22+12345,proc)); self.assertFalse(is_tvwcs_process("x",proc))

SESSION=Path(__file__).resolve().parents[2]/"data"/"tvwcs-session"
STANDARD="""# Default config for sway
set $mod Mod4
bar {
    position top
    status_command while date +'%Y-%m-%d %X'; do sleep 1; done
    colors {
        statusline #ffffff
    }
}
mode "resize" {
    bindsym Left resize shrink width 10px
}
include /etc/sway/config.d/*
"""
class SessionConfigTests(unittest.TestCase):
    """tvwcs-session's config: made from sway's standard one, without its bar (swaybar would flash before TV mode hid it)."""
    def run_session(self, d, systemd=False):
        d=Path(d); (d/"bin").mkdir(exist_ok=True); sway=d/"bin"/"sway"
        sway.write_text("#!/bin/sh\necho \"$@\" > \"$HOME/sway-args\"\n"); sway.chmod(0o755)
        cat=d/"bin"/"systemd-cat"; cat.write_text("#!/bin/sh\necho \"$@\" > \"$HOME/systemd-cat-args\"\nshift 2; exec \"$@\"\n"); cat.chmod(0o755)
        (d/"standard").write_text(STANDARD)
        env={"HOME":str(d),"PATH":f"{d/'bin'}:/usr/bin:/bin","TVWCS_SWAY_STANDARD_CONFIG":str(d/"standard"),
             "TVWCS_SYSTEMD_RUN":str(d) if systemd else str(d/"no-systemd")}
        subprocess.run(["sh",str(SESSION)],env=env,check=True,stdin=subprocess.DEVNULL,stderr=subprocess.PIPE)
        return d/".config"/"tvwcs"/"sway-session.conf"
    def test_sways_messages_go_to_the_journal(self):
        with tempfile.TemporaryDirectory() as d:
            # greetd drops a session's output, so a session that ended by itself left no trace of why
            cfg=self.run_session(d,systemd=True)
            self.assertEqual((Path(d)/"systemd-cat-args").read_text().split(),["-t","sway","sway","-c",str(cfg)])
            self.assertEqual((Path(d)/"sway-args").read_text().split(),["-c",str(cfg)])
        with tempfile.TemporaryDirectory() as d:
            self.run_session(d); self.assertFalse((Path(d)/"systemd-cat-args").exists())   # without systemd: as before
    def test_waits_for_logind_to_make_the_session_active(self):
        with tempfile.TemporaryDirectory() as d:
            # LightDM switches to the session's console a moment after starting it; sway's libseat 0.8 checks only once
            b=Path(d)/"bin"; b.mkdir(); n=Path(d)/"asked"; s=Path(d)/"sway-asked"
            (b/"loginctl").write_text(f"#!/bin/sh\necho x >> {n}\n[ $(wc -l < {n}) -ge 3 ] && echo yes || echo no\n")
            (b/"sway").write_text(f"#!/bin/sh\nwc -l < {n} > {s}\n")
            for f in b.iterdir(): f.chmod(0o755)
            env={"HOME":d,"PATH":f"{b}:/usr/bin:/bin","TVWCS_SWAY_STANDARD_CONFIG":"/dev/null","XDG_SESSION_ID":"c3","TVWCS_SYSTEMD_RUN":"/nonexistent"}
            subprocess.run(["sh",str(SESSION)],env=env,check=True,stdin=subprocess.DEVNULL)
            self.assertEqual(s.read_text().strip(),"3")
            (b/"loginctl").write_text("#!/bin/sh\nexit 1\n"); (b/"sway").write_text("#!/bin/sh\n"); t=time.monotonic()   # no such session: no wait
            subprocess.run(["sh",str(SESSION)],env=env,check=True,stdin=subprocess.DEVNULL)
            self.assertLess(time.monotonic()-t,1)
    def live(self, cfg): return [l for l in cfg.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    def test_a_new_config_has_no_bar(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=self.run_session(d); live=self.live(cfg)
            self.assertFalse([l for l in live if l.lstrip().startswith(("bar","position","status_command","colors","statusline"))])
            self.assertIn('mode "resize" {',live); self.assertIn("    bindsym Left resize shrink width 10px",live)
            self.assertIn("include /etc/sway/config.d/*",live); self.assertEqual(live[-1],"include /usr/share/tvwcs/tvwcs.conf")
            self.assertEqual(live.count("}"),1)   # the resize mode's: the bar's are commented out with it
            self.assertEqual((Path(d)/"sway-args").read_text().split(),["-c",str(cfg)])
    def test_an_older_config_loses_its_bar_once(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/".config"/"tvwcs"/"sway-session.conf"; cfg.parent.mkdir(parents=True)
            cfg.write_text("# made by 5.2.0\n"+STANDARD+"include /usr/share/tvwcs/tvwcs.conf\n")
            self.run_session(d); live=self.live(cfg)
            self.assertFalse([l for l in live if l.lstrip().startswith("bar")]); self.assertIn("set $mod Mod4",live)
            self.assertFalse((cfg.parent/"sway-session.conf.tmp").exists())
            with cfg.open("a") as f: f.write("bar {\n    position bottom\n}\n")   # a bar added afterwards is kept
            self.run_session(d); self.assertIn("bar {",self.live(cfg))
if __name__=="__main__": unittest.main()
