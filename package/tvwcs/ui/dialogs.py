"""Dialogs drawn over the panels, remote-navigable. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs.core.model import channel_range
from tvwcs.ui.widgets import NavGroup, S, clear_box, glyph, muted_label, usable


class DialogsMixin:
    """Dialogs drawn over the panels, so they cannot get lost behind the window."""

    # ---------------------------------------------------------- dialogs (drawn over the panels, remote-navigable)
    def _begin_modal(self):
        if not self._modal_groups:
            self._return_focus = self.get_focus()
        clear_box(self.modal_card)
        self.modal_card.set_size_request(self._card_width, -1)
        self.modal_reveal.set_visible(True)
        self.modal_reveal.set_can_target(True)
        self.modal_reveal.set_reveal_child(True)
        GLib.idle_add(lambda: (self.app.fit_quick_menu(), GLib.SOURCE_REMOVE)[1])  # once filled: taller for a keyboard

    def close_modal(self):
        if self._text is not None and self._text.get("secret"):
            self._text["entry"].set_text("")  # a typed password is never left in the widget
        self._modal_groups = []
        self._modal_back = None
        self._capture = None
        self._pin = None
        self._text = None
        self._chan = None
        self.modal_reveal.set_can_target(False)
        self.modal_reveal.set_reveal_child(False)
        self.modal_reveal.set_visible(False)
        self.app.fit_quick_menu()  # back to the Quick Menu's own height
        back = self._return_focus
        if back is not None and usable(back):
            back.grab_focus()
        else:
            self.focus_pane("quick")

    def _title(self, text):
        t = Gtk.Label(label=text)
        t.add_css_class("pane-title")
        t.set_xalign(0)
        t.set_wrap(True)
        t.set_margin_bottom(S(8))
        self.modal_card.append(t)

    def dialog_button(self, icon, fallback, text):
        b = Gtk.Button()
        b.add_css_class("dialog-button")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(14))
        g = glyph(icon, fallback, 24) if icon else Gtk.Label()
        g.set_size_request(S(28), -1)
        row.append(g)
        l = Gtk.Label(label=text)
        l.set_xalign(0)
        l.set_hexpand(True)
        l.set_wrap(True)
        l.set_max_width_chars(34)  # long labels wrap inside the Quick Menu
        row.append(l)
        b.set_child(row)
        return b

    def show_message(self, message, title="Something went wrong", done=None):
        """A message with an OK button, drawn in the window (no separate dialog window to lose behind TVWCS)."""
        self._begin_modal()
        self._title(title)
        text = muted_label(message)
        text.set_margin_bottom(S(14))
        self.modal_card.append(text)
        finish = lambda: (self.close_modal(), done and done())
        ok = Gtk.Button(label="OK")
        ok.add_css_class("active")
        ok.connect("clicked", lambda *_: finish())
        self.modal_card.append(ok)
        self._modal_groups = [NavGroup([ok])]
        self._modal_back = finish
        ok.grab_focus()

    def show_starting(self, name, on_back):
        """“Starting Kodi…” while an application opens its first window (main.App waits for it)."""
        self._begin_modal()
        self._title(f"Starting {name}…")
        spinner = Gtk.Spinner()
        spinner.set_size_request(S(48), S(48))
        spinner.set_halign(Gtk.Align.START)
        spinner.set_margin_bottom(S(10))
        spinner.start()
        self.modal_card.append(spinner)
        text = muted_label("It opens in a moment. Some apps take a few seconds the first time.")
        self.modal_card.append(text)
        self._starting_text = text
        hide = Gtk.Button(label="Hide")
        hide.set_margin_top(S(12))
        hide.connect("clicked", lambda *_: on_back())
        self.modal_card.append(hide)
        self._modal_groups = [NavGroup([hide])]
        self._modal_back = on_back
        hide.grab_focus()

    def starting_slow(self, name):
        if getattr(self, "_starting_text", None) is not None and self._modal_groups:
            self._starting_text.set_text(
                f"{name} has not opened a window yet. It may still be starting, or it may not have started."
            )

    def first_run(self, done):
        """The first time TVWCS opens: where it is used (TV or desk), then how to add favorites."""

        def picked(use):
            self.app.set_use(use)
            self.show_message(
                f"{self.guide_hint()} to see every application. Press ☆ beside the ones "
                "you use most to add them to this menu, and ✎ to give one a channel number or a hotkey. Everything else is in "
                f"Settings, channel {self.app.store.channel_text(0)}.",
                "Welcome to TVWCS",
                done,
            )

        self._begin_modal()
        self._title("Welcome to TVWCS")
        self.modal_card.append(muted_label("Where is this computer used? You can change this later in Settings."))
        groups = []
        for key, label, icon, fallback in (
            ("tv", "On a TV, with a remote", "video-display-symbolic", "▭"),
            ("desktop", "At a desk, with a mouse and keyboard", "input-mouse-symbolic", "🖱"),
        ):
            b = self.dialog_button(icon, fallback, label)
            b.connect("clicked", lambda _b, k=key: picked(k))
            self.modal_card.append(b)
            groups.append(NavGroup([b]))
        self._modal_groups = groups
        self._modal_back = lambda: picked("tv")
        groups[0][0].grab_focus()

    def confirm(self, title, message, label, on_confirm, back=None):
        """Ask before doing something destructive. Cancel is focused, so a stray Enter is harmless."""
        self._begin_modal()
        self._title(title)
        text = muted_label(message)
        text.set_margin_bottom(S(14))
        self.modal_card.append(text)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(6))
        row.set_homogeneous(True)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: (back or self.close_modal)())
        row.append(cancel)
        go = Gtk.Button(label=label)
        go.add_css_class("danger")
        go.connect("clicked", lambda *_: (self.close_modal(), on_confirm()))
        row.append(go)
        self.modal_card.append(row)
        self._modal_groups = [[cancel, go]]
        self._modal_back = back or self.close_modal
        cancel.grab_focus()

    def system_action(self, action):
        if action.confirm:
            self.confirm(f"{action.label}?", action.confirm, action.label, lambda a=action: self._execute(a))
        else:
            self._execute(action)

    def _execute(self, action):
        if action.id == "refresh":
            self.app.refresh_data(rebuild=True)
        else:
            self.app.run_system_action(action.id)

    def ask_pin(self, profile, on_ok, message=""):
        """A PIN keypad that works with a D-pad (and with digit keys). Runs on_ok() once the right PIN is entered."""
        self._begin_modal()
        self._title(f"PIN for {profile.name}")
        shown = Gtk.Label()
        shown.add_css_class("pin-display")
        shown.set_margin_bottom(S(8))
        self.modal_card.append(shown)
        if message:
            e = Gtk.Label(label=message)
            e.add_css_class("error")
            e.set_wrap(True)
            e.set_margin_bottom(S(8))
            self.modal_card.append(e)
        self._pin = {"profile": profile, "on_ok": on_ok, "digits": "", "shown": shown}
        self._pin_refresh()
        groups = []

        def key(text, handler, css=None):
            b = Gtk.Button(label=text)
            b.add_css_class("pin-key")
            if css:
                b.add_css_class(css)
            b.connect("clicked", lambda *_: handler())
            return b

        for digits in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"), (None, "0", None)):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
            line.set_homogeneous(True)
            line.set_margin_bottom(S(4))
            row = []
            for d in digits:
                if d is not None:
                    b = key(d, lambda d=d: self._pin_press(d))
                elif not row:
                    b = key("⌫", self._pin_back)
                else:
                    b = key("OK", self._pin_submit, "active")
                line.append(b)
                row.append(b)
            self.modal_card.append(line)
            g = NavGroup(row)
            g.column = True
            groups.append(g)
        cancel = Gtk.Button(label="Cancel")
        cancel.set_margin_top(S(6))
        cancel.connect("clicked", lambda *_: self.close_modal())
        self.modal_card.append(cancel)
        groups.append(NavGroup([cancel]))
        self._modal_groups = groups
        self._modal_back = self.close_modal
        groups[0][0].grab_focus()

    def _pin_refresh(self):
        n = len(self._pin["digits"])
        self._pin["shown"].set_text("  ".join("●" * n) if n else "– – – –")

    def _pin_press(self, digit):
        if len(self._pin["digits"]) < 8:
            self._pin["digits"] += digit
            self._pin_refresh()

    def _pin_back(self):
        self._pin["digits"] = self._pin["digits"][:-1]
        self._pin_refresh()

    def _pin_key(self, keyval):
        """Digit and Backspace keys also work on the keypad (the remote's number keys, a keyboard)."""
        ch = Gdk.keyval_to_unicode(keyval)
        if 48 <= ch <= 57:
            self._pin_press(chr(ch))
            return True
        if keyval == Gdk.KEY_BackSpace:
            self._pin_back()
            return True
        return False

    def _pin_submit(self):
        st = self._pin
        profile = st["profile"]
        status, wait = self.app.pin_gate.attempt(profile.id, st["digits"], profile.pin_hash)
        if status == "ok":
            on_ok = st["on_ok"]
            self.close_modal()
            on_ok()
            return
        self.ask_pin(
            profile,
            st["on_ok"],
            "Wrong PIN." if status == "wrong" else f"Too many wrong tries. Try again in {wait} seconds.",
        )

    def ask_channel(self, title, callback, current="", back=None):
        """A channel number in a box per digit (the channel_digits setting), typed on the keypad (or the remote's number
        keys). The boxes start empty, so a new number replaces the old one without deleting it first. callback(text) gets
        the digits typed ("7" is channel 07), the current number when OK is pressed with nothing typed, or "" for No channel.
        """
        self._begin_modal()
        self._title(title)
        digits = self.app.store.channel_digits()
        m = muted_label(
            f"{channel_range(digits)}. Type it in the Quick Menu to open this app."
            + (f" Now: {self.app.store.channel_text(int(current))}." if str(current).strip().isdigit() else "")
        )
        m.set_margin_bottom(S(8))
        self.modal_card.append(m)
        boxes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(8))
        boxes.set_halign(Gtk.Align.CENTER)
        boxes.set_margin_bottom(S(10))
        cells = []
        for _ in range(digits):
            c = Gtk.Label()
            c.add_css_class("digit-box")
            boxes.append(c)
            cells.append(c)
        self.modal_card.append(boxes)
        cancelled = back or self.close_modal

        def submit():
            typed = self._chan["digits"]
            self.close_modal()
            callback(typed if typed else str(current or ""))

        def none():
            self.close_modal()
            callback("")

        self._chan = {"digits": "", "cells": cells, "length": digits}
        self._chan_refresh()
        groups = []

        def key(text, handler, css=None):
            b = Gtk.Button(label=text)
            b.add_css_class("pin-key")
            if css:
                b.add_css_class(css)
            b.connect("clicked", lambda *_: handler())
            return b

        for row in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"), ("⌫", "0", "OK")):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
            line.set_homogeneous(True)
            line.set_margin_bottom(S(4))
            made = []
            for d in row:
                b = (
                    key(d, self._chan_back)
                    if d == "⌫"
                    else key("OK", submit, "active") if d == "OK" else key(d, lambda d=d: self._chan_press(d))
                )
                line.append(b)
                made.append(b)
                if d == "OK":
                    self._chan["ok"] = b
            self.modal_card.append(line)
            g = NavGroup(made)
            g.column = True
            groups.append(g)
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(6))
        bottom.set_homogeneous(True)
        bottom.set_margin_top(S(6))
        clear = Gtk.Button(label="No channel")
        clear.connect("clicked", lambda *_: none())
        bottom.append(clear)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: cancelled())
        bottom.append(cancel)
        self.modal_card.append(bottom)
        groups.append(NavGroup([clear, cancel]))
        self._modal_groups = groups
        self._modal_back = cancelled
        groups[0][0].grab_focus()

    def _chan_refresh(self):
        digits = self._chan["digits"]
        for i, c in enumerate(self._chan["cells"]):
            c.set_text(digits[i] if i < len(digits) else "–")
            (c.add_css_class if i == len(digits) else c.remove_css_class)("current")

    def _chan_press(self, digit):
        if len(self._chan["digits"]) < self._chan["length"]:
            self._chan["digits"] += digit
            self._chan_refresh()
        if len(self._chan["digits"]) == self._chan["length"] and self._chan.get("ok") is not None:
            self._chan["ok"].grab_focus()  # complete: OK is next

    def _chan_back(self):
        self._chan["digits"] = self._chan["digits"][:-1]
        self._chan_refresh()

    def _chan_key(self, keyval):
        ch = Gdk.keyval_to_unicode(keyval)
        if 48 <= ch <= 57:
            self._chan_press(chr(ch))
            return True
        if keyval == Gdk.KEY_BackSpace:
            self._chan_back()
            return True
        return False

    def ask_password(self, action_label, on_ok, message=""):
        """The administrator (sudo) password for a power action, typed on a keyboard (such as the one on the back of a
        remote) or on the on-screen keyboard, shown as it was last left (hidden, full or the number pad).
        on_ok(password) runs on OK; the field is emptied when it closes."""

        def got(password):
            if password:
                on_ok(password)

        self.ask_text(
            f"Password for {action_label}",
            got,
            "",
            f"{action_label} needs administrator rights. Enter your password (the one sudo asks for). "
            "It is used once and never stored.",
            secret=True,
            error=message,
        )
