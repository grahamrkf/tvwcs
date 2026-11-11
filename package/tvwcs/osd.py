"""The volume indicator: a small panel near the bottom of the screen that shows the volume for a moment after a volume
key (`tvwcs volume up|down|mute`), over every window, full-screen ones too.

On sway a full-screen window is drawn above every other window (see window_manager.leave_fullscreen), so the
indicator is a layer-shell surface on the overlay layer (gtk4-layer-shell, preloaded as the screen saver was before
5.0), which takes no keyboard focus. Without gtk4-layer-shell (Ubuntu 24.04 has none) it is a floating window that
sway never focuses (tvwcs.conf): it then shows over everything but a full-screen window.

One process (`python3 -m tvwcs.osd`) stays running once it has started, so a held key keeps up: `tvwcs volume` writes
the new level to LEVEL_FILE and signals it (SIGUSR1), or starts it. The top part has no GTK dependency."""
from __future__ import annotations
import glob, os, signal, subprocess, sys

from tvwcs.session import runtime_dir

LEVEL_NAME="tvwcs-osd"           # "<percent> <muted 0|1>", the level to show
PID_NAME="tvwcs-osd.pid"         # the running indicator's process id (held under an flock while it runs)
STARTING_NAME="tvwcs-osd.starting"   # there while a key is starting the indicator
SHOW_MS=1000                     # how long it stays after the last key
LAYER_SHELL_LIB="libgtk4-layer-shell.so.0"
LAYER_SHELL_TYPELIB="Gtk4LayerShell-1.0.typelib"
LIB_DIRS=("/usr/lib/x86_64-linux-gnu","/usr/lib/aarch64-linux-gnu","/usr/lib/arm-linux-gnueabihf","/usr/lib64","/usr/lib","/usr/local/lib")
APP_ID="com.tvwcs.Osd"           # tvwcs.conf's rules for the floating window match it
TITLE="TVWCS · Volume"           # a TVWCS title (model.is_tvwcs_title): never listed among the open applications

def _sway(env): return bool((os.environ if env is None else env).get("SWAYSOCK"))

# ---------------------------------------------------------------------- the level
def format_level(volume, muted): return f"{max(0,int(volume))} {1 if muted else 0}\n"

def parse_level(text):
    """LEVEL_FILE's text -> (percent, muted); (None, False) when it holds none."""
    parts=(text or "").split()
    try: return max(0,int(parts[0])),len(parts)>1 and parts[1]=="1"
    except (IndexError,ValueError): return None,False

def fraction(volume, top):
    """How full the bar is: the volume against the top the volume keys stop at (100 %, or 150 % with
    over-amplification), never past full."""
    return 0.0 if not top else max(0.0,min(1.0,volume/top))

def describe(volume, muted):
    """(icon name, text glyph, the words shown) for a level, as the Quick Menu's volume icon (quick_status)."""
    from tvwcs.quick_status import Status, volume_icon
    icon,fallback,_=volume_icon(Status(volume=volume,muted=muted))
    return icon,fallback,("Muted" if muted else f"{volume}%")

# ---------------------------------------------------------------------- gtk4-layer-shell
def layer_shell_found(dirs=LIB_DIRS):
    """Both gtk4-layer-shell's library and its introspection data are installed (Debian's gir1.2-gtk4layershell-1.0
    does not bring the library). The check loads neither: the library must be loaded before GTK."""
    lib=any(os.path.exists(os.path.join(d,LAYER_SHELL_LIB)) for d in dirs) or glob.glob(f"/usr/lib/*/{LAYER_SHELL_LIB}")
    gir=any(os.path.exists(os.path.join(d,"girepository-1.0",LAYER_SHELL_TYPELIB)) for d in dirs) \
        or glob.glob(f"/usr/lib/*/girepository-1.0/{LAYER_SHELL_TYPELIB}")
    return bool(lib and gir)

def launch_env(env=None, found=None):
    """The environment to start the indicator in: drawn without the GPU, and on sway with gtk4-layer-shell, with it
    preloaded (it must be loaded before libwayland-client, which GTK loads as soon as it is imported; from Python that
    means LD_PRELOAD)."""
    env=dict(os.environ if env is None else env)
    env.setdefault("GSK_RENDERER","cairo")   # a few flat boxes: no GPU context to set up and keep (a third of the memory)
    if _sway(env) and (layer_shell_found() if found is None else found):
        preload=env.get("LD_PRELOAD","").split()
        if LAYER_SHELL_LIB not in preload: env["LD_PRELOAD"]=" ".join([LAYER_SHELL_LIB]+preload)
    return env

# ---------------------------------------------------------------------- telling it (no GTK)
def running_pid(env=None, proc="/proc"):
    """The running indicator's process id, or None: not one that has ended (a zombie) or a reused id."""
    try:
        pid=int((runtime_dir(env)/PID_NAME).read_text(encoding="ascii").strip())
        with open(f"{proc}/{pid}/cmdline","rb") as f: cmdline=f.read()
        with open(f"{proc}/{pid}/stat","rb") as f: state=f.read().rsplit(b")",1)[1].split()[0]
    except (OSError,ValueError,IndexError): return None
    return pid if b"tvwcs.osd" in cmdline and state not in (b"Z",b"X") else None

def can_show(env=None):
    """There is a graphical session to show it in (not over SSH, not at a text console)."""
    env=os.environ if env is None else env
    return bool(env.get("WAYLAND_DISPLAY") or env.get("SWAYSOCK"))

def _claim_start(rt, now=None, patience=5.0):
    """Only the first of a burst of keys starts the indicator (STARTING_NAME marks it, until the indicator runs or
    `patience` seconds have passed, in case it never came up)."""
    import time
    mark=rt/STARTING_NAME; now=time.time() if now is None else now
    try: os.close(os.open(mark,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)); return True
    except FileExistsError:
        try:
            if now-mark.stat().st_mtime<patience: return False
            mark.touch(); return True
        except OSError: return True
    except OSError: return True

def show(volume, muted, env=None):
    """Show this level: hand it to the running indicator, or start one. Never raises: a volume key still works
    without it (no display, no GTK)."""
    env=os.environ if env is None else env
    if volume is None or not can_show(env): return False
    rt=runtime_dir(env)
    try:
        rt.mkdir(parents=True,exist_ok=True)
        tmp=rt/(LEVEL_NAME+".tmp"); tmp.write_text(format_level(volume,muted),encoding="ascii"); tmp.replace(rt/LEVEL_NAME)
    except OSError: return False
    pid=running_pid(env)
    if pid:
        try: os.kill(pid,signal.SIGUSR1); return True
        except OSError: pass
    if not _claim_start(rt): return True   # another key is starting it: it shows the newest level once up
    try:
        subprocess.Popen([sys.executable,"-m","tvwcs.osd"],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,env=launch_env(env))
        return True
    except OSError: return False

# ---------------------------------------------------------------------- the indicator (GTK)
OSD_CSS="""
window.tvwcs-osd { background: transparent; }
.osd-panel { background: @PANE@; color: @FG@; padding: 18px 26px; border: 2px solid @BORDER@; }
.osd-panel .glyph { color: @FG@; font-size: 26px; }
.osd-panel levelbar trough { background: @TROUGH@; border: none; border-radius: 0; min-height: 10px; padding: 0; }
.osd-panel levelbar block { border: none; border-radius: 0; min-height: 10px; }
.osd-panel levelbar block.filled { background: @ACCENT@; }
.osd-panel levelbar block.empty { background: transparent; }
.osd-panel .osd-value { font-size: 22px; font-weight: 700; min-width: 96px; }
.osd-panel.muted-level levelbar block.filled { background: @FAINT@; }
"""
BAR_WIDTH=320   # px at desktop size

def main(args=()):
    env=os.environ
    if _sway(env) and layer_shell_found() and LAYER_SHELL_LIB not in env.get("LD_PRELOAD","").split():
        e=launch_env(env,found=True); os.execve(sys.executable,[sys.executable,"-m","tvwcs.osd",*args],e)   # started by hand
    import fcntl
    rt=runtime_dir(); rt.mkdir(parents=True,exist_ok=True)
    lock=open(rt/PID_NAME,"a+",encoding="ascii")
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:   # one is running already (two keys raced to start it): it shows the level
        pid=running_pid()
        if pid: os.kill(pid,signal.SIGUSR1)
        return 0
    signal.signal(signal.SIGUSR1,signal.SIG_IGN)   # until GTK is up (keys may signal it from now on): the level is read then
    lock.seek(0); lock.truncate(); lock.write(f"{os.getpid()}\n"); lock.flush()
    try: (rt/STARTING_NAME).unlink()
    except OSError: pass

    import gi
    gi.require_version("Gtk","4.0"); gi.require_version("Gdk","4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk
    GLib.set_prgname(APP_ID)   # the app_id tvwcs.conf's rules match (else "python3")
    layer=None
    if LAYER_SHELL_LIB in env.get("LD_PRELOAD","").split():
        try:
            gi.require_version("Gtk4LayerShell","1.0")
            from gi.repository import Gtk4LayerShell as layer
            if not layer.is_supported(): layer=None
        except (ImportError,ValueError,AttributeError): layer=None
    from tvwcs import widgets
    from tvwcs.control_sound import top
    from tvwcs.model import ConfigStore, effective_scale, scale_key
    from tvwcs.theme import render_css

    class Indicator(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.NON_UNIQUE)
            self.win=None; self.hide_id=0; self.look=None; self.provider=Gtk.CssProvider()
        def do_activate(self):
            self.hold()
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGUSR1,lambda:(self.update(),GLib.SOURCE_CONTINUE)[1])
            for sig in (signal.SIGTERM,signal.SIGINT): GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,sig,lambda:(self.quit(),GLib.SOURCE_REMOVE)[1])
            self.update()
        def build(self, settings):
            """The panel, in the current theme and size (rebuilt when either changed since the last key)."""
            scale=effective_scale(scale_key(settings),widgets.screen_height())
            look=(settings.get("accent"),settings.get("theme"),settings.get("style"),settings.get("phosphor"),settings.get("retro_font"),
                  scale,settings.get("margin"))
            if look==self.look and self.win is not None: return
            self.look=look; widgets.set_scale(scale)
            widgets.use_retro(settings.get("style")=="retro",settings.get("retro_font","pixel"))
            self.provider.load_from_data(render_css(settings.get("accent","#0078d7"),scale,OSD_CSS,theme=settings.get("theme","dark"),
                                                    style=settings.get("style","modern"),phosphor=settings.get("phosphor","green"),
                                                    retro_font=settings.get("retro_font","pixel")).encode("utf-8"))
            if self.win is not None: self.win.destroy()
            win=Gtk.Window(application=self,title=TITLE,decorated=False,resizable=False); win.add_css_class("tvwcs-osd")
            win.set_can_focus(False); win.set_focusable(False)
            box=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=widgets.S(16)); box.add_css_class("osd-panel"); box.add_css_class("tvwcs-root")
            self.panel=box; self.icon_slot=Gtk.Box(); box.append(self.icon_slot)
            self.bar=Gtk.LevelBar(min_value=0,max_value=1); self.bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
            for name in ("low","high","full"): self.bar.remove_offset_value(name)
            self.bar.set_size_request(widgets.S(BAR_WIDTH),-1); self.bar.set_valign(Gtk.Align.CENTER); box.append(self.bar)
            self.value=Gtk.Label(xalign=1); self.value.add_css_class("osd-value"); box.append(self.value)
            win.set_child(box); self.icon_name=None
            margin=widgets.S(int(settings.get("margin") or 0)+48)
            if layer is not None:
                layer.init_for_window(win); layer.set_namespace(win,"tvwcs-osd"); layer.set_layer(win,layer.Layer.OVERLAY)
                layer.set_anchor(win,layer.Edge.BOTTOM,True); layer.set_margin(win,layer.Edge.BOTTOM,margin)
                layer.set_exclusive_zone(win,-1); layer.set_keyboard_mode(win,layer.KeyboardMode.NONE)
            else:
                win.connect("map",lambda w:GLib.timeout_add(30,lambda:(place_floating(w,margin),GLib.SOURCE_REMOVE)[1]))
            self.win=win
        def update(self):
            try: volume,muted=parse_level((rt/LEVEL_NAME).read_text(encoding="ascii"))
            except OSError: volume,muted=None,False
            if volume is None: return
            settings=ConfigStore().settings; self.build(settings)
            icon,fallback,words=describe(volume,muted)
            if icon!=self.icon_name:
                for child in list(self.icon_slot): self.icon_slot.remove(child)
                self.icon_slot.append(widgets.glyph(icon,fallback,26)); self.icon_name=icon
            self.bar.set_value(fraction(volume,top(bool(settings.get("audio_boost")))))
            self.value.set_text(words)
            (self.panel.add_css_class if muted else self.panel.remove_css_class)("muted-level")
            self.win.set_visible(True)
            if self.hide_id: GLib.source_remove(self.hide_id)
            self.hide_id=GLib.timeout_add(SHOW_MS,self.hide)
        def hide(self):
            self.hide_id=0
            if self.win is not None: self.win.set_visible(False)
            return GLib.SOURCE_REMOVE

    def place_floating(win, margin):
        """Without layer-shell: bottom centre of the focused display (sway first maps a floating window in the middle)."""
        import json
        try:
            outs=json.loads(subprocess.run(["swaymsg","-t","get_outputs","-r"],capture_output=True,text=True,timeout=2).stdout or "[]")
            out=next((o for o in outs if o.get("focused")),None) or next((o for o in outs if o.get("active")),None)
            if not out: raise ValueError("no display")
            r=out["rect"]; w=win.get_width(); h=win.get_height()
            x=r["x"]+(r["width"]-w)//2; y=r["y"]+r["height"]-h-margin
            subprocess.run(["swaymsg",f'[app_id="^{APP_ID.replace(".",chr(92)+".")}$"] move absolute position {x} {y}, opacity 1'],
                           capture_output=True,timeout=2)
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):   # shown where sway put it rather than not at all
            subprocess.run(["swaymsg",f'[app_id="^{APP_ID.replace(".",chr(92)+".")}$"] opacity 1'],capture_output=True,timeout=2)

    return Indicator().run([])

if __name__=="__main__": raise SystemExit(main(sys.argv[1:]))
