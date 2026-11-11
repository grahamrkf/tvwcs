#!/usr/bin/env python3
"""TVWCS — Metro-style TV launcher and workspace switcher for sway. Application controller and command line."""
from __future__ import annotations
import os, shlex, signal, subprocess, sys, threading, time
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from tvwcs.applications import ApplicationCatalogue, match_window
from tvwcs.hotkeys import MODIFIER_KEYSYMS, render_bindings
from tvwcs.model import CONFIG_HOME, SETTINGS_DESKTOP_ID, default_of, display_name, effective_scale, LAUNCH_NEW_WORKSPACE, LAUNCH_PLAIN, PIN_LAUNCH_AND_SHOW, ConfigStore, compute_layout, corner_top, dark_look, wallpaper_of, is_4k, scale_key, tv_mode as in_tv_mode
from tvwcs.ownership import WindowOwners
from tvwcs.pinlock import PinGate
from tvwcs import appearance, control_sound, cursor, last_app, power, privilege, quick_status, return_focus, sway_include, tv_mode
from tvwcs.session import first_time_this_login, is_tvwcs_process, runtime_dir
from tvwcs.system_actions import POWER_VERBS, SYSTEM_ACTIONS, allowed, command_for, unavailable_message
from tvwcs.ui_editors import ProfileEditor
from tvwcs.ui_window import TVWCSWindow
from tvwcs.widgets import app_icon, has_icon, screen_height, set_scale
from tvwcs.window_manager import WindowManager
from tvwcs.workspaces import build_entries

APP_ID="com.tvwcs.TVWCS"
RUNTIME=runtime_dir()                            # XDG_RUNTIME_DIR, or ~/.cache/tvwcs without one (see session.py)
PID_FILE=RUNTIME/"tvwcs.pid"
STARTUP_MARKER=RUNTIME/"tvwcs-startup-done"      # records the login the start-up action last ran in
PASSWORD_TRIES=3                                  # wrong administrator passwords before TVWCS gives up
REQUESTS_FILE=RUNTIME/"tvwcs-requests"          # `tvwcs launch <id>` appends a line here, then signals the running TVWCS
HOTKEYS_FILE=CONFIG_HOME/"tvwcs"/"hotkeys.conf"  # generated from Settings; included by tvwcs.conf
BAR_MODES_FILE=RUNTIME/"tvwcs-bar-modes.json"    # the modes the bars had before TV mode hid them (see tv_mode.py)
LAUNCHER=sway_include.launcher()

class IdleWatcher:
    """The Power and sleep times (Settings > Power and sleep): after so long without input, turn the screen off, lock,
    sleep. TVWCS runs swayidle with them, which calls `tvwcs idle …` back. Nothing happens while sound plays or an
    application keeps the computer awake (see power.py)."""
    BATTERY_TICK=20   # seconds between looks at the battery
    def __init__(self, app):
        self.app=app; self.swayidle=power.SwayIdle()
        self.battery=power.read_battery(); self.battery_source=0; self.critical_done=False
    def times(self): return power.active_idle(self.app.store.settings,self.battery)
    def apply(self):
        if self.battery.present and not self.battery_source:
            self.battery_source=GLib.timeout_add_seconds(self.BATTERY_TICK,self._battery_tick)
        problem=self.swayidle.apply(self.times(),LAUNCHER)
        if problem: print(problem,file=sys.stderr)
    def _battery_tick(self):
        """Plugging in or unplugging switches between the two sets of times; a nearly empty battery does what
        Settings > Power and sleep says (once, until the charger is plugged in)."""
        before=self.battery.on_battery; self.battery=power.read_battery()
        if self.battery.on_battery!=before: self.apply()
        if not self.battery.on_battery: self.critical_done=False
        action=power.critical(self.app.store.settings,self.battery)
        if action and not self.critical_done:
            self.critical_done=True; print(f"The battery is at {self.battery.percent}%: {action}.",file=sys.stderr)
            self.app.run_system_action(action)
        return GLib.SOURCE_CONTINUE
    def stop(self): self.swayidle.stop()

class CursorWatcher:
    """Hides the mouse pointer in TV mode (cursor.py)."""
    def __init__(self, app):
        self.app=app; self.hider=cursor.CursorHider()
    def apply(self):
        problem=self.hider.apply(self.app.store.settings)
        if problem: print(problem,file=sys.stderr)
    def stop(self): pass

class VolumeWatcher:
    """Keeps every output at or under the volume limit (100 %, or 150 % with Settings > Sound > Allow
    over-amplification), whatever raised it (control_sound.VolumeGuard)."""
    def __init__(self, app):
        self.guard=control_sound.VolumeGuard(lambda:app.store.settings.get("audio_boost"))
    def apply(self): self.guard.start()
    def stop(self): self.guard.stop()

class CecWatcher:
    """The TV's remote over HDMI-CEC (cec.py), when this computer has a CEC port and it is on in Settings."""
    def __init__(self, app):
        self.app=app; self.service=None
    def apply(self):
        from tvwcs import cec
        options=self.app.store.settings["cec"]
        if not options["enabled"] or not cec.present():
            if self.service is not None: self.service.stop(release=True); self.service=None
            return
        if self.service is not None: self.service.update(options); return
        self.service=cec.CecService(RUNTIME,self._hotkey,self._tv_off)
        if not self.service.start(options): self.service=None
    def _hotkey(self, action):
        if action=="menu": self.app.show_mode("toggle")
        elif action=="last": self.app.switch_to_last_app()
    def _tv_off(self):
        print("TVWCS: the TV turned off; sleeping (Settings > Remote and hotkeys)",file=sys.stderr); self.app.run_system_action("sleep")
    def stop(self):
        if self.service is not None: self.service.stop(); self.service=None

class StatusWatcher:
    """Keeps the bottom of the Quick Menu current (the clock, and the network, volume, Bluetooth and updates icons) and
    does TV mode's housekeeping: the bar stays hidden, and the Quick Menu comes back once no application is open.
    Everything that runs a command runs on a worker thread."""
    TICK=2            # seconds between looks
    READ_EVERY=4      # seconds between reads of the status while the Quick Menu is on screen
    BAR_EVERY=4       # seconds between checks that the bar is still hidden (a sway reload shows it again)
    UPDATES_EVERY=3*3600   # seconds between update checks (the package lists, Flathub)
    def __init__(self, app):
        self.app=app; self.source=0; self.reading=False; self.last_read=0.0; self.last_bar=0.0; self.updates=0; self.reboot=False
        self.updates_due=time.monotonic()+90; self.checking_updates=False; self.bar_hidden=False; self.kept_open=False; self.had_windows=False
    def start(self):
        if not self.source: self.source=GLib.timeout_add_seconds(self.TICK,self._tick)
        self.apply_bar(); self.read_now()
    def stop(self):
        if self.source: GLib.source_remove(self.source); self.source=0
        if self.bar_hidden: tv_mode.restore_bars(self.app.wm,BAR_MODES_FILE); self.bar_hidden=False
    def _tick(self):
        app=self.app; w=app.window; now=time.monotonic()
        if w is None: return GLib.SOURCE_CONTINUE
        visible=w.is_visible()
        if visible:
            w.tick_clock()
            if now-self.last_read>=self.READ_EVERY: self.read_now()
        if app.tv:
            # "No application open" means nothing on screen: an app left on a workspace out of sight (Settings closed
            # over it, say) still leaves an empty screen to come back to
            has_windows=app.wm.screen_has_windows()
            if visible and self.had_windows and not has_windows and not w._modal_groups:
                w.focus_pane_soon("search")   # the last app on screen closed (from the ⋯ menu, say): back to the search field
            self.had_windows=has_windows
            if not visible:
                self.kept_open=False
                if has_windows: app.grace_until=0.0   # an app is open: whatever was launched has arrived
                elif tv_mode.should_show_menu(True,visible,has_windows,now,app.grace_until) and not app.has_dialogs(): app.show_mode("toggle")
            elif not has_windows: self.kept_open=True
            elif self.kept_open and tv_mode.should_step_aside(True,w.is_active(),has_windows,w._popovers>0 or app.has_dialogs()):
                # kept open over an empty screen, and a window opened from elsewhere (Settings from a shell, an app
                # started by a hotkey) took the focus: it would be hidden under the floating menu
                self.kept_open=False; app.hide_window(launched=True)
        if now-self.last_bar>=self.BAR_EVERY: self.apply_bar()
        if now>=self.updates_due and not self.checking_updates: self._check_updates()
        return GLib.SOURCE_CONTINUE
    def read_now(self):
        if self.reading: return
        self.reading=True; self.last_read=time.monotonic(); updates=self.updates; reboot=self.reboot
        def work():
            try: status=quick_status.read(updates,reboot)
            except Exception: status=None   # a status icon must never break the menu
            GLib.idle_add(lambda:(self._got(status),GLib.SOURCE_REMOVE)[1])
        threading.Thread(target=work,daemon=True).start()
    def _got(self, status):
        self.reading=False
        if status is None or status==self.app.status: return
        self.app.status=status
        if self.app.window is not None: self.app.window.show_status(status)
    def _check_updates(self):
        self.checking_updates=True
        def work():
            n,reboot=quick_status.check_updates()
            GLib.idle_add(lambda:(self._got_updates(n,reboot),GLib.SOURCE_REMOVE)[1])
        threading.Thread(target=work,daemon=True).start()
    def _got_updates(self, n, reboot=False):
        self.checking_updates=False; self.updates=n; self.reboot=reboot; self.updates_due=time.monotonic()+self.UPDATES_EVERY; self.read_now()
    def updates_changed(self):
        """Updates were installed or checked in Settings: count them again soon."""
        self.updates_due=min(self.updates_due,time.monotonic()+5)
    def apply_bar(self):
        """Hide the bar in TV mode, or give back one hidden before (desktop mode never changes it)."""
        self.last_bar=time.monotonic(); app=self.app
        if not app.wm.available: return
        hide=app.tv
        if not hide and not self.bar_hidden and not BAR_MODES_FILE.exists(): return
        def work():
            if hide: tv_mode.hide_bars(app.wm,BAR_MODES_FILE)
            else: tv_mode.restore_bars(app.wm,BAR_MODES_FILE)
        self.bar_hidden=hide
        threading.Thread(target=work,daemon=True).start()

def idle_action(action):
    """`tvwcs idle screen_off|lock|sleep|resume`: what swayidle runs when a Power and sleep time is reached."""
    if action=="resume": power.screen_on(); return 0
    if power.keep_awake(): return 0
    if action=="screen_off": return 0 if power.screen_off().ok else 1
    if not allowed(action): return 0   # server mode: an idle sleep set before it was turned on
    command=command_for(action,ConfigStore().settings)
    if not command: print(unavailable_message(action),file=sys.stderr); return 1
    return subprocess.call(command,env=privilege.c_locale_env())

class TVWCSApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.window=None; self.catalogue=ApplicationCatalogue(); self.store=ConfigStore(); self.wm=WindowManager()
        self.layout=None; self._area=None; self._owns_pid=False
        self.pin_gate=PinGate(); self.owners=WindowOwners()
        self._fullscreen=set()   # windows that were fullscreen when TVWCS was shown; they are made fullscreen again when it hides
        self._behind=None        # the app the Quick Menu was shown over, to go back to when Settings closes (return_focus.py)
        self.idle=IdleWatcher(self); self.cursor=CursorWatcher(self); self.volume_guard=VolumeWatcher(self); self.cec=CecWatcher(self)
        self.status=quick_status.Status(); self.watch=StatusWatcher(self)
        self.focus_history=last_app.FocusHistory(); self.focus_follower=last_app.FocusFollower(self.focus_history)   # for the Last app hotkeys
        # TV mode: the start-up action may be about to open an app (it runs 1.5 s after start)
        self.grace_until=time.monotonic()+(10 if self.store.settings["startup"]["mode"] in ("app","last") else 0)

    @property
    def scale_factor(self): return effective_scale(scale_key(self.store.settings),screen_height())
    @property
    def tv(self):
        """TV mode (a TVWCS session, see model.tv_mode), under sway: the bar is hidden and the Quick Menu stays
        open while no application is."""
        return in_tv_mode() and self.wm.available

    # ---------------------------------------------------------- lifecycle
    def do_startup(self):
        Gtk.Application.do_startup(self)
        if not self._claim_pid(): GLib.idle_add(self.quit); return
        set_scale(self.scale_factor)
        # Keep the application alive while its only window is hidden; IPC arrives as Unix signals handled by the GLib loop.
        self.hold()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGUSR1,lambda:(self.show_mode("toggle"),GLib.SOURCE_CONTINUE)[1])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGUSR2,lambda:(self.show_mode("guide"),GLib.SOURCE_CONTINUE)[1])
        # Requests that carry an argument (an application hotkey) are queued in REQUESTS_FILE. SIGWINCH is harmless to
        # ignore and GLib can watch it; a stray one finds no queue and does nothing.
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGWINCH,lambda:(self._take_requests(),GLib.SOURCE_CONTINUE)[1])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,self._on_stop_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,self._on_stop_signal)
        threading.Thread(target=self._restore_displays,daemon=True).start()
    @staticmethod
    def _restore_displays():
        """The display settings kept in Settings: sway forgets them at log-out."""
        from tvwcs import control_display
        problem=control_display.restore()
        if problem: print(f"Could not apply the saved display settings: {problem}",file=sys.stderr)
        if not os.environ.get("SWAYSOCK"):
            problem=control_display.restore_tearing()
            if problem: print(f"Could not set tear-free drawing: {problem}",file=sys.stderr)
    def _sway_reloaded(self):
        """sway drops every output setting it was given over IPC when it reloads (the scale Settings set goes back to
        sway's default, 200 % on many laptops), so put the saved display settings back."""
        threading.Thread(target=self._restore_displays,daemon=True).start()
    def _on_stop_signal(self): self.quit(); return GLib.SOURCE_REMOVE
    def do_activate(self):
        first=self.window is None
        self.refresh_data(rebuild=False)
        if first:
            self.apply_look(); self._update_layout(False,False,focus_output=False); self.window=TVWCSWindow(self)
            if self.wm.available and sway_include.reload_if_updated(RUNTIME):
                print("TVWCS: tvwcs.conf was updated; sway reloaded it",file=sys.stderr); self._sway_reloaded()
            self.apply_hotkeys(); self.idle.apply(); self.cursor.apply(); self.volume_guard.apply(); self.cec.apply(); self.focus_follower.start(); self.watch.start(); GLib.timeout_add(1500,self._run_startup_action)
        self.window.set_visible(False)
    def do_shutdown(self):
        self.idle.stop(); self.cursor.stop(); self.volume_guard.stop(); self.cec.stop(); self.focus_follower.stop(); self.watch.stop(); self._release_pid(); Gtk.Application.do_shutdown(self)
    def _claim_pid(self):
        try:
            PID_FILE.parent.mkdir(parents=True,exist_ok=True)
            if PID_FILE.exists():
                try: pid=int(PID_FILE.read_text().strip())
                except ValueError: pid=None
                if pid is not None and pid!=os.getpid() and is_tvwcs_process(pid):
                    print("TVWCS is already running.",file=sys.stderr); return False
            PID_FILE.write_text(str(os.getpid())); self._owns_pid=True; return True
        except OSError as exc: print(f"Cannot create PID file {PID_FILE}: {exc}",file=sys.stderr); return False
    def _release_pid(self):
        if self._owns_pid:
            try:
                if PID_FILE.read_text().strip()==str(os.getpid()): PID_FILE.unlink(missing_ok=True)
            except OSError: pass
    def refresh_data(self,rebuild=True):
        self.catalogue=ApplicationCatalogue.discover(); self.store.ensure_defaults(self.catalogue.applications)
        if rebuild and self.window is not None: self.window._build()

    # ---------------------------------------------------------- showing, hiding, geometry
    def _fallback_area(self):
        display=Gdk.Display.get_default()
        monitors=display.get_monitors() if display else None
        if monitors is not None and monitors.get_n_items():
            g=monitors.get_item(0).get_geometry(); return {"x":g.x,"y":g.y,"width":g.width,"height":g.height}
        return {"x":0,"y":0,"width":1920,"height":1080}
    def _update_layout(self,guide,options,focus_output=True,area=None):
        area=area or self.wm.usable_area(focus=focus_output) or self._fallback_area()
        self._area=area
        s=self.store.settings; f=self.scale_factor
        width=height=None; quick_width=round(s["quick_width"]*f)
        if guide and not in_tv_mode() and self.window is not None:
            try: width=self.window.apps_width()
            except Exception as exc: print(f"Cannot measure the Applications pane: {exc}",file=sys.stderr)
        if not guide and self.window is not None:
            # the Quick Menu alone is only as tall as its contents, in its corner
            try: height=self.window.quick_height(quick_width)
            except Exception as exc: print(f"Cannot measure the Quick Menu: {exc}",file=sys.stderr)
        self.layout=compute_layout(area,round(s["margin"]*f),quick_width,guide,options,width,height,corner=s["quick_corner"])
    def fit_quick_menu(self):
        """The Quick Menu's contents changed (search results, favorites): resize it to fit them."""
        w=self.window
        if w is None or not w.is_visible() or w.guide_open: return
        before=self.layout; self._update_layout(False,False,area=self._area)
        if before is not None and (before.y,before.height)==(self.layout.y,self.layout.height): return
        # In a bottom corner the window grows and shrinks upwards, its bottom row kept still. Left to GTK it would grow
        # downwards from its old top (its bottom row off the screen) and only then jump up into place: a flicker. In a top
        # corner growing downwards is what it should do, so it is resized at once.
        w.set_default_size(self.layout.width,self.layout.height)
        if before is None or self.layout.height>=before.height or corner_top(self.store.settings["quick_corner"]):
            self.apply_geometry(mapped=True)   # taller: moved and resized now, before GTK draws the new contents
            return
        # shorter: GTK first draws the new contents at the bottom of the window as it is, then it is made smaller
        pane=w.quick_pane; pane.set_valign(Gtk.Align.END); clock=w.get_frame_clock()
        def painted(*_):
            clock.disconnect(handler); self.apply_geometry(mapped=True)
            GLib.timeout_add(500,lambda:(pane.set_valign(Gtk.Align.FILL),GLib.SOURCE_REMOVE)[1])
        if clock is None: self.apply_geometry(mapped=True); pane.set_valign(Gtk.Align.FILL); return
        handler=clock.connect("after-paint",painted)
    def apply_geometry(self,mapped=False):
        """Ask sway to float the window at the computed rectangle. Repeated shortly after mapping because
        sway can only match the window once it exists (and GTK may still resize it after); a window already `mapped` is
        also placed at once."""
        if not self.wm.available or self.layout is None: return
        def place():   # where it should be by then: a later fit may have changed it
            l=self.layout
            if l is not None: self.wm.place_tvwcs(l.x,l.y,l.width,l.height)
            return GLib.SOURCE_REMOVE
        if mapped: place()
        for delay in (40,160,420): GLib.timeout_add(delay,place)
    def hide_window(self,launched=False):
        """Hide TVWCS, then make fullscreen again whatever was fullscreen when it was shown. `launched`: an app was just
        started, so nothing on the current workspace is made fullscreen over it."""
        if self.window is None: return
        if launched: self.grace_until=time.monotonic()+tv_mode.LAUNCH_GRACE
        elif self.window.is_visible() and self.tv and time.monotonic()>=self.grace_until and not self.wm.screen_has_windows():
            # TV mode with nothing open: there is nothing to go back to, so the Quick Menu stays (the Guide still closes)
            # The menu key or Back then goes back to the search field, ready for a channel number
            if self.window.guide_open: self.show_panels(False,False,focus="search")
            else: self.window.focus_pane_soon("search")
            return
        shown=self.window.is_visible(); self.window.set_visible(False); self.window.note_shown()
        if shown and self._fullscreen:
            ids=self._fullscreen; self._fullscreen=set()
            GLib.timeout_add(150,lambda:(self.wm.restore_fullscreen(ids,skip_current=launched),GLib.SOURCE_REMOVE)[1])   # once sway has refocused
    def has_dialogs(self):
        return any(w is not self.window and w.is_visible() for w in self.get_windows())
    def dismiss_dialogs(self):
        """Close every dialog (profile editor, application profiles, messages) without saving what is in it. Used when
        the TVWCS window is clicked while one is open: it then comes to the front, and a dialog left behind it would block it."""
        for w in list(self.get_windows()):
            if w is self.window or not w.is_visible(): continue
            discard=getattr(w,"discard",None)
            if discard is not None: discard()
            else: w.close()
    def has_4k_display(self):
        """True when a connected monitor is 4K (3840×2160) or larger."""
        display=Gdk.Display.get_default(); monitors=display.get_monitors() if display else None
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m=monitors.get_item(i); g=m.get_geometry(); f=max(1,m.get_scale_factor())
            if is_4k(g.width*f,g.height*f): return True
        return any(is_4k((o.get("rect") or {}).get("width",0),(o.get("rect") or {}).get("height",0)) for o in self.wm.outputs())

    def show_mode(self,mode):
        """'toggle' (the menu hotkey): show or hide the Quick Menu. 'guide' (the guide hotkey): open the Guide beside
        the Quick Menu, or close it again if it is already open."""
        w=self.window
        if w is None: return False
        visible=w.is_visible()
        if visible and self.wm.available and self.wm.tvwcs_on_screen() is False:
            visible=False   # left on a workspace out of sight (an app opened elsewhere while it showed): bring it here
        if mode=="toggle" and visible: self.hide_window(); return False
        guide=(mode=="guide") and not (visible and w.guide_open)
        if visible: self.show_panels(guide,False,focus="guide" if guide else "quick"); return False
        self._fullscreen=self.wm.fullscreen_windows()   # restored when TVWCS hides (see hide_window)
        behind=next((x for x in self.wm.windows() if x.get("focused")),None) if self.wm.available else None
        self._behind="settings" if return_focus.is_settings(behind) else return_focus.target_of(behind,fullscreen=behind is not None and int(behind["con_id"]) in self._fullscreen)   # Settings goes back to it
        self.wm.focus_output_under_mouse(); self.wm.leave_fullscreen(); self.wm.move_tvwcs_to_current_workspace(); self.refresh_data(rebuild=False)
        w.reset_scroll(); w.note_shown(); w.guide_open=guide; w.options_open=False
        self._update_layout(guide,False,focus_output=True)
        w.set_default_size(self.layout.width,self.layout.height); w._build()
        if not guide: self._update_layout(False,False,area=self._area); w.set_default_size(self.layout.width,self.layout.height)   # measured once built
        w.present(); self.apply_geometry()
        w.focus_pane_soon("guide" if guide else "search")   # the Quick Menu opens on its search field, ready for a channel number
        return False
    def show_panels(self,guide,options,focus=None):
        """Open or close the Guide / Settings panels of the visible window and resize it to fit."""
        w=self.window
        if w is None or not w.is_visible(): return
        if w.guide_open and not guide and self.has_dialogs(): self.dismiss_dialogs()   # an app's dialog from Applications closes with it
        back=w._last_focus.get("quick")   # closing the Guide moves GTK's selection to the first button (✕), not back here
        self._update_layout(guide,options,focus_output=False)
        w.set_panels(guide,options); w.set_default_size(self.layout.width,self.layout.height); self.apply_geometry()
        if focus: w.focus_pane_soon(focus,back if focus=="quick" else None)
    def apply_scale(self):
        """The interface size changed (in Settings > Options): rebuild everything at the new size."""
        set_scale(self.scale_factor); w=self.window
        self._update_layout(w.guide_open,w.options_open,focus_output=False)
        w.set_default_size(self.layout.width,self.layout.height); w._build()
        if not w.guide_open: self._update_layout(False,False,area=self._area); w.set_default_size(self.layout.width,self.layout.height)
        self.apply_geometry(); w.focus_pane_soon("guide" if w.guide_open else "quick")

    # ---------------------------------------------------------- open windows and workspaces
    def workspace_entries(self): return build_entries(self.wm.windows(),self.wm.workspaces(),self.match_application_window)
    def default_profile(self,application):
        return default_of(self.store.for_app(application.desktop_id),application.name)
    def profile_name(self,profile,application=None):
        """The name lists show: the application's, then the profile's own unless it is the default one."""
        app=application or self.catalogue.by_id().get(profile.desktop_id)
        if app is None: return profile.name
        main=self.default_profile(app)
        return display_name(profile,app.name,main is not None and main.id==profile.id)
    def match_application_window(self,window): return match_window(window,self.catalogue.applications)
    def window_icon(self,window,size=32,badge=None):
        app=self.match_application_window(window)
        spec=app.icon if app and app.icon else None
        if not spec:
            for candidate in (window.get("class"),window.get("instance")):
                if candidate and has_icon(candidate.lower()): spec=candidate.lower(); break
        return app_icon(spec,(app.name if app else None) or window.get("class") or window.get("title"),size,badge)
    def alongside_names(self):
        """The apps on the workspace on screen now (TVWCS itself left out), for the Quick Menu's "Open alongside …"."""
        names=[]
        for w in self.wm.windows():
            if not w.get("workspace_visible"): continue
            app=self.match_application_window(w); name=(app.name if app else None) or w.get("class") or w.get("title") or ""
            if name and name not in names: names.append(name)
        return names
    def open_favorites(self,windows=None):
        """{desktop id: the open window} for the favorites that are open now: the Quick Menu shows those once, as the
        open application (with ★), not twice. Matched by the application each window belongs to (its class), so a
        browser whose title changes with every page still matches."""
        found={}
        for w in self.wm.windows() if windows is None else windows:
            app=self.match_application_window(w)
            if app is not None: found.setdefault(app.desktop_id,w)
        return found
    def window_mode(self,window):
        """How selecting an open app shows it: in TV mode alone in a workspace of its own, in desktop mode where it is."""
        return LAUNCH_NEW_WORKSPACE if self.tv else LAUNCH_PLAIN
    def launch_mode(self,profile=None):
        """Where an app opens: in TV mode in a workspace of its own, full screen; in desktop mode where sway opens it.
        The Quick Menu's one-time choice (open alongside, or in a new workspace) passes its own mode instead."""
        return LAUNCH_NEW_WORKSPACE if self.tv else LAUNCH_PLAIN
    # PIN protection. A profile's PIN is asked when it is launched; if its scope is "launch and show" it is also asked
    # when an open window of it would be brought up from a workspace that is not on screen.
    def _with_pins(self,profiles,action):
        """Ask for each profile's PIN in turn, then run `action`."""
        if not profiles: action(); return
        self.window.ask_pin(profiles[0],lambda:self._with_pins(profiles[1:],action))
    def _window_profile(self,w):
        """The profile a window belongs to: the one that launched it, else its application's main profile."""
        owner=self.owners.owner(w["con_id"]); profile=self.store.get(owner) if owner else None
        if profile is None:
            app=self.match_application_window(w); profile=self.default_profile(app) if app else None
        return profile
    def _show_lock(self,w):
        p=self._window_profile(w)
        return p if p and p.pin_hash and p.pin_scope==PIN_LAUNCH_AND_SHOW and not w.get("workspace_visible") else None
    def _locks_for_workspace(self,name):
        locks=[]
        for w in self.wm.windows():
            if w["workspace"]==name:
                p=self._show_lock(w)
                if p and all(p.id!=q.id for q in locks): locks.append(p)
        return locks

    def focus_window(self,con_id,mode=None):
        w=next((x for x in self.wm.windows() if int(x["con_id"])==int(con_id)),None)
        if w is None: self.notify_message("Could not focus that window. It may have closed."); return
        lock=self._show_lock(w)
        self._with_pins([lock] if lock else [],lambda:self._focus_window_now(w,mode))
    def _focus_window_now(self,w,mode):
        if not self.wm.focus(w["con_id"],mode or self.window_mode(w)): self.notify_message("Could not focus that window. It may have closed."); return
        app=self.match_application_window(w); profile=self.default_profile(app) if app else None
        if profile: self.store.record_last_profile(profile.id)
        self.hide_window()
    def open_workspace(self,name):
        def go():
            if self.wm.focus_workspace(name): self.hide_window()
            else: self.notify_message("Could not switch to that workspace.")
        self._with_pins(self._locks_for_workspace(name),go)
    def move_workspace(self,name,output):
        def go():
            if self.wm.move_workspace_to_output(name,output): GLib.timeout_add(250,lambda:(self.refresh_data(rebuild=True),GLib.SOURCE_REMOVE)[1])
            else: self.notify_message("Could not move that workspace to another monitor.")
        self._with_pins(self._locks_for_workspace(name),go)   # moving can bring it on screen
    def close_workspace(self,entry):
        if not self.wm.close_workspace(entry.name): self.notify_message("Could not close every application on that workspace.")
        GLib.timeout_add(400,lambda:(self.refresh_data(rebuild=True),GLib.SOURCE_REMOVE)[1])

    # ---------------------------------------------------------- profiles and launching
    def toggle_favorite(self,profile):
        p=self.store.get(profile.id)
        if p: p.favorite=not p.favorite; self.store.save(); self.window.refresh_favorites(p.id)   # in place: no rebuild, no jump
    def edit_profile(self,profile,application):
        """The profile editor, in the TVWCS window. A new profile is not stored until Save."""
        if profile is None and application is None: return
        ProfileEditor(self.window,profile,application or self.catalogue.by_id().get(profile.desktop_id)).open()
    def edit_application_profiles(self,desktop_id):
        """✎ on an application: its default profile's editor (4.0 has no list of profiles: each is a row of its own)."""
        app=self.catalogue.by_id().get(desktop_id); main=self.default_profile(app) if app else None
        if main is not None: self.edit_profile(main,app)
    def activate_result(self,result):
        if result["kind"]=="profile": self.launch_profile(result["profile"])
        elif result["kind"]=="window": self.focus_window(result["window"]["con_id"])
    STARTING_SLOW=20   # seconds before "Starting …" says the app may not have started
    STARTING_GIVE_UP=60
    URGENT_WATCH=15    # seconds a launch made with TVWCS hidden is watched for an app that only flags its open window
    def _launched(self,profile,started=False,before=None,urgent=None,mode=None):
        """After a launch: hide TVWCS once the app's first window appears. Until then the app's button shows a spinner
        wherever the screen would otherwise stay empty (an app opening in a workspace of its own takes a few seconds to
        draw anything), and TVWCS stays reachable with its hotkey. Started with no button of it on screen (a hotkey), a
        "Starting Jellyfin…" card shows instead. An app that was already running in a way TVWCS could not match often
        opens no new window and only flags its open one as urgent: that window is shown."""
        self.store.record_last_profile(profile.id)
        w=self.window
        if not started or before is None or w is None or not self.wm.available: self.hide_window(launched=started); return
        urgent=set(urgent or ())
        blank=mode==LAUNCH_NEW_WORKSPACE or not self.wm.screen_has_windows()
        waiting=w.is_visible() or blank
        card=False
        if waiting:
            if w.is_visible(): self.wm.move_tvwcs_to_current_workspace(); self.apply_geometry(); w.present()   # follow to the new workspace, keeping the focus
            else: self.show_mode("toggle")
            self.grace_until=time.monotonic()+tv_mode.LAUNCH_GRACE   # Back hides TVWCS over the empty screen meanwhile
            card=not w.set_launching(profile.id,True)
        else: self.hide_window(launched=True)
        state={"done":False,"t":0.0}
        def finish(show=None):
            if state["done"]: return
            state["done"]=True; w.set_launching(profile.id,False)
            if card and w._modal_groups: w.close_modal()
            if show is not None and not self.wm.focus(show,mode or LAUNCH_PLAIN): show=None
            if waiting and w.is_visible(): self.hide_window(launched=show is None)
        def check():
            if state["done"]: return GLib.SOURCE_REMOVE
            if waiting and (not w.is_visible() or (card and not w._modal_groups)):   # closed some other way
                state["done"]=True; w.set_launching(profile.id,False); return GLib.SOURCE_REMOVE
            state["t"]+=0.4
            windows=self.wm.windows()
            if any(int(x["con_id"]) not in before for x in windows): finish(); return GLib.SOURCE_REMOVE
            flagged=[int(x["con_id"]) for x in windows if x.get("urgent") and int(x["con_id"]) in before and int(x["con_id"]) not in urgent]
            if flagged: finish(flagged[0]); return GLib.SOURCE_REMOVE
            if state["t"]>=(self.STARTING_GIVE_UP if waiting else self.URGENT_WATCH): finish(); return GLib.SOURCE_REMOVE
            if waiting and abs(state["t"]-self.STARTING_SLOW)<0.2:
                if card: w.starting_slow(profile.name)
                else: w.launching_slow(profile.id,profile.name)
            return GLib.SOURCE_CONTINUE
        if card: w.show_starting(profile.name,finish)
        GLib.timeout_add(400,check)
    def launch_profile(self,profile,bypass_pin=False,mode=None):
        """Start a profile (or show its open window). `mode`: the Quick Menu's one-time "open alongside" (LAUNCH_SAME)
        or "open in a new workspace" (LAUNCH_NEW_WORKSPACE), instead of the mode's usual way."""
        if profile is None: return
        if self.window is not None and profile.id in self.window.launching: return   # starting already: its button spins
        self.note_settings_return(profile.desktop_id)
        app=self.catalogue.by_id().get(profile.desktop_id)
        # A plain profile returns to an existing window when it can; custom commands and desktop actions
        # run as written because they may stand for a separate session of the app.
        existing=None if (profile.command.strip() or profile.desktop_action) else self.wm.find_matching(profile,app)
        if existing is not None:
            needs_pin=profile.pin_scope==PIN_LAUNCH_AND_SHOW and not existing.get("workspace_visible")
            go=lambda:self._show_existing(profile,app,existing,mode)
        else: needs_pin=True; go=lambda:self._start(profile,app,mode)
        if profile.pin_hash and needs_pin and not bypass_pin: self.window.ask_pin(profile,go)
        else: go()
    def _show_existing(self,profile,app,window,mode=None):
        if self.wm.focus(window["con_id"],mode or self.window_mode(window)): self._launched(profile)
        else: self._start(profile,app,mode)
    def _start(self,profile,app,mode=None):
        before={int(w["con_id"]) for w in self.wm.windows()}; urgent=self.wm.urgent_ids()
        known=before if any(p.pin_hash for p in self.store.profiles) else None
        mode=mode or self.launch_mode(profile)
        try:
            if profile.desktop_action and app:
                info=Gio.DesktopAppInfo.new(profile.desktop_id)
                if info is None: raise RuntimeError(f"No desktop launcher is available for {profile.desktop_id}.")
                self.wm.prepare_for_launch(mode); info.launch_action(profile.desktop_action,None)
            elif profile.command.strip():
                args=shlex.split(profile.command)
                if not args: raise ValueError("The custom launch command is empty.")
                self.wm.prepare_for_launch(mode)
                subprocess.Popen(args,start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:
                info=Gio.DesktopAppInfo.new(profile.desktop_id)
                if info is None: raise RuntimeError(f"No desktop launcher is available for {profile.desktop_id}.")
                self.wm.prepare_for_launch(mode)
                if not info.launch([],None): raise RuntimeError(f"Linux refused to launch {profile.name}.")
            if known is not None: self._remember_windows(profile,app,known)
            self._launched(profile,started=True,before=before,urgent=urgent,mode=mode)
        except (OSError,ValueError,RuntimeError) as exc: self.notify_message(f"Could not launch {profile.name}: {exc}")
    def _remember_windows(self,profile,app,known):
        """Note which windows this launch opened, so a later 'show' knows whose PIN applies. The app needs a moment to map them."""
        def claim():
            windows=self.wm.windows()
            self.owners.claim(known,windows,profile.id,lambda w:app is None or match_window(w,[app]) is app)
            self.owners.forget_closed(windows); return GLib.SOURCE_REMOVE
        for delay in (1500,4000,9000): GLib.timeout_add(delay,claim)
    def launch_action(self,application,action_id,mode=None):
        profile=self.default_profile(application)
        def go():
            self.note_settings_return(application.desktop_id)
            try:
                info=Gio.DesktopAppInfo.new(application.desktop_id)
                if info is None: raise RuntimeError("Desktop launcher is no longer available.")
                before={int(w["con_id"]) for w in self.wm.windows()}; urgent=self.wm.urgent_ids(); launch=mode or self.launch_mode(profile)
                # An app that is open usually takes its own actions in the window it has (Settings' pages), and does not
                # always flag it (sway without an activation token): no new workspace, and its window is shown.
                existing=self.wm.find_matching(profile,application) if profile is not None and mode is None else None
                if existing is None: self.wm.prepare_for_launch(launch)
                info.launch_action(action_id,None)
            except Exception as exc: self.notify_message(f"Could not launch desktop action: {exc}"); return
            if existing is not None: GLib.timeout_add(1200,self._show_after_action,existing,before); return
            # watched like any launch: an app that is already open often only flags its window, which is then shown
            if profile is not None: self._launched(profile,started=True,before=before,urgent=urgent,mode=launch)
            else: self.hide_window(launched=True)
        # An action starts the application, so the main profile's PIN applies to it too.
        self._with_pins([profile] if profile and profile.pin_hash else [],go)
    def _show_after_action(self,window,before):
        """After an open app's action: a new window it opened is already shown; otherwise show the window it has."""
        if not any(int(w["con_id"]) not in before for w in self.wm.windows()) and not self.wm.focus(window["con_id"],self.window_mode(window)):
            self.notify_message("Could not show that application. It may have closed."); return GLib.SOURCE_REMOVE
        self.hide_window(launched=True); return GLib.SOURCE_REMOVE
    def restart(self,launcher=None):
        """Start a fresh TVWCS once this process has exited (after an update replaced the program files), then quit.
        `launcher`: the new install's launcher, when the update moved TVWCS to another folder. It runs `tvwcs start`,
        the old name of `tvwcs launcher`, which a release rolled back to before 5.10.0 knows too."""
        wait='while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; exec "$2" start'
        try: subprocess.Popen(["sh","-c",wait,"sh",str(os.getpid()),str(launcher or LAUNCHER)],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError as exc: self.notify_message(f"TVWCS was updated, but could not restart itself: {exc}. Restart it (or sway) to use the new version."); return
        self.hide_window(); self.quit()
    def run_system_action(self,action_id):
        if not allowed(action_id):
            self.notify_message("This computer is in server mode: it is not put to sleep, restarted or shut down from TVWCS."); return
        command=command_for(action_id,self.store.settings)
        if not command:
            self.notify_message(unavailable_message(action_id)); return
        self.hide_window()
        power=action_id in POWER_VERBS; label=next((a.label for a in SYSTEM_ACTIONS if a.id==action_id),action_id)
        if power and privilege.needs_root(command): self._run_as_root(command,label); return
        def done(code,err):
            if code==0: return
            if power and privilege.polkit_refused(err): self._run_as_root(command,label); return   # no polkit agent to ask for a password
            self._failed(command,err)
        self._spawn(command,done,env=privilege.c_locale_env() if power else None)
    def _spawn(self,command,done,password=None,env=None):
        """Run a command without waiting for it; done(exit code, stderr) once it ends. `password` is written to its stdin."""
        try: proc=subprocess.Popen(command,start_new_session=True,env=env,stdin=subprocess.PIPE if password is not None else subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        except OSError as exc: self.notify_message(f"Could not run {command[0]}: {exc}"); return
        if password is not None:
            try: proc.stdin.write((password+"\n").encode()); proc.stdin.close()
            except OSError: pass   # it ended without reading it; its exit says why
        def finished(_pid,status):
            # Only what is there now: a program that forks (i3lock) leaves its child holding the pipe open, and a read to
            # the end would block the main loop until the screen is unlocked
            try:
                os.set_blocking(proc.stderr.fileno(),False); data=proc.stderr.read() or b""
                err=data.decode(errors="replace").strip()[-300:]
            except (OSError,ValueError): err=""
            try: proc.stderr.close()
            except OSError: pass
            proc.returncode=code=os.waitstatus_to_exitcode(status)   # GLib reaped it; tell Popen
            done(code,err)
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT,proc.pid,finished)
    def _failed(self,command,err):
        self.notify_message(f"{' '.join(command)} did not work{': '+err if err else '.'}")

    # Power actions that need root: a no-password doas or sudo rule (install.sh offers one), else the user's password.
    def _run_as_root(self,command,label):
        if os.geteuid()==0: self._spawn(command,lambda code,err:code and self._failed(command,err),env=privilege.c_locale_env()); return
        doas=privilege.doas_command(command)
        if doas: self._spawn(doas,lambda code,err:None if code==0 else self._sudo(command,label),env=privilege.c_locale_env())
        else: self._sudo(command,label)
    def _sudo(self,command,label):
        sudo=privilege.sudo_command(command)
        if sudo is None:
            self.notify_message(f"{label} needs administrator rights, and neither sudo nor a doas rule for it is available. "
                                "Install sudo, or run TVWCS's install.sh to set up a rule for it."); return
        def done(code,err):
            outcome=privilege.sudo_outcome(code,err)
            if outcome=="password": self._ask_root_password(command,label)
            elif outcome!="ok": self._sudo_failed(command,label,outcome,err)
        self._spawn(sudo,done,env=privilege.c_locale_env())
    def _ask_root_password(self,command,label,message="",tries=0):
        if self.window is None: return
        if not self.window.is_visible(): self.show_mode("toggle")   # the dialog is drawn in the TVWCS window
        self.window.ask_password(label,lambda password:self._sudo_with_password(command,label,password,tries),message)
    def _sudo_with_password(self,command,label,password,tries):
        self.hide_window()
        def done(code,err):
            outcome=privilege.sudo_outcome(code,err)
            if outcome=="wrong" and tries+1<PASSWORD_TRIES: self._ask_root_password(command,label,"Wrong password. Try again.",tries+1)
            elif outcome=="wrong": self.notify_message(f"{label}: the password was wrong {PASSWORD_TRIES} times.")
            elif outcome!="ok": self._sudo_failed(command,label,outcome,err)
        self._spawn(privilege.sudo_command(command,with_password=True),done,password=password,env=privilege.c_locale_env())
    def _sudo_failed(self,command,label,outcome,err):
        if outcome=="denied": self.notify_message(f"{label} needs administrator rights, and your user may not use sudo for it.")
        elif outcome=="tty": self.notify_message(f"{label}: sudo is set up to work only in a terminal (requiretty), so TVWCS cannot pass it a password.")
        else: self._failed(command,err)

    # ---------------------------------------------------------- hotkeys and start-up
    def set_hotkey(self,device,name,spec):
        """Set (or, with "", clear) one device's hotkey ("menu", "guide" or the remote's "fullscreen"). A key that
        something else had is taken from it (Settings asks first)."""
        self.store.set_slot_hotkey(device,name,spec); self.apply_hotkeys()
    def set_profile_hotkey(self,profile_id,spec):
        """Set (or, with "", clear) the hotkey that launches a profile, taking the key from whatever had it."""
        self.store.set_profile_hotkey(profile_id,spec); self.apply_hotkeys()
    def apply_hotkeys(self):
        """Write hotkeys.conf from the settings, the profiles' hotkeys and (on a TV) the border rules, and ask sway to reload
        if it changed."""
        text=render_bindings(self.store.settings["hotkeys"],str(LAUNCHER),self._modifier_keycodes(),self.store.app_hotkeys(),in_tv_mode())
        try: old=HOTKEYS_FILE.read_text(encoding="utf-8")
        except OSError: old=None
        if old!=text:
            try:
                HOTKEYS_FILE.parent.mkdir(parents=True,exist_ok=True); HOTKEYS_FILE.write_text(text,encoding="utf-8")
                if self.wm.reload(): self._sway_reloaded()
                GLib.timeout_add(800,lambda:(self.watch.apply_bar(),self.apply_look(),GLib.SOURCE_REMOVE)[2])   # a reload shows the bar again and drops the background
            except OSError as exc: self.notify_message(f"Could not save the hotkeys: {exc}")
    @staticmethod
    def _modifier_keycodes():
        """This keyboard's keycodes for the left Super/Alt/Ctrl/Shift keys, as X reports them (missing ones use the defaults)."""
        display=Gdk.Display.get_default(); codes={}
        if display is None: return codes
        for mod,name in MODIFIER_KEYSYMS.items():
            try: ok,keys=display.map_keyval(Gdk.keyval_from_name(name))
            except (AttributeError,TypeError): continue
            if ok and keys: codes[mod]=min(k.keycode for k in keys)
        return codes
    def _take_requests(self):
        """Run the requests queued by `tvwcs launch <id>` (an application's hotkey)."""
        work=REQUESTS_FILE.with_name(REQUESTS_FILE.name+".work")
        try: REQUESTS_FILE.replace(work); lines=work.read_text(encoding="utf-8").splitlines(); work.unlink(missing_ok=True)
        except OSError: return
        for line in lines:
            parts=line.split()
            if len(parts)==2 and parts[0]=="launch": self.launch_by_hotkey(parts[1])
            elif parts==["last-app"]: self.switch_to_last_app()
            elif parts==["reload"]: self.reload_options()
            elif parts==["status"]: self.watch.updates_changed()
            elif parts[:1]==["restart"]: self.restart(Path(line.split(" ",1)[1].strip()) if len(parts)>1 else None)
    def reload_options(self):
        """The Settings app changed TVWCS's options (the Options page): read them again, and apply the interface size
        and the hotkeys. Profiles are read again too, so nothing TVWCS saves afterwards undoes the change."""
        old=scale_key(self.store.settings); look=self._look(); corner=self.store.settings["quick_corner"]
        self.store.load(); self.store.ensure_defaults(self.catalogue.applications)
        self.apply_hotkeys(); self.idle.apply(); self.cursor.apply(); self.volume_guard.apply(); self.cec.apply(); self.watch.apply_bar(); self.watch.updates_changed()
        if self._look()!=look: self.apply_look()
        if self.window is None: return
        if scale_key(self.store.settings)!=old: set_scale(self.scale_factor)
        moved=self.store.settings["quick_corner"]!=corner   # placed and laid out again, like a new size
        if self.window.is_visible(): self.apply_scale() if scale_key(self.store.settings)!=old or moved else self.window._build()
    def note_settings_return(self,desktop_id=SETTINGS_DESKTOP_ID):
        """Just before Settings is started or shown: write down the app to go back to when it closes (return_focus.py),
        the one the Quick Menu shows over, else (a hotkey, TVWCS hidden) the one in use now. Over Settings itself nothing
        is written, so Settings keeps going back where it would have."""
        if desktop_id!=SETTINGS_DESKTOP_ID or not self.wm.available: return
        if self.window is not None and self.window.is_visible(): behind=self._behind
        else:
            focused=next((x for x in self.wm.windows() if x.get("focused")),None)
            behind="settings" if return_focus.is_settings(focused) else return_focus.target_of(focused)
        if behind!="settings": return_focus.note(behind)
    def open_settings(self,page=None):
        """A status icon or panel's settings button, opening its page (or channel 0, with no page): the Settings app, a
        separate application. It opens where any app would in this mode: an open Settings window is brought up that way,
        else a new one starts (in TV mode in a workspace of its own)."""
        app=self.catalogue.by_id().get(SETTINGS_DESKTOP_ID)
        profile=self.default_profile(app) if app else None
        mode=self.launch_mode(profile)
        existing=self.wm.find_matching(profile,app) if profile is not None else None
        self.note_settings_return()
        self.hide_window(launched=True)
        if existing is not None: self.wm.focus(existing["con_id"],mode)
        else: self.wm.prepare_for_launch(mode)
        try: subprocess.Popen([str(LAUNCHER),"settings",*([page] if page else [])],start_new_session=True,stdin=subprocess.DEVNULL)
        except OSError as exc: self.notify_message(f"Could not open Settings: {exc}")
    def switch_to_last_app(self):
        """The Last app hotkey (Super+Tab, a remote's key, the TV remote's Previous channel): bring up the app that was in
        use before the one in use now (last_app.py); pressed again, it goes back. Over the Quick Menu the app it shows
        over is the one in use; over an empty screen, the app used last comes back."""
        if not self.wm.available or self.window is None: return
        windows=self.wm.windows()
        if self.window.is_visible():
            behind=self._behind   # Settings is "settings" there
            if behind=="settings": current=next((int(w["con_id"]) for w in windows if return_focus.is_settings(w)),None)
            else: current=behind["con_id"] if isinstance(behind,dict) else None
        else: current=next((int(w["con_id"]) for w in windows if w.get("focused")),None)
        target=last_app.pick(self.focus_history.ids(),windows,current,last_app.tree_order(self.wm._tree() or {}))
        if target is None:   # the Quick Menu instead, to pick one
            if not self.window.is_visible(): self.show_mode("toggle")
            self.window.show_message("No other app is open. Choose one in the Quick Menu.",title="Nothing to switch to"); return
        if self._show_lock(target) and not self.window.is_visible(): self.show_mode("toggle")   # the PIN keypad is drawn in the window
        self.focus_window(target["con_id"])
    def launch_by_hotkey(self,profile_id):
        profile=self.store.get(profile_id)
        if profile is None: self.apply_hotkeys(); return   # deleted since the hotkeys were written
        if profile.pin_hash and self.window is not None and not self.window.is_visible(): self.show_mode("toggle")   # the PIN keypad is drawn in the window
        self.launch_profile(profile)
    def _run_startup_action(self):
        """Once per login: open the chosen app, or whichever app was used last. (In TV mode the Quick Menu shows by itself
        while nothing is open.)"""
        if not first_time_this_login(STARTUP_MARKER): return GLib.SOURCE_REMOVE   # TVWCS was restarted during this login
        st=self.store.settings["startup"]
        profile=self.store.get(st["profile_id"]) if st["mode"]=="app" else self.store.get(st["last_profile_id"]) if st["mode"]=="last" else None
        if profile: self.launch_profile(profile,bypass_pin=True)   # chosen by the owner in Settings, so no PIN at login
        return GLib.SOURCE_REMOVE

    def _look(self): return (dark_look(self.store.settings),wallpaper_of(self.store.settings))
    def apply_look(self):
        """Settings > Appearance > Theme, Light or dark and Background: dark or light for TVWCS's own widgets and for the
        applications that follow the desktop's colour scheme (appearance.py; the Retro theme is dark), and the colour
        (or the TV static) behind everything."""
        dark,wallpaper=self._look(); theme="dark" if dark else "light"
        gtk_settings=Gtk.Settings.get_default()
        if gtk_settings is not None: gtk_settings.set_property("gtk-application-prefer-dark-theme",dark)
        def work():
            for problem in (appearance.apply_theme(theme),appearance.apply_wallpaper(wallpaper) if self.wm.available else ""):
                if problem: print(f"TVWCS appearance: {problem}",file=sys.stderr)
        threading.Thread(target=work,daemon=True).start()
    def notify_message(self,message):
        """A problem to tell the user about, shown in the TVWCS window (opened for it when hidden)."""
        w=self.window
        if w is not None:
            if not w.is_visible(): self.show_mode("toggle")
            w.show_message(message); return
        d=Gtk.MessageDialog(application=self,transient_for=self.window,modal=True,message_type=Gtk.MessageType.ERROR,buttons=Gtk.ButtonsType.OK,text=message)
        d.connect("response",lambda w,*_:w.destroy()); d.present()

def send_signal(sig):
    try:
        pid=int(PID_FILE.read_text(encoding="ascii").strip()); os.kill(pid,sig); return 0
    except (OSError,ValueError) as exc:
        print(f"TVWCS is not running (or its PID file is stale): {exc}. Start `./tvwcs` first.",file=sys.stderr); return 1

def send_request(line):
    try:
        with open(REQUESTS_FILE,"a",encoding="utf-8") as f: f.write(line+"\n")
    except OSError as exc: print(f"Cannot queue the request in {REQUESTS_FILE}: {exc}",file=sys.stderr); return 1
    return send_signal(signal.SIGWINCH)

def main():
    args=sys.argv[1:]
    if args==["toggle"]: return send_signal(signal.SIGUSR1)
    if args==["guide"]: return send_signal(signal.SIGUSR2)
    if args in (["--version"],["version"]): from tvwcs import __version__; print(f"TVWCS {__version__}"); return 0
    if args==["stop"]: return send_signal(signal.SIGTERM)
    if args==["reload"]: return send_request("reload")
    if args==["last-app"]: return send_request("last-app")
    if args in (["lock"],["lock","--nofork"],["lock-at-start"]):   # TVWCS's lock screen (the launcher starts it without GTK, see lockscreen.main)
        from tvwcs.lockscreen import main as lockscreen_main
        return lockscreen_main(args)
    if len(args)==2 and args[0]=="idle" and args[1] in (*power.ACTIONS,"resume"): return idle_action(args[1])
    if len(args)==2 and args[0]=="launch" and args[1] and not any(c.isspace() for c in args[1]): return send_request(f"launch {args[1]}")
    if args[:1] in (["settings"],["control"]) and len(args)<=2:   # the Settings app, separate (optionally opened on one page); "control" is its old name
        from tvwcs.ui_control import main as settings_app
        return settings_app(args[1:])
    # the launcher itself, whatever the session (tvwcs.conf starts it so); "start" is its old name, which an older
    # TVWCS's restart after an update still runs
    if args in (["launcher"],["start"]): return TVWCSApp().run([])
    if args: from tvwcs import usage; return usage.wrong()
    return start_here()

def start_here():
    """Plain `tvwcs`: what fits where it runs (sway_include.where). In TVWCS's session, or a sway session that includes
    tvwcs.conf, the launcher (or its Quick Menu, when it runs already); in another sway session, Settings, which offers
    to add TVWCS to it; in any other graphical session, Settings with its sway pages turned off. At a text console the
    launcher script starts TVWCS's session before Python is reached."""
    place=sway_include.where()
    if place=="console":
        print("There is no graphical session here. Run tvwcs at the computer's own text console to start TVWCS's session.",file=sys.stderr); return 1
    if place=="other":
        from tvwcs.ui_control import main as settings_app
        return settings_app([])
    try: running=is_tvwcs_process(int(PID_FILE.read_text(encoding="ascii").strip()))
    except (OSError,ValueError): running=False
    if running: return send_signal(signal.SIGUSR1)
    if sway_include.active(): return TVWCSApp().run([])
    from tvwcs.ui_control import ADD_TO_SWAY, main as settings_app
    return settings_app([ADD_TO_SWAY])

if __name__=="__main__": raise SystemExit(main())
