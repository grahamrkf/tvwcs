"""The TVWCS window: Quick Menu | Applications, remote-friendly navigation and dialogs.
TVWCS's own options are a page of the Settings app (channel 0, or a status panel's settings button)."""
from __future__ import annotations
import sys, threading, types
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs import control_bluetooth, control_network, control_sound, power, quick_status, servermode
from tvwcs.control_datetime import clock_text, short_date_text
from tvwcs.hotkeys import HotkeyCapture, describe, is_navigation
from tvwcs.model import LAUNCH_NEW_WORKSPACE, LAUNCH_SAME, MAIN_TITLE, channel_range, corner_right, corner_top, extract_badge, profile_detail, row_description, search_items, startup_choices
from tvwcs.system_actions import power_menu
from tvwcs.theme import render_css
from tvwcs import cursor
from tvwcs.workspaces import quick_list
from tvwcs.widgets import (KEEP_LTR, NO_ICON, NavGroup, PointerWatch, S, app_icon, child_marker, clear_box, flip_children, glyph, held_modifiers, icon_button, Marquee, mirror, muted_label, scroll_to_show, section_title, usable, use_retro)

NAME_SCROLL_DELAY=3000                   # ms a selected Quick Menu row waits before a name too long to fit scrolls by
CHANNEL_DELAY=1000                       # a full channel number and nothing else for this many ms launches that channel

def pointer_only(*widgets):
    """A click on these buttons does not move the remote's selection onto them: the mouse and the D-pad are
    independent in the Quick Menu and Applications (a clicked ☆ does not get the selection's highlight)."""
    for w in widgets:
        if isinstance(w,Gtk.Button): w.set_focus_on_click(False)

_TYPING_BLOCKED=Gdk.ModifierType.CONTROL_MASK|Gdk.ModifierType.ALT_MASK|Gdk.ModifierType.SUPER_MASK|Gdk.ModifierType.META_MASK

class TVWCSWindow(Gtk.ApplicationWindow):
    """One borderless window holding two panels side by side. The Quick Menu is always there; the
    Applications pane opens beside it, to its right (to its left with the Quick Menu in a right-hand corner).
    The Quick Menu is built for the bottom-left corner. In a right-hand corner GTK lays it out right to left (mirror);
    in a top corner its stacks are put the other way up (flip_children) and ↑/↓ work the other way round."""
    search_folds=False; search_line=None; search_button=None   # the search_icon setting (_build_quick_pane)
    def __init__(self, app):
        super().__init__(application=app,title=MAIN_TITLE)
        self.app=app; self.guide_open=False; self.options_open=False
        self.guide_pane=None; self.options_pane=None; self.guide_scroll=None; self.guide_button=None; self.quick_content=None
        self.apps_title=None; self.apps_subtitle=None
        self._channel_source=0; self._capture_cancel=None
        self._provider=None; self._expanded={"Media","Internet","Games"}; self._guide_scroll=0.0
        self._popovers=0; self._was_active=False; self._capture=None; self._capture_cb=None; self._pin=None
        self._panel_token=0; self._volume_target={}; self._volume_busy=set()
        self.launching=set(); self._launch_slots=[]   # profiles starting now: their buttons show a spinner (set_launching)
        self._reset_nav()
        self.set_decorated(False); self.set_hide_on_close(True); self.set_resizable(True); self.add_css_class("tvwcs-window")
        self.pointer=PointerWatch(self,lambda:cursor.hide_ms(self.app.store.settings))   # hover colours only while the mouse is in use
        key=Gtk.EventControllerKey(); key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed",self._key_pressed); key.connect("key-released",self._key_released); self.add_controller(key)
        self.connect("notify::focus-widget",self._focus_changed); self.connect("notify::is-active",self._active_changed)
        self._build()

    @property
    def right(self): return corner_right(self.app.store.settings.get("quick_corner"))   # the Quick Menu is mirrored
    @property
    def top(self): return corner_top(self.app.store.settings.get("quick_corner"))      # ... and stacked the other way up
    def _mirror(self,widget):
        if widget is not None and self.right: mirror(widget)
    def _flip(self,box):
        if self.top: flip_children(box)
    def _flip_margins(self,widget):
        if self.top:
            t,b=widget.get_margin_top(),widget.get_margin_bottom(); widget.set_margin_top(b); widget.set_margin_bottom(t)
    def guide_hint(self):
        """Where Applications is, for the notes that point to it: ⊞ is in the clock's row, at the far side from the corner."""
        side=("top" if self.top else "bottom")+"-"+("left" if self.right else "right")
        return f"Press {'←' if self.right else '→'} (or ⊞ in the {side} corner of this menu)"

    def _reset_nav(self):
        self._groups={"quick":[],"guide":[],"options":[]}; self._header_group=[]
        self._search_results=[]; self._selected_result=0; self._result_groups=[]; self._result_mains=[]; self._stars={}
        self._modal_groups=[]; self._modal_back=None; self._return_focus=None; self._last_focus={}; self._pin=None; self._chan=None
        self._open_row=None; self._text=None
        self._panel_key=None; self._panel_groups=[]; self._panel_prefer=None; self._panel_busy=False; self._keep_panel=False; self._panel_placeholder=False
        self._descriptions=[]

    # ================================================================== construction
    def _build(self):
        if self.guide_scroll is not None: self._guide_scroll=self.guide_scroll.get_vadjustment().get_value()
        self._reset_nav(); self.guide_pane=None; self.options_pane=None; self.guide_scroll=None
        layout=self.app.layout
        self.set_child(None); self._install_css()
        overlay=Gtk.Overlay(); overlay.add_css_class("tvwcs-root")
        self.panes=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=0)
        self.quick_pane=self._build_quick_pane(layout.quick_width); self.panes.append(self.quick_pane)
        overlay.set_child(self.panes)
        self.modal_layer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.modal_layer.add_css_class("modal-scrim")
        self.modal_reveal=Gtk.Revealer(); self.modal_reveal.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.modal_reveal.set_transition_duration(120)
        self.modal_reveal.set_child(self.modal_layer); self.modal_reveal.set_can_target(False); self.modal_reveal.set_visible(False)
        self.modal_card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(6)); self.modal_card.add_css_class("modal-card")
        self.modal_card.set_halign(Gtk.Align.CENTER); self.modal_card.set_valign(Gtk.Align.CENTER); self.modal_card.set_hexpand(True); self.modal_card.set_vexpand(True)
        self._card_width=min(S(440),max(S(280),layout.quick_width-S(40))); self.modal_card.set_size_request(self._card_width,-1)
        self.modal_layer.append(self.modal_card); overlay.add_overlay(self.modal_reveal)
        self.set_child(overlay)
        self._mirror(self.panes)   # not the dialogs drawn over them: a keyboard or number pad keeps its order
        self.set_panels(self.guide_open,self.options_open); self._refresh_search_results()

    def _install_css(self):
        display=Gdk.Display.get_default()
        if self._provider is None:
            self._provider=Gtk.CssProvider()
            if display: Gtk.StyleContext.add_provider_for_display(display,self._provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings=self.app.store.settings; font=settings.get("retro_font","pixel")
        use_retro(settings.get("style")=="retro",font)   # before the widgets: their icons depend on it
        self._provider.load_from_data(render_css(settings["accent"],self.app.scale_factor,theme=settings.get("theme","dark"),
                                                 style=settings.get("style","modern"),phosphor=settings.get("phosphor","green"),retro_font=font,
                                                 media=settings.get("media_look","jellyfin")).encode("utf-8"))

    def set_panels(self,guide,options=None):
        """Show or hide the Applications pane, built once and kept, so closing and opening it again never disturbs
        scroll positions, open categories or focus. `options` is accepted for older callers but opens nothing."""
        guide=bool(guide)
        self.guide_open=guide; self.options_open=False
        if guide and self.guide_pane is None: self.guide_pane=self._build_guide_pane(); self.panes.append(self.guide_pane); self._mirror(self.guide_pane)
        layout=self.app.layout
        self.quick_pane.set_size_request(layout.quick_width,-1)
        if self.guide_pane is not None: self.guide_pane.set_visible(guide)
        if self.guide_button is not None:
            (self.guide_button.add_css_class if guide else self.guide_button.remove_css_class)("active")
            self.guide_button.set_tooltip_text("Close Applications" if guide else f"Open Applications ({'←' if self.right else '→'})")

    def _build_quick_pane(self,width):
        pane=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0); pane.add_css_class("pane"); pane.set_size_request(width,-1); pane.set_hexpand(False)
        # Desktop mode: "TVWCS" and ✕ close at the top (power and Applications are at the bottom, after the status
        # icons). TV mode has no header: the remote's Back key closes the Quick Menu.
        buttons=[]
        if not self.app.tv:
            header=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10)); header.set_margin_top(S(14)); header.set_margin_start(S(20)); header.set_margin_end(S(20)); header.set_margin_bottom(S(10))
            title=Gtk.Label(label="TVWCS"); title.add_css_class("brand"); title.set_xalign(0); title.set_hexpand(True); header.append(title)
            close_btn=icon_button("window-close-symbolic","✕","Close"); close_btn.add_css_class("close-button"); close_btn.add_css_class("square"); close_btn.connect("clicked",lambda *_:self.app.hide_window()); buttons.append(close_btn)
            controls=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); controls.add_css_class("window-controls")
            for b in buttons: controls.append(b)
            header.append(controls); pane.append(header); self._flip_margins(header)
        else:   # space inside the pane, not a margin outside it, which would show the window's black background above it
            top=Gtk.Box(); top.set_size_request(-1,S(14)); pane.append(top)
        self._header_group=buttons
        # Everything below the header sits at the bottom, nearest the search field: favorites and open applications, the
        # search results, the search field, then the status row. The space left over (on a TV, or with Applications
        # open) is above them. At a desk the window is only as tall as all this (main.fit_quick_menu).
        body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(10)); body.set_margin_start(S(20)); body.set_margin_end(S(20)); body.set_margin_top(S(4)); body.set_margin_bottom(S(10)); body.set_vexpand(True); pane.append(body)
        scroll=Gtk.ScrolledWindow(); scroll.set_vexpand(True); scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC); scroll.set_propagate_natural_height(True); body.append(scroll)
        self._flip_margins(body); toward=Gtk.Align.START if self.top else Gtk.Align.END   # toward the search field
        content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4)); content.set_valign(toward); scroll.set_child(content); self.quick_content=content; self.quick_scroll=scroll
        scroll.get_vadjustment().connect("changed",self._keep_at_bottom)   # what overflows is above: start at the bottom
        self._build_quick_content(content)
        self.results_scroll=Gtk.ScrolledWindow(); self.results_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC); self.results_scroll.set_max_content_height(S(280)); self.results_scroll.set_propagate_natural_height(True); self.results_scroll.set_visible(False)
        self.results_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2)); self.results_box.set_valign(toward); self.results_scroll.set_child(self.results_box); body.append(self.results_scroll)
        self.results_scroll.get_vadjustment().connect("changed",self._keep_at_bottom)
        self.search_entry=Gtk.SearchEntry(); self.search_entry.connect("search-changed",lambda *_:self._refresh_search_results()); self.search_entry.connect("activate",self._activate_search)
        self.search_entry.connect("changed",self._search_typed)
        # On a TV the field is as wide as a channel number, with what to type beside it; it stretches once letters (or
        # one digit too many) show it is a search. At a desk it is one full-width field.
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12)); line.append(self.search_entry)
        self.channel_hint=Gtk.Label(label="Channel number or search"); self.channel_hint.add_css_class("channel-hint")
        self.channel_hint.set_xalign(0); self.channel_hint.set_hexpand(True); self.channel_hint.set_wrap(True); line.append(self.channel_hint)
        body.append(line); self._search_narrow=None; self._shape_search()
        # With the search_icon setting the bar stays folded away until the search icon (in the status row) opens it, or
        # typing anywhere does; it folds again once the selection leaves it empty (_fold_search).
        self.search_line=line; self.search_folds=bool(self.app.store.settings.get("search_icon",False)); line.set_visible(not self.search_folds)
        # what a status icon (or ⏻) unfolds: above the status row, a little indented, like a row's options
        self.status_panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4)); self.status_panel.add_css_class("status-panel"); self.status_panel.set_visible(False)
        self.status_panel.set_margin_start(S(34)); self.status_panel.set_margin_end(S(34)); self.status_panel.set_margin_bottom(S(4)); pane.append(self.status_panel)
        self._flip_margins(self.status_panel)
        pane.append(self._build_status_bar())
        self._flip(body); self._flip(pane)   # in a top corner: the status rows at the top, then the search field, then the lists
        return pane

    def quick_height(self,width):
        """How tall the Quick Menu needs to be, at `width`, to show everything in it without scrolling, or a card
        drawn over it (the on-screen keyboard), whichever is taller."""
        height=self.quick_pane.measure(Gtk.Orientation.VERTICAL,width)[1]
        if self.modal_reveal.get_visible():
            card=self.modal_card.measure(Gtk.Orientation.VERTICAL,self._card_width)[1]
            height=max(height,card+2*S(24))   # with a little of the scrim around it
        return height

    def _shape_search(self):
        """TV: a narrow channel field with its hint while the text could still be a channel number (empty, or up to
        the channel_digits setting's digits); the full width otherwise. Desktop: always the full width, without the hint."""
        e=self.search_entry; q=e.get_text(); tv=self.app.tv; digits=self.app.store.channel_digits()
        narrow=tv and (q=="" or (q.isdigit() and len(q)<=digits))
        if getattr(self,"_search_narrow",None)==(narrow,digits): return
        self._search_narrow=(narrow,digits)
        e.set_hexpand(not narrow); e.set_halign(Gtk.Align.START if narrow else Gtk.Align.FILL)
        # the digits, + a little for the field's padding (the theme hides the ✕ while narrow)
        e.set_width_chars(digits+1 if narrow else -1); e.set_max_width_chars(digits+1 if narrow else -1)
        (e.add_css_class if narrow else e.remove_css_class)("channel-entry")
        (e.add_css_class if tv else e.remove_css_class)("tv-search")   # the app buttons' fill, no magnifier
        e.set_placeholder_text("_"*digits if narrow else "Search, or type a channel number")
        self.channel_hint.set_visible(narrow)

    # ---------------------------------------------------------- the bottom: clock, status icons and power
    STATUS_KEYS=("updates","network","volume","bluetooth","battery")
    def _build_status_bar(self):
        """Two rows. Above: icons for waiting updates, the network, the volume, Bluetooth and the battery (with its
        charge, and whether it is charging; only on a computer with a battery), and ⏻ at the far right. Below: the time
        and date, and ⊞ Applications in the corner. Each row keeps its width whatever the icons show (an update count).
        The clock and the updates icon open their page of the Settings app; the others, and ⏻, unfold a panel above the
        rows (toggle_status_panel).
        The icons are refreshed by main.StatusWatcher."""
        bar=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2)); bar.add_css_class("quick-status")
        icons=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); bar.append(icons)
        self._status_buttons={}; self.search_button=None
        if self.search_folds:   # first, nearest the corner: it stays put while the others come and go
            b=Gtk.Button(); b.add_css_class("square"); b.add_css_class("status-icon"); b.set_valign(Gtk.Align.CENTER)
            b.set_child(glyph("edit-find-symbolic","⌕",22)); b.set_tooltip_text("Search, or type a channel number")
            b.connect("clicked",lambda *_:self.toggle_search()); icons.append(b); self.search_button=b
        for key in self.STATUS_KEYS:
            b=Gtk.Button(); b.add_css_class("square"); b.add_css_class("status-icon"); b.set_valign(Gtk.Align.CENTER)
            if key=="updates": b.connect("clicked",lambda *_:self.app.open_settings("updates"))
            else: b.connect("clicked",lambda _b,k=key:self.toggle_status_panel(k))
            icons.append(b); self._status_buttons[key]=b
        gap=Gtk.Box(); gap.set_hexpand(True); icons.append(gap)
        power=Gtk.Button(); power.set_child(glyph("system-shutdown-symbolic","⏻",22)); power.set_tooltip_text("Lock, sleep, reboot or shut down"); power.add_css_class("square"); power.add_css_class("status-icon"); power.set_valign(Gtk.Align.CENTER)
        power.connect("clicked",lambda *_:self.toggle_status_panel("power")); icons.append(power); self._status_buttons["power"]=power
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); bar.append(line)
        clock=Gtk.Button(); clock.add_css_class("clock-button"); clock.set_hexpand(True); clock.set_tooltip_text("Date and time")
        # one line: the time, then the date to its right, on the same baseline
        text=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10)); text.set_halign(Gtk.Align.START)
        self.clock_time=Gtk.Label(); self.clock_time.add_css_class("clock-time"); self.clock_time.set_valign(Gtk.Align.BASELINE); text.append(self.clock_time)
        self.clock_date=Gtk.Label(); self.clock_date.add_css_class("clock-date"); self.clock_date.set_valign(Gtk.Align.BASELINE); text.append(self.clock_date)
        clock.set_child(text); clock.connect("clicked",lambda *_:self.app.open_settings("datetime")); line.append(clock)
        # ⚙ beside ⊞: the Settings app (channel 0), one click from anywhere
        gear=Gtk.Button(); gear.set_child(glyph("emblem-system-symbolic","⚙",22)); gear.add_css_class("square"); gear.add_css_class("status-icon"); gear.set_valign(Gtk.Align.CENTER)
        gear.set_tooltip_text("Settings"); gear.connect("clicked",lambda *_:self.app.open_settings()); line.append(gear); self.settings_button=gear
        guide=Gtk.Button(); guide.set_child(glyph("view-grid-symbolic","⊞",22)); guide.add_css_class("square"); guide.add_css_class("status-icon"); guide.set_valign(Gtk.Align.CENTER)
        # ⊞ is on screen when it is clicked: open or close Applications here and now (show_mode would first ask the
        # window manager where TVWCS is, and an answer from before the click showed it again instead of closing it)
        guide.connect("clicked",lambda *_:self.app.show_panels(not self.guide_open,False,focus="guide" if not self.guide_open else "quick"))
        line.append(guide); self.guide_button=guide
        self._status_group=NavGroup(([self.search_button] if self.search_button else [])+list(self._status_buttons.values())); self._clock_group=NavGroup([clock,gear,guide])
        pointer_only(*self._status_group,*self._clock_group)
        self._status_shown=None; self.tick_clock(); self.show_status(self.app.status)
        self._flip(bar)   # the clock's row is nearest the corner
        return bar
    def tick_clock(self):
        if getattr(self,"clock_time",None) is None: return
        t=clock_text(None,self.app.store.settings.get("clock_24h",False)); d=short_date_text()
        if self.clock_time.get_text()!=t: self.clock_time.set_text(t)
        if self.clock_date.get_text()!=d: self.clock_date.set_text(d)
    def show_status(self,status):
        buttons=getattr(self,"_status_buttons",None)
        if not buttons or status==self._status_shown: return
        self._status_shown=status
        looks={"network":quick_status.network_icon(status),"volume":quick_status.volume_icon(status),
               "bluetooth":quick_status.bluetooth_icon(status),"updates":quick_status.updates_icon(status),
               "battery":quick_status.battery_icon(status)}
        shown={"network":True,"volume":status.volume is not None,
               "bluetooth":bool(status.bluetooth),"updates":quick_status.updates_shown(status),
               "battery":status.battery is not None}
        for key,(icon,fallback,tip) in looks.items():
            b=buttons[key]
            if key in ("updates","battery"):   # an icon and a number: how many updates, the battery's percent
                child=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); child.set_halign(Gtk.Align.CENTER)
                child.append(glyph(icon,fallback,22))
                n=Gtk.Label(label=str(status.updates) if key=="updates" else f"{status.battery or 0}%"); n.add_css_class("status-count")
                if key!="updates" or status.updates: child.append(n)   # a restart alone: just its icon
                b.add_css_class("status-wide")
            else: child=glyph(icon,fallback,22)
            if key=="bluetooth": (b.add_css_class if status.bluetooth=="off" else b.remove_css_class)("status-off")
            b.set_child(child); b.set_tooltip_text(tip); b.set_visible(shown[key]); self._mirror(child)
            if not shown[key] and self._panel_key==key: self._close_open()

    # ---------------------------------------------------------- status panels: what a status icon (or ⏻) unfolds
    # A panel opens above the status row, like a row's options. One is open at a time; it folds away once the selection
    # leaves it (and its icon), with Back, or with its icon again. Details that take a command to read (network,
    # Bluetooth, sound) are read on a worker thread: the panel says "Loading…" until they arrive, and the selection
    # moves into it then, if it is still on the icon.
    def toggle_status_panel(self,key):
        opener=self._status_buttons[key]
        if self._panel_key==key: self._close_open(); opener.grab_focus(); return
        self._close_open()
        self._panel_key=key; self._panel_token+=1; opener.add_css_class("active")
        self._open_row=types.SimpleNamespace(opener=opener,expanded=lambda k=key:self._panel_key==k,collapse=self._collapse_status_panel,
                                             owns=lambda w,o=opener:w is o or self._contains(self.status_panel,w))
        self.status_panel.set_visible(True)
        getattr(self,f"_panel_{key}")()
    def _collapse_status_panel(self):
        key=self._panel_key; self._panel_key=None; self._panel_token+=1; self._panel_groups=[]; self._panel_placeholder=False
        b=self._status_buttons.get(key) if key else None
        if b is not None: b.remove_css_class("active")
        self.status_panel.set_visible(False); clear_box(self.status_panel); self.app.fit_quick_menu()
    def _fill_panel(self,build):
        """(Re)draw the open panel: build() adds its lines (_panel_line). A line that was selected stays selected; with
        the selection still on the panel's icon, it moves to the line build() prefers (_panel_prefer), else the last."""
        focused=self.get_focus(); at=None; placeholder=self._panel_placeholder; self._panel_placeholder=False
        for g in self._panel_groups if not placeholder else ():   # "Loading…" moved the selection in; the real lines choose again
            for k,w in enumerate(g):
                if w is focused: at=(g.ident,k)
        self._keep_panel=True
        try:
            clear_box(self.status_panel); self._panel_groups=[]; self._panel_prefer=None; build()
            self._flip(self.status_panel); self._mirror(self.status_panel)   # its first line nearest its icon, as below it
        finally: self._keep_panel=False
        groups=self._panel_groups; target=None
        if at is not None:
            g=next((g for g in groups if g.ident==at[0]),None)
            if g is not None: target=g[min(at[1],len(g)-1)]
        opener=self._status_buttons.get(self._panel_key)
        if target is None and groups and (placeholder or at is not None or focused is None or focused is opener):
            g=next((g for g in groups if g.ident==self._panel_prefer),groups[-1]); target=self._landing(g) or g[0]
        if target is not None: target.grab_focus()
        self.app.fit_quick_menu()
    def _panel_line(self,widget,ident=None,*focusable,column=False):
        """Add a line to the open panel; its buttons (focusable) are one navigation row, known as `ident` across redraws."""
        self.status_panel.append(widget)
        if focusable:
            pointer_only(*focusable); g=NavGroup(list(focusable)); g.ident=ident; g.column=column; self._panel_groups.append(g)
        return widget
    def _panel_text(self,text,css="muted"):
        l=Gtk.Label(label=text); l.set_xalign(0); l.set_wrap(True); l.add_css_class(css); return self._panel_line(l)
    def _panel_button(self,ident,icon,fallback,label,action,danger=False):
        b=self.dialog_button(icon,fallback,label); b.add_css_class("menu-item")
        if danger: b.add_css_class("danger")
        b.connect("clicked",lambda *_:action()); self._panel_line(b,ident,b); return b
    def _panel_settings(self,page,label):
        if page=="network" and servermode.active(): return   # turned off in server mode
        self._panel_button("settings","emblem-system-symbolic","⚙",label,lambda:self.app.open_settings(page))
    def _panel_read(self,read,build):
        """Read in the background, then draw build(result) if the same panel is still open (result is None when the read failed)."""
        token=self._panel_token
        def work():
            try: result=read()
            except Exception as exc:   # a panel must never break the menu
                print(f"Cannot read the status details: {exc}",file=sys.stderr); result=None
            GLib.idle_add(lambda:(token==self._panel_token and self._fill_panel(lambda:build(result)),GLib.SOURCE_REMOVE)[1])
        threading.Thread(target=work,daemon=True).start()
    def _panel_do(self,work,reload):
        """Run a change (Wi-Fi off, disconnect a device, ...) in the background: work() -> "" when done, else why not.
        Then the panel is read again and the status icons refreshed."""
        if self._panel_busy: return
        self._panel_busy=True; token=self._panel_token
        def run():
            try: problem=work() or ""
            except Exception as exc: problem=str(exc)
            GLib.idle_add(lambda:(done(problem),GLib.SOURCE_REMOVE)[1])
        def done(problem):
            self._panel_busy=False; self.app.watch.read_now()
            if problem: self.show_message(problem,"That didn't work")
            if token==self._panel_token: reload()
        threading.Thread(target=run,daemon=True).start()
    def _panel_loading(self,page,label):
        def build():
            self._panel_text("Loading…"); self._panel_settings(page,label)
        self._fill_panel(build); self._panel_placeholder=True

    def _panel_power(self):
        """Lock, Sleep, Reboot, Shut down and (with a login screen) Log out, the first nearest ⏻."""
        def run(action):
            self._close_open(); self._status_buttons["power"].grab_focus(); self.system_action(action)
        def build():
            for action in reversed(power_menu()):
                self._panel_button(action.id,action.icon,action.fallback,action.label,lambda a=action:run(a),danger=bool(action.confirm))
        self._fill_panel(build)

    def _panel_network(self):
        """The connection in use (Wi-Fi network and signal, or the wired connection, with its address), Wi-Fi on or off,
        and Network settings."""
        self._panel_loading("network","Network settings")
        def build(state):
            if state is None: self._panel_text("The network details could not be read.")
            else:
                connected=[i for i in state.interfaces if i.connected]
                if not connected: self._panel_text("Not connected to a network","panel-title")
                for i in connected:
                    net=next((n for n in state.networks if n.in_use),None) if i.kind=="wifi" else None
                    if i.kind=="wifi": head=f"Wi-Fi · {net.ssid if net else i.connection or i.device}"
                    else: head=f"Wired · {i.connection or i.device}"
                    self._panel_text(head,"panel-title")
                    details=[f"Signal {net.signal}%" if net else "",", ".join(a.split("/")[0] for a in i.addresses),
                             f"gateway {i.gateway}" if i.gateway else "",i.device]
                    self._panel_text(" · ".join(d for d in details if d))
                if state.message: self._panel_text(state.message)
                if state.managed and state.of_kind("wifi"):
                    on=state.wifi_enabled
                    if on: self._panel_button("scan","view-refresh-symbolic","⟳","Find Wi-Fi networks",self._panel_wifi_scan)
                    self._panel_button("wifi","network-wireless-symbolic" if not on else "network-wireless-offline-symbolic","⌔",
                                       "Turn Wi-Fi off" if on else "Turn Wi-Fi on",lambda:self._panel_do(lambda:control_network.set_wifi(not on),self._panel_network))
                    self._panel_prefer="scan" if on else "wifi"
            self._panel_settings("network","Network settings")
        self._panel_read(control_network.read_details,build)

    def _panel_wifi_scan(self):
        """The Wi-Fi networks in range, strongest first: choose one to connect (a password is asked when it needs one)."""
        self._fill_panel(lambda:(self._panel_text("Looking for Wi-Fi networks…"),self._panel_settings("network","Network settings")))
        self._panel_placeholder=True
        def build(state):
            networks=[n for n in (state.networks if state else []) if n.ssid and not n.in_use]
            seen=set(); networks=[n for n in sorted(networks,key=lambda n:-n.signal) if not (n.ssid in seen or seen.add(n.ssid))]
            self._panel_text("Wi-Fi networks" if networks else "No other Wi-Fi networks were found","panel-title")
            for n in networks[:12]:
                label=f"{n.ssid}  ·  {n.signal}%"+("  🔒" if n.secured and not n.saved_uuid else "")
                self._panel_button(f"net:{n.ssid}","network-wireless-symbolic","⌔",label,lambda n=n:self._join_wifi(n))
                if self._panel_prefer is None: self._panel_prefer=f"net:{n.ssid}"
            self._panel_button("back","go-previous-symbolic","←","Back",self._panel_network)
            self._panel_settings("network","Network settings")
        self._panel_read(lambda:control_network.read_state(scan=True),build)
    def _join_wifi(self,n,error=""):
        if n.saved_uuid: self._panel_do(lambda:control_network.activate(n.saved_uuid),self._panel_network); return
        if not n.secured: self._panel_do(lambda:control_network.join_wifi(n.ssid),self._panel_network); return
        def got(password):
            if password: self._panel_do(lambda:control_network.join_wifi(n.ssid,password),self._panel_network)
        self.ask_text(f"Password for {n.ssid}",got,"",f"{n.security} network. NetworkManager saves the password for next time.",secret=True,ok_label="Connect",error=error)

    def _panel_bluetooth(self):
        """The devices that are connected, each with Disconnect; Bluetooth on or off; Bluetooth settings."""
        self._panel_loading("bluetooth","Bluetooth settings")
        def build(state):
            if state is None or not state.available: self._panel_text(state.message if state else "The Bluetooth details could not be read.")
            else:
                if not state.powered: self._panel_text("Bluetooth is off"+(" (blocked, as in airplane mode)" if state.blocked else ""),"panel-title")
                else:
                    connected=[d for d in state.devices if d.connected]
                    self._panel_text("Connected" if connected else "No devices are connected","panel-title")
                    for d in connected:
                        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10))
                        icon,fallback,_kind=d.kind; g=glyph(icon,fallback,22); g.set_size_request(S(28),-1); line.append(g)
                        name=Gtk.Label(label=d.name+(f" · {d.battery}%" if d.battery is not None else "")); name.set_xalign(0); name.set_hexpand(True); name.set_ellipsize(3); line.append(name)
                        off=Gtk.Button(label="Disconnect"); off.connect("clicked",lambda _b,a=d.address:self._panel_do(lambda:control_bluetooth.disconnect(a),self._panel_bluetooth))
                        line.append(off); self._panel_line(line,f"device:{d.address}",off)
                        if self._panel_prefer is None: self._panel_prefer=f"device:{d.address}"
                on=state.powered
                if on: self._panel_button("scan","view-refresh-symbolic","⟳","Find Bluetooth devices",self._panel_bluetooth_scan)
                self._panel_button("power","bluetooth-disabled-symbolic" if on else "bluetooth-active-symbolic","ᛒ",
                                   "Turn Bluetooth off" if on else "Turn Bluetooth on",lambda:self._panel_do(lambda:control_bluetooth.set_powered(not on),self._panel_bluetooth))
                if self._panel_prefer is None: self._panel_prefer="power"
            self._panel_settings("bluetooth","Bluetooth settings")
        self._panel_read(control_bluetooth.read_state,build)

    def _panel_bluetooth_scan(self):
        """Look for devices for a few seconds, then list the ones not connected: choose one to pair (or connect)."""
        self._fill_panel(lambda:(self._panel_text("Looking for Bluetooth devices… Put the device in pairing mode."),self._panel_settings("bluetooth","Bluetooth settings")))
        self._panel_placeholder=True
        def read():
            control_bluetooth.scan(8); return control_bluetooth.read_state()
        def build(state):
            found=[d for d in (state.devices if state and state.available else []) if not d.connected]
            self._panel_text("Bluetooth devices" if found else "No devices were found","panel-title")
            for d in found[:12]:
                icon,fallback,_kind=d.kind
                self._panel_button(f"dev:{d.address}",icon,fallback,("Connect " if d.paired else "Pair ")+d.name,
                                   lambda d=d:self._panel_do(lambda:control_bluetooth.connect(d.address) if d.paired else control_bluetooth.pair(d.address),self._panel_bluetooth))
                if self._panel_prefer is None: self._panel_prefer=f"dev:{d.address}"
            self._panel_button("back","go-previous-symbolic","←","Back",self._panel_bluetooth)
            self._panel_settings("bluetooth","Bluetooth settings")
        self._panel_read(read,build)

    def _panel_battery(self):
        """The charge, and about how long until the battery is empty (or charged)."""
        def build():
            b=power.read_battery(); seconds,_direction=power.battery_time()
            if not b.present: self._panel_text("No battery was found.")
            else:
                self._panel_text(f"Battery {b.percent}%"+(", on battery" if b.on_battery else ", charging" if b.charging else ", plugged in"),"panel-title")
                if b.on_battery: text=f"About {power.time_text(seconds)} left" if seconds else "Working out how long it will last…"
                elif b.charging: text=f"About {power.time_text(seconds)} until it is fully charged" if seconds else "Working out how long it will take to charge…"
                else: text="Fully charged" if b.percent>=95 else "Not charging"
                self._panel_text(text)
            self._panel_settings("power","Power settings")
        self._fill_panel(build)

    def _panel_volume(self):
        """The output and the input: mute, − and + (and a slider for the mouse); Sound settings."""
        self._panel_loading("sound","Sound settings")
        def build(state):
            if state is None or not state.available: self._panel_text(state.message if state else "The sound details could not be read.")
            else:
                for kind,device in (("Output",state.output()),("Input",state.input())):
                    if device is not None: self._volume_line(kind,device)
                if not state.outputs: self._panel_text("No sound output was found.")
            self._panel_settings("sound","Sound settings")
        self._panel_read(control_sound.read_state,build)
    def _volume_line(self,kind,device):
        self._panel_text(f"{kind} · {device.label}","panel-title")
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4))
        output=kind=="Output"
        def mute_look():
            if output: icon,fallback=("audio-volume-muted-symbolic","🔇") if device.muted else ("audio-volume-high-symbolic","🔊")
            else: icon,fallback=("microphone-sensitivity-muted-symbolic","🎙") if device.muted else ("audio-input-microphone-symbolic","🎙")
            mute.set_child(glyph(icon,fallback,22)); mute.set_tooltip_text(f"Unmute the {kind.lower()}" if device.muted else f"Mute the {kind.lower()}")
            (mute.add_css_class if device.muted else mute.remove_css_class)("active")
        mute=Gtk.Button(); mute.add_css_class("square"); mute_look()
        def toggle_mute():
            device.muted=not device.muted; mute_look(); muted=device.muted
            def work():
                result=control_sound.set_muted(device,muted); return "" if result.ok else result.message
            self._panel_do(work,lambda:None)
        mute.connect("clicked",lambda *_:toggle_mute())
        less=Gtk.Button(label="−"); less.add_css_class("square"); less.set_tooltip_text(f"{kind} volume down")
        more=Gtk.Button(label="+"); more.add_css_class("square"); more.set_tooltip_text(f"{kind} volume up")
        boost=bool(self.app.store.settings.get("audio_boost"))
        slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,control_sound.top(boost),1); slider.set_draw_value(False); slider.set_hexpand(True); slider.set_focusable(False); slider.add_css_class(KEEP_LTR)
        percent=Gtk.Label(); percent.set_width_chars(5); percent.set_xalign(1); percent.add_css_class("status-count")
        def show(value):
            percent.set_text(f"{value}%"); slider.set_value(min(control_sound.top(boost),value))
        def apply(value):
            device.volume=max(0,min(control_sound.top(boost),int(value))); show(device.volume)
            self._volume_target[device.name]=device.volume
            if device.name not in self._volume_busy: self._send_volume(device)
        less.connect("clicked",lambda *_:apply(control_sound.stepped(device.volume,-1,boost)))
        more.connect("clicked",lambda *_:apply(control_sound.stepped(device.volume,1,boost)))
        slider.connect("change-value",lambda _s,_scroll,value:(apply(round(value)),False)[1])
        show(device.volume)
        for w in (mute,less,slider,more,percent): line.append(w)
        self._panel_line(line,kind,mute,less,more,column=True)
        if self._panel_prefer is None: self._panel_prefer=kind
    def _send_volume(self,device):
        """Set the volume on a worker thread, one change at a time per device: presses that come quicker than pactl
        answers are merged into the last one."""
        self._volume_busy.add(device.name); target=self._volume_target[device.name]
        def run():
            try: control_sound.set_volume(device,target,bool(self.app.store.settings.get("audio_boost")))
            except Exception: pass
            GLib.idle_add(lambda:(done(),GLib.SOURCE_REMOVE)[1])
        def done():
            self._volume_busy.discard(device.name)
            if self._volume_target.get(device.name)!=target: self._send_volume(device)
            else: self.app.watch.read_now()
        threading.Thread(target=run,daemon=True).start()

    def _build_quick_content(self,content):
        """One list: favorites in their order, then the other open applications (nearest the search field), with no
        headings. An open favorite shows once, as the open application (with ★). With neither, a note says where the
        installed applications are."""
        entries=self.app.workspace_entries(); outputs=self.app.wm.outputs()
        opened=self.app.open_favorites([w for e in entries for w in e.windows])
        # an app that is uninstalled stays a favorite, hidden, and comes back if it is installed again
        installed=self.app.catalogue.by_id()
        favorites=[p for p in self.app.store.favorites() if p.desktop_id in installed]
        rows,self._starred=quick_list(favorites,entries,opened)
        for kind,item in rows:
            if kind=="favorite": content.append(self._favorite_row(item))
            else: content.append(self._window_row(item.windows[0]) if len(item.windows)==1 else self._workspace_row(item,outputs))
        if not self.app.wm.available: content.append(muted_label("TVWCS can't see open apps here: it needs the sway window manager."))
        if not rows:
            content.append(muted_label(f"Nothing is open and there are no favorites yet. {self.guide_hint()} to see your installed applications."))
        self._flip(content); self._mirror(content)   # the open applications stay nearest the search field
    def _keep_at_bottom(self,adj):
        """The Quick Menu's lists grow upwards from the search field: when they overflow, show their bottom (in a top
        corner they grow downwards, and show their top). "changed"
        comes while GTK is sizing the list, when a new value would not move it yet, so it is set just after. Not while
        a row's options are open: they unfold upwards, and the list scrolls to show them instead."""
        if self._open_row is not None and getattr(self._open_row,"opener",None) is None: return
        GLib.idle_add(lambda:(adj.set_value(adj.get_lower() if self.top else adj.get_upper()-adj.get_page_size()),GLib.SOURCE_REMOVE)[1])

    # ---------------------------------------------------------- Quick Menu rows
    # Each row is the application (or workspace) with one ⋯ button before it. ⋯, ← on the row or a right-click unfolds
    # the row's options above it: every option it has, each with its name (where it opens, its own shortcuts, Close, ...).
    def _favorite_row(self,p):
        app=self.app.catalogue.by_id().get(p.desktop_id)
        main=Gtk.Button(); main.add_css_class("launch-row"); main.set_hexpand(True)
        inner=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12)); self._launch_slot(p,inner,app_icon(app.icon if app else None,p.name,32),32)
        if p.channel is not None:
            ch=Gtk.Label(label=self.app.store.channel_text(p.channel)); ch.add_css_class("channel-number"); inner.append(ch)
        inner.append(Marquee(self.app.profile_name(p,app),delay=NAME_SCROLL_DELAY).follow(main))
        if p.pin_hash: inner.append(self._lock_mark())
        inner.append(self._star_mark())
        main.set_child(inner)
        main.connect("clicked",lambda _b,profile=p:self.app.launch_profile(profile))
        box,group=self._options_row(main,lambda profile=p,a=app:self._profile_items(profile,a))
        self._groups["quick"].append(group); return box

    def _window_row(self,w,nested=False):
        """An application on a workspace of its own (or one app inside an expanded workspace)."""
        title,badge=extract_badge(w["title"],w.get("urgent",False))
        app=self.app.match_application_window(w)
        main=Gtk.Button(); main.add_css_class("launch-row"); main.add_css_class("open-app"); main.set_hexpand(True)
        inner=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12)); inner.append(self.app.window_icon(w,32,badge))
        inner.append(Marquee(title,delay=NAME_SCROLL_DELAY).follow(main))
        if w["con_id"] in getattr(self,"_starred",()): inner.append(self._star_mark())
        main.set_child(inner)
        main.connect("clicked",lambda _b,con=w["con_id"]:self.app.focus_window(con))
        box,group=self._options_row(main,lambda win=w,a=app:self._window_items(win,a))
        if nested: box.set_margin_start(S(28))
        self._groups["quick"].append(group); return box

    def _workspace_row(self,entry,outputs):
        """Apps that share a workspace, grouped under a name built from what is in it. Its apps unfold above it."""
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4))
        main=Gtk.Button(); main.add_css_class("launch-row"); main.add_css_class("open-app"); main.set_hexpand(True); main.set_tooltip_text("Open this workspace and everything on it")
        inner=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12)); icons=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(2))
        for w in entry.windows[:3]: icons.append(self.app.window_icon(w,24,extract_badge(w["title"],w.get("urgent",False))[1]))
        inner.append(icons)
        inner.append(Marquee(entry.label,delay=NAME_SCROLL_DELAY).follow(main))
        count=Gtk.Label(label=f"{len(entry.windows)} apps"); count.add_css_class("muted"); inner.append(count); main.set_child(inner)
        main.connect("clicked",lambda _b,name=entry.name:self.app.open_workspace(name))
        # the individual apps sit above the workspace, so they are registered first: navigation goes top to bottom
        children=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4)); children.set_visible(False)
        for w in entry.windows: children.append(self._window_row(w,nested=True))
        others=[o["name"] for o in outputs if o["name"]!=entry.output]
        def items():
            out=[]
            for name in others:   # only offered when there is somewhere else to send it
                out.append(("video-display-symbolic","▭",f"Move to monitor {name}",lambda n=name:self.app.move_workspace(entry.name,n),False))
            out.append(("window-close-symbolic","✕","Close this workspace and its apps",
                        lambda:self.confirm("Close workspace?",f"Close {entry.label} and its {len(entry.windows)} applications? Unsaved work in them may be lost.",
                                            "Close workspace",lambda:self.app.close_workspace(entry)),True))
            return out
        row,group=self._options_row(main,items)
        # Showing or hiding the individual apps is its own square button between ⋯ and the name, shown even when ⋯ is hidden
        expander=Gtk.Button(); expander.add_css_class("square")
        def show_expander():
            shown=children.get_visible()
            unfold=not shown if self.top else shown   # the arrow points the way its apps fold: away from the row, or back to it
            expander.set_child(glyph("pan-down-symbolic" if unfold else "pan-up-symbolic","▾" if unfold else "▴"))
            expander.set_tooltip_text("Hide the individual apps" if shown else "Show the individual apps, to open just one")
        def flip(*_):
            self._close_open(); children.set_visible(not children.get_visible()); show_expander(); self._mirror(expander); self.app.fit_quick_menu()
        expander.connect("clicked",flip); pointer_only(expander)
        show_expander(); group.line.insert_child_after(expander,group[0]); group.insert(1,expander)   # group[0] is ⋯, even when hidden
        group.lead=expander   # ← on the name moves onto it; ← on it opens the row's menu
        self._groups["quick"].append(group)
        box.append(children); box.append(row); self._flip(box); self._flip(children); return box

    def _options_row(self,main,items):
        """A row: ⋯ then the application, with its options folded away above it. ⋯, ← on the application or a
        right-click unfolds them upwards, a little indented on both sides and close to their row (with a small gap to
        the row above), in the order items() makes them, top to bottom: the last one (Close) is nearest the row.
        items() makes them when they open: (icon, fallback glyph, label, action, dangerous). The ⋯ button can be hidden in Settings.
        -> (the options and the row, the row's NavGroup); the NavGroup's `line` is the row itself."""
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2)); panel.add_css_class("row-options"); panel.set_visible(False)
        panel.set_margin_start(S(16)); panel.set_margin_end(S(16)); panel.set_margin_top(S(6)); panel.set_margin_bottom(S(2)); self._flip_margins(panel)
        row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4))
        hide=bool(self.app.store.settings.get("hide_options_buttons",False))
        toggle=Gtk.Button(); toggle.add_css_class("options-toggle"); toggle.add_css_class("square"); toggle.set_visible(not hide)
        toggle.set_child(glyph("view-more-symbolic","⋯")); toggle.set_tooltip_text("Options")
        group=NavGroup([toggle,main],entry=main); group.toggle=toggle if not hide else None; group.line=row; pointer_only(toggle,main)
        def collapse():
            group.options=[]
            if panel.get_visible(): panel.set_visible(False); clear_box(panel); self.app.fit_quick_menu()
        def run(action):
            main.grab_focus(); self._close_open(); action()
        def open_options(*_):
            if panel.get_visible():   # ⋯ (or a right-click) again folds them
                main.grab_focus(); self._close_open(); return True
            self._close_open(); made=items(); buttons=[]
            if not made: panel.append(muted_label("Nothing to choose here."))
            for icon,fallback,label,action,danger in made:
                b=self.dialog_button(icon,fallback,label); b.add_css_class("menu-item")
                if danger: b.add_css_class("danger")
                b.connect("clicked",lambda _b,a=action:run(a)); panel.append(b); buttons.append(b); pointer_only(b)
            self._flip(panel); self._mirror(panel)   # in a top corner they unfold downwards, Close still nearest the row
            options=[]
            for b in buttons:
                g=NavGroup([b]); g.option_item=True; options.append(g)
            group.options=options; panel.set_visible(True); self._open_row=group
            # the selection lands on the option nearest the row that is not Close
            safe=[b for b in buttons if not b.has_css_class("danger")]
            (safe[-1] if safe else buttons[-1] if buttons else main).grab_focus(); self.app.fit_quick_menu()
            scroll=box.get_ancestor(Gtk.ScrolledWindow)
            if scroll is not None:   # unfolded upwards: bring the top of the options into sight, keeping the row in sight
                GLib.timeout_add(60,lambda:(scroll_to_show(scroll,box),GLib.SOURCE_REMOVE)[1])
            return True
        toggle.connect("clicked",open_options)
        click=Gtk.GestureClick(); click.set_button(3); click.connect("pressed",lambda *_a:open_options()); main.add_controller(click)
        row.append(toggle); row.append(main); box.append(panel); box.append(row); self._flip(box)
        group.expanded=panel.get_visible; group.expand=open_options; group.collapse=collapse
        group.open_options=open_options; group.menu=[toggle]
        group.owns=lambda w:any(w is x for x in group) or self._contains(panel,w)
        return box,group
    def _close_open(self):
        """Fold away the open row options or status panel, if any."""
        row=self._open_row; self._open_row=None
        if row is not None and row.expanded(): row.collapse()

    def _launch_slot(self,p,inner,icon,size):
        """Put a profile's icon in its button, with a spinner that takes the icon's place while the profile starts."""
        spinner=Gtk.Spinner(); spinner.set_size_request(S(size),S(size)); spinner.set_tooltip_text("Starting…")
        inner.append(icon); inner.append(spinner); self._launch_slots.append((p.id,icon,spinner))
        self._show_launching(icon,spinner,p.id in self.launching)
    @staticmethod
    def _show_launching(icon,spinner,on):
        icon.set_visible(not on and not icon.has_css_class(NO_ICON)); spinner.set_visible(on); (spinner.start if on else spinner.stop)()
    def set_launching(self,profile_id,on):
        """Show (or stop) the spinner on every button of a profile that is starting. -> whether one is on screen."""
        (self.launching.add if on else self.launching.discard)(profile_id)
        self._launch_slots=[s for s in self._launch_slots if s[1].get_root() is self]   # rows rebuilt since are gone
        shown=False
        for pid,icon,spinner in self._launch_slots:
            if pid!=profile_id: continue
            self._show_launching(icon,spinner,on); shown=shown or spinner.is_visible()   # it and every container it is in
        return shown
    def launching_slow(self,profile_id,name):
        for pid,_icon,spinner in self._launch_slots:
            if pid==profile_id: spinner.set_tooltip_text(f"{name} has not opened a window yet. It may still be starting, or it may not have started.")

    @staticmethod
    def _star_mark():
        """The grey ★ of a favorite in the Quick Menu (an open one also has the band of an open app)."""
        star=Gtk.Label(label="★"); star.add_css_class("favorite-mark"); star.set_tooltip_text("A favorite"); return star
    @staticmethod
    def _lock_mark():
        mark=glyph("changes-prevent-symbolic","🔒",16); mark.set_tooltip_text("Protected by a PIN"); return mark

    def _action_items(self,app):
        """The application's own shortcuts (its .desktop actions), such as a browser's New private window."""
        if not app: return []
        return [("view-list-bullet-symbolic","≡",name,lambda a=app,aid=action_id:self.app.launch_action(a,aid),False) for action_id,name in app.desktop_actions]
    def _one_time_item(self,run):
        """This once, the other way: in desktop mode in a new workspace; in TV mode alongside the apps on screen now
        (none when nothing is). run(mode) opens it."""
        if not self.app.tv: return [("view-fullscreen-symbolic","▣","Open in new workspace",lambda:run(LAUNCH_NEW_WORKSPACE),False)]
        names=self.app.alongside_names()
        if not names: return []
        shown=", ".join(names[:2])+(f" and {len(names)-2} more" if len(names)>2 else "")
        return [("view-dual-symbolic","◫",f"Open alongside {shown}",lambda:run(LAUNCH_SAME),False)]
    def _profile_items(self,p,app):
        """A favorite's (or search result's) menu, top to bottom: its shortcuts, open it the other way this once, and
        Close (nearest the row) when it is open."""
        items=self._action_items(app)
        items+=self._one_time_item(lambda mode:self.app.launch_profile(p,mode=mode))
        if not p.command.strip() and not p.desktop_action:
            w=self.app.wm.find_matching(p,app)
            if w is not None: items.append(("window-close-symbolic","✕",f"Close {p.name}",lambda con=w["con_id"]:self._close_open_window(con),True))
        return items
    def _window_items(self,w,app):
        """An open application's menu, top to bottom: its shortcuts, open it the other way this time, then Close
        (nearest the row)."""
        items=self._action_items(app)
        if not (self.app.tv and w.get("workspace_visible")): items+=self._one_time_item(lambda mode:self.app.focus_window(w["con_id"],mode))
        items.append(("window-close-symbolic","✕","Close this application",lambda:self._close_open_window(w["con_id"]),True))
        return items

    def _popup(self,anchor,child):
        pop=Gtk.Popover(); pop.set_parent(anchor); pop.set_child(child); self._popovers+=1
        def closed(p): self._popovers=max(0,self._popovers-1); GLib.idle_add(p.unparent)
        pop.connect("closed",closed)
        key=Gtk.EventControllerKey(); key.connect("key-pressed",lambda _c,kv,_kc,_st:(pop.popdown(),True)[1] if kv==Gdk.KEY_Back else False); pop.add_controller(key)
        pop.popup(); return pop
    def _close_open_window(self,con_id):
        if not self.app.wm.close_window(con_id): self.app.notify_message("Could not close that application window.")
        # its row is gone once the list is rebuilt: the selection goes back to the search field, not to the header
        GLib.timeout_add(250,lambda:(self.app.refresh_data(rebuild=True),self.focus_pane_soon("search"),GLib.SOURCE_REMOVE)[2])

    # ---------------------------------------------------------- Applications pane
    def _build_guide_pane(self):
        """The Applications pane: a title over the applications guide. Its focusable widgets register into pane "guide"."""
        pane=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0); pane.add_css_class("pane"); pane.set_hexpand(True); pane.set_margin_start(self.app.layout.margin)
        head=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(14)); head.set_margin_top(S(12)); head.set_margin_start(S(24)); head.set_margin_end(S(24)); head.set_margin_bottom(S(2))
        self.apps_title=Gtk.Label(label="Applications"); self.apps_title.add_css_class("pane-title"); self.apps_title.set_xalign(0); head.append(self.apps_title)
        self.apps_subtitle=Gtk.Label(); self.apps_subtitle.add_css_class("muted"); self.apps_subtitle.set_valign(Gtk.Align.END); self.apps_subtitle.set_margin_bottom(S(4)); self.apps_subtitle.set_xalign(0); head.append(self.apps_subtitle)
        pane.append(head)
        self.apps_list_scroll=Gtk.ScrolledWindow(); self.apps_list_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC); self.apps_list_scroll.set_vexpand(True)
        self.apps_content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4)); self.apps_content.set_margin_start(S(24)); self.apps_content.set_margin_end(S(24)); self.apps_content.set_margin_bottom(S(16))
        self.apps_list_scroll.set_child(self.apps_content); pane.append(self.apps_list_scroll)
        self._rebuild_apps_content()
        return pane

    def _rebuild_apps_content(self):
        """Applications: your channels, then every installed application by category."""
        clear_box(self.apps_content)
        assigned=self.app.store.assigned()
        if self.apps_subtitle is not None: self.apps_subtitle.set_text(f"{len(assigned)} channel{'s' if len(assigned)!=1 else ''}" if assigned else "")
        self.guide_scroll=self.apps_list_scroll
        self.apps_content.append(section_title("CHANNELS"))
        if not assigned: self.apps_content.append(muted_label("No channels yet. Give an app a number with ✎, then type that number in the Quick Menu to open it."))
        for profile in assigned: self.apps_content.append(self._profile_row(profile,lineup=True))
        self.apps_content.append(section_title("ALL APPLICATIONS"))
        grouped=self.app.catalogue.by_category()
        if not grouped: self.apps_content.append(muted_label("No graphical applications were found in the XDG application directories."))
        for category,apps in grouped.items(): self.apps_content.append(self._category_section(category,apps))
        if self._guide_scroll>0:
            for delay in (30,200): GLib.timeout_add(delay,self._restore_guide_scroll)

    def _category_section(self,category,apps):
        """A focusable header button that folds its applications; open/closed state survives rebuilds."""
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2))
        head=Gtk.Button(); head.add_css_class("category-header")
        line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12)); arrow=Gtk.Label(); arrow.set_width_chars(2)
        label=Gtk.Label(label=f"{category}  ({len(apps)})"); label.set_xalign(0); label.set_hexpand(True); line.append(arrow); line.append(label); head.set_child(line)
        inner=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2)); inner.set_margin_top(S(2)); inner.set_margin_bottom(S(8))
        def apply():
            opened=category in self._expanded; inner.set_visible(opened); arrow.set_text("▾" if opened else "◂" if self.right else "▸")
        def flip(*_):
            self._expanded.symmetric_difference_update({category}); apply()
        head.connect("clicked",flip); apply(); self._register("guide",head)
        for application in apps:
            default=self.app.default_profile(application)
            if default: inner.append(self._profile_row(default))
            for profile in self.app.store.for_app(application.desktop_id):
                if default and profile.id==default.id: continue
                inner.append(self._profile_row(profile))
        box.append(head); box.append(inner); return box

    def _profile_row(self,p,lineup=False):
        app=self.app.catalogue.by_id().get(p.desktop_id)
        default=self.app.default_profile(app) if app else None
        primary=default is not None and default.id==p.id
        row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); row.add_css_class("profile-row")
        if not primary and not lineup: row.set_margin_start(S(16))   # a secondary profile hangs under its application
        main=Gtk.Button(); main.set_hexpand(True); main.add_css_class("launch-row")
        inner=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(12))
        self._launch_slot(p,inner,app_icon(app.icon if app else None,p.name,32) if (primary or lineup) else child_marker(32),32)
        ch=Gtk.Label(label=self.app.store.channel_text(p.channel) if p.channel is not None else ""); ch.set_width_chars(self.app.store.channel_digits()+1); ch.set_xalign(0); ch.add_css_class("channel-number"); inner.append(ch)
        name=Gtk.Label(label=self.app.profile_name(p,app)); name.set_xalign(0); name.set_ellipsize(3); inner.append(name)
        # Each profile has its own description; without one the main profile shows its application's, another its launch options.
        description=row_description(p,app,primary,self.app.store.app_descriptions.get(p.desktop_id,""))
        if description:
            name.set_max_width_chars(32)
            if p.pin_hash: inner.append(self._lock_mark())
            # cut with … when it does not fit: it scrolls by while the row is selected, and the pointer shows all of it
            d=Marquee(description,"description").follow(main); inner.append(d); self._descriptions.append((main,d))
            main.set_has_tooltip(True); main.connect("query-tooltip",self._description_tip,d)
        else:
            name.set_hexpand(True)
            if p.pin_hash: inner.append(self._lock_mark())
        main.set_child(inner); main.connect("clicked",lambda _b,profile=p:self.app.launch_profile(profile)); row.append(main)
        fav=Gtk.Button(); fav.add_css_class("square"); self._style_star(fav,p.favorite); self._stars.setdefault(p.id,[]).append(fav)
        fav.connect("clicked",lambda _b,profile=p:self.app.toggle_favorite(profile)); row.append(fav)
        edit=Gtk.Button(); edit.add_css_class("square"); edit.set_child(glyph("document-edit-symbolic","✎"))
        edit.set_tooltip_text("Edit"); edit.connect("clicked",lambda _b,profile=p:self.app.edit_profile(profile,None))
        row.append(edit); self._register("guide",main,fav,edit)
        # Right-clicking the application (or ← while it is selected) opens its options too — Edit and ☆/★ —
        # which also works when the ⋯ buttons are hidden in Settings.
        pop_holder=[]
        def open_options(*_):
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4))
            star=Gtk.Button(label="Remove favorite" if p.favorite else "Add to favorites")
            star.connect("clicked",lambda _b:(pop_holder and pop_holder[0].popdown(),self.app.toggle_favorite(p)))
            box.append(star)
            manage=Gtk.Button(label="Edit")
            manage.connect("clicked",lambda _b:(pop_holder and pop_holder[0].popdown(),self.app.edit_profile(p,None)))
            box.append(manage)
            pop_holder.append(self._popup(main,box)); return True
        click=Gtk.GestureClick(); click.set_button(3); click.connect("pressed",lambda *_a:open_options()); main.add_controller(click)
        group=self._groups["guide"][-1]
        if group:
            group.entry=main; group.open_options=open_options
            group.expand=lambda:open_options(); group.expanded=lambda:bool(pop_holder and pop_holder[-1].get_visible())
        return row

    @staticmethod
    def _description_tip(_widget,_x,_y,_keyboard,tooltip,marquee):
        if not marquee.truncated: return False
        tooltip.set_text(marquee.text); return True
    def apps_width(self):
        """At a desk the Applications pane is only as wide as its rows need: the widest row without its description,
        plus room for most descriptions (four in five) in full. The rest are cut with … (see Marquee)."""
        if self.guide_pane is None:
            self.guide_pane=self._build_guide_pane(); self.panes.append(self.guide_pane); self.guide_pane.set_visible(self.guide_open); self._mirror(self.guide_pane)
        rows=[]; texts=[]
        for main,d in self._descriptions:
            row=main.get_parent()
            if row is None: continue
            rows.append(row.measure(Gtk.Orientation.HORIZONTAL,-1)[1]-d.label.measure(Gtk.Orientation.HORIZONTAL,-1)[1])
            texts.append(d.label.measure(Gtk.Orientation.HORIZONTAL,-1)[1])
        if not rows: return S(640)
        texts.sort(); most=texts[min(len(texts)-1,int(len(texts)*0.8))]
        return max(rows)+most+2*S(24)+S(16)   # the list's side margins, and its scroll bar
    def _style_star(self,button,favorite):
        button.set_child(glyph("starred-symbolic" if favorite else "non-starred-symbolic","★" if favorite else "☆"))
        button.set_tooltip_text("Remove favorite" if favorite else "Add to favorites")
    def refresh_favorites(self,profile_id):
        """A favorite changed: restyle its star(s) and rebuild only the Quick Menu list; Applications stays put."""
        p=self.app.store.get(profile_id)
        for b in self._stars.get(profile_id,[]): self._style_star(b,bool(p and p.favorite))
        if self.quick_content is not None:
            if any(self._open_row is g for g in self._groups["quick"]): self._open_row=None
            self._groups["quick"]=[]; clear_box(self.quick_content); self._build_quick_content(self.quick_content)
            self.app.fit_quick_menu()
    def _restore_guide_scroll(self):
        if self.guide_scroll is not None: self.guide_scroll.get_vadjustment().set_value(self._guide_scroll)
        return GLib.SOURCE_REMOVE
    def reset_scroll(self): self._guide_scroll=0.0

    # ---------------------------------------------------------- search
    def _refresh_search_results(self):
        if not hasattr(self,"results_box"): return
        if self._contains(self.results_box,self.get_focus()): self.search_entry.grab_focus()   # its row is about to go (the field's ✕ clicked)
        if any(self._open_row is g for g in self._result_groups): self._open_row=None
        clear_box(self.results_box); self._result_groups=[]; self._result_mains=[]; self._selected_result=0
        q=self.search_entry.get_text(); self._results_query=q
        self.results_scroll.set_visible(bool(q.strip()))
        self._shape_search()
        if not q.strip(): self._search_results=[]; self.app.fit_quick_menu(); return
        self._search_results=search_items(q,self.app.store.profiles,self.app.catalogue.by_id(),self.app.wm.windows(),self.app.store.channel_digits())[:12]
        if not self._search_results:
            self.results_box.append(muted_label("No matches. Try an app name, profile name, channel number, or window title.")); self._mirror(self.results_box); self.app.fit_quick_menu(); return
        for i,result in enumerate(self._search_results):
            main=Gtk.Button(); main.add_css_class("launch-row"); main.set_hexpand(True)
            row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10))
            if result["kind"]=="window":
                w=result["window"]; row.append(self.app.window_icon(w,28,result.get("badge"))); app=self.app.match_application_window(w)
                items=lambda w=w,a=app:self._window_items(w,a)
            else:
                p=result["profile"]; app=self.app.catalogue.by_id().get(p.desktop_id); self._launch_slot(p,row,app_icon(app.icon if app else None,p.name,28),28)
                items=lambda p=p,a=app:self._profile_items(p,a)
            row.append(Marquee(result["label"] if result["kind"]=="window" else self.app.profile_name(p,app),delay=NAME_SCROLL_DELAY).follow(main))
            detail=Gtk.Label(label=result["detail"]); detail.add_css_class("muted"); detail.set_ellipsize(3); row.append(detail); main.set_child(row)
            if i==self._selected_result: main.add_css_class("tvwcs-selected")
            main.connect("clicked",lambda _b,r=result:self.app.activate_result(r))
            # the best match is nearest the search field, at the bottom; ↑ goes on to the next one
            # (below it in a top corner; ↓ goes on)
            line,group=self._options_row(main,items); self._result_groups.append(group); self._result_mains.append(main)
            (self.results_box.append if self.top else self.results_box.prepend)(line)
        self._mirror(self.results_box); self.app.fit_quick_menu()
    def _activate_search(self,*_):
        if self._channel_source: GLib.source_remove(self._channel_source); self._channel_source=0   # Enter launches it now
        # typed and OK'd at once: list the results first (GTK waits a moment), so the launch spinner has its button
        if getattr(self,"_results_query",None)!=self.search_entry.get_text(): self._refresh_search_results()
        q=self.search_entry.get_text().strip()
        if q.isdigit():
            p=next((p for p in self.app.store.profiles if p.channel==int(q)),None)
            if p: self.app.launch_profile(p); return
        if self._search_results: self.app.activate_result(self._search_results[self._selected_result])
    def _search_typed(self,*_):
        """A full channel number (all its digits) left alone for a second launches its channel, without Enter."""
        if self._channel_source: GLib.source_remove(self._channel_source); self._channel_source=0
        q=self.search_entry.get_text().strip()
        if len(q)==self.app.store.channel_digits() and q.isdigit() and any(p.channel==int(q) for p in self.app.store.profiles):
            self._channel_source=GLib.timeout_add(CHANNEL_DELAY,self._launch_typed_channel,q)
    def _launch_typed_channel(self,q):
        self._channel_source=0
        if self.is_visible() and not self._modal_groups and self.search_entry.get_text().strip()==q:
            p=next((p for p in self.app.store.profiles if p.channel==int(q)),None)
            if p: self.app.launch_profile(p)
        return GLib.SOURCE_REMOVE
    def _select_result(self,index):
        self._selected_result=index
        for i,b in enumerate(self._result_mains):
            b.remove_css_class("tvwcs-selected")
            if i==index: b.add_css_class("tvwcs-selected")
        # the highlight moves while the selection stays in the search field, so the list does not follow it by itself
        if 0<=index<len(self._result_mains): scroll_to_show(self.results_scroll,self._result_mains[index])
    def _type_to_search(self,text):
        e=self.search_entry; value=e.get_text()+text
        self._show_search(); e.grab_focus(); e.set_text(value); e.set_position(-1)
    def _show_search(self):
        """Unfold the search bar (search_icon setting); it is always there otherwise."""
        if self.search_line.get_visible(): return
        self.search_line.set_visible(True); self.search_button.add_css_class("active"); self.app.fit_quick_menu()
    def _hide_search(self):
        if not self.search_folds or not self.search_line.get_visible(): return
        self.search_line.set_visible(False); self.search_button.remove_css_class("active"); self.app.fit_quick_menu()
    def toggle_search(self):
        """The search icon: unfold the search bar and type in it; again, fold it away (and what was typed)."""
        if self.search_line.get_visible():
            self.search_entry.set_text(""); self._hide_search(); self.search_button.grab_focus(); return
        self._show_search(); self.search_entry.grab_focus()
    def _fold_search(self,focused):
        """Fold the search bar away once the selection has left it with nothing typed (not for a dialog: the on-screen
        keyboard, opened from it, types into it)."""
        if not self.search_folds or focused is None or self._modal_groups or self._popovers: return
        if self.search_line.get_visible() and not self._in_search(focused) and not self.search_entry.get_text().strip(): self._hide_search()
    def _nearest_row(self):
        """The search bar folded away: the row next to where it would be (the lists' lowest row, else the search icon)."""
        for g in reversed(self._groups["quick"]):
            w=self._landing(g)
            if w is not None and w.grab_focus(): return True
        return self.search_button.grab_focus()

    # ---------------------------------------------------------- remote / keyboard navigation
    def _register(self,pane,*widgets,entry=None):
        pointer_only(*widgets)
        group=NavGroup([w for w in widgets if w is not None],entry)
        if group: self._groups[pane].append(group); return group
        return None
    def _focus_changed(self,*_):
        w=self.get_focus()
        if w is not None: self._last_focus[self._pane_of(w)]=w
        self._fold_options(w); self._fold_search(w)
    def _fold_options(self,focused):
        """Fold a Quick Menu row's options (or a status panel) away once the selection has left them and their row (or
        icon). Not while a pop-up or a dialog opened from one of them is up, nor while a panel is redrawn."""
        row=self._open_row
        if row is None or focused is None or self._popovers or self._modal_groups or getattr(self,"_keep_panel",False): return
        owns=getattr(row,"owns",None)
        if owns(focused) if owns is not None else any(focused is w for w in row.menu): return
        self._open_row=None
        if row.expanded(): row.collapse()

    def _pane_of(self,widget):
        for name,pane in (("options",self.options_pane),("guide",self.guide_pane)):
            if widget is not None and pane is not None and (widget is pane or widget.is_ancestor(pane)): return name
        return "quick"
    def _ordered_groups(self,pane):
        if self._modal_groups: return self._modal_groups
        if pane!="quick": return list(self._groups[pane])
        # top to bottom as on screen: the results are listed upwards from the search field, a row's open options are
        # just above it, and an open status panel is between the search field and the status row. In a top corner all of
        # it is the other way up, so the order is too.
        def unfolded(groups):
            out=[]
            for g in groups: out+=getattr(g,"options",None) or []; out.append(g)
            return out
        order=([self._header_group]+unfolded(self._groups["quick"])+unfolded(reversed(self._result_groups))
               +[[self.search_entry]]+list(getattr(self,"_panel_groups",[]))+[getattr(self,"_status_group",[]),getattr(self,"_clock_group",[])])
        return order[::-1] if self.top else order
    @staticmethod
    def _contains(widget,focused): return focused is not None and (focused is widget or focused.is_ancestor(widget))
    def _in_search(self,focused): return self._contains(self.search_entry,focused)   # focus sits on the entry's inner text widget
    def _group_index(self,groups,focused):
        # An exact match wins; only then accept "inside" (an entry's inner text widget). Otherwise a button nested in
        # a container that is itself a group would be mistaken for that container.
        for i,g in enumerate(groups):
            if any(w is focused for w in g): return i
        for i,g in enumerate(groups):
            if any(self._contains(w,focused) for w in g): return i
        return -1
    def _landing(self,group,column=None):
        if column is not None and getattr(group,"column",False):   # a grid row: stay in the same column
            active=[w for w in group if usable(w)]
            if active: return active[min(column,len(active)-1)]
        entry=getattr(group,"entry",None)
        if entry is not None and usable(entry): return entry
        return next((w for w in group if usable(w)),None)
    def _focus_first(self,groups):
        for g in groups:
            w=self._landing(g)
            if w is not None and w.grab_focus(): return True
        return False
    def focus_pane(self,pane):
        """Select something in a pane: where the selection last was in it, else its first row. "search": the Quick
        Menu's search field, whatever was selected before (GTK selects the first button when the window appears)."""
        folded=self.search_folds and not self.search_line.get_visible()
        if pane=="search": return self._nearest_row() if folded else self.search_entry.grab_focus()
        last=self._last_focus.get(pane)
        if last is not None and usable(last) and last.grab_focus(): return True
        if pane=="quick": return self._nearest_row() if folded else self.search_entry.grab_focus()
        return self._focus_first(self._groups[pane])
    def focus_pane_soon(self,pane,prefer=None):
        """Focus once a freshly shown panel has been mapped: `prefer` if it is still there, else focus_pane(pane)."""
        def go():
            if prefer is None or not usable(prefer) or not prefer.grab_focus(): self.focus_pane(pane)
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(70,go)
    def _move_group(self,step):
        focused=self.get_focus(); pane=self._pane_of(focused)
        groups=[g for g in self._ordered_groups(pane) if any(usable(w) for w in g)]
        if not groups: return False
        current=self._group_index(groups,focused)
        lane=getattr(groups[current],"lane",None) if current>=0 else None
        if lane is not None:   # in a column layout ↑/↓ stays in its column (rows outside any column are shared)
            groups=[g for g in groups if getattr(g,"lane",None) in (None,lane)]; current=self._group_index(groups,focused)
        column=next((k for k,w in enumerate(groups[current]) if w is focused),None) if current>=0 else None
        start=(current+step)%len(groups) if current>=0 else (0 if step>0 else len(groups)-1)
        for offset in range(len(groups)):
            w=self._landing(groups[(start+step*offset)%len(groups)],column)
            if w is not None and w.grab_focus(): return True
        return False
    def _move_within_group(self,step):
        focused=self.get_focus(); pane=self._pane_of(focused)
        groups=self._ordered_groups(pane); gi=self._group_index(groups,focused)
        if gi<0: return False
        group=groups[gi]; active=[w for w in group if usable(w)]
        if not active: return False
        i=next((k for k,w in enumerate(active) if w is focused),None)
        if i is None: i=next((k for k,w in enumerate(active) if self._contains(w,focused)),0)
        if getattr(group,"option_item",False) and not self._modal_groups: return True   # one option: ←/→ stay on it
        open_options=getattr(group,"open_options",None)
        lead=getattr(group,"lead",None)
        if step<0 and pane=="quick" and open_options is not None and focused is (lead or group.entry) and group.expanded is not None and not group.expanded():
            return open_options()   # ← on a Quick Menu row opens its options, next to the application (or its first button after ⋯)
        nxt=i+step
        if 0<=nxt<len(active): return active[nxt].grab_focus()
        if self._modal_groups: return active[nxt%len(active)].grab_focus()
        if getattr(group,"lane",None) is not None and self._jump_lane(groups,group,active[i],step): return True
        toggle=getattr(group,"toggle",None)
        if step<0:
            if toggle is not None and active[i] is toggle:
                if any(group is g for g in self._result_groups): self.search_entry.grab_focus()   # back to typing
                return True
            if pane=="guide": return self.focus_pane("quick")
            if pane=="options": self.app.show_panels(True,False,focus="guide"); return True
            return active[nxt%len(active)].grab_focus()
        # Past the right-hand end: continue into the next panel, opening it if it is closed.
        if pane=="quick":
            if self.guide_open: return self.focus_pane("guide")
            self.app.show_panels(True,False,focus="guide"); return True
        if pane=="guide" and self.options_open: return self.focus_pane("options")
        return True
    def _jump_lane(self,groups,group,focused,step):
        """←/→ past the edge of a row in a column layout: go to the row beside it in the neighbouring column."""
        target=group.lane+step
        candidates=[g for g in groups if getattr(g,"lane",None)==target and self._landing(g) is not None]
        if not candidates: return False
        y=self._middle_y(focused)
        best=min(candidates,key=lambda g:abs(self._middle_y(self._landing(g))-y))
        return self._landing(best).grab_focus()
    def _middle_y(self,widget):
        try:
            ok,rect=widget.compute_bounds(self)
            return rect.get_y()+rect.get_height()/2 if ok else 0.0
        except (AttributeError,TypeError,ValueError): return 0.0
    def _result_index(self,focused):
        for i,g in enumerate(self._result_groups):
            if any(w is focused for w in g): return i
        return -1

    def _key_pressed(self,_controller,keyval,_keycode,state):
        if self._capture is not None and self._capture_key(keyval,state): return True
        focused=self.get_focus(); editable=isinstance(focused,Gtk.Editable); typing=self._in_search(focused)
        if keyval in (Gdk.KEY_Escape,Gdk.KEY_Back): self._escape(); return True   # the remote's Back key (XF86Back) is Esc
        if self._pin is not None and self._pin_key(keyval): return True
        if self._chan is not None and self._chan_key(keyval): return True
        if self._text is not None and not editable and self._text_key(keyval): return True
        # Typing anywhere starts a search (not while a dialog is up, in another text field, or with a shortcut modifier held).
        if not self._modal_groups and not editable and not (state & _TYPING_BLOCKED):
            ch=Gdk.keyval_to_unicode(keyval)
            if ch>32 and chr(ch).isprintable(): self._type_to_search(chr(ch)); return True
        if keyval in (Gdk.KEY_Down,Gdk.KEY_Up):
            step=1 if keyval==Gdk.KEY_Down else -1
            if not self._modal_groups:
                # The results are above the search field, the best one nearest it: ↑ goes on to the next result (below
                # it in a top corner: ↓ does). Keep focus in the search field while arrows change the highlighted result
                # so typing can continue. `away` is +1 for the key that leads away from the search field.
                away=step if self.top else -step
                if typing and self.search_entry.get_text().strip() and self._search_results:
                    nxt=self._selected_result+away
                    if 0<=nxt<len(self._search_results): self._select_result(nxt); return True
                    if away>0: self._focus_above_results(); return True   # past the last result: on to the lists
                ri=self._result_index(focused)
                if ri>=0 and not (away>0 and self._result_groups[ri].expanded()):   # on into its own open options instead
                    nxt=ri+away
                    if 0<=nxt<len(self._result_groups): self._select_result(nxt); self._landing(self._result_groups[nxt]).grab_focus(); return True
                    if nxt<0: self.search_entry.grab_focus(); return True
                    self._focus_above_results(); return True
            self._move_group(step); return True
        if keyval==Gdk.KEY_Right and typing and self._search_results and not self._modal_groups \
                and self.search_entry.get_position()==len(self.search_entry.get_text()):
            g=self._result_groups[self._selected_result]   # at the end of the text, Right opens the highlighted result's menu
            if g.open_options is not None: g.open_options(); return True
        if keyval in (Gdk.KEY_Left,Gdk.KEY_Right) and not editable:
            step=1 if keyval==Gdk.KEY_Right else -1
            if self.right and not self._modal_groups: step=-step   # mirrored: rows run right to left (dialogs do not)
            if self._move_within_group(step): return True
        if keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter) and typing:
            if not self.search_entry.get_text().strip(): self.ask_search(); return True   # Enter on an empty search: the on-screen keyboard
            self._activate_search(); return True
        return False
    def _focus_above_results(self):
        """↑ past the last search result: the lowest row of the lists above it, else the header (↓ and the highest row of
        the lists below it, in a top corner)."""
        for g in reversed(self._groups["quick"]):
            w=self._landing(g)
            if w is not None and w.grab_focus(): return
        if self._header_group: self._header_group[0].grab_focus()
    def _key_released(self,_controller,keyval,_keycode,state):
        if self._capture is not None:
            spec=self._capture.release(Gdk.keyval_name(keyval))
            if spec: self._end_capture(spec)
    def _escape(self):
        if self._modal_groups: (self._modal_back or self.close_modal)(); return
        if self.search_folds and self.search_line.get_visible() and self._in_search(self.get_focus()):
            self.toggle_search(); return   # Back folds the search bar away first, back onto the search icon
        row=self._open_row
        if row is not None and row.expanded():   # Back folds open options (or a status panel) first, back onto their row
            back=getattr(row,"opener",None) or getattr(row,"entry",None)
            if back is not None and usable(back): back.grab_focus()
            self._close_open(); return
        if self.guide_open: self.app.show_panels(False,False,focus="quick"); return    # then Applications, keep the Quick Menu
        self.app.hide_window()

    # ---------------------------------------------------------- close when focus leaves
    def _active_changed(self,*_):
        if self.is_active():
            self._was_active=True
            # Clicking TVWCS brings it in front of an open dialog (profile editor, application profiles), which would
            # then sit hidden behind it, blocking it. Close the dialogs instead, dropping what was not saved.
            if self.app.has_dialogs(): GLib.timeout_add(120,self._dismiss_dialogs_if_active)
            return
        if self._was_active and self.is_visible() and self.app.store.settings["close_on_click_outside"]:
            GLib.timeout_add(150,self._close_if_unfocused)
    def _close_if_unfocused(self):
        # Child windows (profile editor) and open popovers legitimately take focus; only a click elsewhere closes TVWCS.
        # Nor while an app starts: opening it in a workspace of its own moves the focus, and its button shows the spinner.
        if self.is_visible() and not self.is_active() and self._popovers==0 and not self.app.has_dialogs() and not self.launching: self.app.hide_window()
        return GLib.SOURCE_REMOVE
    def _dismiss_dialogs_if_active(self):
        if self.is_visible() and self.is_active(): self.app.dismiss_dialogs()   # still in front: not a passing focus change
        return GLib.SOURCE_REMOVE
    def note_shown(self): self._was_active=False

    # ---------------------------------------------------------- dialogs (drawn over the panels, remote-navigable)
    def _begin_modal(self):
        if not self._modal_groups: self._return_focus=self.get_focus()
        clear_box(self.modal_card); self.modal_card.set_size_request(self._card_width,-1)
        self.modal_reveal.set_visible(True); self.modal_reveal.set_can_target(True); self.modal_reveal.set_reveal_child(True)
        GLib.idle_add(lambda:(self.app.fit_quick_menu(),GLib.SOURCE_REMOVE)[1])   # once filled: taller for a keyboard
    def close_modal(self):
        if self._text is not None and self._text.get("secret"): self._text["entry"].set_text("")   # a typed password is never left in the widget
        self._modal_groups=[]; self._modal_back=None; self._capture=None; self._pin=None; self._text=None; self._chan=None
        self.modal_reveal.set_can_target(False); self.modal_reveal.set_reveal_child(False); self.modal_reveal.set_visible(False)
        self.app.fit_quick_menu()   # back to the Quick Menu's own height
        back=self._return_focus
        if back is not None and usable(back): back.grab_focus()
        else: self.focus_pane("quick")
    def _title(self,text):
        t=Gtk.Label(label=text); t.add_css_class("pane-title"); t.set_xalign(0); t.set_wrap(True); t.set_margin_bottom(S(8)); self.modal_card.append(t)
    def dialog_button(self,icon,fallback,text):
        b=Gtk.Button(); b.add_css_class("dialog-button"); row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(14))
        g=glyph(icon,fallback,24) if icon else Gtk.Label(); g.set_size_request(S(28),-1); row.append(g)
        l=Gtk.Label(label=text); l.set_xalign(0); l.set_hexpand(True); l.set_wrap(True); l.set_max_width_chars(34)   # long labels wrap inside the Quick Menu
        row.append(l); b.set_child(row); return b

    def show_message(self,message,title="Something went wrong",done=None):
        """A message with an OK button, drawn in the window (no separate dialog window to lose behind TVWCS)."""
        self._begin_modal(); self._title(title)
        text=muted_label(message); text.set_margin_bottom(S(14)); self.modal_card.append(text)
        finish=lambda:(self.close_modal(),done and done())
        ok=Gtk.Button(label="OK"); ok.add_css_class("active"); ok.connect("clicked",lambda *_:finish()); self.modal_card.append(ok)
        self._modal_groups=[NavGroup([ok])]; self._modal_back=finish; ok.grab_focus()
    def show_starting(self,name,on_back):
        """“Starting Kodi…” while an application opens its first window (main.App waits for it)."""
        self._begin_modal(); self._title(f"Starting {name}…")
        spinner=Gtk.Spinner(); spinner.set_size_request(S(48),S(48)); spinner.set_halign(Gtk.Align.START); spinner.set_margin_bottom(S(10)); spinner.start(); self.modal_card.append(spinner)
        text=muted_label("It opens in a moment. Some apps take a few seconds the first time."); self.modal_card.append(text); self._starting_text=text
        hide=Gtk.Button(label="Hide"); hide.set_margin_top(S(12)); hide.connect("clicked",lambda *_:on_back()); self.modal_card.append(hide)
        self._modal_groups=[NavGroup([hide])]; self._modal_back=on_back; hide.grab_focus()
    def starting_slow(self,name):
        if getattr(self,"_starting_text",None) is not None and self._modal_groups:
            self._starting_text.set_text(f"{name} has not opened a window yet. It may still be starting, or it may not have started.")
    def first_run(self,done):
        """The first time TVWCS opens: where it is used (TV or desk), then how to add favorites."""
        def picked(use):
            self.app.set_use(use)
            self.show_message(f"{self.guide_hint()} to see every application. Press ☆ beside the ones "
                              "you use most to add them to this menu, and ✎ to give one a channel number or a hotkey. Everything else is in "
                              f"Settings, channel {self.app.store.channel_text(0)}.",
                              "Welcome to TVWCS",done)
        self._begin_modal(); self._title("Welcome to TVWCS")
        self.modal_card.append(muted_label("Where is this computer used? You can change this later in Settings."))
        groups=[]
        for key,label,icon,fallback in (("tv","On a TV, with a remote","video-display-symbolic","▭"),("desktop","At a desk, with a mouse and keyboard","input-mouse-symbolic","🖱")):
            b=self.dialog_button(icon,fallback,label); b.connect("clicked",lambda _b,k=key:picked(k)); self.modal_card.append(b); groups.append(NavGroup([b]))
        self._modal_groups=groups; self._modal_back=lambda:picked("tv"); groups[0][0].grab_focus()

    def confirm(self,title,message,label,on_confirm,back=None):
        """Ask before doing something destructive. Cancel is focused, so a stray Enter is harmless."""
        self._begin_modal(); self._title(title)
        text=muted_label(message); text.set_margin_bottom(S(14)); self.modal_card.append(text)
        row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(6)); row.set_homogeneous(True)
        cancel=Gtk.Button(label="Cancel"); cancel.connect("clicked",lambda *_:(back or self.close_modal)()); row.append(cancel)
        go=Gtk.Button(label=label); go.add_css_class("danger"); go.connect("clicked",lambda *_:(self.close_modal(),on_confirm())); row.append(go)
        self.modal_card.append(row); self._modal_groups=[[cancel,go]]; self._modal_back=back or self.close_modal; cancel.grab_focus()

    def system_action(self,action):
        if action.confirm: self.confirm(f"{action.label}?",action.confirm,action.label,lambda a=action:self._execute(a))
        else: self._execute(action)
    def _execute(self,action):
        if action.id=="refresh": self.app.refresh_data(rebuild=True)
        else: self.app.run_system_action(action.id)

    def ask_pin(self,profile,on_ok,message=""):
        """A PIN keypad that works with a D-pad (and with digit keys). Runs on_ok() once the right PIN is entered."""
        self._begin_modal(); self._title(f"PIN for {profile.name}")
        shown=Gtk.Label(); shown.add_css_class("pin-display"); shown.set_margin_bottom(S(8)); self.modal_card.append(shown)
        if message:
            e=Gtk.Label(label=message); e.add_css_class("error"); e.set_wrap(True); e.set_margin_bottom(S(8)); self.modal_card.append(e)
        self._pin={"profile":profile,"on_ok":on_ok,"digits":"","shown":shown}; self._pin_refresh()
        groups=[]
        def key(text,handler,css=None):
            b=Gtk.Button(label=text); b.add_css_class("pin-key")
            if css: b.add_css_class(css)
            b.connect("clicked",lambda *_:handler()); return b
        for digits in (("1","2","3"),("4","5","6"),("7","8","9"),(None,"0",None)):
            line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); line.set_homogeneous(True); line.set_margin_bottom(S(4)); row=[]
            for d in digits:
                if d is not None: b=key(d,lambda d=d:self._pin_press(d))
                elif not row: b=key("⌫",self._pin_back)
                else: b=key("OK",self._pin_submit,"active")
                line.append(b); row.append(b)
            self.modal_card.append(line); g=NavGroup(row); g.column=True; groups.append(g)
        cancel=Gtk.Button(label="Cancel"); cancel.set_margin_top(S(6)); cancel.connect("clicked",lambda *_:self.close_modal()); self.modal_card.append(cancel); groups.append(NavGroup([cancel]))
        self._modal_groups=groups; self._modal_back=self.close_modal; groups[0][0].grab_focus()
    def _pin_refresh(self):
        n=len(self._pin["digits"]); self._pin["shown"].set_text("  ".join("●"*n) if n else "– – – –")
    def _pin_press(self,digit):
        if len(self._pin["digits"])<8: self._pin["digits"]+=digit; self._pin_refresh()
    def _pin_back(self):
        self._pin["digits"]=self._pin["digits"][:-1]; self._pin_refresh()
    def _pin_key(self,keyval):
        """Digit and Backspace keys also work on the keypad (the remote's number keys, a keyboard)."""
        ch=Gdk.keyval_to_unicode(keyval)
        if 48<=ch<=57: self._pin_press(chr(ch)); return True
        if keyval==Gdk.KEY_BackSpace: self._pin_back(); return True
        return False
    def _pin_submit(self):
        st=self._pin; profile=st["profile"]
        status,wait=self.app.pin_gate.attempt(profile.id,st["digits"],profile.pin_hash)
        if status=="ok": on_ok=st["on_ok"]; self.close_modal(); on_ok(); return
        self.ask_pin(profile,st["on_ok"],"Wrong PIN." if status=="wrong" else f"Too many wrong tries. Try again in {wait} seconds.")

    def ask_channel(self,title,callback,current="",back=None):
        """A channel number in a box per digit (the channel_digits setting), typed on the keypad (or the remote's number
        keys). The boxes start empty, so a new number replaces the old one without deleting it first. callback(text) gets
        the digits typed ("7" is channel 07), the current number when OK is pressed with nothing typed, or "" for No channel."""
        self._begin_modal(); self._title(title); digits=self.app.store.channel_digits()
        m=muted_label(f"{channel_range(digits)}. Type it in the Quick Menu to open this app."
                      +(f" Now: {self.app.store.channel_text(int(current))}." if str(current).strip().isdigit() else ""))
        m.set_margin_bottom(S(8)); self.modal_card.append(m)
        boxes=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(8)); boxes.set_halign(Gtk.Align.CENTER); boxes.set_margin_bottom(S(10)); cells=[]
        for _ in range(digits):
            c=Gtk.Label(); c.add_css_class("digit-box"); boxes.append(c); cells.append(c)
        self.modal_card.append(boxes)
        cancelled=back or self.close_modal
        def submit():
            typed=self._chan["digits"]; self.close_modal(); callback(typed if typed else str(current or ""))
        def none(): self.close_modal(); callback("")
        self._chan={"digits":"","cells":cells,"length":digits}; self._chan_refresh()
        groups=[]
        def key(text,handler,css=None):
            b=Gtk.Button(label=text); b.add_css_class("pin-key")
            if css: b.add_css_class(css)
            b.connect("clicked",lambda *_:handler()); return b
        for row in (("1","2","3"),("4","5","6"),("7","8","9"),("⌫","0","OK")):
            line=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); line.set_homogeneous(True); line.set_margin_bottom(S(4)); made=[]
            for d in row:
                b=key(d,self._chan_back) if d=="⌫" else key("OK",submit,"active") if d=="OK" else key(d,lambda d=d:self._chan_press(d))
                line.append(b); made.append(b)
                if d=="OK": self._chan["ok"]=b
            self.modal_card.append(line); g=NavGroup(made); g.column=True; groups.append(g)
        bottom=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(6)); bottom.set_homogeneous(True); bottom.set_margin_top(S(6))
        clear=Gtk.Button(label="No channel"); clear.connect("clicked",lambda *_:none()); bottom.append(clear)
        cancel=Gtk.Button(label="Cancel"); cancel.connect("clicked",lambda *_:cancelled()); bottom.append(cancel)
        self.modal_card.append(bottom); groups.append(NavGroup([clear,cancel]))
        self._modal_groups=groups; self._modal_back=cancelled; groups[0][0].grab_focus()
    def _chan_refresh(self):
        digits=self._chan["digits"]
        for i,c in enumerate(self._chan["cells"]):
            c.set_text(digits[i] if i<len(digits) else "–")
            (c.add_css_class if i==len(digits) else c.remove_css_class)("current")
    def _chan_press(self,digit):
        if len(self._chan["digits"])<self._chan["length"]: self._chan["digits"]+=digit; self._chan_refresh()
        if len(self._chan["digits"])==self._chan["length"] and self._chan.get("ok") is not None: self._chan["ok"].grab_focus()   # complete: OK is next
    def _chan_back(self):
        self._chan["digits"]=self._chan["digits"][:-1]; self._chan_refresh()
    def _chan_key(self,keyval):
        ch=Gdk.keyval_to_unicode(keyval)
        if 48<=ch<=57: self._chan_press(chr(ch)); return True
        if keyval==Gdk.KEY_BackSpace: self._chan_back(); return True
        return False

    def ask_password(self,action_label,on_ok,message=""):
        """The administrator (sudo) password for a power action, typed on a keyboard (such as the one on the back of a
        remote) or on the on-screen keyboard, shown as it was last left (hidden, full or the number pad).
        on_ok(password) runs on OK; the field is emptied when it closes."""
        def got(password):
            if password: on_ok(password)
        self.ask_text(f"Password for {action_label}",got,"",f"{action_label} needs administrator rights. Enter your password (the one sudo asks for). "
                      "It is used once and never stored.",secret=True,error=message)

    # ---------------------------------------------------------- the on-screen keyboard (typing with a remote)
    KEYS={"lower":("1234567890","qwertyuiop","asdfghjkl'","zxcvbnm,.-"),
          "upper":("1234567890","QWERTYUIOP","ASDFGHJKL\"","ZXCVBNM;:_"),
          "symbols":("!@#$%^&*()","~`+=[]{}\\|","/?<>€£¥§°¿","…·•×÷¡«»¢¤")}
    def ask_text(self,title,callback,initial="",message="",back=None,digits=False,secret=False,ok_label="OK",max_len=0,error="",keyboard=None):
        """Type a piece of text with the D-pad or a real keyboard. callback(text) runs on OK or Enter; Cancel or Back
        runs back() (or just closes). With digits (a PIN), only the number pad is offered. Otherwise the on-screen
        keyboard is hidden, full (letters, capitals, symbols) or a number pad, as it was last left (settings
        "keyboard"), and buttons change between them, keeping what is typed."""
        st=self.app.store.settings
        kind="digits" if digits else (keyboard or st.get("keyboard","hidden"))
        if kind not in ("hidden","full","digits"): kind="hidden"
        self._begin_modal(); self._title(title)
        if message:
            m=muted_label(message); m.set_margin_bottom(S(8)); self.modal_card.append(m)
        if error:
            e=Gtk.Label(label=error); e.add_css_class("error"); e.set_wrap(True); e.set_xalign(0); e.set_margin_bottom(S(8)); self.modal_card.append(e)
        entry=Gtk.PasswordEntry() if secret else Gtk.Entry()
        if secret: entry.set_show_peek_icon(True)
        entry.add_css_class("pin-display" if kind=="digits" else "text-display"); entry.set_text(initial or ""); entry.set_margin_bottom(S(8))
        if max_len and not secret: entry.set_max_length(max_len)
        self.modal_card.append(entry)
        cancelled=back or self.close_modal
        def submit(*_):
            text=entry.get_text(); self.close_modal(); callback(text)
        entry.connect("activate",submit)
        self._text={"entry":entry,"submit":submit,"layer":"lower","keys":[],"digits":kind=="digits" and digits,"max":max_len,"secret":secret}
        def switch(to):   # another keyboard, with what is typed so far; remembered for next time
            typed=entry.get_text(); self._remember_keyboard(to)
            self.ask_text(title,callback,typed,message,back,digits,secret,ok_label,max_len,error,keyboard=to)
        groups=[NavGroup([entry])]
        def key(text,handler,css=None):
            b=Gtk.Button(label=text); b.add_css_class("pin-key")
            if css: b.add_css_class(css)
            b.connect("clicked",lambda *_:handler()); return b
        def line(buttons):
            box=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); box.set_homogeneous(True); box.set_margin_bottom(S(4))
            for b in buttons: box.append(b)
            self.modal_card.append(box); g=NavGroup(buttons); g.column=True; groups.append(g)
        if kind=="hidden":
            show=key("⌨  Show keyboard",lambda:switch("full")); ok=key(ok_label,submit,"active")
            line([show,ok])
        elif kind=="digits":
            for row in (("1","2","3"),("4","5","6"),("7","8","9")): line([key(d,lambda d=d:self._type(d)) for d in row])
            line([key("⌫",self._erase),key("0",lambda:self._type("0")),key(ok_label,submit,"active")])
            if not digits: line([key("ABC  Full keyboard",lambda:switch("full")),key("Hide keyboard",lambda:switch("hidden"))])
        else:
            for r in range(4):
                buttons=[key("",lambda r=r,c=c:self._type(self.KEYS[self._text["layer"]][r][c]),"kb-key") for c in range(10)]
                self._text["keys"].append(buttons); line(buttons)
            shift=key("⇧",lambda:self._layer("lower" if self._text["layer"]=="upper" else "upper"))
            symbols=key("&123",lambda:self._layer("lower" if self._text["layer"]=="symbols" else "symbols"))
            space=key("Space",lambda:self._type(" ")); erase=key("⌫",self._erase); ok=key(ok_label,submit,"active")
            box=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(4)); box.set_margin_bottom(S(4))
            for b in (shift,symbols,space,erase,ok): b.add_css_class("kb-key"); box.append(b)
            space.set_hexpand(True)
            for b,w in ((shift,56),(symbols,64),(erase,56),(ok,88)): b.set_size_request(S(w),-1)
            self.modal_card.append(box); g=NavGroup([shift,symbols,space,erase,ok]); groups.append(g)
            pad=key("123  Number pad",lambda:switch("digits"),"kb-key"); hide=key("Hide keyboard",lambda:switch("hidden"),"kb-key")
            line([pad,hide])
            self._text["shift"]=shift; self._text["symbols"]=symbols; self._label_keys()
        cancel=Gtk.Button(label="Cancel"); cancel.set_margin_top(S(6)); cancel.connect("clicked",lambda *_:cancelled()); self.modal_card.append(cancel); groups.append(NavGroup([cancel]))
        self._modal_groups=groups; self._modal_back=cancelled
        first=entry if kind=="hidden" else groups[1][0]; first.grab_focus()
        GLib.timeout_add(150,lambda:(self._text is not None and self._text["entry"] is entry and self.get_focus() is None and first.grab_focus(),GLib.SOURCE_REMOVE)[1])
    def _remember_keyboard(self,kind):
        """The on-screen keyboard was changed: the next text dialog opens with it."""
        store=self.app.store
        if store.settings.get("keyboard")!=kind:
            store.settings["keyboard"]=kind
            try: store.save()
            except OSError: pass
    def _label_keys(self):
        st=self._text; rows=self.KEYS[st["layer"]]
        for r,buttons in enumerate(st["keys"]):
            for c,b in enumerate(buttons): b.set_label(rows[r][c])
        (st["shift"].add_css_class if st["layer"]=="upper" else st["shift"].remove_css_class)("active")
        st["symbols"].set_label("abc" if st["layer"]=="symbols" else "&123")
    def _layer(self,name):
        self._text["layer"]=name; self._label_keys()
    def _type(self,text):
        st=self._text; e=st["entry"]; value=e.get_text()
        if st["max"] and len(value)>=st["max"]: return
        e.set_text(value+text)
        if st["layer"]=="upper" and not st["digits"]: self._layer("lower")   # one capital, like a phone keyboard
    def _erase(self):
        e=self._text["entry"]; e.set_text(e.get_text()[:-1])
    def _text_key(self,keyval):
        """With a key of the on-screen keyboard selected, a real keyboard still types into the text."""
        if keyval==Gdk.KEY_BackSpace: self._erase(); return True
        if keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter): return False   # activates the selected key
        ch=Gdk.keyval_to_unicode(keyval)
        if ch>=32 and chr(ch).isprintable() and (not self._text["digits"] or chr(ch).isdigit()):
            e=self._text["entry"]; value=e.get_text()
            if not self._text["max"] or len(value)<self._text["max"]: e.set_text(value+chr(ch))
            return True
        return False
    def ask_search(self):
        """The search field typed with the on-screen keyboard (Enter on the empty search field)."""
        def done(text):
            self.search_entry.set_text(text); self.search_entry.grab_focus(); self.search_entry.set_position(-1)
        self.ask_text("Search",done,self.search_entry.get_text(),"Apps, channels, workspaces or window titles.",ok_label="Search")

    def choose_option(self,title,options,current,callback,back=None):
        """A small pop-up listing the choices for a setting, with the current one ticked. back() runs on Cancel."""
        self._begin_modal(); self._title(title); groups=[]; focus=None
        for key,label in options:
            chosen=key==current
            b=self.dialog_button("object-select-symbolic" if chosen else None,"✓" if chosen else "",label)
            b.connect("clicked",lambda _b,k=key:(self.close_modal(),callback(k))); self.modal_card.append(b); groups.append(NavGroup([b]))
            if chosen: focus=b
        cancelled=back or self.close_modal
        cancel=Gtk.Button(label="Cancel"); cancel.set_margin_top(S(8)); cancel.connect("clicked",lambda *_:cancelled()); self.modal_card.append(cancel); groups.append(NavGroup([cancel]))
        self._modal_groups=groups; self._modal_back=cancelled; (focus or groups[0][0]).grab_focus()

    def choose_profile(self,callback):
        """Pick an application: favorites first, then apps with channel numbers, then everything else."""
        self._begin_modal(); self._title("Choose an application")
        scroll=Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC); scroll.set_max_content_height(S(380)); scroll.set_propagate_natural_height(True)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(2)); scroll.set_child(box); self.modal_card.append(scroll)
        groups=[]; apps=self.app.catalogue.by_id()
        for heading,profiles in startup_choices(self.app.store.profiles):
            box.append(section_title(heading))
            for p in profiles:
                a=apps.get(p.desktop_id); b=Gtk.Button(); b.add_css_class("launch-row")
                row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10)); row.append(app_icon(a.icon if a else None,p.name,28))
                if p.channel is not None:
                    ch=Gtk.Label(label=self.app.store.channel_text(p.channel)); ch.add_css_class("channel-number"); row.append(ch)
                l=Gtk.Label(label=p.name); l.set_xalign(0); l.set_hexpand(True); l.set_ellipsize(3); row.append(l)
                detail=profile_detail(p,a)
                if detail:
                    d=Gtk.Label(label=detail); d.add_css_class("muted"); d.set_ellipsize(3); row.append(d)
                b.set_child(row); b.connect("clicked",lambda _b,prof=p:(self.close_modal(),callback(prof))); box.append(b); groups.append(NavGroup([b]))
        cancel=Gtk.Button(label="Cancel"); cancel.set_margin_top(S(8)); cancel.connect("clicked",lambda *_:self.close_modal()); self.modal_card.append(cancel); groups.append(NavGroup([cancel]))
        self._modal_groups=groups; self._modal_back=self.close_modal; groups[0][0].grab_focus()

    def assign_hotkey(self,owner,label,on_set,back=None):
        """Choose a hotkey for `owner` (("slot", device, action) or ("profile", id)) and pass it to on_set ("" clears it).
        A key that something else already has is only taken from it after a warning and a confirmation.
        back() runs instead of closing the dialog when it is cancelled."""
        store=self.app.store
        def got(spec):
            other=store.hotkey_owner(spec,owner) if spec else None
            if other is None: on_set(spec); return
            taken=store.owner_label(other)
            self.confirm("Hotkey already in use",f"{describe(spec)} is already the hotkey for “{taken}”. Use it for “{label}” instead? "
                         f"“{taken}” will no longer have a hotkey.","Use it here",lambda:on_set(spec),back=back)
        self.capture_hotkey(label,got,can_clear=True,cancelled=back)

    def show_app_hotkeys(self,changed=None):
        """The applications that have a hotkey: change or remove each one's. changed() runs after every change."""
        self._begin_modal(); self._title("Application hotkeys"); groups=[]
        again=lambda:self.show_app_hotkeys(changed)
        def set_key(profile_id,spec):
            self.app.set_profile_hotkey(profile_id,spec)
            if changed: changed()
            again()
        profiles=self.app.store.hotkey_profiles()
        if not profiles: self.modal_card.append(muted_label("No application has a hotkey yet. Give an app a hotkey with ✎ beside it in Applications."))
        scroll=Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC); scroll.set_max_content_height(S(380)); scroll.set_propagate_natural_height(True)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=S(4)); scroll.set_child(box); self.modal_card.append(scroll)
        apps=self.app.catalogue.by_id()
        for p in profiles:
            a=apps.get(p.desktop_id); row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(10))
            row.append(app_icon(a.icon if a else None,p.name,28))
            name=Gtk.Label(label=p.name); name.set_xalign(0); name.set_hexpand(True); name.set_ellipsize(3); row.append(name)
            key=Gtk.Label(label=describe(p.hotkey)); key.add_css_class("setting-value"); row.append(key)
            change=Gtk.Button(); change.add_css_class("square"); change.set_child(glyph("document-edit-symbolic","✎")); change.set_tooltip_text(f"Change the hotkey for {p.name}")
            change.connect("clicked",lambda _b,prof=p:self.assign_hotkey(("profile",prof.id),prof.name,lambda spec,pid=prof.id:set_key(pid,spec),back=again))
            remove=Gtk.Button(); remove.add_css_class("square"); remove.add_css_class("close-button"); remove.set_child(glyph("window-close-symbolic","✕")); remove.set_tooltip_text(f"Remove the hotkey for {p.name}")
            remove.connect("clicked",lambda _b,pid=p.id:set_key(pid,""))
            row.append(change); row.append(remove); box.append(row); groups.append(NavGroup([change,remove]))
        close=Gtk.Button(label="Close"); close.set_margin_top(S(8)); close.connect("clicked",lambda *_:self.close_modal()); self.modal_card.append(close); groups.append(NavGroup([close]))
        self._modal_groups=groups; self._modal_back=self.close_modal; groups[0][0].grab_focus()

    def capture_hotkey(self,label,callback,can_clear=False,cancelled=None):
        """Wait for a key or combination and pass its spec to callback; with can_clear, a Clear button passes "".
        cancelled() runs when it is cancelled instead of nothing."""
        self._begin_modal(); self._title("New hotkey"); self.modal_card.append(muted_label(f"Press the key or key combination for “{label}”.\nTap a modifier on its own (such as Super) to use it by itself. "
                                                                                   "The arrow keys and OK move to and press Cancel or Clear; Back cancels."))
        row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=S(6)); row.set_homogeneous(True); row.set_margin_top(S(14))
        cancel=Gtk.Button(label="Cancel"); cancel.connect("clicked",lambda *_:self._end_capture(None)); row.append(cancel); buttons=[cancel]
        if can_clear:
            clear=Gtk.Button(label="Clear"); clear.connect("clicked",lambda *_:self._end_capture("")); row.append(clear); buttons.append(clear)
        self.modal_card.append(row)
        self._modal_groups=[buttons]; self._modal_back=lambda:self._end_capture(None); self._capture=HotkeyCapture(); self._capture_cb=callback; self._capture_cancel=cancelled; cancel.grab_focus()
    def _capture_key(self,keyval,state):
        """True when the key was taken as (part of) the hotkey. The D-pad and OK keys on their own are not: they move
        between Cancel and Clear and press them (hotkeys.is_navigation)."""
        name=Gdk.keyval_name(keyval) or ""
        held=held_modifiers(state)
        if keyval in (Gdk.KEY_Escape,Gdk.KEY_Back) and not held: self._end_capture(None); return True
        if is_navigation(name,held): return False
        spec=self._capture.press(name,held)
        if spec: self._end_capture(spec)
        return True
    def _end_capture(self,spec):
        callback=self._capture_cb; cancelled=self._capture_cancel; self._capture=None; self._capture_cb=None; self._capture_cancel=None; self.close_modal()
        if spec is not None and callback: callback(spec)   # "" is Clear
        elif spec is None and cancelled: cancelled()
