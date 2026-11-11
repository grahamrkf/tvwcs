"""TVWCS Settings: Options, Remote and hotkeys, Sound, Displays, Power and sleep, Bluetooth, Apps, Software updates and
more, as vertical tabs on the left with the chosen page beside them. It is an ordinary application (it has its own
launcher, so it is in Applications under System), drawn with the TVWCS Metro theme at the interface size and accent
colour chosen in its Options (a change to them is drawn at once), and it works with a D-pad alone:

- ↑ / ↓ on the tabs changes page at once; → (or Enter) goes into the page, ← from a page's left edge comes back.
- In a page, ↑ / ↓ move between rows and ← / → along a row; Esc (or the remote's Back key) goes back to the tabs,
  and from the tabs closes Settings.
- Dialogs are drawn over the window, as in TVWCS. Text (a Wi-Fi password, an address) is typed on a keyboard, or on
  the on-screen keyboard with the D-pad."""
from __future__ import annotations
import codecs, os, re, subprocess, sys, threading, time
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from tvwcs import privilege, return_focus
from tvwcs.control_updates import is_prompt
from tvwcs.hotkeys import HotkeyCapture, describe, is_navigation
from tvwcs.model import ConfigStore, effective_scale, key_hints, scale_key, tv_mode
from tvwcs.theme import render_css
from tvwcs.window_manager import WindowManager
from tvwcs import cursor
from tvwcs.widgets import METRO_COLORS, NavGroup, PointerWatch, S, clear_box, glyph, held_modifiers, screen_height, scroll_into_view, scroll_to_show, set_scale, usable, use_retro

APP_ID="com.tvwcs.ControlPanel"
TITLE="Settings"
PASSWORD_TRIES=3
PAGE_FADE_MS=150
ADD_TO_SWAY="add-to-sway"   # the argument plain `tvwcs` passes in a sway session TVWCS is not part of (main.start_here)   # pages cross-fade, so it is clear what changed

CONTROL_CSS="""
button.big-button { min-height: 64px; font-size: 22px; }
.tab-column { background: @PANE@; }
button.tab-button { min-height: 48px; padding: 0 18px; font-size: 18px; font-weight: 300; background: transparent; }
window.pointer button.tab-button:hover { background: @RAISED@; }
button.tab-button.active { background: @RAISED@; box-shadow: inset 6px 0 0 @ACCENT@; }
button.tab-button:focus, button.tab-button:focus-visible { background: @ACCENT@; box-shadow: none; }
button.tab-button label { font-weight: 300; }
button.tab-button.icon-tab { padding: 0 20px; }
button.tab-button:focus label { font-weight: 700; }
button.info-row:focus .setting-value { color: #ffffff; }
.display-box { background: alpha(@ACCENT@, 0.6); border: 2px solid @PANE@; }
.display-box.primary { background: @ACCENT@; }
.display-number { font-size: 30px; font-weight: 700; color: #ffffff; }
.display-name { font-size: 12px; color: #ffffff; }
/* secondary text: the theme’s #8a8a8a at 12px is about 4:1 on a #2d2d2d row, too faint from a sofa */
.row-detail, .description { color: @MUTED@; font-size: 13px; }
.buttons-head { font-size: 15px; }   /* the name over a row of choice buttons (Interface size, Scale): like a row's name */
.muted { color: @MUTED@; font-size: 14px; }
.muted.error { color: @ERROR@; }   /* a warning note: .muted comes after the theme's .error and would win */
button.launch-row:disabled { opacity: 0.45; }   /* rows turned off outside sway (Page.draw_off): the theme's colours would hide GTK's own dimming */
.accent-swatch { min-width: 26px; min-height: 26px; border: 2px solid alpha(@FG@, 0.7); }
.accent-current { background: @ACCENT@; }
button:focus .row-detail { color: #e3eefa; }
.state-on { color: @ON@; font-weight: 700; }
button:focus .state-on { color: #ffffff; }
.volume-value { font-size: 20px; font-weight: 300; min-width: 64px; }
scale { padding: 0 6px; }
scale trough { background: @TROUGH@; border: none; border-radius: 0; min-height: 10px; }
scale highlight { background: @ACCENT@; border: none; border-radius: 0; min-height: 10px; margin: 0; }
scale.muted highlight { background: #6e6e6e; }
scale slider { background: @FG@; border: none; border-radius: 0; min-width: 14px; min-height: 22px; margin: -6px 0; box-shadow: none; }
textview.console, textview.console text { background: #0c0c0c; color: #d0d0d0; font-family: "DejaVu Sans Mono", "Noto Mono", monospace; font-size: 13px; }
.console-frame { border: 2px solid @LINE@; }
button.key { min-height: 48px; min-width: 40px; padding: 0 6px; font-size: 18px; }
button.key.wide { font-size: 15px; }
entry.text-field { font-size: 22px; min-height: 52px; }
button.app-tool { min-height: 48px; padding: 0 12px; }
entry.search-bar { min-height: 48px; font-size: 18px; }
button.app-tool.current { box-shadow: inset 0 -4px 0 @ACCENT@; }
button.app-tile { padding: 16px 10px 12px 10px; min-height: 170px; }
.app-name { font-size: 16px; font-weight: 600; }
button:focus .app-name { font-weight: 700; }
.app-summary { font-size: 17px; }
.wallpaper-swatch { min-width: 64px; min-height: 48px; padding: 0; border: 2px solid @LINE@; }
button.wallpaper-swatch:focus, button.wallpaper-swatch:focus-visible { outline: 4px solid @ACCENT@; outline-offset: 2px; }
entry.time-field { font-size: 36px; font-weight: 300; min-height: 64px; padding: 0 6px; }
.time-colon { font-size: 40px; font-weight: 300; margin-bottom: 26px; }
button.ampm { padding: 6px 14px; margin-bottom: 26px; }
.ampm-on { font-size: 22px; font-weight: 700; border-bottom: 3px solid currentColor; }
.ampm-off { font-size: 18px; opacity: 0.45; }
"""

def colour_swatch(colour):
    """A square of `colour` (a Metro colour, a background colour, a Retro background's key or the current accent):
    theme.render_css paints .tile-N in METRO_COLORS[N], .wall-N in WALLPAPERS[N] and .retro-wall-<key>."""
    c=(colour or "").lower(); box=Gtk.Box(); box.add_css_class("accent-swatch"); box.set_valign(Gtk.Align.CENTER)
    box.add_css_class(swatch_class(c) or "accent-current"); return box

def swatch_class(colour):
    from tvwcs.model import RETRO_WALLPAPERS, WALLPAPERS
    if colour in METRO_COLORS: return f"tile-{METRO_COLORS.index(colour)}"
    if colour in WALLPAPERS: return f"wall-{WALLPAPERS.index(colour)}"
    if colour in RETRO_WALLPAPERS: return f"retro-wall-{colour}"
    return None

def in_background(work, done, failed=None):
    """work() on a worker thread, so a slow tool never freezes the remote; then done(result) (or failed(error))
    back on the GTK main loop."""
    def run():
        try: result=work()
        except Exception as exc:   # a bug in a reader must not leave the page saying "Working…" for ever
            if failed: GLib.idle_add(lambda e=exc:(failed(e),GLib.SOURCE_REMOVE)[1])
            else: print(f"Settings: {exc!r}",file=sys.stderr)
            return
        GLib.idle_add(lambda:(done(result),GLib.SOURCE_REMOVE)[1])
    threading.Thread(target=run,daemon=True).start()

_COLOUR=re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

class StreamedRun:
    """Run a command and pass each line it prints (stdout and stderr together) to on_line, then done(exit code, the
    last lines) on the GTK main loop. `password` is written to its stdin (sudo -S) and the pipe closed.
    With on_prompt, its stdin stays open: a question it waits on without ending the line (pacman's "[Y/n]") goes to
    on_prompt(run, question, the lines before it) on the GTK main loop, and run.send(answer) types the answer."""
    def __init__(self, argv, on_line, done, password=None, env=None, on_prompt=None):
        self.argv=argv; self.on_line=on_line; self.done=done; self.tail=[]; self.on_prompt=on_prompt
        try:
            self.proc=subprocess.Popen(argv,stdin=subprocess.PIPE if password is not None or on_prompt else subprocess.DEVNULL,stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT,env=env or privilege.c_locale_env(),start_new_session=True)
        except OSError as exc:
            GLib.idle_add(lambda why=f"Could not run {argv[0]}: {exc}":(done(-1,why),GLib.SOURCE_REMOVE)[1]); self.proc=None; return
        if password is not None:
            try:
                self.proc.stdin.write((password+"\n").encode())
                if on_prompt: self.proc.stdin.flush()
                else: self.proc.stdin.close()
            except OSError: pass
        threading.Thread(target=self._read_prompts if on_prompt else self._read,daemon=True).start()
    def _line(self, line):
        for part in line.split("\r"):   # progress bars redraw a line with \r: show each state
            if part.strip():
                self.tail=(self.tail+[part])[-12:]; GLib.idle_add(lambda p=part:(self.on_line(p),GLib.SOURCE_REMOVE)[1])
                if "sorry, try again" in part.lower(): self._close_stdin()   # a wrong sudo password: sudo would wait for another
    def _read(self):
        for raw in iter(self.proc.stdout.readline,b""): self._line(raw.decode(errors="replace").rstrip("\n"))
        self._finish()
    def _read_prompts(self):
        """Read as it comes, not by lines: a question ends without a newline."""
        decode=codecs.getincrementaldecoder("utf-8")(errors="replace"); buf=""; fd=self.proc.stdout.fileno()
        while True:
            try: chunk=os.read(fd,4096)
            except OSError: break
            if not chunk: break
            buf+=_COLOUR.sub("",decode.decode(chunk))   # a question in colour (yay's) still ends in "[Y/n] "
            *lines,buf=buf.split("\n")
            for line in lines: self._line(line)
            if is_prompt(buf):
                question=buf; buf=""; before=list(self.tail); self._line(question)
                GLib.idle_add(lambda q=question,b=before:(self.on_prompt(self,q,b),GLib.SOURCE_REMOVE)[1])
        if buf: self._line(buf)
        self._close_stdin(); self._finish()
    def _finish(self):
        code=self.proc.wait()
        GLib.idle_add(lambda:(self.done(code,"\n".join(self.tail)),GLib.SOURCE_REMOVE)[1])
    def send(self, answer):
        """Type an answer to the question it waits on."""
        try: self.proc.stdin.write((answer+"\n").encode()); self.proc.stdin.flush()
        except (OSError,ValueError,AttributeError): pass
    def _close_stdin(self):
        try:
            if self.proc.stdin is not None and not self.proc.stdin.closed: self.proc.stdin.close()
        except OSError: pass
    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try: os.killpg(self.proc.pid,15)
            except OSError: pass

def _doas_refused(text):
    t=(text or "").lower(); return "authorization required" in t or "not permitted" in t or "operation not permitted" in t

class ControlWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app,title=TITLE)
        self.app=app; self.pages=[]; self.page=None; self.tab_buttons={}
        self._modal_groups=[]; self._modal_back=None; self._return_focus=None; self._text=None; self._last_page_focus={}; self._countdown=None
        self._capture=None; self._capture_cb=None; self._capture_cancel=None
        self.add_css_class("tvwcs-window"); self.set_icon_name("preferences-system")
        self.set_default_size(S(1180),S(760))
        self._hide_ms=(0.0,None); self.pointer=PointerWatch(self,self.pointer_hide_ms)   # hover colours only while the mouse is in use
        key=Gtk.EventControllerKey(); key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed",self._key_pressed); key.connect("key-released",self._key_released); self.add_controller(key)
        self.connect("notify::focus-widget",self._focus_changed)
        self.connect("close-request",self._closing)
        self._provider=Gtk.CssProvider(); display=Gdk.Display.get_default()
        if display: Gtk.StyleContext.add_provider_for_display(display,self._provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._load_css(); self._build()

    def _closing(self, *_):
        """Closed from here (Back from the tabs, sway's kill key): back to the app in use before Settings opened. Closed
        from elsewhere (the Quick Menu's ⋯ menu), the focus stays where the user is."""
        if self.is_active() and self.app.back_to: return_focus.go_back(self.app.wm,self.app.back_to)
        return False

    def _load_css(self):
        retro=self.app.style=="retro"; use_retro(retro,self.app.retro_font)
        self._provider.load_from_data(render_css(self.app.accent,self.app.scale,CONTROL_CSS,theme=self.app.theme,style=self.app.style,
                                                 phosphor=self.app.phosphor,retro_font=self.app.retro_font).encode("utf-8"))
        gtk_settings=Gtk.Settings.get_default()
        if gtk_settings is not None: gtk_settings.set_property("gtk-application-prefer-dark-theme",retro or self.app.theme!="light")

    def settings_changed(self, settings):
        """Options saved a change: draw this window with its accent, size, key names and motion too."""
        app=self.app; scale=effective_scale(scale_key(settings),screen_height())
        restyled=settings.get("style","modern")!=app.style or settings.get("retro_font","pixel")!=app.retro_font   # the icons change too: built again, like a new size
        resized=scale!=app.scale or restyled
        app.accent=settings.get("accent",app.accent)
        app.theme=settings.get("theme","dark"); app.keyboard=settings.get("keyboard","hidden")
        app.style=settings.get("style","modern"); app.phosphor=settings.get("phosphor","green"); app.retro_font=settings.get("retro_font","pixel")
        if resized and self._running():   # rebuilding would lose the run's output: the new size waits for the next time
            self._load_css(); self._apply_settings()
            self.notice("Interface size","TVWCS uses the new size now. Settings uses it the next time it opens, once what is running here has finished."); return
        app.scale=scale; self._load_css(); self._apply_settings()
        if resized: GLib.idle_add(lambda:(self._rebuild(),GLib.SOURCE_REMOVE)[1])   # after the dialog that chose it has gone
    def _apply_settings(self):
        self.footer.set_text(key_hints(tv_mode()))
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    def _running(self):
        return any(getattr(p,"running",None) for p in self.pages) or any(
            getattr(p,"process",None) is not None and p.process.proc is not None and p.process.proc.poll() is None for p in self.pages)
    def _rebuild(self):
        """Every widget again at the new interface size (S() is read as they are made), on the same page and row."""
        page=self.page; focused=self.get_focus()
        ident=next((i for i,w in page._ids.items() if w is focused),None) if page is not None and self._area(focused)=="page" else None
        for p in self.pages:
            p.hidden()
        self.pages=[]; self.page=None; self.tab_buttons={}; self._last_page_focus={}; self._modal_groups=[]; self._text=None
        set_scale(self.app.scale); self.set_default_size(S(1180),S(760)); self._build()
        new=self.page_by_key(page.key if page is not None else "") or self.pages[0]
        if ident: new.focus_ident=ident   # taken by its first redraw
        self.select_tab(new.key)

    # ================================================================== construction
    def _build(self):
        from tvwcs.ui_control_pages import PAGES   # the pages import this module's helpers
        overlay=Gtk.Overlay(); overlay.add_css_class("tvwcs-root"); self.set_child(overlay)
        panes=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=0); overlay.set_child(panes)
        # ---- the tabs, down the left
        column=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0); column.add_css_class("pane"); column.add_css_class("tab-column")
        column.set_size_request(S(330),-1); column.set_hexpand(False); panes.append(column); self.tab_column=column
        header=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10)); header.set_margin_top(S(14)); header.set_margin_start(S(20)); header.set_margin_end(S(20)); header.set_margin_bottom(S(14))
        brand=Gtk.Label(label="Settings"); brand.add_css_class("brand"); brand.set_xalign(0); brand.set_hexpand(True); header.append(brand)
        self.tab_header=header; self.brand=brand; self.tab_labels=[]; self._narrow=None
        column.append(header)   # no close button: Esc (or Back) from the tabs, or the window manager, closes Settings
        tabs=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2))
        tab_scroll=Gtk.ScrolledWindow(); tab_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC); tab_scroll.set_vexpand(True)
        tab_scroll.set_child(tabs); column.append(tab_scroll); self.tab_scroll=tab_scroll   # in TV Mode on a 1080p screen the tabs can be taller than it; they scroll
        # ---- the page, beside them
        self.stack=Gtk.Stack(); self.stack.set_hhomogeneous(False); self.stack.set_hexpand(True); self.stack.set_vexpand(True); self.stack.set_transition_duration(PAGE_FADE_MS)
        self.stack.add_css_class("pane"); self.stack.set_margin_start(S(12)); panes.append(self.stack)
        for cls in PAGES:
            page=cls(self); self.pages.append(page)
            b=Gtk.Button(); b.add_css_class("tab-button"); line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(16))
            icon=glyph(page.icon,page.fallback,24); icon.set_size_request(S(28),-1); line.append(icon)
            label=Gtk.Label(label=page.title); label.set_xalign(0); label.set_hexpand(True); line.append(label); b.set_child(line); self.tab_labels.append(label)
            b.connect("clicked",lambda _b,p=page:self.enter_page(p)); tabs.append(b); self.tab_buttons[page.key]=b
            self.stack.add_named(page.widget(),page.key)
        footer=Gtk.Label(); footer.add_css_class("muted"); footer.set_xalign(0); footer.set_wrap(True); self.footer=footer
        footer.set_margin_start(S(20)); footer.set_margin_end(S(20)); footer.set_margin_top(S(8)); footer.set_margin_bottom(S(12)); column.append(footer)
        # ---- dialogs, drawn over everything
        self.modal_layer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.modal_layer.add_css_class("modal-scrim"); self.modal_layer.set_visible(False)
        self.modal_card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(6)); self.modal_card.add_css_class("modal-card")
        self.modal_card.set_halign(Gtk.Align.CENTER); self.modal_card.set_valign(Gtk.Align.CENTER); self.modal_card.set_hexpand(True); self.modal_card.set_vexpand(True)
        self.modal_card.set_size_request(S(520),-1)
        self.modal_layer.append(self.modal_card); overlay.add_overlay(self.modal_layer)
        self._apply_settings()
        surface=self.get_surface()
        if surface is not None: self._narrow=None; self._fit_tabs(surface.get_width(),surface.get_height())

    # ---- a window taller than it is wide (a tile, a monitor turned on its side): the tabs shrink to their icons
    # The window manager's size for the window is the surface's: a tile narrower than the wide layout's minimum width
    # would otherwise only clip it.
    def pointer_hide_ms(self):
        """The pointer's hiding time (cursor.py), read from the options at most every few seconds: it is asked at every
        mouse movement."""
        when,ms=self._hide_ms
        if time.monotonic()-when>5: ms=cursor.hide_ms(ConfigStore().settings); self._hide_ms=(time.monotonic(),ms)
        return ms
    def do_realize(self):
        Gtk.ApplicationWindow.do_realize(self)
        self.get_surface().connect("layout",lambda _s,w,h:GLib.idle_add(lambda:(self._fit_tabs(w,h),GLib.SOURCE_REMOVE)[1]))
    def _fit_tabs(self, width, height):
        narrow=width>0 and height>width
        if narrow is self._narrow or not hasattr(self,"tab_column"): return
        self._narrow=narrow
        self.tab_column.set_size_request(S(76) if narrow else S(330),-1)
        self.tab_header.set_visible(not narrow); self.footer.set_visible(not narrow)
        for label,(key,b) in zip(self.tab_labels,self.tab_buttons.items()):
            label.set_visible(not narrow); b.set_tooltip_text(label.get_text() if narrow else None)
            (b.add_css_class if narrow else b.remove_css_class)("icon-tab")

    def page_by_key(self, key):
        key={"options":"appearance","features":"user"}.get(key,key)   # the tabs before 4.0
        return next((p for p in self.pages if p.key==key),None)

    def show_page(self, page):
        """Show a page (its tab is marked) without moving the selection off the tabs."""
        if page is self.page: return
        if self.page is not None:
            self.tab_buttons[self.page.key].remove_css_class("active"); self.page.hidden()
        self.page=page; self.tab_buttons[page.key].add_css_class("active")
        self.stack.set_visible_child_name(page.key); page.shown()

    def select_tab(self, key):
        page=self.page_by_key(key) or self.pages[0]
        self.show_page(page); self.tab_buttons[page.key].grab_focus()

    def enter_page(self, page=None):
        """Move the selection into the page: back to where it was in it, else onto its first row."""
        page=page or self.page; self.show_page(page)
        last=self._last_page_focus.get(page.key)
        if last is not None and usable(last) and self._in(last,page.root) and last.grab_focus(): return True
        return self._focus_first(page.groups) or self._focus_first(page.nav_groups()) or True   # the first row, not ⟳

    # ================================================================== navigation
    def _in(self, widget, ancestor): return widget is not None and ancestor is not None and (widget is ancestor or widget.is_ancestor(ancestor))
    def _focus_changed(self, *_):
        w=self.get_focus()
        if w is None or self._modal_groups: return
        for page in self.pages:
            if self._in(w,page.root): self._last_page_focus[page.key]=w; return
        for key,b in self.tab_buttons.items():   # moving along the tabs shows each page straight away
            if w is b:
                self.show_page(self.page_by_key(key)); GLib.idle_add(lambda:(scroll_to_show(self.tab_scroll,b),GLib.SOURCE_REMOVE)[1]); return
    def _area(self, focused):
        if self._modal_groups: return "modal"
        if self.page is not None and self._in(focused,self.page.root): return "page"
        return "tabs"
    def _groups(self, area):
        if area=="modal": return self._modal_groups
        if area=="page": return self.page.nav_groups()
        return [NavGroup([b]) for b in self.tab_buttons.values()]
    def _group_index(self, groups, focused):
        for i,g in enumerate(groups):
            if any(w is focused for w in g): return i
        for i,g in enumerate(groups):
            if any(self._in(focused,w) for w in g): return i
        return -1
    @staticmethod
    def _landing(group, column=None):
        if column is not None and getattr(group,"column",False):
            active=[w for w in group if usable(w)]
            if active: return active[min(column,len(active)-1)]
        entry=getattr(group,"entry",None)
        if entry is not None and usable(entry): return entry
        return next((w for w in group if usable(w)),None)
    def _focus_first(self, groups):
        for g in groups:
            w=self._landing(g)
            if w is not None and w.grab_focus(): return True
        return False
    def _move_group(self, step):
        focused=self.get_focus(); area=self._area(focused)
        groups=[g for g in self._groups(area) if any(usable(w) for w in g)]
        if not groups: return False
        current=self._group_index(groups,focused)
        column=next((k for k,w in enumerate(groups[current]) if w is focused or self._in(focused,w)),None) if current>=0 else None
        if area=="tabs" or area=="modal":   # wrap around, as the TVWCS menus do
            start=(current+step)%len(groups) if current>=0 else 0
            order=[(start+step*k)%len(groups) for k in range(len(groups))]
        else:                               # a page stops at its first and last row
            start=current+step if current>=0 else 0
            order=range(start,len(groups)) if step>0 else range(start,-1,-1)
        for i in order:
            w=self._landing(groups[i],column)
            if w is not None and w.grab_focus(): return True
        return True
    def _move_within(self, step):
        focused=self.get_focus(); area=self._area(focused)
        if area=="tabs":
            if step>0 and self.page is not None: return self.enter_page()
            return True
        groups=self._groups(area); gi=self._group_index(groups,focused)
        if gi<0: return self.enter_page() if area=="page" else False
        active=[w for w in groups[gi] if usable(w)]
        i=next((k for k,w in enumerate(active) if w is focused or self._in(focused,w)),0)
        nxt=i+step
        if 0<=nxt<len(active): return active[nxt].grab_focus()
        if area=="modal": return active[nxt%len(active)].grab_focus()
        if step<0: return self.tab_buttons[self.page.key].grab_focus()   # ← from the page's left edge: back to its tab
        return True

    def _key_pressed(self, _controller, keyval, _keycode, state):
        if self._capture is not None and self._capture_key(keyval,state): return True
        focused=self.get_focus()
        if keyval in (Gdk.KEY_Escape,Gdk.KEY_Back): self.back(); return True
        editable=isinstance(focused,Gtk.Editable) or isinstance(focused,Gtk.Text)
        if self._text is not None and not editable and self._text_key(keyval): return True
        if keyval in (Gdk.KEY_Up,Gdk.KEY_Down):
            return self._move_group(1 if keyval==Gdk.KEY_Down else -1)
        if keyval in (Gdk.KEY_Left,Gdk.KEY_Right) and not editable:
            return self._move_within(1 if keyval==Gdk.KEY_Right else -1)
        if keyval in (Gdk.KEY_Left,Gdk.KEY_Right) and self._area(focused)=="page" and isinstance(focused,Gtk.Editable):
            # in a text field on a page (Apps > Search), ← at its start and → at its end move along the row
            at=focused.get_position(); selected=focused.get_selection_bounds()   # PyGObject: () when nothing is selected
            if not selected and ((keyval==Gdk.KEY_Left and at==0) or (keyval==Gdk.KEY_Right and at>=len(focused.get_text()))):
                return self._move_within(1 if keyval==Gdk.KEY_Right else -1)
        return False

    def _key_released(self, _controller, keyval, _keycode, _state):
        if self._capture is not None:
            spec=self._capture.release(Gdk.keyval_name(keyval) or "")
            if spec: self._end_capture(spec)

    def back(self):
        """Esc / Back: close a dialog, else leave the page for its tab, else close Settings."""
        if self._modal_groups: (self._modal_back or self.close_modal)(); return
        if self._area(self.get_focus())=="page": self.tab_buttons[self.page.key].grab_focus(); return
        self.close()

    # ================================================================== dialogs (drawn over the window)
    def _begin_modal(self, title):
        if not self._modal_groups: self._return_focus=self.get_focus()
        self._text=None; clear_box(self.modal_card); self.modal_layer.set_visible(True)
        t=Gtk.Label(label=title); t.add_css_class("pane-title"); t.set_xalign(0); t.set_wrap(True); t.set_margin_bottom(S(8)); self.modal_card.append(t)
    def _finish_modal(self, groups, back, focus=None):
        self._modal_groups=[g if isinstance(g,NavGroup) else NavGroup(g) for g in groups]; self._modal_back=back
        target=focus or self._landing(self._modal_groups[0])
        if target is not None:
            target.grab_focus(); GLib.timeout_add(60,lambda:(self._modal_groups and target.grab_focus(),GLib.SOURCE_REMOVE)[1])
    @property
    def modal_open(self): return bool(self._modal_groups)
    def close_modal(self):
        if self._text is not None: self._text["entry"].set_text("")   # a typed password is never left in the widget
        self._modal_groups=[]; self._modal_back=None; self._text=None; self.modal_layer.set_visible(False)
        back=self._return_focus; self._return_focus=None
        if back is not None and usable(back) and back.grab_focus(): return
        if self.page is not None: self.tab_buttons[self.page.key].grab_focus()
    def _message(self, text, css="muted"):
        l=Gtk.Label(label=text); l.set_xalign(0); l.set_wrap(True); l.set_max_width_chars(60); l.add_css_class(css); l.set_margin_bottom(S(10)); self.modal_card.append(l); return l
    def _buttons(self, *specs):
        """A row of equal buttons: specs are (label, handler, css or None)."""
        row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(6)); row.set_homogeneous(True); row.set_margin_top(S(6)); made=[]
        for label,handler,css in specs:
            b=Gtk.Button(label=label)
            if css: b.add_css_class(css)
            b.connect("clicked",lambda _b,h=handler:h()); row.append(b); made.append(b)
        self.modal_card.append(row); return made

    def notice(self, title, message, on_close=None):
        """Tell the user something (an error, a result) until they press OK."""
        self._begin_modal(title); self._message(message)
        done=lambda:(self.close_modal(),on_close and on_close())
        ok,=self._buttons(("OK",done,"active")); self._finish_modal([[ok]],done)

    def ask_choice(self, title, message, answers, back):
        """A question with a button for each answer: answers are (label, handler), the default first and selected.
        Back (Esc) runs back()."""
        self._begin_modal(title)
        if message: self._message(message)
        made=self._buttons(*[(label,lambda h=h:(self.close_modal(),h()),"active" if i==0 else None) for i,(label,h) in enumerate(answers)])
        self._finish_modal([made],lambda:(self.close_modal(),back()),made[0])

    def confirm(self, title, message, label, on_confirm, danger=True, back=None):
        """Ask before doing something that is hard to undo. Cancel is selected, so a stray Enter is harmless."""
        self._begin_modal(title); self._message(message)
        cancel_action=back or self.close_modal
        cancel,go=self._buttons(("Cancel",cancel_action,None),(label,lambda:(self.close_modal(),on_confirm()),"danger" if danger else "active"))
        self._finish_modal([[cancel,go]],cancel_action,cancel)

    def choose_option(self, title, options, current, callback, back=None, swatches=False):
        """A list of choices with the current one ticked. A long list scrolls, following the selection. With swatches,
        each key is a colour, shown beside its name."""
        self._begin_modal(title); groups=[]; focus=None; holder=self.modal_card
        if len(options)>8:
            scroll=Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
            scroll.set_max_content_height(S(440)); scroll.set_propagate_natural_height(True)
            holder=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(6)); scroll.set_child(holder); self.modal_card.append(scroll)
        for key,label in options:
            chosen=key==current
            b=Gtk.Button(); b.add_css_class("dialog-button"); row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(14))
            mark=glyph("object-select-symbolic","✓",24) if chosen else Gtk.Label(); mark.set_size_request(S(28),-1); row.append(mark)
            if swatches: row.append(colour_swatch(key))
            l=Gtk.Label(label=label); l.set_xalign(0); l.set_hexpand(True); l.set_wrap(True); row.append(l); b.set_child(row)
            b.connect("clicked",lambda _b,k=key:(self.close_modal(),callback(k))); holder.append(b); groups.append([b])
            if chosen: focus=b
        cancel_action=back or self.close_modal
        cancel,=self._buttons(("Cancel",cancel_action,None)); groups.append([cancel])
        self._finish_modal(groups,cancel_action,focus)
        if focus is not None and holder is not self.modal_card: GLib.timeout_add(80,lambda:(scroll_into_view(scroll,focus),GLib.SOURCE_REMOVE)[1])

    def choose_swatch(self, title, message, colours, current, callback, per_row=6, names=None):
        """Colours as a grid of squares without names (Appearance > Background colour); the current one has a ✓.
        The arrows move around the grid, OK chooses. A colour may be a Retro background's key (RETRO_WALLPAPERS),
        named in `names`."""
        from tvwcs.model import RETRO_WALLPAPERS
        self._begin_modal(title)
        if message: self._message(message)
        groups=[]; focus=None
        for start in range(0,len(colours),per_row):
            line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(6)); line.set_margin_bottom(S(6)); made=[]
            for colour in colours[start:start+per_row]:
                b=Gtk.Button(); b.add_css_class("wallpaper-swatch")
                if swatch_class(colour): b.add_css_class(swatch_class(colour))
                if colour==current:
                    mark=Gtk.Label(label="✓"); mark.add_css_class("pane-title"); b.set_child(mark); focus=b
                    hexa=RETRO_WALLPAPERS.get(colour,colour); hexa=hexa if hexa.startswith("#") else "#000000"   # TV static: dark enough
                    dark=sum(int(hexa[i:i+2],16) for i in (1,3,5))<380
                    mark.set_markup(f"<span foreground='{'#ffffff' if dark else '#000000'}'>✓</span>")
                b.set_tooltip_text((names or {}).get(colour,colour))
                b.connect("clicked",lambda _b,c=colour:(self.close_modal(),callback(c))); line.append(b); made.append(b)
            self.modal_card.append(line); g=NavGroup(made); g.column=True; groups.append(g)
        cancel,=self._buttons(("Cancel",self.close_modal,None)); groups.append([cancel])
        self._finish_modal(groups,self.close_modal,focus)

    # ---------------------------------------------------------- choosing a hotkey (Options)
    def capture_hotkey(self, label, callback, can_clear=False, cancelled=None):
        """Wait for a key or combination and pass its spec to callback; with can_clear, a Clear button passes "".
        cancelled() runs when it is cancelled."""
        self._begin_modal("New hotkey")
        self._message(f"Press the key or key combination for “{label}”.\nTap a modifier on its own (such as Super) to use it by itself. "
                      "The arrow keys and OK move to and press Cancel or Clear; Back cancels.")
        specs=[("Cancel",lambda:self._end_capture(None),None)]+([("Clear",lambda:self._end_capture(""),None)] if can_clear else [])
        buttons=self._buttons(*specs)
        self._capture=HotkeyCapture(); self._capture_cb=callback; self._capture_cancel=cancelled
        self._finish_modal([buttons],lambda:self._end_capture(None),buttons[0])
    def _capture_key(self, keyval, state):
        name=Gdk.keyval_name(keyval) or ""; held=held_modifiers(state)
        if keyval in (Gdk.KEY_Escape,Gdk.KEY_Back) and not held: self._end_capture(None); return True
        if is_navigation(name,held): return False   # moves between Cancel and Clear and presses them
        spec=self._capture.press(name,held)
        if spec: self._end_capture(spec)
        return True
    def _end_capture(self, spec):
        callback=self._capture_cb; cancelled=self._capture_cancel; self._capture=None; self._capture_cb=None; self._capture_cancel=None
        self.close_modal()
        if spec is not None and callback: callback(spec)   # "" is Clear
        elif spec is None and cancelled: cancelled()
    def assign_hotkey(self, store, owner, label, on_set, back=None):
        """Choose a hotkey for `owner` (("slot", device, action) or ("profile", id)) and pass it to on_set ("" clears it).
        A key something else already has is only taken from it after a warning."""
        def got(spec):
            other=store.hotkey_owner(spec,owner) if spec else None
            if other is None: on_set(spec); return
            taken=store.owner_label(other)
            self.confirm("Hotkey already in use",f"{describe(spec)} is already the hotkey for “{taken}”. Use it for “{label}” instead? "
                         f"“{taken}” will no longer have a hotkey.","Use it here",lambda:on_set(spec),back=back)
        self.capture_hotkey(label,got,can_clear=True,cancelled=back)

    def countdown(self, title, message, seconds, keep_label, on_keep, undo_label, on_undo):
        """Ask whether to keep a change that may have left the screen unreadable. message(seconds) is the text; with
        no answer by the end of the countdown (or on Esc), on_undo runs. Going back is selected, so a blind Enter on a
        screen that shows nothing undoes the change; whoever can see the dialog moves right to Keep."""
        self._begin_modal(title); text=self._message(""); left=[seconds]; token=object(); self._countdown=token
        def finish(handler):
            if self._countdown is not token: return
            self._countdown=None; self.close_modal(); handler()
        def tick():
            if self._countdown is not token: return GLib.SOURCE_REMOVE
            left[0]-=1
            if left[0]<=0: finish(on_undo); return GLib.SOURCE_REMOVE
            text.set_text(message(left[0])); return GLib.SOURCE_CONTINUE
        text.set_text(message(seconds))
        undo,keep=self._buttons((undo_label,lambda:finish(on_undo),None),(keep_label,lambda:finish(on_keep),"active"))
        GLib.timeout_add_seconds(1,tick); self._finish_modal([[undo,keep]],lambda:finish(on_undo),undo)

    def form(self, title, rows, save_label, on_save, message="", error="", back=None):
        """A small form: each row (label, value, handler) is one button showing its current value, Enter changes it
        (usually through another dialog that comes back here); then Cancel or `save_label`."""
        self._begin_modal(title); groups=[]
        if message: self._message(message)
        for label,value,handler in rows:
            b=Gtk.Button(); b.add_css_class("launch-row"); line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12))
            l=Gtk.Label(label=label); l.set_xalign(0); l.set_hexpand(True); line.append(l)
            v=Gtk.Label(label=value or "—"); v.add_css_class("setting-value"); v.set_xalign(1); v.set_ellipsize(3); line.append(v)
            b.set_child(line); b.connect("clicked",lambda _b,h=handler:h()); self.modal_card.append(b); groups.append([b])
        if error: self._message(error,"error")
        cancel_action=back or self.close_modal
        cancel,save=self._buttons(("Cancel",cancel_action,None),(save_label,on_save,"active")); groups.append([cancel,save])
        self._finish_modal(groups,cancel_action)

    # ---------------------------------------------------------- typing: a keyboard, or the on-screen one
    KEYS={"lower":("1234567890","qwertyuiop","asdfghjkl'","zxcvbnm,.-"),
          "upper":("1234567890","QWERTYUIOP","ASDFGHJKL\"","ZXCVBNM;:_"),
          "symbols":("!@#$%^&*()","`~-_=+[]{}","\\|;:'\",.<>","/?€£¥§°·×÷")}
    def ask_text(self, title, message, callback, initial="", secret=False, ok_label="OK", back=None, error="", digits=None, keyboard=None):
        """Ask for a line of text: typed on a keyboard, or picked letter by letter on the on-screen keyboard with
        the D-pad. callback(text) runs on OK or Enter; Cancel (or Esc) runs back() or just closes. The on-screen
        keyboard is hidden, full or a number pad, as it was last left (settings "keyboard", shared with TVWCS), and
        buttons change between them, keeping what is typed. digits=True offers only the number pad."""
        only_digits=bool(digits)
        kind="digits" if only_digits else (keyboard or self.app.keyboard)
        if kind not in ("hidden","full","digits"): kind="hidden"
        self._begin_modal(title)
        if message: self._message(message)
        if error: self._message(error,"error")
        entry=Gtk.PasswordEntry() if secret else Gtk.Entry()
        if secret: entry.set_show_peek_icon(True)
        entry.add_css_class("text-field"); entry.set_text(initial); entry.set_margin_bottom(S(8)); self.modal_card.append(entry)
        cancel_action=back or self.close_modal
        def submit(*_):
            text=entry.get_text(); self.close_modal(); callback(text)
        def switch(to):
            typed=entry.get_text(); self._remember_keyboard(to)
            self.ask_text(title,message,callback,typed,secret,ok_label,back,error,digits,keyboard=to)
        entry.connect("activate",submit)
        self._text={"entry":entry,"layer":"lower","keys":[],"digits":kind=="digits"}
        groups=[NavGroup([entry])]
        if kind=="digits":
            for row in (("1","2","3"),("4","5","6"),("7","8","9"),("⌫","0",None)):
                line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(3)); line.set_homogeneous(True); made=[]
                for d in row:
                    if d is None: continue
                    b=Gtk.Button(label=d); b.add_css_class("key")
                    b.connect("clicked",lambda _b,d=d:self._erase() if d=="⌫" else self._type(d)); line.append(b); made.append(b)
                self.modal_card.append(line); g=NavGroup(made); g.column=True; groups.append(g)
        elif kind=="full":
            for r in range(4):
                line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(3)); line.set_homogeneous(True); row=[]
                for c in range(10):
                    b=Gtk.Button(); b.add_css_class("key"); b.connect("clicked",lambda _b,rc=(r,c):self._type(self.KEYS[self._text["layer"]][rc[0]][rc[1]]))
                    line.append(b); row.append(b); self._text["keys"].append((r,c,b))
                self.modal_card.append(line); g=NavGroup(row); g.column=True; groups.append(g)
        controls=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(3)); controls.set_homogeneous(True); controls.set_margin_top(S(3)); made=[]
        specs=[("⇧ Shift",lambda:self._layer("upper" if self._text["layer"]!="upper" else "lower")),
               ("&123",lambda:self._layer("symbols" if self._text["layer"]!="symbols" else "lower")),
               ("Space",lambda:self._type(" ")),("⌫",self._erase)] if kind=="full" else []
        if kind=="hidden": specs.append(("⌨  Show keyboard",lambda:switch("full")))
        elif not only_digits:
            specs.append(("ABC  Full keyboard" if kind=="digits" else "123  Number pad",lambda:switch("full" if kind=="digits" else "digits")))
            specs.append(("Hide keyboard",lambda:switch("hidden")))
        for label,handler in specs:
            b=Gtk.Button(label=label); b.add_css_class("key"); b.add_css_class("wide"); b.connect("clicked",lambda _b,h=handler:h()); controls.append(b); made.append(b)
        if made: self.modal_card.append(controls); g=NavGroup(made); g.column=True; groups.append(g)
        cancel,ok=self._buttons(("Cancel",cancel_action,None),(ok_label,submit,"active")); groups.append(NavGroup([cancel,ok]))
        if kind=="full": self._label_keys()
        self._finish_modal(groups,cancel_action,entry)
        # the keyboard rows keep their column when moving up and down; the last row of keys has 4, so it maps 10 -> 4
    def _remember_keyboard(self, kind):
        """The on-screen keyboard was changed: text dialogs open with it from now on, here and in TVWCS."""
        if self.app.keyboard==kind: return
        self.app.keyboard=kind
        try:
            store=ConfigStore(); store.settings["keyboard"]=kind; store.save()
        except OSError: return
        from tvwcs.ui_control_pages import tell_tvwcs
        tell_tvwcs("reload")
    def _label_keys(self):
        layer=self.KEYS[self._text["layer"]]
        for r,c,b in self._text["keys"]: b.set_label(layer[r][c])
    def _layer(self, name): self._text["layer"]=name; self._label_keys()
    def _type(self, text):
        e=self._text["entry"]; pos=len(e.get_text()); e.set_text(e.get_text()+text); e.set_position(pos+len(text))
        if self._text["layer"]=="upper" and not self._text["digits"]: self._layer("lower")   # Shift is for one letter
    def _erase(self):
        e=self._text["entry"]; e.set_text(e.get_text()[:-1])
    def _text_key(self, keyval):
        """With an on-screen key selected, a real keyboard still types into the field."""
        if keyval==Gdk.KEY_BackSpace: self._erase(); return True
        if keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter): return False   # presses the selected key
        ch=Gdk.keyval_to_unicode(keyval)
        if ch>=32 and chr(ch).isprintable() and (not self._text["digits"] or chr(ch).isdigit()): e=self._text["entry"]; e.set_text(e.get_text()+chr(ch)); return True
        return False

    # ================================================================== commands that need root
    def run_as_root(self, argv, label, on_line, done, tries=0, message="", on_prompt=None):
        """Run argv as root and stream its output: directly when already root, through a no-password doas or sudo
        rule when there is one, else with the sudo password asked for in a dialog (used once, never stored).
        done(exit code, last lines) runs at the end; a refused or cancelled password reports code -1.
        on_prompt: see StreamedRun (questions the command asks while it runs)."""
        if os.geteuid()==0: StreamedRun(argv,on_line,done,on_prompt=on_prompt); return
        doas=privilege.doas_command(argv)
        if doas and tries==0 and not message:
            def after_doas(code,tail):
                if code!=0 and _doas_refused(tail): self._sudo(argv,label,on_line,done,on_prompt=on_prompt)
                else: done(code,tail)
            StreamedRun(doas,lambda line:None if _doas_refused(line) else on_line(line),after_doas,on_prompt=on_prompt); return
        self._sudo(argv,label,on_line,done,tries,message,on_prompt)
    def _sudo(self, argv, label, on_line, done, tries=0, message="", on_prompt=None):
        sudo=privilege.sudo_command(argv)
        if sudo is None: done(-1,f"{label} needs administrator rights, and neither sudo nor a doas rule for it is available."); return
        def after(code,tail):
            outcome=privilege.sudo_outcome(code,tail)
            if outcome=="password": self._ask_password(argv,label,on_line,done,tries,message,on_prompt)
            elif outcome in ("denied","tty"): done(-1,f"{label} needs administrator rights, and sudo will not run it for this user"
                                                     +(" outside a terminal (requiretty)." if outcome=="tty" else "."))
            else: done(code,tail)
        StreamedRun(sudo,lambda line:None if line.startswith("sudo:") else on_line(line),after,on_prompt=on_prompt)   # sudo's own complaints are handled here
    def _ask_password(self, argv, label, on_line, done, tries, message, on_prompt=None):
        def go(password):
            if not password: done(-1,"No password was given."); return
            def after(code,tail):
                outcome=privilege.sudo_outcome(code,tail)
                if outcome=="wrong" and tries+1<PASSWORD_TRIES: self._ask_password(argv,label,on_line,done,tries+1,"Wrong password. Try again.",on_prompt)
                elif outcome=="wrong": done(-1,f"The password was wrong {PASSWORD_TRIES} times.")
                else: done(code,tail)
            StreamedRun(privilege.sudo_command(argv,with_password=True),
                        lambda line:None if line.startswith("sudo:") or "try again" in line.lower() else on_line(line),after,password=password,on_prompt=on_prompt)
        self.ask_text("Administrator password",f"{label} needs administrator rights. Enter your password (the one sudo asks for). "
                      "It is used once and never stored.",go,secret=True,ok_label="Continue",
                      back=lambda:(self.close_modal(),done(-1,"Cancelled.")),error=message)

class ControlPanelApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        settings=ConfigStore().settings   # TVWCS's interface size, accent colour, use and motion; Options changes them (settings_changed)
        self.scale_key=scale_key(settings); self.scale=effective_scale(self.scale_key); self.accent=settings.get("accent","#0078d7"); self.window=None
        self.theme=settings.get("theme","dark"); self.keyboard=settings.get("keyboard","hidden")
        self.style=settings.get("style","modern"); self.phosphor=settings.get("phosphor","green"); self.retro_font=settings.get("retro_font","pixel")
        self.wm=WindowManager(); self.back_to=None   # the app to go back to when Settings closes (return_focus.py)
    def note_return(self):
        """Settings is being opened or brought up: what to go back to is what TVWCS noted, else (a shell, the user's own
        key binding) the window sway has focused now. Brought up again from Settings itself, it stays as it was."""
        noted=return_focus.take()
        if noted is not return_focus.MISSING: self.back_to=noted; return
        here=return_focus.focused_app(self.wm) if self.wm.available else None
        if here is not None: self.back_to=here
    def do_startup(self):
        Gtk.Application.do_startup(self); self.scale=effective_scale(self.scale_key,screen_height()); set_scale(self.scale)   # fitted to the screen, now there is one
    def do_command_line(self, command_line):
        args=command_line.get_arguments()[1:]
        self.note_return()   # before the window is shown, so sway still has the app focused
        if self.window is None: self.window=ControlWindow(self)
        self.window.present()
        if args[:1]==[ADD_TO_SWAY]:   # plain `tvwcs` in a sway session without TVWCS (main.start_here): offer to add it
            self.window.select_tab("hotkeys"); page=self.window.page_by_key("hotkeys")
            GLib.idle_add(lambda:(page.add_to_sway(),GLib.SOURCE_REMOVE)[1]); return 0
        self.window.select_tab(args[0] if args else (self.window.page.key if self.window.page else self.window.pages[0].key))
        return 0

def main(args=()):
    GLib.set_prgname(APP_ID)   # the window's app_id matches the launcher's StartupWMClass
    GLib.set_application_name(TITLE)
    return ControlPanelApp().run([sys.argv[0],*args])

if __name__=="__main__": raise SystemExit(main(sys.argv[1:]))
