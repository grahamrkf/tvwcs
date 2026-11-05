"""The Settings app's pages. Each reads the system on a worker thread (control_* modules), then draws its rows;
a page that is on screen re-reads quietly every few seconds and only redraws when something changed, keeping the
selection on the same row."""
from __future__ import annotations
import os, shutil, signal, time
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from tvwcs import control_storage as storage
from tvwcs import control_bluetooth as bluetooth, control_datetime as timedate, control_display as display, control_ssh as ssh, control_network as network, control_sound as sound, control_sysinfo as sysinfo, control_ubuntu as ubuntu, control_updates as updates
from tvwcs import __version__, distro, features, power, privilege, selfupdate, servermode, sway_include
from tvwcs import ui_control_login as login_ui
from tvwcs.hotkeys import ACTION_LABELS, DEFAULT_HOTKEYS, DEVICE_ACTIONS, DEVICE_LABELS, DEVICES, describe
from tvwcs.model import (AUTO_SIZE, CHANNEL_DIGITS, CORNERS, PHOSPHORS, RETRO_FONTS, RETRO_WALLPAPER_LABELS, RETRO_WALLPAPERS, SIZES, STYLES, THEMES, WALLPAPERS, ConfigStore, accent_name, auto_size, channel_range, corner_right, is_4k,
                         size_label, tv_mode)
from tvwcs.session import runtime_dir
from tvwcs.system_actions import command_for
from tvwcs.ui_control import StreamedRun, colour_swatch, in_background
from tvwcs.widgets import METRO_COLORS, NavGroup, S, clear_box, glyph, muted_label, section_title, usable

class Page:
    key=""; title=""; icon=""; fallback=""
    poll=0              # seconds between quiet re-reads while the page is on screen (0: only when asked)
    refreshable=True    # a ⟳ button at the top right re-reads the page
    sway_only=False     # it changes what TVWCS or sway do: shown turned off outside sway (sway_include.in_sway)
    server_off=False    # an administrator's page: shown turned off in server mode (servermode.py)

    def __init__(self, win):
        self.win=win; self.state=None; self.busy=False; self.status=""; self._loaded=False; self._poll=0
        self.header=[]; self.groups=[]; self._ids={}; self.root=None

    # ---------------------------------------------------------- frame
    def widget(self):
        root=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0); self.root=root
        head=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(14)); head.set_margin_top(S(12)); head.set_margin_start(S(24)); head.set_margin_end(S(24)); head.set_margin_bottom(S(6))
        title=Gtk.Label(label=self.title); title.add_css_class("pane-title"); title.set_xalign(0); head.append(title)
        self.subtitle=Gtk.Label(); self.subtitle.add_css_class("muted"); self.subtitle.set_valign(Gtk.Align.END); self.subtitle.set_margin_bottom(S(6))
        self.subtitle.set_xalign(0); self.subtitle.set_hexpand(True); self.subtitle.set_ellipsize(Pango.EllipsizeMode.END); head.append(self.subtitle)
        if self.refreshable:
            b=Gtk.Button(); b.add_css_class("square"); b.set_valign(Gtk.Align.START); b.set_child(glyph("view-refresh-symbolic","⟳")); b.set_tooltip_text("Check again")
            b.connect("clicked",lambda *_:self.refresh()); head.append(b); self.header=[b]
        root.append(head); root.append(self.content()); return root

    def content(self):
        scroll=Gtk.ScrolledWindow(); scroll.set_vexpand(True); scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        self.body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4)); self.body.set_margin_start(S(24)); self.body.set_margin_end(S(24)); self.body.set_margin_bottom(S(16))
        scroll.set_child(self.body); self.scroll=scroll; return scroll

    def nav_groups(self):
        return ([NavGroup(self.header)] if self.header else [])+self.groups

    # ---------------------------------------------------------- reading
    def shown(self):
        if not self._loaded: self._loaded=True; self.refresh()
        if self.poll and not self._poll: self._poll=GLib.timeout_add_seconds(self.poll,self._tick)
    def hidden(self):
        if self._poll: GLib.source_remove(self._poll); self._poll=0
    def _tick(self):
        if not self.busy and not self.win.modal_open and self.win.is_visible(): self.refresh(quiet=True)
        return GLib.SOURCE_CONTINUE
    def read(self): return None
    def feature_off(self):
        """The software this page needs (features.py) is not installed: the page only offers to install it."""
        key=features.PAGE_FEATURE.get(self.key)
        return key is not None and not features.installed(features.BY_KEY[key])
    def refresh(self, quiet=False):
        if self.feature_off():
            if not quiet or self.state is not None: self.state=None; self.redraw()
            return
        if self.busy: return
        self.busy=True
        if not quiet: self.set_status("Checking…")
        def done(state):
            self.busy=False
            if not quiet: self.set_status("")
            if quiet and state==self.state: return
            self.state=state; self.redraw()
        def failed(exc):
            self.busy=False; self.set_status(""); self.win.notice(f"{self.title}",f"Could not read the settings: {exc}")
        in_background(self.read,done,failed)
    def set_status(self, text):
        self.status=text; self.subtitle.set_text(text or self.summary())
    def summary(self): return ""

    def act(self, work, status, title, after=None):
        """Change something on a worker thread: work() returns "" when it worked, else why not, which is shown.
        The page is read again afterwards."""
        self.set_status(status)
        def done(problem):
            self.set_status("")
            if problem: self.win.notice(title,problem)
            if after: after()
            self.busy=False; self.refresh(quiet=True)
        def failed(exc): done(str(exc))
        self.busy=True; in_background(work,done,failed)

    # ---------------------------------------------------------- drawing
    def redraw(self):
        """Draw the rows again from self.state, keeping the selection on the same row (by its id)."""
        focused=self.win.get_focus(); old=None
        if focused is not None and self.root is not None and (focused is self.root or focused.is_ancestor(self.root)):
            old=next((i for i,w in self._ids.items() if w is focused or focused.is_ancestor(w)),None)
        stale={id(w):i for i,w in self._ids.items()}; old_rows=dict(self._ids)
        def row_of(w):   # a row's id from one of its widgets (its own button, or a ✕ beside it that may be gone after the change)
            if w is None: return None
            if id(w) in stale: return stale[id(w)]
            return next((i for i,ow in old_rows.items() if w.is_ancestor(ow)),None)
        wanted=getattr(self,"focus_after",None); self.focus_after=None   # the row a change turns the focused one into
        if wanted is not None and old is not None: old=wanted
        scroll=getattr(self,"scroll",None); top=scroll.get_vadjustment().get_value() if scroll is not None else 0
        clear_box(self.body); self.groups=[]; self._ids={}
        if self.server_off and servermode.active(): self.draw_off(lambda:self.draw(self.state),SERVER_OFF)
        elif self.feature_off(): self.draw_feature_off()
        elif self.sway_only and not sway_include.in_sway(): self.draw_off(lambda:self.draw(self.state))
        else: self.draw(self.state)
        if top and scroll is not None:   # rows drawn again (a dialog open over the page, say) stay where they were
            GLib.idle_add(lambda:(scroll.get_vadjustment().set_value(top),GLib.SOURCE_REMOVE)[1]); self.subtitle.set_text(self.status or self.summary())
        for widget_ref in ("_return_focus",):   # a dialog open over this page goes back to the row's new button
            w=getattr(self.win,widget_ref,None); i=row_of(w)
            if i is not None and i not in self._ids: i=i.split("#")[0]
            if i in self._ids: setattr(self.win,widget_ref,self._ids[i])
        i=row_of(self.win._last_page_focus.get(self.key))
        if i is not None and i not in self._ids: i=i.split("#")[0]
        if i in self._ids: self.win._last_page_focus[self.key]=self._ids[i]
        ident=getattr(self,"focus_ident",None)
        if ident is not None and old is None and self._ids.get(ident) is not None:
            self.focus_ident=None; GLib.idle_add(lambda w=self._ids[ident]:(usable(w) and w.grab_focus(),GLib.SOURCE_REMOVE)[1])
        if old is not None:
            # a row's ✕ (id "row#1") that went with the change: the row itself
            target=self._ids.get(old) or self._ids.get(old.split("#")[0]) or (next((w for i,w in self._ids.items() if i.startswith(old)),None) if old==wanted else None)
            if target is not None and usable(target): target.grab_focus()
            elif not self.win._focus_first(self.groups): self.win.tab_buttons[self.key].grab_focus()
    def draw(self, state): pass
    def draw_feature_off(self):
        f=features.BY_KEY[features.PAGE_FEATURE[self.key]]
        self.section("NOT INSTALLED")
        self.note(f"{f.what} It needs software that is not installed yet.")
        if servermode.active(): self.note(SERVER_HIDDEN); return
        self.row(f"Install {f.label}","",lambda:install_feature(self,f),icon="list-add-symbolic",fallback="+",ident="feature:on",
                 detail=f"Installs {', '.join(features.packages_for(f))}. It asks for your password.")

    def draw_off(self, draw, note=None):
        """The rows draw() adds, shown turned off under a note: outside sway they would change nothing (a GNOME or KDE
        session, say). They cannot be selected."""
        self.note(note or SWAY_ONLY,"error")
        mark=self.body.get_last_child(); groups=len(self.groups); ids=set(self._ids)
        draw()
        w=mark.get_next_sibling()
        while w is not None: w.set_sensitive(False); w=w.get_next_sibling()
        del self.groups[groups:]
        for i in set(self._ids)-ids: del self._ids[i]

    def add(self, widget): self.body.append(widget); return widget
    def section(self, text): return self.add(section_title(text))
    def note(self, text, css=None):
        l=muted_label(text)
        if css: l.add_css_class(css)
        return self.add(l)
    def register(self, *widgets, ident=None, column=False):
        g=NavGroup([w for w in widgets if w is not None]); g.column=column
        if g: self.groups.append(g)
        if ident is not None and g: self._ids[ident]=g[0]
        for k,w in enumerate(g[1:],1):
            if ident is not None: self._ids[f"{ident}#{k}"]=w
        return g

    def row(self, label, value="", on_activate=None, detail="", icon=None, fallback="", ident=None, extras=(), value_css="setting-value", swatch=None, indent=0):
        """One row: an optional icon, its name (and a detail line under it), its value on the right (after a square of
        the colour `swatch`); square extra buttons follow it on the same row. ← / → move between them. `indent` (px)
        sets it in under the row before it, as a partition under its drive."""
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4))
        if indent: line.set_margin_start(S(indent))
        b=Gtk.Button(); b.add_css_class("launch-row"); b.set_hexpand(True)
        if on_activate is None: b.add_css_class("info-row")
        inner=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(14))
        if icon is not None or fallback:
            g=glyph(icon,fallback,24); g.set_size_request(S(32),-1); inner.append(g)
        text=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0); text.set_hexpand(True); text.set_valign(Gtk.Align.CENTER)
        name=Gtk.Label(label=label); name.set_xalign(0); name.set_ellipsize(Pango.EllipsizeMode.END); text.append(name)
        if detail:
            d=Gtk.Label(label=detail); d.add_css_class("row-detail"); d.set_xalign(0); d.set_ellipsize(Pango.EllipsizeMode.END); text.append(d)
        inner.append(text)
        if swatch: inner.append(colour_swatch(swatch))
        if value:
            v=Gtk.Label(label=value); v.add_css_class(value_css); v.set_xalign(1); inner.append(v)
        b.set_child(inner)
        if on_activate is not None: b.connect("clicked",lambda *_:on_activate())
        line.append(b)
        extras=[e for e in extras if e is not None]
        for e in extras: e.add_css_class("square"); line.append(e)
        self.add(line); self.register(b,*extras,ident=ident); return b

    def button(self, icon, fallback, tooltip, handler, danger=False):
        b=Gtk.Button(); b.set_child(glyph(icon,fallback)); b.set_tooltip_text(tooltip); b.connect("clicked",lambda *_:handler())
        if danger: b.add_css_class("close-button")
        return b

SWAY_ONLY=("These settings work in sway only: in TVWCS's own session (choose \"TVWCS\" at the login screen, or type tvwcs at a "
           "text console) or in a sway session TVWCS is added to.")

SERVER_OFF=("This computer is in server mode, so these settings are left to its administrator. An administrator can turn "
            "server mode off in Settings › User.")
SERVER_HIDDEN="This computer is in server mode: changes that need an administrator are left to them."

def digits_label(digits): return f"{digits} digit{'s' if digits!=1 else ''}"

def _on_off(flag): return "On" if flag else "Off"
def _outcome(result, otherwise):
    """A control_cmd.Result as act() wants it: "" when it worked, else why not."""
    return "" if result.ok else (result.message or otherwise)

# ====================================================================== Appearance (TVWCS's own)
def tell_tvwcs(request):
    """Ask the running TVWCS to read its options again ("reload") or to restart ("restart PATH"); False when it is not running.
    The same files and signal as main.send_request, written here rather than imported: after an update, main.py on disk
    is the new version, and importing it into this process (with the old versions of the other modules) can fail."""
    runtime=runtime_dir()
    try:
        pid=int((runtime/"tvwcs.pid").read_text(encoding="ascii").strip()); os.kill(pid,0)
        with open(runtime/"tvwcs-requests","a",encoding="utf-8") as f: f.write(request+"\n")
        os.kill(pid,signal.SIGWINCH); return True
    except (OSError,ValueError): return False   # not running: it reads its options when it starts

class _ConfigPage(Page):
    """A page of TVWCS's own options. Each change is saved to TVWCS's config file, read fresh first so nothing TVWCS
    saved meanwhile is lost, and the running TVWCS is asked to read it again; so is this Settings window."""
    refreshable=False
    def read(self): return ConfigStore()
    def summary(self): return f"TVWCS {__version__}"
    def change(self, edit, notice=""):
        """edit(store) changes a freshly read store; it is saved, and TVWCS reads it again."""
        store=ConfigStore(); edit(store); store.save(); self.state=store; self.redraw()
        tell_tvwcs("reload"); self.win.settings_changed(store.settings)
        if notice: self.win.notice(self.title,notice)
    def toggle(self, key):
        def edit(store): store.settings[key]=not store.settings[key]
        return lambda:self.change(edit)
    def option(self, label, key, hint="", invert=False):
        on=bool(self.state.settings[key])!=invert
        self.row(label,_on_off(on),self.toggle(key),ident=f"opt:{key}")
        if hint: self.note(hint)
    def note(self, text, css=None):
        l=super().note(text,css); l.set_margin_bottom(S(6)); return l

class AppearancePage(_ConfigPage):
    """How TVWCS looks (size, colours) and the few choices left in 4.0: closing when it loses focus and the screen edge
    margin. What depends on the mode is fixed: in TV mode (a TVWCS session) apps open in a workspace of their own, the
    pointer hides after 3 seconds, the bar is off and the Quick Menu stays open; in desktop mode none of that changes
    the desktop. Hotkeys have their own page, the application to open at login is on User, and TVWCS's own updates are
    on Software updates."""
    key="appearance"; title="Appearance"; icon="preferences-desktop-appearance-symbolic"; fallback="◐"; sway_only=True

    def draw(self, store):
        st=store.settings
        self.section("LOOK")
        self.size_buttons(st)
        self.row("Theme",STYLES[st["style"]],self.choose_style,ident="opt:style")
        if st["style"]=="retro":
            self.note("Like the menus of an old CRT TV: pixel text in one colour on black, buttons without borders until one is "
                      "selected, and no application icons. Applications that follow the desktop's colour scheme are dark.")
            self.row("Colour",PHOSPHORS[st["phosphor"]],self.choose_phosphor,ident="opt:phosphor")
            self.row("Font",RETRO_FONTS[st["retro_font"]],self.choose_retro_font,ident="opt:retro_font")
            self.note("Pixel is TVWCS's own pixel fonts, sharp at every size. VT323 is a 1970s computer terminal's font. "
                      "Inter is a smooth font made to be easy to read.")
            self.row("Background",RETRO_WALLPAPER_LABELS[st["retro_wallpaper"]],self.choose_retro_wallpaper,ident="opt:retro_wallpaper",
                     swatch=st["retro_wallpaper"])
        else:
            self.note("TVWCS's flat look, in the accent colour.")
            self.row("Light or dark",THEMES[st["theme"]],self.choose_theme,ident="opt:theme")
            self.note("For TVWCS and Settings. Applications that follow the desktop's colour scheme (most GTK apps, "
                      "and browsers through the desktop portal) switch with it.")
            self.row("Accent colour",accent_name(st["accent"]),self.choose_accent,ident="opt:accent",swatch=st["accent"])
            self.row("Background colour","",self.choose_wallpaper,ident="opt:wallpaper",swatch=st["wallpaper"])
        self.note("The background is shown where no application is open, and behind the Quick Menu.")

        self.section("BEHAVIOR")
        self.option("Close TVWCS when it loses focus","close_on_click_outside","Clicking another window, or another window opening, closes the Quick Menu.")
        self.option("Options buttons (⋯) on Quick Menu rows","hide_options_buttons","Even hidden, a row's options open by pressing "
                    +("→" if corner_right(st["quick_corner"]) else "←")+" on it, or by right-clicking it.",invert=True)
        self.option("Search bar on the Quick Menu","search_icon","Off: a search icon beside the status icons opens it. Typing "
                    "anywhere in the Quick Menu opens it too, with what was typed already in it.",invert=True)
        self.row("Quick Menu corner",CORNERS[st["quick_corner"]],self.choose_corner,ident="opt:quick_corner")
        self.note("The corner of the screen the Quick Menu sits in. Its layout mirrors to match: in a right-hand corner it runs "
                  "right to left and Applications opens to its left; in a top corner its lists and menus open downwards.")
        self.row("Channel number digits",digits_label(st["channel_digits"]),self.choose_channel_digits,ident="opt:channel_digits")
        self.note("How many digits a channel number has. Typing them all in the Quick Menu opens that channel a second later.")
        self.row("Screen edge margin",f"{st['margin']} px",self.choose_margin,ident="opt:margin")
        self.note("Many TVs cut off the edges of the picture (overscan). This opens a full-screen preview: move the slider until the "
                  "Quick Menu and Applications are fully on screen.")

    # ---------------------------------------------------------- choices
    def has_4k(self):
        gd=Gdk.Display.get_default(); monitors=gd.get_monitors() if gd else None
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m=monitors.get_item(i); g=m.get_geometry(); f=max(1,m.get_scale_factor())
            if is_4k(g.width*f,g.height*f): return True
        return False
    def size_buttons(self, st):
        """Interface size: Auto, then 1 to 5 from small to large, the one chosen marked; and, with a 4K display, whether
        it is sized for a 4K screen."""
        tv=tv_mode(); chosen=st["scale"] or ""; auto=auto_size(st,tv)
        head=Gtk.Label(label="Interface size"); head.add_css_class("buttons-head"); head.set_xalign(0); head.set_margin_top(S(6)); self.add(head)
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); line.set_homogeneous(True); buttons=[]
        for key,text in [("","Auto")]+[(str(n),str(n)) for n in SIZES]:
            b=Gtk.Button(label=text); b.set_tooltip_text(f"Automatic: size {auto} here" if not key else size_label(int(key)))
            if key==chosen: b.add_css_class("active")
            else: b.connect("clicked",lambda _b,key=key:self.pick_scale(key))
            line.append(b); buttons.append(b)
        self.add(line); self.register(*buttons,ident="opt:scale")
        self.note(f"From 1 (smallest) to 5 (largest): 3 is the desktop size and 4 the TV size. Auto is size {auto} here: "
                  f"{AUTO_SIZE[(True,False)]} in TV mode and {AUTO_SIZE[(False,False)]} in desktop mode, and a size smaller in the "
                  f"Retro theme ({AUTO_SIZE[(True,True)]} and {AUTO_SIZE[(False,True)]}).")
        if st["scale_4k"] or self.has_4k():
            self.option("Sized for a 4K screen","scale_4k","Makes every size about twice as large, for a 4K TV whose picture isn't scaled up by "
                        "Displays (size 4 is then 4K TV Mode from earlier versions).")
    def pick_scale(self, key): self.change(lambda s:s.settings.update(scale=key))   # settings_changed redraws Settings at it
    def choose_accent(self):
        current=self.state.settings["accent"].lower()
        options=[(c,accent_name(c)) for c in METRO_COLORS]+([] if current in METRO_COLORS else [(current,f"{current} (set in config.json)")])
        self.win.choose_option("Accent colour",options,current,lambda c:self.change(lambda s:s.settings.update(accent=c)),swatches=True)
    def choose_style(self):
        self.win.choose_option("Theme",list(STYLES.items()),self.state.settings["style"],lambda t:self.change(lambda s:s.settings.update(style=t)))
    def choose_phosphor(self):
        self.win.choose_option("Colour",list(PHOSPHORS.items()),self.state.settings["phosphor"],lambda c:self.change(lambda s:s.settings.update(phosphor=c)))
    def choose_retro_font(self):
        self.win.choose_option("Font",list(RETRO_FONTS.items()),self.state.settings["retro_font"],lambda f:self.change(lambda s:s.settings.update(retro_font=f)))
    def choose_retro_wallpaper(self):
        self.win.choose_swatch("Background","Gray, blue, or the static of a TV between channels.",list(RETRO_WALLPAPERS),
                               self.state.settings["retro_wallpaper"],lambda k:self.change(lambda s:s.settings.update(retro_wallpaper=k)),
                               names=RETRO_WALLPAPER_LABELS)
    def choose_theme(self):
        self.win.choose_option("Light or dark",list(THEMES.items()),self.state.settings["theme"],lambda t:self.change(lambda s:s.settings.update(theme=t)))
    def choose_wallpaper(self):
        self.win.choose_swatch("Background colour","Six greys, six colours and the same colours darker.",WALLPAPERS,self.state.settings["wallpaper"],
                               lambda c:self.change(lambda s:s.settings.update(wallpaper=c)))
    def choose_corner(self):
        self.win.choose_option("Quick Menu corner",list(CORNERS.items()),self.state.settings["quick_corner"],
                               lambda c:self.change(lambda s:s.settings.update(quick_corner=c)))
    def choose_channel_digits(self):
        def chosen(digits):
            if digits==self.state.settings["channel_digits"]: return
            lost=ConfigStore().too_long_channels(digits)
            if not lost: self.change(lambda s:s.set_channel_digits(digits)); return
            names=", ".join(f"{p.channel} ({p.name})" for p in lost[:6])+(f" and {len(lost)-6} more" if len(lost)>6 else "")
            self.win.confirm("Remove the longer channel numbers?",
                             f"With {digits_label(digits).lower()}, channels run from {channel_range(digits)}. "
                             f"{'This channel is' if len(lost)==1 else 'These channels are'} too long and will be removed: {names}. "
                             f"You can give {'that app a new number' if len(lost)==1 else 'those apps new numbers'} afterwards.",
                             "Remove",lambda:self.change(lambda s:s.set_channel_digits(digits)))
        self.win.choose_option("Channel number digits",[(d,f"{digits_label(d)}: {channel_range(d)}") for d in CHANNEL_DIGITS],
                               self.state.settings["channel_digits"],chosen)
    def choose_margin(self):
        from tvwcs.ui_margin import MarginPreview
        st=self.state.settings
        def done(margin):
            if margin is not None and margin!=st["margin"]: self.change(lambda s:s.settings.update(margin=int(margin)))
            GLib.idle_add(lambda:(self._ids.get("opt:margin") is not None and self._ids["opt:margin"].grab_focus(),GLib.SOURCE_REMOVE)[1])
        MarginPreview(self.win,st["margin"],st["quick_width"],self.win.app.scale,st["accent"],done,corner=st["quick_corner"])

# ====================================================================== Remote and hotkeys
class HotkeysPage(_ConfigPage):
    """The keys that open the Quick Menu and Applications from a keyboard, a remote or a gamepad (TVWCS writes
    hotkeys.conf when it reads them again), and the apps that have a hotkey of their own."""
    key="hotkeys"; title="Remote and hotkeys"; icon="input-keyboard-symbolic"; fallback="⌨"; sway_only=True
    not_added=False     # this is a sway session without TVWCS's include line: the page offers to add it
    def summary(self): return ""
    def read(self):
        self.not_added=sway_include.where()=="sway" and not sway_include.active()
        return ConfigStore()

    def draw(self, store):
        st=store.settings
        if self.not_added:
            self.section("THIS SWAY SESSION")
            self.row("Add TVWCS to sway","",self.add_to_sway,icon="list-add-symbolic",fallback="+",ident="key:add-sway",
                     detail="TVWCS is not part of this session yet, so these hotkeys do nothing here")
        self.section("QUICK MENU HOTKEYS")
        for device in DEVICES:
            for name in DEVICE_ACTIONS[device]:
                self.row(DEVICE_LABELS[device],describe(st["hotkeys"][device][name]),lambda d=device,n=name:self.change_hotkey(store,d,n),ident=f"key:{device}:{name}")
        self.note("Keyboard: a modifier tapped on its own (such as Super) triggers when it is released, so Super combinations keep working. "
                  "Remote: most remotes send ordinary keys; F2 suits many of them. Gamepad: a mapper such as AntiMicroX turns its buttons into keys.")
        self.section("APPLICATION HOTKEYS")
        profiles=store.hotkey_profiles()
        if not profiles: self.note("No application has a hotkey. "+APP_HOTKEY_HINT)
        for p in profiles:
            remove=self.button("window-close-symbolic","✕",f"Remove the hotkey for {p.name}",lambda pid=p.id:self.change(lambda s:s.set_profile_hotkey(pid,"")),danger=True)
            self.row(p.name,describe(p.hotkey),lambda pid=p.id,name=p.name:self.change_app_hotkey(store,pid,name),ident=f"key:app:{p.id}",extras=[remove])
        if profiles: self.note(APP_HOTKEY_HINT)
        self.row("Reset all hotkeys","Defaults",self.reset_hotkeys,ident="key:reset",
                 detail="Keyboard: tap Super. Remote: F2. Gamepad: none. Removes every application hotkey")

    def change_hotkey(self, store, device, name):
        label=f"{DEVICE_LABELS[device]}: {ACTION_LABELS[name]}"
        def chosen(spec):
            if spec or not store.settings["hotkeys"][device][name]: self.change(lambda s:s.set_slot_hotkey(device,name,spec)); return
            # Clear: without this key the Quick Menu may only open from another device, so ask first
            others=[DEVICE_LABELS[d] for d in DEVICES if d!=device and any(store.settings["hotkeys"][d].values())]
            self.win.confirm("Remove this Quick Menu hotkey?",
                             f"{describe(store.settings['hotkeys'][device][name])} will no longer open the Quick Menu from the {DEVICE_LABELS[device].lower()}. "
                             +(f"It still opens with the {' or '.join(o.lower() for o in others)} hotkey." if others else
                               "No other Quick Menu hotkey is set, so only the command tvwcs toggle would open it."),
                             "Remove",lambda:self.change(lambda s:s.set_slot_hotkey(device,name,"")))
        self.win.assign_hotkey(store,("slot",device,name),label,chosen)
    def add_to_sway(self):
        """Add the include line to the user's sway config, reload sway, start TVWCS, then ask for the Quick Menu's key."""
        cfg=sway_include.user_config()
        def go():
            try: sway_include.add()
            except OSError as exc: self.win.notice("Add TVWCS to sway",f"Could not change {cfg}: {exc}"); return
            self.not_added=False; self.redraw()
            sway_include.reload(); started=sway_include.start_launcher()
            self.win.notice("TVWCS is part of sway now",f"TVWCS starts with sway from now on{'' if started else ' (start it now with: tvwcs launcher)'}. "
                            "Next, choose the keyboard key that opens the Quick Menu.",lambda:self.change_hotkey(ConfigStore(),"keyboard","menu"))
        self.win.confirm("Add TVWCS to sway?",f"TVWCS adds one line to {cfg}:\n\n    {sway_include.INCLUDE}\n\nWith it, TVWCS starts with sway in "
                         "desktop mode, and its hotkeys and window rules work. A copy of the file from before is kept as "
                         f"{cfg.name}.tvwcs-backup. To undo it, delete the line.","Add",go,danger=False)

    def change_app_hotkey(self, store, pid, name):
        self.win.assign_hotkey(store,("profile",pid),name,lambda spec:self.change(lambda s:s.set_profile_hotkey(pid,spec)))
    def reset_hotkeys(self):
        def edit(s):
            for device in DEVICES:
                for name in DEVICE_ACTIONS[device]: s.set_slot_hotkey(device,name,DEFAULT_HOTKEYS[device][name])
            for p in s.hotkey_profiles(): s.set_profile_hotkey(p.id,"")
        n=len(ConfigStore().hotkey_profiles())
        self.win.confirm("Reset all hotkeys?","The Quick Menu hotkeys go back to their defaults"+(f", and the {n} application hotkey{'s' if n!=1 else ''} are removed." if n else "."),
                         "Reset",lambda:self.change(edit))

APP_HOTKEY_HINT="Give an app a hotkey with ✎ Edit on it in Applications."

# ====================================================================== TVWCS's own updates (on the Software updates page)
class _SelfUpdate:
    """TVWCS updates: a newer release from GitHub, prereleases, and the way back to the latest release."""
    update_text=""; updating=False
    def draw_self_update(self):
        self.section("TVWCS UPDATES")
        self.row("Check for TVWCS updates",self.update_text or f"Version {__version__}",None if self.updating else self.check_updates,ident="opt:update",
                 icon="view-refresh-symbolic",fallback="⟳")
        if selfupdate.builds_itself():
            self.note(f"Looks for a newer release of TVWCS on GitHub ({selfupdate.GITHUB_REPO}). This copy was built from TVWCS's "
                      "Arch package: install a new release by running TVWCS's installer again in a terminal (or with makepkg -si, as in docs/INSTALL-ARCH.md).")
            return
        self.note(f"Looks for a newer release of TVWCS on GitHub ({selfupdate.GITHUB_REPO}) and offers to install it.")
        pre=ConfigStore().settings["update_prereleases"]
        self.row("Include prereleases",_on_off(pre),self.toggle_prereleases,ident="opt:update_prereleases")
        self.note("Every change is released as a prerelease first, and marked as the latest release once it has been tested "
                  "on a TV computer. On: Check for TVWCS updates offers prereleases too.")
        self.row("Roll back to the latest release","",None if self.updating else self.roll_back,ident="opt:rollback")
        self.note("Installs the release marked latest, even when it is older than this version: the way back from a prerelease.")
    def toggle_prereleases(self):
        store=ConfigStore(); store.settings["update_prereleases"]=not store.settings["update_prereleases"]; store.save(); tell_tvwcs("reload"); self.redraw()
    def check_updates(self):
        self.updating=True; self.update_text="Checking…"; self.redraw()
        def failed(exc): self.updating=False; self.update_text="Check failed"; self.redraw(); self.win.notice("TVWCS updates",f"Could not check for updates: {exc}")
        prereleases=bool(ConfigStore().settings["update_prereleases"]) and not selfupdate.builds_itself()
        in_background(lambda:selfupdate.latest_release(prereleases),self.checked,failed)
    def roll_back(self):
        self.updating=True; self.update_text="Checking…"; self.redraw()
        def failed(exc): self.updating=False; self.update_text="Check failed"; self.redraw(); self.win.notice("TVWCS updates",f"Could not check for updates: {exc}")
        def found(release):
            self.updating=False; self.update_text=""; self.redraw()
            if selfupdate.parse_version(release.version)==selfupdate.parse_version(__version__):
                self.win.notice("TVWCS updates",f"This is already the latest release, TVWCS {__version__}."); return
            if not selfupdate.packaged(): self.win.notice("TVWCS updates","This copy runs from a source checkout: change its version with git."); return
            self.win.confirm("Roll back TVWCS?",f"Install TVWCS {release.version}, the latest release, in place of {__version__}? It asks for your password. "
                             "TVWCS restarts afterwards; your channels, favorites, options and hotkeys are kept.","Install "+release.version,
                             lambda:self.install(release),danger=False)
        in_background(selfupdate.latest_release,found,failed)
    def checked(self, release):
        self.updating=False
        if not selfupdate.is_newer(release.version,__version__): self.update_text=f"Up to date ({__version__})"; self.redraw(); return
        self.update_text=f"{release.version} available"; self.redraw()
        if selfupdate.builds_itself():
            self.win.notice("TVWCS updates",f"TVWCS {release.version} is available (you have {__version__}). Install it by running TVWCS's "
                            "installer again in a terminal:\n\ncurl -fsSL https://github.com/grahamrkf/tvwcs/releases/latest/download/install.sh | bash"); return
        if not selfupdate.packaged():
            self.win.notice("TVWCS updates",f"TVWCS {release.version} is available. This copy runs from a source checkout: update it with git pull."); return
        kind=" prerelease" if release.prerelease else ""
        self.win.confirm("Update TVWCS?",f"TVWCS {release.version}{kind} is available (you have {__version__}). Download and install it now? "
                         "It asks for your password. TVWCS restarts afterwards; your channels, favorites, options and hotkeys are kept.","Install update",
                         lambda:self.install(release),danger=False)
    def install(self, release):
        """Download the release's packages (those installed here), then install them as root with apt (or dnf)."""
        self.updating=True; self.update_text="Downloading…"; self.redraw()
        def failed(exc): self.updating=False; self.update_text="Update failed"; self.redraw(); self.win.notice("TVWCS updates",f"The update failed: {exc}")
        def downloaded(result):
            folder,files=result; lines=[]
            self.update_text="Installing…"; self.redraw()
            def done(code, tail):
                selfupdate.discard(folder); self.updating=False
                if code:
                    self.update_text="Update failed"; self.redraw()
                    self.win.notice("TVWCS updates","The update failed:\n"+("\n".join(lines[-4:]) or tail or "The package manager did not finish.").strip()); return
                self.update_text=f"Installed {release.version}"; self.redraw()
                restarted=tell_tvwcs("restart /usr/bin/tvwcs")
                self.win.notice("TVWCS updated",f"TVWCS {release.version} is installed"+(" and has restarted." if restarted else ".")+
                                " Close Settings and open it again to use the new version.")
            self.win.run_as_root(selfupdate.install_argv(files,current=__version__,version=release.version),"Installing TVWCS "+release.version,lines.append,done)
        in_background(lambda:selfupdate.download(release,selfupdate.installed_packages()),downloaded,failed)

# ====================================================================== Power and sleep
class PowerPage(Page):
    """After how long without input the screen turns off, the computer locks and it sleeps (swayidle, see power.py),
    and what the system does by itself: logind's idle action and the lid."""
    key="power"; title="Power and sleep"; icon="system-shutdown-symbolic"; fallback="⏻"; sway_only=True; server_off=True
    def read(self):
        store=ConfigStore(); st=store.settings
        return power.read_state(st,command_for("lock",st) is not None,command_for("sleep",st) is not None)
    def draw(self, s):
        if s.battery.present:
            b=s.battery
            self.section("BATTERY")
            self.row("Battery",f"{b.percent}%",None,detail="Running on the battery" if b.on_battery else "Plugged in",
                     icon="battery-symbolic",fallback="🔋",ident="bat:now")
            c=s.critical
            self.row("When the battery is nearly empty",power.CRITICAL_ACTIONS[c["action"]],self.choose_critical,
                     icon="battery-caution-symbolic",fallback="🪫",ident="bat:action",
                     detail="" if c["action"]=="nothing" else f"At {c['percent']}% or less, while not plugged in")
            if c["action"]!="nothing": self.row("Nearly empty means",f"{c['percent']}%",self.choose_critical_percent,ident="bat:percent",indent=44)
            self.idle_rows(s,s.settings,"idle","WHEN NOTHING IS TOUCHED, PLUGGED IN")
            self.idle_rows(s,s.battery_settings,"idle_battery","WHEN NOTHING IS TOUCHED, ON BATTERY")
        else: self.idle_rows(s,s.settings,"idle","WHEN NOTHING IS TOUCHED")
        self.note("Times count from the last key, remote button or mouse movement. Nothing happens while sound is playing, "
                  "or while an application keeps the computer awake.")
        if not s.idle_works and any(s.settings[a] or s.battery_settings[a] for a in power.ACTIONS):
            self.note("These times need swayidle. Install it, then sign out and in again.","error")
        self.section("LOCKING")
        self.note("In a TVWCS session the computer locks with swaylock, in TVWCS's theme: type your password and press Enter. "
                  "In another session, Lock uses that desktop's own screen locker." if tv_mode() else
                  "This is not a TVWCS session, so Lock uses this desktop's own screen locker, such as swaylock.")
        l=s.logind
        if l.available:
            self.section("WHAT THE SYSTEM DOES BY ITSELF")
            action={"ignore":"Nothing","suspend":"Sleep","hibernate":"Hibernate","hybrid-sleep":"Hybrid sleep","suspend-then-hibernate":"Sleep, then hibernate",
                    "poweroff":"Shut down","lock":"Lock"}.get(l.idle_action,l.idle_action)
            self.row("The system's idle action",action+(f" after {power.duration_text(l.idle_seconds)}" if l.idle_action!="ignore" and l.idle_seconds else ""),None,
                     detail="logind's IdleAction, set in /etc/systemd/logind.conf",ident="sys:logind")
            if l.lid: self.row("Closing the lid",{"suspend":"Sleep","ignore":"Nothing","poweroff":"Shut down","lock":"Lock","hibernate":"Hibernate"}.get(l.lid,l.lid),None,
                               detail="logind's HandleLidSwitch",ident="sys:lid")
            self.note("logind's settings are changed in /etc/systemd/logind.conf, as root.")

    def idle_rows(self, s, times, option, heading):
        """The three times of one set: "idle" (plugged in, or a computer without a battery) or "idle_battery"."""
        self.section(heading); tag="" if option=="idle" else "bat"
        self.row(power.LABELS["screen_off"],power.duration_text(times["screen_off"]),lambda:self.choose("screen_off",times["screen_off"],option=option),
                 icon="video-display-symbolic",fallback="🖵",ident=f"idle{tag}:screen_off")
        self.row(power.LABELS["lock"],power.duration_text(times["lock"]),lambda:self.choose("lock",times["lock"],option=option),
                 detail="" if s.locker else "swaylock is not installed",
                 icon="system-lock-screen-symbolic",fallback="🔒",ident=f"idle{tag}:lock")
        self.row(power.LABELS["sleep"],power.duration_text(times["sleep"]),lambda:self.choose("sleep",times["sleep"],option=option),
                 detail="" if s.can_sleep else "Nothing on this computer can make it sleep",
                 icon="weather-clear-night-symbolic",fallback="☾",ident=f"idle{tag}:sleep")
    def choose_critical(self):
        def picked(key):
            store=ConfigStore(); store.settings["battery_critical"]["action"]=key; store.save(); tell_tvwcs("reload"); self.refresh(quiet=True)
        self.win.choose_option("When the battery is nearly empty",list(power.CRITICAL_ACTIONS.items()),self.state.critical["action"],picked)
    def choose_critical_percent(self):
        def picked(key):
            store=ConfigStore(); store.settings["battery_critical"]["percent"]=int(key); store.save(); tell_tvwcs("reload"); self.refresh(quiet=True)
        self.win.choose_option("Nearly empty means",[(str(p),f"{p}%") for p in power.CRITICAL_PERCENTS],str(self.state.critical["percent"]),picked)

    def choose(self, action, current, option="idle"):
        options=[(str(v),power.duration_text(v)) for v in power.CHOICES]
        def picked(key):
            value=int(key)
            store=ConfigStore(); store.settings[option][action]=value; store.save(); tell_tvwcs("reload")
            if action in ("lock","sleep") and value and not (self.state.locker if action=="lock" else self.state.can_sleep):
                self.win.notice(power.LABELS[action].replace(" after",""),"Saved, but this computer has nothing to do that with yet.")
            self.refresh(quiet=True)
        self.win.choose_option(power.LABELS[action],options,str(current),picked)

# ====================================================================== Sound
class SoundPage(Page):
    key="sound"; title="Sound"; icon="audio-volume-high-symbolic"; fallback="🔊"; poll=3
    def read(self): return sound.read_state()
    def summary(self): return self.state.server if self.state and self.state.available else ""
    def draw(self, state):
        if not state.available: self.note(state.message); return
        self.section("OUTPUT")
        current=state.output()
        shown,unplugged=sound.split_unplugged(state.outputs,current.name if current else "")
        if current is None: self.note(self.no_output_text(state))
        else:
            self.volume_row(current,"out"); self.device_row(current,True,"audio-speakers-symbolic","🔈")
        others=[d for d in shown if current is None or d.name!=current.name]+unplugged
        self.unplugged_rows("out",[lambda d=d:self.device_row(d,False,"audio-speakers-symbolic","🔈") for d in others]
                            +[lambda o=o:self.card_output_row(o) for o in state.other_outputs])
        self.section("INPUT")
        current=state.input()
        shown,unplugged=sound.split_unplugged(state.inputs,current.name if current else "")
        if current is None: self.note("No microphone or other input is connected.")
        else:
            self.volume_row(current,"in"); self.device_row(current,True,"audio-input-microphone-symbolic","🎤")
        others=[d for d in shown if current is None or d.name!=current.name]+unplugged
        self.unplugged_rows("in",[lambda d=d:self.device_row(d,False,"audio-input-microphone-symbolic","🎤") for d in others])
        self.note("Choosing a device uses it from now on; sound that is already playing moves to it too.")
        self.section("VOLUME")
        boost=bool(ConfigStore().settings["audio_boost"])
        self.row("Allow over-amplification",_on_off(boost),self.toggle_boost,ident="sound:boost",value_css="state-on" if boost else "setting-value",
                 detail="Up to 150 %. Louder, but the sound can distort. Off, volumes stop at 100 %")

    def toggle_boost(self):
        store=ConfigStore(); store.settings["audio_boost"]=not store.settings["audio_boost"]; store.save(); tell_tvwcs("reload"); self.redraw()

    def unplugged_rows(self, kind, draws):
        """The inactive outputs or inputs (nothing plugged in, or another profile of the card), folded under one row,
        "3 inactive outputs", that opens and closes them: they can still be tried, but seldom are."""
        if not draws: return
        opened=getattr(self,"opened",set()); self.opened=opened; is_open=kind in opened
        def toggle():
            opened.symmetric_difference_update({kind}); self.redraw()
        what=("output" if kind=="out" else "input")+("s" if len(draws)!=1 else "")
        self.row(f"{len(draws)} inactive {what}","Hide" if is_open else "Show",toggle,
                 detail="Not in use now, but they can be tried",icon="pan-down-symbolic" if is_open else "pan-end-symbolic",
                 fallback="▾" if is_open else "▸",ident=f"unplugged:{kind}")
        if is_open:
            for draw in draws: draw()

    def device_row(self, d, in_use, icon, fallback):
        ports=[p for p in d.ports if p.available]
        port=next((p.label for p in d.ports if p.name==d.active_port),"")
        extra=None
        if len(ports)>1:
            extra=self.button("view-list-symbolic","⋯",f"Choose the connector of {d.label}",lambda d=d,ports=ports:self.choose_port(d,ports))
        self.row(d.label,"In use" if in_use else "",(lambda d=d:self.act(lambda:_outcome(sound.make_default(d),"Could not switch to that device."),
                 f"Switching to {d.label}…","Sound")) if not in_use else None,
                 detail=port if len(ports)>1 else "",icon=icon,fallback=fallback,ident=f"{d.kind}:{d.name}",extras=[extra],
                 value_css="state-on")

    @staticmethod
    def no_output_text(state):
        if state.alsa_cards==0:
            if distro.is_arch():
                return ("The computer has no sound card the system can use: its driver, or the firmware it needs, is missing. "
                        "Install sof-firmware (Intel laptops and mini PCs) and linux-firmware, then restart.")
            if distro.is_fedora():
                return ("The computer has no sound card the system can use: its driver, or the firmware it needs, is missing. "
                        "Install alsa-sof-firmware (Intel laptops and mini PCs) and linux-firmware, then restart.")
            return ("The computer has no sound card the system can use: its driver, or the firmware it needs, is missing. On Debian, "
                    "install firmware-sof-signed (Intel laptops and mini PCs) or firmware-misc-nonfree (from non-free-firmware), then restart.")
        return "No sound output was found."

    def card_output_row(self, o):
        """An output of a profile the card is not using now (often its HDMI output): choosing it switches the card over."""
        detail=f"{o.card_label} · switches the sound card to this output"
        def use(o=o):
            self.act(lambda:_outcome(sound.use_card_output(o),f"Could not switch {o.card_label} to {o.label}."),f"Switching to {o.label}…",
                     "Sound",after=lambda:setattr(self,"focus_after",f"sink:{sound.sink_for(o.card,o.output)}"))
        self.row(o.label,"",use,detail=detail,icon="video-display-symbolic" if o.hdmi else "audio-speakers-symbolic",
                 fallback="🖵" if o.hdmi else "🔈",ident=f"card:{o.card}:{o.output}")

    def choose_port(self, d, ports):
        def picked(name): self.act(lambda:_outcome(sound.set_port(d,name),"Could not switch the connector."),"Switching…","Sound")
        self.win.choose_option(f"Connector · {d.label}",[(p.name,p.label) for p in ports],d.active_port,picked)

    def volume_row(self, d, ident):
        """− [ level ] + and mute. The bar can be dragged with a mouse; the D-pad uses − and +."""
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(6)); line.set_margin_top(S(2)); line.set_margin_bottom(S(4))
        minus=self.button("list-remove-symbolic","−","Quieter",lambda:step(-1)); plus=self.button("list-add-symbolic","+","Louder",lambda:step(1))
        mute=Gtk.Button()
        boost=bool(ConfigStore().settings["audio_boost"])
        # a volume already above the top (set elsewhere) widens the bar, so it still shows where the volume is
        scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,max(sound.top(boost),d.volume),1); scale.set_draw_value(False); scale.set_hexpand(True)
        scale.set_focusable(False); scale.set_valign(Gtk.Align.CENTER)
        value=Gtk.Label(); value.add_css_class("volume-value"); value.set_xalign(1)
        guard=[False]; pending=[0]
        def show():
            guard[0]=True; scale.set_value(d.volume); guard[0]=False
            value.set_text(f"{d.volume} %")
            (scale.add_css_class if d.muted else scale.remove_css_class)("muted")
            mute.set_child(glyph("audio-volume-muted-symbolic" if d.muted else "audio-volume-high-symbolic","🔇" if d.muted else "🔊"))
            mute.set_tooltip_text(("Unmute " if d.muted else "Mute ")+d.label)
            (mute.add_css_class if d.muted else mute.remove_css_class)("active")
        def applied(result, what):
            if result.ok: return
            self.win.notice("Sound",f"Could not {what} {d.label}: {result.message}"); self.refresh(quiet=True)
        def apply_volume():
            pending[0]=0; level=d.volume
            in_background(lambda:sound.set_volume(d,level,boost),lambda r:applied(r,"change the volume of")); return GLib.SOURCE_REMOVE
        def step(direction):
            d.volume=sound.stepped(d.volume,direction,boost); show()
            if pending[0]: GLib.source_remove(pending[0])
            pending[0]=GLib.timeout_add(120,apply_volume)   # holding the key sends one change, not twenty
        def dragged(*_):
            if guard[0]: return
            d.volume=int(scale.get_value()); value.set_text(f"{d.volume} %")
            if pending[0]: GLib.source_remove(pending[0])
            pending[0]=GLib.timeout_add(120,apply_volume)
        def toggle_mute():
            d.muted=not d.muted; show(); muted=d.muted
            in_background(lambda:sound.set_muted(d,muted),lambda r:applied(r,"mute" if muted else "unmute"))
        scale.connect("value-changed",dragged); mute.connect("clicked",lambda *_:toggle_mute())
        for w in (minus,plus,mute): w.add_css_class("square")
        label=Gtk.Label(label="Volume"); label.set_xalign(0); label.set_size_request(S(110),-1)
        for w in (label,minus,scale,value,plus,mute): line.append(w)
        show(); self.add(line); self.register(minus,plus,mute,ident=f"volume:{ident}")

# ====================================================================== Displays
class DisplaysPage(Page):
    """Resolution, refresh rate and scale of each display; with several, which are on and where each one is. A change
    that can leave a screen blank or unreadable goes back by itself unless it is kept."""
    key="displays"; title="Displays"; icon="video-display-symbolic"; fallback="🖵"; poll=5; sway_only=True
    KEEP_SECONDS=15
    def read(self):
        s=display.read_state()
        if s.available:
            names=self.monitor_names()
            for o in s.outputs: o.label=o.label or names.get(o.name,"")
        return s
    def monitor_names(self):
        """Connector -> the display's own name, from GDK."""
        gd=Gdk.Display.get_default(); monitors=gd.get_monitors() if gd else None; names={}
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m=monitors.get_item(i); label=" ".join(x for x in ((m.get_manufacturer() or ""),(m.get_model() or "")) if x and x!="Unknown").strip()
            if m.get_connector() and label: names[m.get_connector()]=label
        return names
    def summary(self):
        s=self.state
        if not s or not s.available: return ""
        n=len(s.outputs); return f"{n} displays connected" if n>1 else "1 display connected"

    def draw(self, s):
        if not s.available: self.note(s.message); return
        outs=s.outputs; on=[o for o in outs if o.enabled]; where=display.placements(outs); ref=display.reference(outs)
        if len(outs)>1 and on: self.add(self.preview(outs))
        for i,o in enumerate(outs,1):
            self.section(f"{i} · {o.title}".upper()+(f"  ({o.name})" if o.label else ""))
            if len(outs)>1:
                self.row("Use this display",_on_off(o.enabled),lambda o=o:self.switch(o),ident=f"{o.name}:on")
            if not o.enabled: continue
            mode=o.mode()
            self.row("Resolution",(display.mode_text(mode) if mode else f"{o.width} × {o.height}")+(" (recommended)" if mode and mode.preferred else ""),
                     (lambda o=o:self.choose_mode(o)) if len(o.modes)>1 else None,ident=f"{o.name}:mode")
            rates=mode.rates if mode else []
            if o.rate or rates:
                self.row("Refresh rate",display.rate_text(o.rate) if o.rate else "—",(lambda o=o:self.choose_rate(o)) if len(rates)>1 else None,ident=f"{o.name}:rate")
            self.scale_buttons(f"{o.name}:scale",display.scale_choices([o],o.scale),o.scale,lambda v,o=o:self.change(o,True,scale=v),
                               "Makes text and controls bigger")
            if len(on)>1:
                if o is ref:
                    other=next((x for x in on if where.get(x.name,("",""))[1]==o.name),None)
                    value=display.RELATION_TEXT[display.relation(o,other)].format(other.title) if other else ""
                else:
                    rel,anchor=where[o.name]; value=display.RELATION_TEXT[rel].format(next(x.title for x in outs if x.name==anchor))
                self.row("Position",value,lambda o=o:self.choose_place(o),ident=f"{o.name}:place")
        notes=[f"A new resolution, refresh rate, scale or display switched on or off goes back after {self.KEEP_SECONDS} seconds unless you keep it, "
               "in case a display cannot show it."]
        notes.append("What you keep is used again at the next log-in, as long as the same displays are connected.")
        self.note(" ".join(notes))

    def preview(self, outs):
        """The displays that are on, drawn where they are, each with the number of its section."""
        on=[(i,o) for i,o in enumerate(outs,1) if o.enabled]
        minx=min(o.x for _i,o in on); miny=min(o.y for _i,o in on)
        maxx=max(o.x+o.size[0] for _i,o in on); maxy=max(o.y+o.size[1] for _i,o in on)
        k=min(S(560)/max(1,maxx-minx),S(180)/max(1,maxy-miny))
        fixed=Gtk.Fixed(); fixed.set_halign(Gtk.Align.CENTER); fixed.set_margin_top(S(8)); fixed.set_margin_bottom(S(8))
        fixed.set_size_request(round((maxx-minx)*k)+S(16),round((maxy-miny)*k)+S(16)); seen={}
        for i,o in on:
            shift=seen.get((o.x,o.y),0); seen[(o.x,o.y)]=shift+1   # mirrored displays sit on each other: offset a little
            w,h=o.size; box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0); box.add_css_class("display-box")
            box.set_size_request(max(S(24),round(w*k)),max(S(24),round(h*k))); box.set_overflow(Gtk.Overflow.HIDDEN)
            number=Gtk.Label(label=str(i)); number.add_css_class("display-number"); number.set_vexpand(True); box.append(number)
            name=Gtk.Label(label=o.title); name.add_css_class("display-name"); name.set_ellipsize(Pango.EllipsizeMode.END); name.set_margin_bottom(S(4))
            name.set_margin_start(S(4)); name.set_margin_end(S(4)); box.append(name)
            fixed.put(box,round((o.x-minx)*k)+shift*S(8),round((o.y-miny)*k)+shift*S(8))
        return fixed

    def scale_buttons(self, ident, choices, current, pick, detail):
        """Scale: one button per scale (75 % to 200 %), the one in use marked."""
        head=Gtk.Label(label="Scale"); head.add_css_class("buttons-head"); head.set_xalign(0); head.set_margin_top(S(6)); self.add(head)
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); line.set_homogeneous(True); buttons=[]
        for v in choices:
            b=Gtk.Button(label=display.scale_text(v))
            if current is not None and abs(v-current)<0.005: b.add_css_class("active")
            else: b.connect("clicked",lambda _b,v=v:pick(v))
            line.append(b); buttons.append(b)
        self.add(line); self.register(*buttons,ident=ident); self.note(detail)

    # ---------------------------------------------------------- choosing
    def choose_mode(self, o):
        mode=o.mode()
        self.win.choose_option(f"Resolution · {o.title}",[(m.key,display.mode_text(m)+(" (recommended)" if m.preferred else "")) for m in o.modes],
                               mode.key if mode else None,lambda key:self.change(o,True,mode=key))
    def choose_rate(self, o):
        mode=o.mode()
        self.win.choose_option(f"Refresh rate · {o.title}",[(r,display.rate_text(r)) for r in mode.rates],o.rate,lambda r:self.change(o,True,rate=r))
    def choose_place(self, o):
        where=display.placements(self.state.outputs).get(o.name)
        def picked(key): rel,anchor=key.split(":",1); self.change(o,False,place=(rel,anchor))
        self.win.choose_option(f"Position · {o.title}",display.choices(self.state.outputs,o),f"{where[0]}:{where[1]}" if where else None,picked)
    def switch(self, o):
        if o.enabled and sum(x.enabled for x in self.state.outputs)==1:
            self.win.notice("Displays","This is the only display that is on, so it stays on."); return
        self.change(o,True,enabled=not o.enabled)

    # ---------------------------------------------------------- changing
    def change(self, o, risky, **changes):
        """Apply a change to one display now. A risky one waits to be kept, else goes back; the rest are kept at once."""
        self.change_all(display.edited(self.state.outputs,o.name,**changes),risky)
    def change_all(self, new, risky):
        s=self.state; old=s.outputs
        self.set_status("Changing the displays…"); self.busy=True
        def done(problem):
            self.busy=False; self.set_status("")
            if problem: self.win.notice("Displays",problem); self.refresh(quiet=True)
            elif risky: GLib.timeout_add(600,lambda:(self.ask_keep(s,old,new),GLib.SOURCE_REMOVE)[1])   # let the screen settle first
            else: self.keep(s,new)
        in_background(lambda:display.apply(s,new),done,lambda exc:done(str(exc)))
    def ask_keep(self, s, old, new):
        def message(n): return f"Keep these display settings? They go back in {n} second{'s' if n!=1 else ''}."
        def undo():
            self.set_status("Going back…"); self.busy=True
            def done(problem):
                self.busy=False; self.set_status("")
                if problem: self.win.notice("Displays",f"Could not go back to the earlier settings: {problem}")
                self.refresh(quiet=True)
            in_background(lambda:display.apply(s,old),done,lambda exc:done(str(exc)))
        self.win.countdown("Displays",message,self.KEEP_SECONDS,"Keep",lambda:self.keep(s,new),"Go back",undo)
    def keep(self, s, outputs):
        try: display.save(outputs)
        except OSError as exc: self.win.notice("Displays",f"The change is in use, but could not be saved for the next log-in: {exc}")
        self.refresh(quiet=True)

# ====================================================================== Bluetooth
class BluetoothPage(Page):
    key="bluetooth"; title="Bluetooth"; icon="bluetooth-active-symbolic"; fallback="ᛒ"; poll=4
    scanning=False
    def read(self): return bluetooth.read_state()
    def summary(self):
        s=self.state
        if not s or not s.available: return ""
        return ("Searching for devices…" if self.scanning else f"Adapter {s.controller}")
    def draw(self, s):
        if not s.available: self.note(s.message); return
        self.row("Bluetooth",_on_off(s.powered),lambda:self.act(lambda:bluetooth.set_powered(not s.powered),
                 "Switching Bluetooth "+("off…" if s.powered else "on…"),"Bluetooth"),ident="power")
        if s.blocked: self.note("Bluetooth is switched off by rfkill (airplane mode); turning it on here lifts that.")
        if not s.powered: self.note("Turn Bluetooth on to connect headphones, speakers, game controllers and remotes."); return
        self.row("Search for devices","Searching…" if self.scanning else "",None if self.scanning else self.scan,
                 detail="Put the device in pairing mode first.",icon="edit-find-symbolic",fallback="⌕",ident="scan")
        self.section("MY DEVICES")
        if not s.paired: self.note("No device is paired yet. Search for devices, then choose one to pair it.")
        for d in s.paired: self.device_row(d)
        self.section("OTHER DEVICES")
        named=[d for d in s.nearby if d.name and d.name.replace("-",":").upper()!=d.address]
        if not named: self.note("None found yet. Choose Search for devices." if not self.scanning else "Looking…")
        for d in named: self.device_row(d)
        if len(named)<len(s.nearby): self.note(f"{len(s.nearby)-len(named)} unnamed devices nearby are not listed.")

    def device_row(self, d):
        icon,fallback,kind=d.kind
        detail=" · ".join(x for x in (kind,f"Battery {d.battery} %" if d.battery is not None else "",d.address) if x)
        if not d.paired:
            self.row(d.name,"Pair",lambda d=d:self.act(lambda:bluetooth.pair(d.address),f"Pairing with {d.name}…",f"Pair {d.name}"),
                     detail=detail,icon=icon,fallback=fallback,ident=f"bt:{d.address}"); return
        forget=self.button("user-trash-symbolic","✕",f"Forget {d.name}",lambda d=d:self.win.confirm(f"Forget {d.name}?",
                           f"{d.name} will be disconnected and unpaired. To use it again, pair it again.","Forget",
                           lambda:self.act(lambda:bluetooth.forget(d.address),f"Forgetting {d.name}…","Bluetooth")),danger=True)
        if d.connected:
            go=lambda d=d:self.act(lambda:bluetooth.disconnect(d.address),f"Disconnecting {d.name}…","Bluetooth")
        else:
            go=lambda d=d:self.act(lambda:bluetooth.connect(d.address),f"Connecting to {d.name}…",f"Connect {d.name}")
        self.row(d.name,"Connected" if d.connected else "Not connected",go,detail=detail,icon=icon,fallback=fallback,
                 ident=f"bt:{d.address}",extras=[forget],value_css="state-on" if d.connected else "setting-value")

    def scan(self):
        self.scanning=True; self.redraw(); self.set_status("Searching for devices…")
        def done(_result):
            self.scanning=False; self.set_status(""); self.busy=False; self.refresh(quiet=True)
        in_background(lambda:bluetooth.scan(),done,lambda _e:done(None))

# ====================================================================== Software updates
class _Console:
    """A read-only console under a page's rows, showing the output of what the page runs."""
    def console(self):
        if self.log is None:
            self.log=Gtk.TextView(); self.log.set_editable(False); self.log.set_cursor_visible(False); self.log.set_focusable(False)
            self.log.add_css_class("console"); self.log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); self.log.set_monospace(True)
            self.log_scroll=Gtk.ScrolledWindow(); self.log_scroll.set_child(self.log); self.log_scroll.set_min_content_height(S(280))
            self.log_scroll.add_css_class("console-frame"); self.log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        if self.log_scroll.get_parent() is not None: self.log_scroll.get_parent().remove(self.log_scroll)
        return self.log_scroll
    def _append(self, line):
        buf=self.log.get_buffer(); buf.insert(buf.get_end_iter(),line+"\n")
        if buf.get_line_count()>2000: buf.delete(buf.get_start_iter(),buf.get_iter_at_line(buf.get_line_count()-2000)[1])
        GLib.idle_add(lambda:(self.log_scroll.get_vadjustment().set_value(self.log_scroll.get_vadjustment().get_upper()),GLib.SOURCE_REMOVE)[1])

class UpdatesPage(_SelfUpdate, _Console, Page):
    """TVWCS's own updates, then the system's packages."""
    key="updates"; title="Software updates"; icon="software-update-available-symbolic"; fallback="⇩"; server_off=True
    MAX_ROWS=300
    def __init__(self, win):
        super().__init__(win); self.running=None; self.log=None; self.fetched=None; self.asker="pacman"; self.echo=None
        self.finished=None; self.outcome=None   # the run that just ended, until the page is read again; then what came of it
    def read(self):
        state=updates.read_state(); state.reboot=updates.reboot_needed(); state.extras=ubuntu.installed_extras()
        state.news=[]; state.pacnew=[]; state.news_unknown=False
        if state.manager is not None and state.manager.id=="pacman":   # Arch: its news since the last full upgrade, and .pacnew files
            items=updates.read_news(); state.news_unknown=items is None
            state.news=updates.news_since(items or [],updates.last_upgrade()); state.pacnew=updates.pacnew_files()
        if self.fetched and (state.checked or 0)<self.fetched: state.checked=self.fetched   # unchanged lists keep their old date
        return state
    def summary(self):
        s=self.state
        if not s or not s.available or s.manager is None: return ""
        age=updates.age_text(s.checked)
        return s.manager.label+(f" · package lists from {age}" if age else "")
    def draw(self, s):
        if self.running:
            self.row(self.running,"Working…",None,icon="emblem-synchronizing-symbolic",fallback="⟳",ident="running")
            self.note("Leave this running until it finishes. Settings can be closed; the update carries on.")
            self.add(self.console()); return
        self.draw_self_update()
        self.section("SYSTEM")
        if not s.available: self.note(s.message); return
        self.row("Check for updates",f"{s.all_total} available" if s.all_total else "Up to date",self.refresh,ident="check",
                 icon="view-refresh-symbolic",fallback="⟳")
        m=s.manager
        if m is not None and m.refresh_argv:
            self.row("Download the latest package lists","",lambda:self.run_steps("Downloading package lists",[(list(m.refresh_argv),True)],fetch=True),
                     detail="Asks for your password, then checks again.",icon="folder-download-symbolic",fallback="⇩",ident="lists")
        if s.total:
            self.row(f"Install {s.total} update{'s' if s.total!=1 else ''}","",self.confirm_install,ident="install",
                     detail="Installs everything listed below." + (" Asks for your password." if s.updates else ""),
                     icon="software-update-available-symbolic",fallback="⇩")
        if m is not None and m.step_argv and s.total:
            self.row("Update step by step","",self.confirm_step_by_step,ident="step",
                     detail="Installs them showing each question pacman asks, with buttons to answer it.",icon="dialog-question-symbolic",fallback="?")
        if m is not None and m.id=="pacman":
            where=(", below." if getattr(s,"news",[]) else " (archlinux.org/news), which has nothing new since your last update."
                   if not getattr(s,"news_unknown",False) else " (archlinux.org/news).")
            self.note("pacman updates everything at once, as Arch expects. Now and then an update needs a step by hand: Arch "
                      "announces those in its news"+where+("" if s.aur_helper else " Packages from the AUR are not included: "
                      "with yay or paru installed, Settings updates them too."))
            self.draw_arch_news(s)
            self.draw_aur(s)
        if getattr(s,"reboot",False):
            self.row("Restart to finish updating","",self.confirm_reboot,detail="Some updates are only used after a restart.",
                     icon="system-reboot-symbolic",fallback="↻",ident="reboot")
        for label,problem in s.problems: self.note(f"{label}: {problem}","error")
        if self.finished: self.outcome=self.outcome_text(self.finished,s); self.finished=None; self._append(f"\n✓ {self.outcome}")
        if self.outcome: self.note(self.outcome,"state-on")
        self.draw_pacnew(getattr(s,"pacnew",[]))
        if self.log is not None and self.log.get_buffer().get_char_count():
            self.section("LAST RUN"); self.add(self.console())
        self.draw_ubuntu_extras(getattr(s,"extras",[]))
        for title,items in ((f"{m.label.upper()} PACKAGES" if m else "PACKAGES",s.updates),):
            if not items: continue
            self.section(f"{title} ({len(items)})")
            for u in items[:self.MAX_ROWS]:
                self.row(u.name,f"{u.old} → {u.new}" if u.old else u.new,lambda u=u:self.details(u),detail=u.source,ident=f"pkg:{title}:{u.name}")
            if len(items)>self.MAX_ROWS: self.note(f"… and {len(items)-self.MAX_ROWS} more.")

    @staticmethod
    def outcome_text(label, s):
        """The line that says a run has finished and what it found, such as: Package lists downloaded at 23:05. Everything is up to date."""
        done={"Downloading package lists":"Package lists downloaded","Installing updates":"Updates installed","Updating step by step":"Updates installed",
              "Updating AUR packages":"AUR packages updated"}.get(label,f"{label}: finished")
        n=getattr(s,"all_total",s.total)
        found=f"{n} update{'s' if n!=1 else ''} available." if n else "Everything is up to date."
        return f"{done} at {time.strftime('%H:%M')}. {found}"

    def details(self, u):
        lines=[f"Version {u.new}"]+([f"Installed now: {u.old}"] if u.old else [])+([f"From: {u.source}"] if u.source else [])
        self.win.notice(u.name,"\n".join(lines))

    def confirm_install(self):
        s=self.state; parts=[]
        if s.updates: parts.append(f"{len(s.updates)} package{'s' if len(s.updates)!=1 else ''} from {s.manager.label}")
        steps=[]
        if s.updates: steps.append((list(s.manager.install_argv),True))
        self.win.confirm("Install updates?",f"Install {' and '.join(parts)} now? Apps being updated may need to be restarted afterwards."+self.news_warning(),
                         "Install",lambda:self.run_steps("Installing updates",steps),danger=False)
    def news_warning(self):
        n=len(getattr(self.state,"news",[]))
        return (f"\n\nArch has posted {'a news item' if n==1 else f'{n} news items'} since your last update (on this page). "
                "Read it first: it says when an update needs a step by hand." if n else "")

    # -------------------------------------------------------------- Arch: step by step, its news, .pacnew files
    def confirm_step_by_step(self):
        self.win.confirm("Update step by step?","pacman installs the updates and stops at each question it asks (go ahead, replace a "
                         "package, remove one that conflicts, choose between packages), with a button for each answer. Back answers No."
                         +self.news_warning(),"Start",self.update_step_by_step,danger=False)
    def update_step_by_step(self):
        m=self.state.manager
        self.asker="pacman"; self.run_steps("Updating step by step",[(list(m.step_argv),True)],prompts=True)
    def answer_prompt(self, run, question, before):
        p=updates.parse_prompt(question,before)
        if p is None: return
        if p.kind=="password":   # an AUR helper's sudo, reading from the pipe (--sudoflags=-S)
            self.win.ask_text("Administrator password","Installing the built packages needs administrator rights. Enter your password "
                              "(the one sudo asks for). It is used once and never stored.",lambda pw:(self.win.close_modal(),run.send(pw)),
                              secret=True,ok_label="Continue",back=lambda:(self.win.close_modal(),run.stop()))
            return
        def answer(text): self._append(f"→ {text or '(default)'}"); self.echo=text or None; run.send(text)
        title=f"{self.asker} asks"
        if len(p.answers)>4:   # a long choice between packages: a list
            self.win.choose_option(title,[(a,label) for label,a in p.answers],p.answers[0][1],answer,back=lambda:(self.win.close_modal(),answer(p.back)))
        else:
            self.win.ask_choice(title,p.question,[(label,lambda a=a:answer(a)) for label,a in p.answers],lambda:answer(p.back))
    def draw_aur(self, s):
        if not s.aur: return
        self.section(f"AUR PACKAGES ({len(s.aur)})")
        self.row(f"Update {len(s.aur)} AUR package{'s' if len(s.aur)!=1 else ''}","",self.confirm_aur,ident="aur",
                 detail=f"With {s.aur_helper}, step by step: it shows what changed in each package's build script first.",
                 icon="software-update-available-symbolic",fallback="⇩")
        for u in s.aur[:self.MAX_ROWS]:
            self.row(u.name,f"{u.old} → {u.new}" if u.old else u.new,lambda u=u:self.details(u),detail="AUR",ident=f"aurpkg:{u.name}")
    def confirm_aur(self):
        h=self.state.aur_helper; n=len(self.state.aur)
        self.win.confirm("Update AUR packages?",f"{h} downloads and builds the new version of {'this package' if n==1 else f'these {n} packages'} "
                         "here, as you. AUR packages are written by their users, not checked by Arch, so it first shows what changed in each "
                         "build script (choose Show all), and you can stop there. It asks for your password before installing them.",
                         "Start",self.update_aur,danger=False)
    def update_aur(self):
        h=self.state.aur_helper; self.asker=h
        self.run_steps("Updating AUR packages",[(updates.aur_update_argv(h),False)],prompts=True,env=updates.AUR_ENV)
    def draw_arch_news(self, s):
        news=getattr(s,"news",[])
        if news:
            self.section(f"ARCH NEWS SINCE YOUR LAST UPDATE ({len(news)})")
            for n in news:
                self.row(n.title,time.strftime("%d %b %Y",time.localtime(n.date)),lambda n=n:self.win.notice(n.title,f"{n.text}\n\n{n.link}"),
                         ident=f"news:{n.link}",icon="dialog-information-symbolic",fallback="i")
        elif getattr(s,"news_unknown",False):
            self.note("Arch's news could not be read (archlinux.org/news). Check it before a big update.")
    def draw_pacnew(self, files):
        if not files: return
        self.section(f"NEW DEFAULT SETTINGS FILES ({len(files)})")
        for f in files:
            self.row(f,"",lambda f=f:self.win.notice(os.path.basename(f),self.pacnew_text(f)),ident=f"pacnew:{f}",icon="document-edit-symbolic",fallback="✎")
        self.note("An update brought a new default version of these settings files, but the old ones had been changed, so pacman kept "
                  "them and put the new version next to each as .pacnew. Compare each pair and merge them by hand, then delete the .pacnew file.")
    @staticmethod
    def pacnew_text(f):
        old=f[:-len(".pacnew")]
        return (f"New default: {f}\nIn use: {old}\n\nCompare them in a terminal with  diff {old} {f}  and copy over what you want "
                "to keep, then delete the .pacnew file. pacdiff (from pacman-contrib) goes through every such file for you: sudo pacdiff")

    def run_steps(self, label, steps, fetch=False, prompts=False, env=None):
        """Run each (argv, as root) in turn, showing their output; stop at the first that fails. prompts: answer the
        questions they ask with buttons (pacman step by step)."""
        self.running=label; self.outcome=None; self.console(); self.log.get_buffer().set_text(""); self.redraw(); self.set_status(label+"…")
        self.win._focus_first(self.groups)
        def finish(problem=""):
            self.running=None; self.set_status(""); self.redraw()
            if problem:
                self._append(f"\n✗ Stopped: {problem}")
                m=self.state.manager if self.state else None
                if label=="Installing updates" and m is not None and m.step_argv:   # often a question --noconfirm answered No
                    self.win.confirm(label,f"{problem}\n\nUpdating step by step shows each question pacman asks, so you can answer "
                                     "it yourself.","Update step by step",self.update_step_by_step,danger=False)
                else: self.win.notice(label,problem)
            else: self.finished=label   # said once the page has been read again, with what it found
            self.refresh(); tell_tvwcs("status")   # the Quick Menu's updates icon counts again
        def next_step(i):
            if i>=len(steps):
                if fetch: self.fetched=time.time()
                finish(); return
            argv,root=steps[i]; self._append("$ "+" ".join(argv))
            def out(line):   # pacman writes the answer it read from a pipe; it is already shown as → answer
                echo,self.echo=self.echo,None
                if echo is None or line.strip()!=echo: self._append(line)
            def done(code,tail):
                if code!=0: finish(tail.strip().splitlines()[-1] if tail.strip() else f"It stopped with exit status {code}."); return
                next_step(i+1)
            if root: self.win.run_as_root(argv,label,out,done,on_prompt=self.answer_prompt if prompts else None)
            else: StreamedRun(argv,out,done,env=privilege.c_locale_env({**os.environ,**(env or {})}),
                              on_prompt=self.answer_prompt if prompts else None)
        next_step(0)

    def draw_ubuntu_extras(self, extras):
        """Ubuntu's Snap, cloud-init and Ubuntu Pro client, each offered for removal while it is installed (control_ubuntu)."""
        if not extras: return
        self.section("UBUNTU EXTRAS")
        for e,pkgs in extras:
            self.row(f"Remove {e.name}","",lambda e=e,pkgs=pkgs:self.remove_ubuntu_extra(e,pkgs),icon="user-trash-symbolic",fallback="✕",
                     ident=f"ubuntu:{e.key}",detail=", ".join(pkgs))
        self.note("Ubuntu comes with these, and a TV computer does without them. "+" ".join(f"{e.name}: {e.what}" for e,_p in extras)
                  +" Each is removed with its settings (purged). Nothing stops a package that needs one of them from installing it again.")
    def remove_ubuntu_extra(self, e, pkgs):
        also=ubuntu.would_remove(pkgs); apps=ubuntu.snap_apps() if e.key=="snap" else []
        text=e.what
        if apps: text+=f"\n\nSnap apps removed with it: {', '.join(apps)}."
        if also: text+=f"\n\nAlso removed, as they need it: {', '.join(also)}."
        text+=" It asks for your password."
        self.win.confirm(f"Remove {e.name}?",text,"Remove",lambda:self.run_steps(f"Removing {e.name}",[(ubuntu.purge_argv([e.key]),True)]))

    def confirm_reboot(self):
        command=command_for("reboot")
        if not command: self.win.notice("Restart","Nothing on this system can restart it from here."); return
        def go():
            if privilege.needs_root(command): self.win.run_as_root(command,"Restart",lambda _l:None,lambda code,tail:code and self.win.notice("Restart",tail))
            else:
                def done(code,tail):
                    if code and privilege.polkit_refused(tail): self.win.run_as_root(command,"Restart",lambda _l:None,lambda c,t:c and self.win.notice("Restart",t))
                    elif code: self.win.notice("Restart",tail)
                StreamedRun(command,lambda _l:None,done)
        self.win.confirm("Restart now?","Restart the computer now? Unsaved work in open applications may be lost.","Restart",go)

# ====================================================================== System information
class SystemPage(Page):
    key="system"; title="System information"; icon="computer-symbolic"; fallback="🖥"
    def read(self): return sysinfo.read_sections(),ssh.read_state()
    def summary(self): return ""
    def draw(self, state):
        sections,remote=state
        displays=self.displays()
        if displays: sections=sections[:2]+[("DISPLAYS",displays)]+sections[2:]
        for title,rows in sections:
            self.section(title)
            for i,(label,value) in enumerate(rows): self.row(label,value,None,ident=f"{title}:{label}:{i}")
        self.draw_ssh(remote)

    # ---------------------------------------------------------- SSH: signing in to this computer from another one
    def draw_ssh(self, s):
        self.section("REMOTE ACCESS (SSH)")
        admin=not servermode.active()   # server mode: shown, not changed here
        if not s.installed:
            self.row("SSH server","Not installed",self.install_ssh if admin and ssh.install_argv() else None,
                     detail="Install it to sign in to this computer from another one" if admin else "",ident="ssh:server"); return
        self.row("SSH server","On" if s.active else "Off",(lambda:self.switch_ssh(s)) if admin else None,
                 detail=("Starts with the computer" if s.enabled else "Stopped at the next restart") if s.active else
                        ("Starts with the computer" if s.enabled else "Turn it on to sign in from another computer"),
                 ident="ssh:server",value_css="state-on" if s.active else "setting-value")
        self.row("Sign in with","Keys only" if not s.passwords else "Password or key",(lambda:self.choose_sign_in(s)) if admin else None,
                 detail=f"{s.keys} key{'s' if s.keys!=1 else ''} added for {s.user}",ident="ssh:auth")
        if s.passwords and s.active and ConfigStore().settings["password_keyboard"]=="digits":
            self.note("Your password keyboard is the number pad, so your password may be only digits, which is easy to guess. "
                      "Keys only is recommended: then nobody can sign in over the network with a password.","error")
        self.row("Connect with",f"ssh {s.user}@{s.address}",None,ident="ssh:command")
        self.row("User",s.user,None,ident="ssh:user")
        self.row("Local name",s.local_name if s.mdns else f"{s.local_name} (not announced)",None,
                 detail="" if s.mdns else "Install avahi-daemon to reach this computer by name",ident="ssh:name")
        for i,(iface,address) in enumerate(s.addresses):
            self.row("IP address" if i==0 else "",address,None,detail=iface,ident=f"ssh:ip:{i}")
        if not s.addresses: self.row("IP address","Not connected to a network",None,ident="ssh:ip:0")

    def as_root(self, argv, label, status):
        """Run one of control_ssh's commands as root, then read the page again; its output is shown if it fails."""
        self.set_status(status); lines=[]
        def done(code,tail):
            self.set_status("")
            if code: self.win.notice("SSH",("\n".join(lines[-6:]) or tail or f"{label} did not work.").strip())
            self.refresh(quiet=True)
        self.win.run_as_root(argv,label,lines.append,done)
    def install_ssh(self):
        self.win.confirm("Install the SSH server?","This installs OpenSSH's server with the package manager. Turn it on here afterwards.",
                         "Install",lambda:self.as_root(ssh.install_argv(),"Installing the SSH server","Installing the SSH server…"),danger=False)
    def switch_ssh(self, s):
        if not s.unit: self.win.notice("SSH","The SSH server has no systemd service here (ssh), so Settings cannot start or stop it."); return
        if s.active:
            self.win.confirm("Turn SSH off?","Nobody can sign in from another computer until it is turned on again. "
                             "Connections open now stay open.","Turn off",lambda:self.as_root(ssh.service_argv(s,False),"Turning SSH off","Turning SSH off…"))
        else: self.as_root(ssh.service_argv(s,True),"Turning SSH on","Turning SSH on…")
    def choose_sign_in(self, s):
        def picked(key):
            allow=key=="password"
            if allow==s.passwords: return
            if not allow:
                problem=ssh.key_only_problem(s)
                if problem: self.win.notice("Keys only",problem); return
            self.as_root(ssh.passwords_argv(s,allow),"Changing how SSH signs in","Changing how SSH signs in…")
        self.win.choose_option("Sign in with",[("password","Password or key"),("keys",f"Keys only (safer; {s.keys} key{'s' if s.keys!=1 else ''} added)")],
                               "password" if s.passwords else "keys",picked)
    def displays(self):
        display=Gdk.Display.get_default(); monitors=display.get_monitors() if display else None; rows=[]
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m=monitors.get_item(i); g=m.get_geometry(); f=max(1,m.get_scale_factor()); hz=m.get_refresh_rate()/1000 if m.get_refresh_rate() else 0
            name=" ".join(x for x in ((m.get_manufacturer() or ""),(m.get_model() or "")) if x and x!="Unknown").strip() or (m.get_connector() or f"Display {i+1}")
            rows.append((name,f"{g.width*f} × {g.height*f}"+(f" at {hz:.0f} Hz" if hz else "")))
        return rows

# ====================================================================== Network
class NetworkPage(Page):
    key="network"; title="Network"; icon="network-wired-symbolic"; fallback="⇄"; poll=6; server_off=True
    scanning=False
    def read(self): return network.read_state(scan=self.scanning)
    def summary(self):
        s=self.state
        if not s: return ""
        return "NetworkManager" if s.managed else "Wi-Fi through iwd" if s.iwd else "Shown only (no NetworkManager)"
    def draw(self, s):
        if not s.managed: self.note(s.message)
        unmanaged=[i for i in s.interfaces if i.state.startswith("unmanaged")]
        if s.managed and unmanaged and network.unmanaged_reason(unmanaged[0].device)=="netplan":
            self.row("Let NetworkManager manage the network","",lambda:self.take_over(unmanaged[0]),icon="emblem-system-symbolic",fallback="⚙",ident="netplan",
                     detail="netplan gives the network to systemd-networkd (as Ubuntu Server does), so it can only be shown here. "
                            "Saved Wi-Fi networks and addresses set by hand are kept.")
        self.section("ETHERNET")
        wired=s.of_kind("ethernet")
        if not wired: self.note("No Ethernet port was found.")
        for i in wired: self.ethernet_row(i,s.managed)
        self.section("WI-FI")
        wireless=s.of_kind("wifi")
        if s.iwd: wireless=[i for i in wireless if i.device in s.iwd_devices] or wireless   # not an access point's interface
        if not wireless: self.note("No Wi-Fi adapter was found."); return
        if s.iwd: self.draw_iwd(s,wireless); return
        if not s.managed or wireless[0].state.startswith("unmanaged"):
            for i in wireless: self.ethernet_row(i,s.managed)
            return
        self.row("Wi-Fi",_on_off(s.wifi_enabled),lambda:self.act(lambda:network.set_wifi(not s.wifi_enabled),
                 "Switching Wi-Fi "+("off…" if s.wifi_enabled else "on…"),"Wi-Fi"),icon="network-wireless-symbolic",fallback="📶",ident="wifi")
        if not s.wifi_enabled: return
        device=wireless[0]
        if device.connected: self.ip_row(device)
        self.row("Search for networks","Searching…" if self.scanning else "",None if self.scanning else self.scan,icon="edit-find-symbolic",fallback="⌕",
                 detail="Looks for Wi-Fi networks nearby. The list is not searched again until you choose this.",ident="scan")
        if not s.networks: self.note("Looking…" if self.scanning else "No networks listed. Choose Search for networks to look for them.")
        for n in s.networks: self.wifi_row(n,device)

    def draw_iwd(self, s, wireless):
        """Wi-Fi run by iwd (no NetworkManager): its adapter, then the networks it sees, to join or forget."""
        for i in wireless: self.ethernet_row(i,False)
        if not s.wifi_enabled: self.note("The Wi-Fi adapter is off (iwd). Turn it on with: iwctl device "+wireless[0].device+" set-property Powered on"); return
        self.row("Search for networks","Searching…" if self.scanning else "",None if self.scanning else self.scan,icon="edit-find-symbolic",fallback="⌕",
                 detail="Looks for Wi-Fi networks nearby. iwd also looks now and then by itself.",ident="scan")
        if not s.networks: self.note("Looking…" if self.scanning else "No networks listed. Choose Search for networks to look for them.")
        device=next((i for i in wireless if i.device==s.iwd_device),wireless[0])
        for n in s.networks: self.wifi_row(n,device)

    def iwd_do(self, work, args, label, status):
        """A change iwd may let this user make (work() -> problem); if it refuses, the same as root (args)."""
        def tried(problem):
            self.busy=False; self.set_status("")
            if problem==network.iwd.DENIED: self.iwd_root(args,label,status); return
            if problem: self.win.notice("Wi-Fi",problem)
            self.refresh(quiet=True)
        self.set_status(status); self.busy=True
        in_background(work,tried,lambda exc:tried(str(exc)))

    def iwd_root(self, args, label, status, cleanup=""):
        """One of control_iwd's root commands (it asks for the password), then the page is read again."""
        self.set_status(status); lines=[]
        def done(code,tail):
            self.set_status("")
            if cleanup:
                try: os.unlink(cleanup)
                except OSError: pass
            if code: self.win.notice("Wi-Fi",("\n".join(lines[-4:]) or tail or f"{label} did not work.").strip())
            self.refresh(quiet=True)
        self.win.run_as_root(network.iwd.root_argv(*args),label,lines.append,done)

    def plain_ip_row(self, i):
        """Without NetworkManager: whether DHCP gave the address, with a warning when it was set by hand."""
        if not i.addresses: return
        self.row(f"IP settings ({i.device})","Automatic (DHCP)" if i.dynamic else "Set by hand",None,ident=f"ip:{i.device}",
                 detail={"networkd":"Set up by systemd-networkd","dhcpcd":"Set up by dhcpcd","iwd":"Set up by iwd"}.get(i.set_by,""))
        if not i.dynamic: self.note(network.hand_set_note(i),"error")

    @staticmethod
    def _details(i):
        return " · ".join(x for x in (", ".join(i.addresses),f"Gateway {i.gateway}" if i.gateway else "",
                                       f"DNS {', '.join(i.dns)}" if i.dns else "",f"MAC {i.mac}" if i.mac else "") if x)
    @staticmethod
    def _state_text(i):
        if i.connected: return "Connected"
        if i.kind=="wifi" and not i.state.startswith("unmanaged"): return "Not connected"
        return {"unavailable":"No cable","disconnected":"Not connected","unmanaged":"Not managed"}.get(i.state.split(" ")[0],i.state.capitalize() or "Unknown")

    def ethernet_row(self, i, managed):
        go=None; extras=[]; detail=self._details(i)
        if managed and i.state.startswith("unmanaged"):
            go=lambda i=i:self.take_over(i)
            detail=" · ".join(x for x in ("Not set up through NetworkManager, so it cannot be changed here. Choose it to let Settings manage it",detail) if x)
        elif managed and i.state not in ("unavailable",):
            if i.connected:
                go=lambda i=i:self.win.confirm(f"Disconnect {i.device}?",f"Disconnect {i.connection or i.device}? Anything using the network will lose it until you connect again.",
                                               "Disconnect",lambda:self.act(lambda:network.disconnect_device(i.device),f"Disconnecting {i.device}…","Ethernet"))
            else: go=lambda i=i:self.act(lambda:network.connect_device(i.device),f"Connecting {i.device}…","Ethernet")
        label=("Ethernet" if i.kind=="ethernet" else "Wi-Fi")+f" ({i.device})"
        self.row(label,self._state_text(i),go,detail=detail,icon="network-wired-symbolic" if i.kind=="ethernet" else "network-wireless-symbolic",
                 fallback="⇄",ident=f"if:{i.device}",extras=extras,value_css="state-on" if i.connected else "setting-value")
        if managed: self.ip_row(i)
        elif i.connected: self.plain_ip_row(i)

    def take_over(self, i):
        """Hand a port that NetworkManager leaves alone to it (control_network: with ifupdown, a minimal Debian
        install's network, ifupdown is uninstalled)."""
        reason=network.unmanaged_reason(i.device); kind="Wi-Fi" if i.kind=="wifi" else "Ethernet"
        if reason=="ifupdown":
            text=(f"{i.device} is set up by ifupdown (/etc/network/interfaces), as a minimal Debian install does, and NetworkManager (which "
                  "Settings uses) will not touch it. Settings can hand the network to NetworkManager: ifupdown is uninstalled, /etc/network "
                  "is removed and NetworkManager is restarted, so it manages every Ethernet port and Wi-Fi adapter from then on.\n\n"
                  "The network drops for a moment. Ethernet connects again by itself, but you have to choose your Wi-Fi network and enter "
                  "its password again here, and any IP address, gateway or DNS servers set by hand have to be set again. It asks for your password.")
            title,ok="Hand the network to NetworkManager?","Hand it over"
        elif reason=="netplan":
            text=(f"{i.device} is set up by netplan (/etc/netplan), which gives it to systemd-networkd, as Ubuntu Server does, so "
                  "NetworkManager (which Settings uses) leaves it alone. Settings can set netplan to use NetworkManager instead: one "
                  "file is added to /etc/netplan (the others are kept, and backed up in /var/backups) and the settings are applied, "
                  "so NetworkManager manages every Ethernet port and Wi-Fi adapter from then on.\n\n"
                  "Your saved Wi-Fi networks and any IP address, gateway or DNS servers set by hand are kept: netplan hands them to "
                  "NetworkManager. The network drops for a moment while it switches. It asks for your password.")
            title,ok="Hand the network to NetworkManager?","Hand it over"
        else:
            text=(f"NetworkManager is set to leave {i.device} alone. Settings can ask it to manage it. "
                  "If that does not last after a restart, a file in /etc/NetworkManager/conf.d lists it under unmanaged-devices.")
            title,ok=f"Manage {i.device} here?","Manage it"
        def go():
            self.set_status(f"Handing {i.device} to NetworkManager…"); lines=[]
            def done(code,tail):
                self.set_status("")
                if code: self.win.notice(kind,("\n".join(lines[-6:]) or tail or "It did not work.").strip())
                else: self.win.notice(kind,"NetworkManager manages the network now."+(" Choose your Wi-Fi network to connect again."
                                      if any(w.kind=="wifi" for w in self.state.interfaces) and reason=="ifupdown" else ""))
                self.refresh(quiet=True)
            self.win.run_as_root(network.take_over_argv(i.device,reason),f"Handing {i.device} to NetworkManager",lines.append,done)
        self.win.confirm(title,text,ok,go,danger=reason in ("ifupdown","netplan"))

    def ip_row(self, i):
        """IP address, default gateway and DNS servers of the interface's connection: from DHCP, or set by hand."""
        if not i.connection_uuid: return
        value="Automatic (DHCP)" if i.method!="manual" else "Fixed"+(f": {i.addresses[0].split('/')[0]}" if i.addresses else "")
        self.row(f"IP settings ({i.device})",value,lambda i=i:self.ip_settings(i),icon="preferences-system-network-symbolic",fallback="⚙",
                 detail="IP address, default gateway and DNS servers, or back to automatic (DHCP)",ident=f"ip:{i.device}")

    def wifi_row(self, n, device):
        detail=f"{network.signal_bars(n.signal)}  {n.signal} %"+(f" · {n.security}" if n.secured else " · Open")
        if n.in_use and device.addresses: detail+=" · "+self._details(device)
        extras=[]; s=self.state
        if s.iwd:   # each change is a root command (it asks for the password)
            iw=network.iwd
            forget=lambda n=n:self.iwd_do(lambda:iw.forget(n.ssid),["forget",n.ssid],f"Forgetting {n.ssid}",f"Forgetting {n.ssid}…")
            disconnect=lambda n=n:self.iwd_do(lambda:iw.disconnect(s.iwd_station),["disconnect",s.iwd_station],f"Disconnecting from {n.ssid}",f"Disconnecting from {n.ssid}…")
            connect=lambda n=n:self.iwd_do(lambda:iw.join(n.ssid),["join",n.ssid],f"Connecting to {n.ssid}",f"Connecting to {n.ssid}…")
        else:
            forget=lambda n=n:self.act(lambda:network.forget(n.saved_uuid),f"Forgetting {n.ssid}…","Wi-Fi")
            disconnect=lambda n=n:self.act(lambda:network.disconnect_device(device.device),f"Disconnecting from {n.ssid}…","Wi-Fi")
            connect=lambda n=n:self.act(lambda:network.activate(n.saved_uuid),f"Connecting to {n.ssid}…",f"Connect to {n.ssid}")
        if n.saved_uuid:
            extras.append(self.button("user-trash-symbolic","✕",f"Forget {n.ssid}",lambda n=n,forget=forget:self.win.confirm(f"Forget {n.ssid}?",
                          f"The saved password and settings for {n.ssid} are removed"+(", and this computer leaves it." if n.in_use else "."),
                          "Forget",forget),danger=True))
        if n.in_use:
            go=lambda n=n:self.win.confirm(f"Disconnect from {n.ssid}?","Anything using the network will lose it until you connect again.","Disconnect",disconnect)
        elif n.saved_uuid: go=connect
        elif n.secured: go=lambda n=n:self.ask_password(n)
        elif s.iwd: go=connect
        else: go=lambda n=n:self.act(lambda:network.join_wifi(n.ssid),f"Connecting to {n.ssid}…",f"Connect to {n.ssid}")
        locked=n.secured
        self.row(n.ssid,"Connected" if n.in_use else "Saved" if n.saved_uuid else "",go,detail=detail,
                 icon="network-wireless-encrypted-symbolic" if locked else "network-wireless-symbolic",fallback="🔒" if locked else "📶",
                 ident=f"wifi:{n.ssid}",extras=extras,value_css="state-on" if n.in_use else "setting-value")

    def ask_password(self, n, error=""):
        def join(password):
            if not password: return
            if self.state.iwd:
                try: secret=network.iwd.password_file(password)
                except (ValueError,OSError) as exc: self.ask_password(n,str(exc)); return
                self.iwd_root(["join",n.ssid,secret],f"Connecting to {n.ssid}",f"Connecting to {n.ssid}…",cleanup=secret); return
            def work():
                problem=network.join_wifi(n.ssid,password)
                if problem!="The password was not accepted.": return problem
                GLib.idle_add(lambda:(self.ask_password(n,"The password was not accepted. Try again."),GLib.SOURCE_REMOVE)[1]); return ""
            self.act(work,f"Connecting to {n.ssid}…",f"Connect to {n.ssid}")
        keeper="iwd saves it (in /var/lib/iwd) for next time. Then Settings asks for your own password, since that needs administrator rights." if self.state.iwd else "NetworkManager saves the password for next time."
        self.win.ask_text(f"Password for {n.ssid}",f"{n.security} network. {keeper}",join,secret=True,ok_label="Connect",error=error)

    def scan(self):
        self.scanning=True; self.redraw(); self.set_status("Searching for networks…")
        def done(state):
            self.scanning=False; self.busy=False; self.set_status("")
            if state is not None: self.state=state
            self.redraw()
        self.busy=True; in_background(lambda:network.read_state(scan=True),done,lambda _e:done(None))

    def ip_settings(self, i):
        uuid,name=i.connection_uuid,i.connection or i.device
        self.set_status("Reading IP settings…")
        in_background(lambda:network.read_ipv4(uuid),lambda s:(self.set_status(""),self.ip_form(uuid,name,s,iface=i)))
    def ip_form(self, uuid, name, s, error="", iface=None):
        again=lambda error="":self.ip_form(uuid,name,s,error,iface)
        def edit(field,title,message):
            def set_value(text): setattr(s,field,text.strip()); again()
            self.win.ask_text(title,message,set_value,getattr(s,field),back=lambda:again())
        def flip():
            nonlocal s
            s=network.Ipv4Settings("auto",s.address,s.gateway,s.dns) if not s.automatic else network.fixed_from(s,iface)
            again()
        rows=[("Get the settings automatically (DHCP)","Yes" if s.automatic else "No, set them here",flip)]
        if not s.automatic:
            rows+=[("IP address",s.address,lambda:edit("address","IP address","With its prefix, for example 192.168.1.20/24 (without one, /24 is used).")),
                   ("Default gateway",s.gateway,lambda:edit("gateway","Default gateway","The router's address, for example 192.168.1.1. Can be left empty.")),
                   ("DNS servers",s.dns,lambda:edit("dns","DNS servers","One or more, separated by commas, for example 1.1.1.1, 9.9.9.9."))]
        def save():
            problem,_args=network.validate_ipv4(s)
            if problem: again(problem); return
            self.win.close_modal()
            self.act(lambda:network.apply_ipv4(uuid,s),f"Applying the IP settings of {name}…","IP settings")
        self.win.form(f"IP settings · {name}",rows,"Save",save,
                      "Automatic (DHCP) asks the router for the address, gateway and DNS servers; choose the first row to switch. "
                      "Saving reconnects, so the connection drops for a moment.",error)

# ====================================================================== Storage
class StoragePage(Page):
    """The drives in the computer and plugged into it (open, close, switch off before unplugging). See control_storage."""
    key="storage"; title="Storage"; icon="drive-harddisk-symbolic"; fallback="🖴"; poll=5
    def read(self): return storage.read_state()
    def summary(self):
        s=self.state
        return f"{len(s.drives)} drive{'s' if len(s.drives)!=1 else ''}" if s else ""
    def draw(self, s):
        self.section("DRIVES")
        if s.message: self.note(s.message,"error")
        if not s.drives: self.note("No drives were found.")
        for d in s.drives: self.drive_rows(d,s)
        if not s.udisks: self.note("Install udisks2 to open and close drives here.","error")
        self.note("Each drive's partitions are listed under it. Mounting a partition makes its files readable, in the folder shown "
                  "under it. Unmount it, or switch the drive off with ⏏, before unplugging it.")

    def drive_rows(self, d, s):
        kind="Inside the computer" if not d.removable else ("USB drive" if d.transport=="usb" else "Removable drive")
        extras=[]
        if d.removable and not d.system and s.udisks:
            extras.append(self.button("media-eject-symbolic","⏏",f"Switch off {d.title} so it can be unplugged",lambda d=d:self.eject(d)))
        self.row(d.title,storage.size_text(d.size),None,detail=kind+(" · holds this system" if d.system else ""),icon="drive-removable-media-symbolic" if d.removable else "drive-harddisk-symbolic",
                 fallback="🖴",ident=f"drive:{d.name}",extras=extras)
        for v in d.volumes:
            if v.fstype=="swap": continue
            space=f"{storage.size_text(v.used)} used, {storage.size_text(v.avail)} free" if v.mounted and (v.used or v.avail) else storage.size_text(v.size)
            where=", ".join(v.mountpoints)
            go=None
            if v.system:   # /, /home, /boot...: always in use, never unmounted from here
                value,detail="Part of the system",f"Always in use · its files are in {where}" if where else "Always in use"
            elif v.mounted:
                value,detail="Mounted",f"Its files are in {where}"
            else:
                value,detail="Not mounted","Mount it to see its files"
            if not v.system and s.udisks and v.fstype not in ("crypto_LUKS","LVM2_member"):
                go=(lambda v=v:self.act(lambda:storage.unmount(v.path),f"Unmounting {v.title}…","Storage")) if v.mounted else \
                   (lambda v=v:self.act(lambda:storage.mount(v.path),f"Mounting {v.title}…","Storage"))
                if not v.mounted: detail="Select to mount it and see its files"
                else: detail+=" · select to unmount"
            detail=" · ".join(x for x in (v.fstype,detail,space) if x)
            self.row(v.title,value,go,detail=detail,ident=f"vol:{v.name}",indent=44,
                     value_css="state-on" if v.mounted and not v.system else "setting-value")

    def eject(self, d):
        def work():
            for v in d.volumes:
                if v.mounted:
                    problem=storage.unmount(v.path)
                    if problem: return problem
            return storage.power_off(d.path)
        self.act(work,f"Switching off {d.title}…","Storage",after=lambda:None)

# ====================================================================== Date and time
class DateTimePage(Page):
    """The time zone, the clock set from the network, and the Quick Menu's 12/24-hour clock."""
    key="datetime"; title="Date and time"; icon="preferences-system-time-symbolic"; fallback="🕓"; poll=20
    def read(self): return timedate.read_state(),ConfigStore().settings["clock_24h"]
    def summary(self):
        return timedate.zone_label(self.state[0].timezone) if self.state else ""
    def draw(self, state):
        s,hours24=state; now=time.time()
        self.section("NOW")
        self.row("Time",timedate.clock_text(now,hours24),None,detail=timedate.date_text(now),icon="preferences-system-time-symbolic",fallback="🕓",ident="dt:now")
        self.section("TIME ZONE")
        admin=not servermode.active()   # server mode: shown, not changed here
        self.row("Time zone",timedate.zone_label(s.timezone),self.choose_zone if admin else None,ident="dt:zone")
        self.note("The time zone is set for the whole computer. It may ask for your password." if admin else SERVER_HIDDEN)
        self.section("NETWORK TIME")
        if s.timedatectl:
            self.row("Set the time from the network",_on_off(s.ntp),self.switch_ntp if admin else None,
                     detail=("Synchronized" if s.synced else "Not synchronized yet") if s.ntp else
                            ("Turn it on to keep the clock right by itself" if s.can_ntp else "No network time service is installed (such as systemd-timesyncd or chrony)"),
                     ident="dt:ntp",value_css="state-on" if s.ntp else "setting-value")
        else: self.row("Set the time from the network","Unknown",None,detail="Needs systemd's timedatectl",ident="dt:ntp")
        self.section("QUICK MENU CLOCK")
        self.row("Clock",'24-hour (14:05)' if hours24 else "12-hour (2:05 PM)",self.choose_clock,ident="dt:clock")
        self.note("How the time at the bottom of the Quick Menu is written.")

    def as_root_if_needed(self, argv, label, status, after=None):
        """timedatectl as the user first (polkit may allow it), then as root when polkit wants a password.
        after() runs when it worked."""
        self.set_status(status); lines=[]
        def finish(code, tail):
            self.set_status("")
            if code: self.win.notice("Date and time",("\n".join(lines[-6:]) or tail or f"{label} did not work.").strip())
            elif after: after()
            self.refresh(quiet=True)
        def first(code, tail):
            if code and (argv[0]!="timedatectl" or privilege.polkit_refused(tail)): self.win.run_as_root(argv,label,lines.append,finish)
            else: finish(code,tail)
        if argv[0]=="timedatectl": StreamedRun(argv,lambda _l:None,first)
        else: self.win.run_as_root(argv,label,lines.append,finish)
    def switch_ntp(self):
        s=self.state[0]
        if not s.ntp and not s.can_ntp:
            self.win.notice("Network time","Install a network time service first, such as systemd-timesyncd (or chrony), with your package manager."); return
        self.focus_after="dt:ntp"
        self.as_root_if_needed(timedate.ntp_argv(not s.ntp),"Network time","Turning network time "+("off…" if s.ntp else "on…"))
    def choose_zone(self):
        s=self.state[0]; zones=timedate.zone_choices(s.zones)
        if not zones: self.win.notice("Time zone","No time zones were found on this computer (/usr/share/zoneinfo is empty)."); return
        def picked(zone):
            if zone==s.timezone or not timedate.valid_zone(zone,s.zones): return
            self.as_root_if_needed(timedate.timezone_argv(zone,s.timedatectl),"Time zone",f"Setting the time zone to {timedate.zone_label(zone)}…")
        self.win.choose_option("Time zone",zones,s.timezone if s.timezone in dict(zones) else None,picked)

    def choose_clock(self):
        def picked(key):
            store=ConfigStore(); store.settings["clock_24h"]=key=="24"; store.save(); tell_tvwcs("reload"); self.refresh(quiet=True)
        self.win.choose_option("Quick Menu clock",[("12","12-hour (2:05 PM)"),("24","24-hour (14:05)")],"24" if self.state[1] else "12",picked)

# ====================================================================== installing what a page needs
def install_feature(page, f, after=None):
    """Install the software a page needs (features.py), asking first; then the page reads again. after() runs once it is
    installed (Apps adds Flathub, say)."""
    def installed():
        tell_tvwcs("reload")
        if after: after()
        page.refresh(quiet=True)
    if features.installed(f): installed(); return
    missing=features.missing_packages(f) or list(features.packages_for(f))
    if not distro.can_install():
        page.win.notice(f.label,f"{f.label} needs {', '.join(f.packages)} (the Debian names). Install them with your package manager.")
        return
    lines=[]
    def done(code, tail):
        page.set_status("")
        if code: page.win.notice(f.label,("\n".join(lines[-6:]) or tail or "The packages could not be installed.").strip()); return
        installed()
    def go():
        page.set_status(f"Installing {', '.join(missing)}…")
        page.win.run_as_root(features.install_argv(missing,f),f"Installing {f.label}",lines.append,done)
    page.win.confirm(f"Install {f.label}?",f"{f.what} It needs {', '.join(missing)}, which will be installed now. It asks for your password.",
                     "Install",go,danger=False)

# ====================================================================== User
class UserPage(Page):
    """This user's account (name, password) and logging in: the login screen in use and the automatic login."""
    key="user"; title="User"; icon="avatar-default-symbolic"; fallback="☺"
    def read(self): return login_ui.read_user()
    def summary(self): return login_ui.role(self.state[0]) if self.state else ""   # "Administrator" or "Standard User", small and grey beside "User"
    def draw(self, state): login_ui.draw_user(self,state)

PAGES=(AppearancePage,UserPage,HotkeysPage,SoundPage,DisplaysPage,PowerPage,BluetoothPage,DateTimePage,UpdatesPage,SystemPage,NetworkPage,StoragePage)
