"""The TVWCS window: Quick Menu | Applications, in one borderless sway window.

TVWCSWindow is built here (construction, closing when focus leaves); each other part of it is a mixin in its own
file: status_panels.py (the bottom row and its panels), quick_menu.py, applications_pane.py, search.py,
navigation.py (remote and keyboard), dialogs.py and onscreen_keyboard.py. They share the window's state on self.
TVWCS's own options are a page of the Settings app (channel 0, or ⚙)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs.core.model import MAIN_TITLE, corner_right, corner_top
from tvwcs.ui.theme import render_css
from tvwcs.system import cursor
from tvwcs.ui.widgets import PointerWatch, S, flip_children, icon_button, mirror, use_retro
from tvwcs.ui.applications_pane import ApplicationsPaneMixin
from tvwcs.ui.dialogs import DialogsMixin
from tvwcs.ui.navigation import NavigationMixin
from tvwcs.ui.onscreen_keyboard import OnScreenKeyboardMixin
from tvwcs.ui.quick_menu import QuickMenuMixin
from tvwcs.ui.search import SearchMixin
from tvwcs.ui.status_panels import StatusPanelsMixin


class TVWCSWindow(
    StatusPanelsMixin,
    QuickMenuMixin,
    ApplicationsPaneMixin,
    SearchMixin,
    NavigationMixin,
    DialogsMixin,
    OnScreenKeyboardMixin,
    Gtk.ApplicationWindow,
):
    """One borderless window holding two panels side by side. The Quick Menu is always there; the
    Applications pane opens beside it, to its right (to its left with the Quick Menu in a right-hand corner).
    The Quick Menu is built for the bottom-left corner. In a right-hand corner GTK lays it out right to left (mirror);
    in a top corner its stacks are put the other way up (flip_children) and ↑/↓ work the other way round."""

    search_folds = False
    search_line = None
    search_button = None  # the search_icon setting (_build_quick_pane)

    def __init__(self, app):
        super().__init__(application=app, title=MAIN_TITLE)
        self.app = app
        self.guide_open = False
        self.options_open = False
        self.guide_pane = None
        self.options_pane = None
        self.guide_scroll = None
        self.guide_button = None
        self.quick_content = None
        self.apps_title = None
        self.apps_subtitle = None
        self._channel_source = 0
        self._capture_cancel = None
        self._provider = None
        self._expanded = {"Media", "Internet", "Games"}
        self._guide_scroll = 0.0
        self._popovers = 0
        self._was_active = False
        self._capture = None
        self._capture_cb = None
        self._pin = None
        self._panel_token = 0
        self._volume_target = {}
        self._volume_busy = set()
        self.launching = set()
        self._launch_slots = []  # profiles starting now: their buttons show a spinner (set_launching)
        self._reset_nav()
        self.set_decorated(False)
        self.set_hide_on_close(True)
        self.set_resizable(True)
        self.add_css_class("tvwcs-window")
        self.pointer = PointerWatch(
            self, lambda: cursor.hide_ms(self.app.store.settings)
        )  # hover colours only while the mouse is in use
        key = Gtk.EventControllerKey()
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._key_pressed)
        key.connect("key-released", self._key_released)
        self.add_controller(key)
        self.connect("notify::focus-widget", self._focus_changed)
        self.connect("notify::is-active", self._active_changed)
        self._build()

    @property
    def right(self):
        return corner_right(self.app.store.settings.get("quick_corner"))  # the Quick Menu is mirrored

    @property
    def top(self):
        return corner_top(self.app.store.settings.get("quick_corner"))  # ... and stacked the other way up

    def _mirror(self, widget):
        if widget is not None and self.right:
            mirror(widget)

    def _flip(self, box):
        if self.top:
            flip_children(box)

    def _flip_margins(self, widget):
        if self.top:
            t, b = widget.get_margin_top(), widget.get_margin_bottom()
            widget.set_margin_top(b)
            widget.set_margin_bottom(t)

    def guide_hint(self):
        """Where Applications is, for the notes that point to it: ⊞ is in the clock's row, at the far side from the corner."""
        side = ("top" if self.top else "bottom") + "-" + ("left" if self.right else "right")
        return f"Press {'←' if self.right else '→'} (or ⊞ in the {side} corner of this menu)"

    def _reset_nav(self):
        self._groups = {"quick": [], "guide": [], "options": []}
        self._header_group = []
        self._search_results = []
        self._selected_result = 0
        self._result_groups = []
        self._result_mains = []
        self._stars = {}
        self._modal_groups = []
        self._modal_back = None
        self._return_focus = None
        self._last_focus = {}
        self._pin = None
        self._chan = None
        self._open_row = None
        self._text = None
        self._panel_key = None
        self._panel_groups = []
        self._panel_prefer = None
        self._panel_busy = False
        self._keep_panel = False
        self._panel_placeholder = False
        self._descriptions = []

    # ================================================================== construction
    def _build(self):
        if self.guide_scroll is not None:
            self._guide_scroll = self.guide_scroll.get_vadjustment().get_value()
        self._reset_nav()
        self.guide_pane = None
        self.options_pane = None
        self.guide_scroll = None
        layout = self.app.layout
        self.set_child(None)
        self._install_css()
        overlay = Gtk.Overlay()
        overlay.add_css_class("tvwcs-root")
        self.panes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.quick_pane = self._build_quick_pane(layout.quick_width)
        self.panes.append(self.quick_pane)
        overlay.set_child(self.panes)
        self.modal_layer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.modal_layer.add_css_class("modal-scrim")
        self.modal_reveal = Gtk.Revealer()
        self.modal_reveal.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.modal_reveal.set_transition_duration(120)
        self.modal_reveal.set_child(self.modal_layer)
        self.modal_reveal.set_can_target(False)
        self.modal_reveal.set_visible(False)
        self.modal_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(6))
        self.modal_card.add_css_class("modal-card")
        self.modal_card.set_halign(Gtk.Align.CENTER)
        self.modal_card.set_valign(Gtk.Align.CENTER)
        self.modal_card.set_hexpand(True)
        self.modal_card.set_vexpand(True)
        self._card_width = min(S(440), max(S(280), layout.quick_width - S(40)))
        self.modal_card.set_size_request(self._card_width, -1)
        self.modal_layer.append(self.modal_card)
        overlay.add_overlay(self.modal_reveal)
        self.set_child(overlay)
        self._mirror(self.panes)  # not the dialogs drawn over them: a keyboard or number pad keeps its order
        self.set_panels(self.guide_open, self.options_open)
        self._refresh_search_results()

    def _install_css(self):
        display = Gdk.Display.get_default()
        if self._provider is None:
            self._provider = Gtk.CssProvider()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        settings = self.app.store.settings
        font = settings.get("retro_font", "pixel")
        use_retro(settings.get("style") == "retro", font)  # before the widgets: their icons depend on it
        self._provider.load_from_data(
            render_css(
                settings["accent"],
                self.app.scale_factor,
                theme=settings.get("theme", "dark"),
                style=settings.get("style", "modern"),
                phosphor=settings.get("phosphor", "green"),
                retro_font=font,
                media=settings.get("media_look", "jellyfin"),
            ).encode("utf-8")
        )

    def set_panels(self, guide, options=None):
        """Show or hide the Applications pane, built once and kept, so closing and opening it again never disturbs
        scroll positions, open categories or focus. `options` is accepted for older callers but opens nothing."""
        guide = bool(guide)
        self.guide_open = guide
        self.options_open = False
        if guide and self.guide_pane is None:
            self.guide_pane = self._build_guide_pane()
            self.panes.append(self.guide_pane)
            self._mirror(self.guide_pane)
        layout = self.app.layout
        self.quick_pane.set_size_request(layout.quick_width, -1)
        if self.guide_pane is not None:
            self.guide_pane.set_visible(guide)
        if self.guide_button is not None:
            (self.guide_button.add_css_class if guide else self.guide_button.remove_css_class)("active")
            self.guide_button.set_tooltip_text(
                "Close Applications" if guide else f"Open Applications ({'←' if self.right else '→'})"
            )

    def _build_quick_pane(self, width):
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        pane.add_css_class("pane")
        pane.set_size_request(width, -1)
        pane.set_hexpand(False)
        # Desktop mode: "TVWCS" and ✕ close at the top (power and Applications are at the bottom, after the status
        # icons). TV mode has no header: the remote's Back key closes the Quick Menu.
        buttons = []
        if not self.app.tv:
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
            header.set_margin_top(S(14))
            header.set_margin_start(S(20))
            header.set_margin_end(S(20))
            header.set_margin_bottom(S(10))
            title = Gtk.Label(label="TVWCS")
            title.add_css_class("brand")
            title.set_xalign(0)
            title.set_hexpand(True)
            header.append(title)
            close_btn = icon_button("window-close-symbolic", "✕", "Close")
            close_btn.add_css_class("close-button")
            close_btn.add_css_class("square")
            close_btn.connect("clicked", lambda *_: self.app.hide_window())
            buttons.append(close_btn)
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
            controls.add_css_class("window-controls")
            for b in buttons:
                controls.append(b)
            header.append(controls)
            pane.append(header)
            self._flip_margins(header)
        else:  # space inside the pane, not a margin outside it, which would show the window's black background above it
            top = Gtk.Box()
            top.set_size_request(-1, S(14))
            pane.append(top)
        self._header_group = buttons
        # Everything below the header sits at the bottom, nearest the search field: favorites and open applications, the
        # search results, the search field, then the status row. The space left over (on a TV, or with Applications
        # open) is above them. At a desk the window is only as tall as all this (main.fit_quick_menu).
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(10))
        body.set_margin_start(S(20))
        body.set_margin_end(S(20))
        body.set_margin_top(S(4))
        body.set_margin_bottom(S(10))
        body.set_vexpand(True)
        pane.append(body)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        body.append(scroll)
        self._flip_margins(body)
        toward = Gtk.Align.START if self.top else Gtk.Align.END  # toward the search field
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        content.set_valign(toward)
        scroll.set_child(content)
        self.quick_content = content
        self.quick_scroll = scroll
        scroll.get_vadjustment().connect(
            "changed", self._keep_at_bottom
        )  # what overflows is above: start at the bottom
        self._build_quick_content(content)
        self.results_scroll = Gtk.ScrolledWindow()
        self.results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.results_scroll.set_max_content_height(S(280))
        self.results_scroll.set_propagate_natural_height(True)
        self.results_scroll.set_visible(False)
        self.results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        self.results_box.set_valign(toward)
        self.results_scroll.set_child(self.results_box)
        body.append(self.results_scroll)
        self.results_scroll.get_vadjustment().connect("changed", self._keep_at_bottom)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.connect("search-changed", lambda *_: self._refresh_search_results())
        self.search_entry.connect("activate", self._activate_search)
        self.search_entry.connect("changed", self._search_typed)
        # On a TV the field is as wide as a channel number, with what to type beside it; it stretches once letters (or
        # one digit too many) show it is a search. At a desk it is one full-width field.
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
        line.append(self.search_entry)
        self.channel_hint = Gtk.Label(label="Channel number or search")
        self.channel_hint.add_css_class("channel-hint")
        self.channel_hint.set_xalign(0)
        self.channel_hint.set_hexpand(True)
        self.channel_hint.set_wrap(True)
        line.append(self.channel_hint)
        body.append(line)
        self._search_narrow = None
        self._shape_search()
        # With the search_icon setting the bar stays folded away until the search icon (in the status row) opens it, or
        # typing anywhere does; it folds again once the selection leaves it empty (_fold_search).
        self.search_line = line
        self.search_folds = bool(self.app.store.settings.get("search_icon", False))
        line.set_visible(not self.search_folds)
        # what a status icon (or ⏻) unfolds: above the status row, a little indented, like a row's options
        self.status_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        self.status_panel.add_css_class("status-panel")
        self.status_panel.set_visible(False)
        self.status_panel.set_margin_start(S(34))
        self.status_panel.set_margin_end(S(34))
        self.status_panel.set_margin_bottom(S(4))
        pane.append(self.status_panel)
        self._flip_margins(self.status_panel)
        pane.append(self._build_status_bar())
        self._flip(body)
        self._flip(pane)  # in a top corner: the status rows at the top, then the search field, then the lists
        return pane

    def quick_height(self, width):
        """How tall the Quick Menu needs to be, at `width`, to show everything in it without scrolling, or a card
        drawn over it (the on-screen keyboard), whichever is taller."""
        height = self.quick_pane.measure(Gtk.Orientation.VERTICAL, width)[1]
        if self.modal_reveal.get_visible():
            card = self.modal_card.measure(Gtk.Orientation.VERTICAL, self._card_width)[1]
            height = max(height, card + 2 * S(24))  # with a little of the scrim around it
        return height

    def _shape_search(self):
        """TV: a narrow channel field with its hint while the text could still be a channel number (empty, or up to
        the channel_digits setting's digits); the full width otherwise. Desktop: always the full width, without the hint.
        """
        e = self.search_entry
        q = e.get_text()
        tv = self.app.tv
        digits = self.app.store.channel_digits()
        narrow = tv and (q == "" or (q.isdigit() and len(q) <= digits))
        if getattr(self, "_search_narrow", None) == (narrow, digits):
            return
        self._search_narrow = (narrow, digits)
        e.set_hexpand(not narrow)
        e.set_halign(Gtk.Align.START if narrow else Gtk.Align.FILL)
        # the digits, + a little for the field's padding (the theme hides the ✕ while narrow)
        e.set_width_chars(digits + 1 if narrow else -1)
        e.set_max_width_chars(digits + 1 if narrow else -1)
        (e.add_css_class if narrow else e.remove_css_class)("channel-entry")
        (e.add_css_class if tv else e.remove_css_class)("tv-search")  # the app buttons' fill, no magnifier
        e.set_placeholder_text("_" * digits if narrow else "Search, or type a channel number")
        self.channel_hint.set_visible(narrow)

    # ---------------------------------------------------------- close when focus leaves
    def _active_changed(self, *_):
        if self.is_active():
            self._was_active = True
            # Clicking TVWCS brings it in front of an open dialog (profile editor, application profiles), which would
            # then sit hidden behind it, blocking it. Close the dialogs instead, dropping what was not saved.
            if self.app.has_dialogs():
                GLib.timeout_add(120, self._dismiss_dialogs_if_active)
            return
        if self._was_active and self.is_visible() and self.app.store.settings["close_on_click_outside"]:
            GLib.timeout_add(150, self._close_if_unfocused)

    def _close_if_unfocused(self):
        # Child windows (profile editor) and open popovers legitimately take focus; only a click elsewhere closes TVWCS.
        # Nor while an app starts: opening it in a workspace of its own moves the focus, and its button shows the spinner.
        if (
            self.is_visible()
            and not self.is_active()
            and self._popovers == 0
            and not self.app.has_dialogs()
            and not self.launching
        ):
            self.app.hide_window()
        return GLib.SOURCE_REMOVE

    def _dismiss_dialogs_if_active(self):
        if self.is_visible() and self.is_active():
            self.app.dismiss_dialogs()  # still in front: not a passing focus change
        return GLib.SOURCE_REMOVE

    def note_shown(self):
        self._was_active = False
