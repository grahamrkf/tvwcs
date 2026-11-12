"""The on-screen keyboard, for typing with a remote. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs.core.hotkeys import HotkeyCapture, describe, is_navigation
from tvwcs.core.model import profile_detail, startup_choices
from tvwcs.ui.widgets import NavGroup, S, app_icon, glyph, held_modifiers, muted_label, section_title


class OnScreenKeyboardMixin:
    """The on-screen keyboard, for typing with a remote."""

    # ---------------------------------------------------------- the on-screen keyboard (typing with a remote)
    KEYS = {
        "lower": ("1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"),
        "upper": ("1234567890", "QWERTYUIOP", 'ASDFGHJKL"', "ZXCVBNM;:_"),
        "symbols": ("!@#$%^&*()", "~`+=[]{}\\|", "/?<>€£¥§°¿", "…·•×÷¡«»¢¤"),
    }

    def ask_text(
        self,
        title,
        callback,
        initial="",
        message="",
        back=None,
        digits=False,
        secret=False,
        ok_label="OK",
        max_len=0,
        error="",
        keyboard=None,
    ):
        """Type a piece of text with the D-pad or a real keyboard. callback(text) runs on OK or Enter; Cancel or Back
        runs back() (or just closes). With digits (a PIN), only the number pad is offered. Otherwise the on-screen
        keyboard is hidden, full (letters, capitals, symbols) or a number pad, as it was last left (settings
        "keyboard"), and buttons change between them, keeping what is typed."""
        st = self.app.store.settings
        kind = "digits" if digits else (keyboard or st.get("keyboard", "hidden"))
        if kind not in ("hidden", "full", "digits"):
            kind = "hidden"
        self._begin_modal()
        self._title(title)
        if message:
            m = muted_label(message)
            m.set_margin_bottom(S(8))
            self.modal_card.append(m)
        if error:
            e = Gtk.Label(label=error)
            e.add_css_class("error")
            e.set_wrap(True)
            e.set_xalign(0)
            e.set_margin_bottom(S(8))
            self.modal_card.append(e)
        entry = Gtk.PasswordEntry() if secret else Gtk.Entry()
        if secret:
            entry.set_show_peek_icon(True)
        entry.add_css_class("pin-display" if kind == "digits" else "text-display")
        entry.set_text(initial or "")
        entry.set_margin_bottom(S(8))
        if max_len and not secret:
            entry.set_max_length(max_len)
        self.modal_card.append(entry)
        cancelled = back or self.close_modal

        def submit(*_):
            text = entry.get_text()
            self.close_modal()
            callback(text)

        entry.connect("activate", submit)
        self._text = {
            "entry": entry,
            "submit": submit,
            "layer": "lower",
            "keys": [],
            "digits": kind == "digits" and digits,
            "max": max_len,
            "secret": secret,
        }

        def switch(to):  # another keyboard, with what is typed so far; remembered for next time
            typed = entry.get_text()
            self._remember_keyboard(to)
            self.ask_text(title, callback, typed, message, back, digits, secret, ok_label, max_len, error, keyboard=to)

        groups = [NavGroup([entry])]

        def key(text, handler, css=None):
            b = Gtk.Button(label=text)
            b.add_css_class("pin-key")
            if css:
                b.add_css_class(css)
            b.connect("clicked", lambda *_: handler())
            return b

        def line(buttons):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
            box.set_homogeneous(True)
            box.set_margin_bottom(S(4))
            for b in buttons:
                box.append(b)
            self.modal_card.append(box)
            g = NavGroup(buttons)
            g.column = True
            groups.append(g)

        if kind == "hidden":
            show = key("⌨  Show keyboard", lambda: switch("full"))
            ok = key(ok_label, submit, "active")
            line([show, ok])
        elif kind == "digits":
            for row in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9")):
                line([key(d, lambda d=d: self._type(d)) for d in row])
            line([key("⌫", self._erase), key("0", lambda: self._type("0")), key(ok_label, submit, "active")])
            if not digits:
                line(
                    [key("ABC  Full keyboard", lambda: switch("full")), key("Hide keyboard", lambda: switch("hidden"))]
                )
        else:
            for r in range(4):
                buttons = [
                    key("", lambda r=r, c=c: self._type(self.KEYS[self._text["layer"]][r][c]), "kb-key")
                    for c in range(10)
                ]
                self._text["keys"].append(buttons)
                line(buttons)
            shift = key("⇧", lambda: self._layer("lower" if self._text["layer"] == "upper" else "upper"))
            symbols = key("&123", lambda: self._layer("lower" if self._text["layer"] == "symbols" else "symbols"))
            space = key("Space", lambda: self._type(" "))
            erase = key("⌫", self._erase)
            ok = key(ok_label, submit, "active")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
            box.set_margin_bottom(S(4))
            for b in (shift, symbols, space, erase, ok):
                b.add_css_class("kb-key")
                box.append(b)
            space.set_hexpand(True)
            for b, w in ((shift, 56), (symbols, 64), (erase, 56), (ok, 88)):
                b.set_size_request(S(w), -1)
            self.modal_card.append(box)
            g = NavGroup([shift, symbols, space, erase, ok])
            groups.append(g)
            pad = key("123  Number pad", lambda: switch("digits"), "kb-key")
            hide = key("Hide keyboard", lambda: switch("hidden"), "kb-key")
            line([pad, hide])
            self._text["shift"] = shift
            self._text["symbols"] = symbols
            self._label_keys()
        cancel = Gtk.Button(label="Cancel")
        cancel.set_margin_top(S(6))
        cancel.connect("clicked", lambda *_: cancelled())
        self.modal_card.append(cancel)
        groups.append(NavGroup([cancel]))
        self._modal_groups = groups
        self._modal_back = cancelled
        first = entry if kind == "hidden" else groups[1][0]
        first.grab_focus()
        GLib.timeout_add(
            150,
            lambda: (
                self._text is not None
                and self._text["entry"] is entry
                and self.get_focus() is None
                and first.grab_focus(),
                GLib.SOURCE_REMOVE,
            )[1],
        )

    def _remember_keyboard(self, kind):
        """The on-screen keyboard was changed: the next text dialog opens with it."""
        store = self.app.store
        if store.settings.get("keyboard") != kind:
            store.settings["keyboard"] = kind
            try:
                store.save()
            except OSError:
                pass

    def _label_keys(self):
        st = self._text
        rows = self.KEYS[st["layer"]]
        for r, buttons in enumerate(st["keys"]):
            for c, b in enumerate(buttons):
                b.set_label(rows[r][c])
        (st["shift"].add_css_class if st["layer"] == "upper" else st["shift"].remove_css_class)("active")
        st["symbols"].set_label("abc" if st["layer"] == "symbols" else "&123")

    def _layer(self, name):
        self._text["layer"] = name
        self._label_keys()

    def _type(self, text):
        st = self._text
        e = st["entry"]
        value = e.get_text()
        if st["max"] and len(value) >= st["max"]:
            return
        e.set_text(value + text)
        if st["layer"] == "upper" and not st["digits"]:
            self._layer("lower")  # one capital, like a phone keyboard

    def _erase(self):
        e = self._text["entry"]
        e.set_text(e.get_text()[:-1])

    def _text_key(self, keyval):
        """With a key of the on-screen keyboard selected, a real keyboard still types into the text."""
        if keyval == Gdk.KEY_BackSpace:
            self._erase()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False  # activates the selected key
        ch = Gdk.keyval_to_unicode(keyval)
        if ch >= 32 and chr(ch).isprintable() and (not self._text["digits"] or chr(ch).isdigit()):
            e = self._text["entry"]
            value = e.get_text()
            if not self._text["max"] or len(value) < self._text["max"]:
                e.set_text(value + chr(ch))
            return True
        return False

    def ask_search(self):
        """The search field typed with the on-screen keyboard (Enter on the empty search field)."""

        def done(text):
            self.search_entry.set_text(text)
            self.search_entry.grab_focus()
            self.search_entry.set_position(-1)

        self.ask_text(
            "Search",
            done,
            self.search_entry.get_text(),
            "Apps, channels, workspaces or window titles.",
            ok_label="Search",
        )

    def choose_option(self, title, options, current, callback, back=None):
        """A small pop-up listing the choices for a setting, with the current one ticked. back() runs on Cancel."""
        self._begin_modal()
        self._title(title)
        groups = []
        focus = None
        for key, label in options:
            chosen = key == current
            b = self.dialog_button("object-select-symbolic" if chosen else None, "✓" if chosen else "", label)
            b.connect("clicked", lambda _b, k=key: (self.close_modal(), callback(k)))
            self.modal_card.append(b)
            groups.append(NavGroup([b]))
            if chosen:
                focus = b
        cancelled = back or self.close_modal
        cancel = Gtk.Button(label="Cancel")
        cancel.set_margin_top(S(8))
        cancel.connect("clicked", lambda *_: cancelled())
        self.modal_card.append(cancel)
        groups.append(NavGroup([cancel]))
        self._modal_groups = groups
        self._modal_back = cancelled
        (focus or groups[0][0]).grab_focus()

    def choose_profile(self, callback):
        """Pick an application: favorites first, then apps with channel numbers, then everything else."""
        self._begin_modal()
        self._title("Choose an application")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(S(380))
        scroll.set_propagate_natural_height(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        scroll.set_child(box)
        self.modal_card.append(scroll)
        groups = []
        apps = self.app.catalogue.by_id()
        for heading, profiles in startup_choices(self.app.store.profiles):
            box.append(section_title(heading))
            for p in profiles:
                a = apps.get(p.desktop_id)
                b = Gtk.Button()
                b.add_css_class("launch-row")
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
                row.append(app_icon(a.icon if a else None, p.name, 28))
                if p.channel is not None:
                    ch = Gtk.Label(label=self.app.store.channel_text(p.channel))
                    ch.add_css_class("channel-number")
                    row.append(ch)
                l = Gtk.Label(label=p.name)
                l.set_xalign(0)
                l.set_hexpand(True)
                l.set_ellipsize(3)
                row.append(l)
                detail = profile_detail(p, a)
                if detail:
                    d = Gtk.Label(label=detail)
                    d.add_css_class("muted")
                    d.set_ellipsize(3)
                    row.append(d)
                b.set_child(row)
                b.connect("clicked", lambda _b, prof=p: (self.close_modal(), callback(prof)))
                box.append(b)
                groups.append(NavGroup([b]))
        cancel = Gtk.Button(label="Cancel")
        cancel.set_margin_top(S(8))
        cancel.connect("clicked", lambda *_: self.close_modal())
        self.modal_card.append(cancel)
        groups.append(NavGroup([cancel]))
        self._modal_groups = groups
        self._modal_back = self.close_modal
        groups[0][0].grab_focus()

    def assign_hotkey(self, owner, label, on_set, back=None):
        """Choose a hotkey for `owner` (("slot", device, action) or ("profile", id)) and pass it to on_set ("" clears it).
        A key that something else already has is only taken from it after a warning and a confirmation.
        back() runs instead of closing the dialog when it is cancelled."""
        store = self.app.store

        def got(spec):
            other = store.hotkey_owner(spec, owner) if spec else None
            if other is None:
                on_set(spec)
                return
            taken = store.owner_label(other)
            self.confirm(
                "Hotkey already in use",
                f"{describe(spec)} is already the hotkey for “{taken}”. Use it for “{label}” instead? "
                f"“{taken}” will no longer have a hotkey.",
                "Use it here",
                lambda: on_set(spec),
                back=back,
            )

        self.capture_hotkey(label, got, can_clear=True, cancelled=back)

    def show_app_hotkeys(self, changed=None):
        """The applications that have a hotkey: change or remove each one's. changed() runs after every change."""
        self._begin_modal()
        self._title("Application hotkeys")
        groups = []
        again = lambda: self.show_app_hotkeys(changed)

        def set_key(profile_id, spec):
            self.app.set_profile_hotkey(profile_id, spec)
            if changed:
                changed()
            again()

        profiles = self.app.store.hotkey_profiles()
        if not profiles:
            self.modal_card.append(
                muted_label("No application has a hotkey yet. Give an app a hotkey with ✎ beside it in Applications.")
            )
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(S(380))
        scroll.set_propagate_natural_height(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        scroll.set_child(box)
        self.modal_card.append(scroll)
        apps = self.app.catalogue.by_id()
        for p in profiles:
            a = apps.get(p.desktop_id)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
            row.append(app_icon(a.icon if a else None, p.name, 28))
            name = Gtk.Label(label=p.name)
            name.set_xalign(0)
            name.set_hexpand(True)
            name.set_ellipsize(3)
            row.append(name)
            key = Gtk.Label(label=describe(p.hotkey))
            key.add_css_class("setting-value")
            row.append(key)
            change = Gtk.Button()
            change.add_css_class("square")
            change.set_child(glyph("document-edit-symbolic", "✎"))
            change.set_tooltip_text(f"Change the hotkey for {p.name}")
            change.connect(
                "clicked",
                lambda _b, prof=p: self.assign_hotkey(
                    ("profile", prof.id), prof.name, lambda spec, pid=prof.id: set_key(pid, spec), back=again
                ),
            )
            remove = Gtk.Button()
            remove.add_css_class("square")
            remove.add_css_class("close-button")
            remove.set_child(glyph("window-close-symbolic", "✕"))
            remove.set_tooltip_text(f"Remove the hotkey for {p.name}")
            remove.connect("clicked", lambda _b, pid=p.id: set_key(pid, ""))
            row.append(change)
            row.append(remove)
            box.append(row)
            groups.append(NavGroup([change, remove]))
        close = Gtk.Button(label="Close")
        close.set_margin_top(S(8))
        close.connect("clicked", lambda *_: self.close_modal())
        self.modal_card.append(close)
        groups.append(NavGroup([close]))
        self._modal_groups = groups
        self._modal_back = self.close_modal
        groups[0][0].grab_focus()

    def capture_hotkey(self, label, callback, can_clear=False, cancelled=None):
        """Wait for a key or combination and pass its spec to callback; with can_clear, a Clear button passes "".
        cancelled() runs when it is cancelled instead of nothing."""
        self._begin_modal()
        self._title("New hotkey")
        self.modal_card.append(
            muted_label(
                f"Press the key or key combination for “{label}”.\nTap a modifier on its own (such as Super) to use it by itself. "
                "The arrow keys and OK move to and press Cancel or Clear; Back cancels."
            )
        )
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(6))
        row.set_homogeneous(True)
        row.set_margin_top(S(14))
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self._end_capture(None))
        row.append(cancel)
        buttons = [cancel]
        if can_clear:
            clear = Gtk.Button(label="Clear")
            clear.connect("clicked", lambda *_: self._end_capture(""))
            row.append(clear)
            buttons.append(clear)
        self.modal_card.append(row)
        self._modal_groups = [buttons]
        self._modal_back = lambda: self._end_capture(None)
        self._capture = HotkeyCapture()
        self._capture_cb = callback
        self._capture_cancel = cancelled
        cancel.grab_focus()

    def _capture_key(self, keyval, state):
        """True when the key was taken as (part of) the hotkey. The D-pad and OK keys on their own are not: they move
        between Cancel and Clear and press them (hotkeys.is_navigation)."""
        name = Gdk.keyval_name(keyval) or ""
        held = held_modifiers(state)
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Back) and not held:
            self._end_capture(None)
            return True
        if is_navigation(name, held):
            return False
        spec = self._capture.press(name, held)
        if spec:
            self._end_capture(spec)
        return True

    def _end_capture(self, spec):
        callback = self._capture_cb
        cancelled = self._capture_cancel
        self._capture = None
        self._capture_cb = None
        self._capture_cancel = None
        self.close_modal()
        if spec is not None and callback:
            callback(spec)  # "" is Clear
        elif spec is None and cancelled:
            cancelled()
