"""Editing launch profiles inside the TVWCS window, with the remote: every field is a row that opens the on-screen
keyboard, the number keypad, a list of choices or the hotkey capture. Nothing is stored until Save."""

from __future__ import annotations
from dataclasses import replace

from tvwcs.core.model import (
    DEFAULT_LABEL,
    MAX_DESCRIPTION,
    PIN_SCOPE_LABELS,
    PIN_SCOPES,
    next_label,
    profile_detail,
    profile_label,
)
from tvwcs.core.hotkeys import describe
from tvwcs.core.profile_draft import ProfileDraft

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from tvwcs.ui.widgets import NavGroup, S, glyph


def _row(win, label, value, handler, icon=None, fallback=""):
    """A field: its name on the left, its value under it. Enter opens what changes it."""
    b = Gtk.Button()
    b.add_css_class("dialog-button")
    b.add_css_class("field-row")
    line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
    if icon:
        line.append(glyph(icon, fallback, 22))
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    text.set_hexpand(True)
    name = Gtk.Label(label=label)
    name.set_xalign(0)
    name.set_ellipsize(3)
    name.set_max_width_chars(24)
    text.append(name)
    v = Gtk.Label(label=value)
    v.add_css_class("field-value")
    v.set_xalign(0)
    v.set_ellipsize(3)
    v.set_max_width_chars(24)
    text.append(v)  # long values do not widen the card
    line.append(text)
    b.set_child(line)
    if handler is None:
        b.add_css_class("info-row")
    else:
        b.connect("clicked", lambda *_: handler())
    return b


class ProfileEditor:
    """One launch profile, drawn in the TVWCS window's dialog card. ✎ on an application opens its default profile here;
    Copy makes another profile from what is shown (unsaved changes go to the copy, the original stays as it was).
    The application's name is never changed: a profile's own name follows it ("Firefox 2"), and the default profile's
    is "Default", not shown. `back` runs after Save, Delete or Cancel."""

    def __init__(self, win, existing, application, back=None, draft=None):
        self.win = win
        self.app = win.app
        self.existing = existing
        self.application = application
        self.back = back
        default = self.app.default_profile(application) if application else None
        self.primary = existing is not None and default is not None and default.id == existing.id
        app_name = application.name if application else ""
        if draft is not None:
            self.draft = draft
        elif existing is not None:
            self.draft = ProfileDraft.of(existing)
            if not self.primary:
                self.draft.name = profile_label(existing, app_name, False)
        else:
            self.draft = ProfileDraft.new(application.desktop_id, next_label(self._labels()))
        self.start = replace(self.draft) if existing is not None else None
        self.error = ""
        self.focus_key = "name"

    def _labels(self):
        app = self.application
        name = app.name if app else ""
        main = self.app.default_profile(app) if app else None
        return [
            profile_label(p, name, main is not None and p.id == main.id)
            for p in self.app.store.for_app(self.application.desktop_id)
        ]

    def open(self):
        """A profile protected by a PIN asks for it before it can be changed or deleted."""
        if self.existing is not None and self.existing.pin_hash:
            self.win.ask_pin(self.existing, self.show)
        else:
            self.show()

    def _done(self):
        self.win.close_modal()
        if self.back:
            self.back()

    def _changed(self):
        return self.start is None or self.draft != self.start

    def _cancel(self):
        if self._changed():
            self.win.confirm(
                "Discard changes?",
                "The changes to this profile have not been saved.",
                "Discard",
                self._done,
                back=self.show,
            )
        else:
            self._done()

    def _title(self):
        app = self.application
        name = app.name if app else self.draft.desktop_id
        if self.primary:
            return f"Edit · {name}"
        return f"{'Edit' if self.existing else 'New profile'} · {name} {self.draft.name}".rstrip()

    def show(self):
        win = self.win
        d = self.draft
        app = self.application
        win._begin_modal()
        win._title(self._title())
        if self.error:
            e = Gtk.Label(label=self.error)
            e.add_css_class("error")
            e.set_wrap(True)
            e.set_xalign(0)
            e.set_margin_bottom(S(6))
            win.modal_card.append(e)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(max(S(260), win.get_height() - S(330)))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        scroll.set_child(box)
        win.modal_card.append(scroll)
        actions = dict(app.desktop_actions) if app else {}
        rows = [
            (
                "name",
                "Profile name",
                DEFAULT_LABEL if self.primary else d.name or "(none)",
                None if self.primary else self._edit_name,
            ),
            (
                "channel",
                "Channel number",
                self.app.store.channel_text(int(d.channel)) if d.channel.strip().isdigit() else "None",
                self._edit_channel,
            ),
            ("hotkey", "Hotkey", describe(d.hotkey) if d.hotkey else "None", self._edit_hotkey),
        ]
        if actions:
            rows.append(
                (
                    "action",
                    "Desktop Action",
                    actions.get(d.action, "None set") if d.action else "None set",
                    self._edit_action,
                )
            )
        rows.append(
            ("command", "Custom command", d.command or "None: the application's own launcher", self._edit_command)
        )
        rows.append(
            ("description", "Description", d.description or self._default_description(), self._edit_description)
        )
        rows.append(("pin", "PIN lock", "On" if d.pin_hash else "Off", self._edit_pin))
        if d.pin_hash:
            rows.append(("scope", "Ask for the PIN", PIN_SCOPE_LABELS[d.pin_scope], self._edit_scope))
        groups = []
        focus = None
        for key, label, value, handler in rows:
            b = _row(
                win,
                label,
                value,
                None if handler is None else (lambda h=handler, k=key: (setattr(self, "focus_key", k), h())),
            )
            box.append(b)
            groups.append(NavGroup([b]))
            if key == self.focus_key:
                focus = b
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(6))
        buttons.set_homogeneous(True)
        buttons.set_margin_top(S(10))
        save = Gtk.Button(label="Save")
        save.add_css_class("active")
        save.connect("clicked", lambda *_: self._save())
        line = [save]
        if app is not None:
            copy = Gtk.Button(label="Copy")
            copy.set_tooltip_text("Make another profile from this one, with the changes shown here")
            copy.connect("clicked", lambda *_: self._copy())
            line.append(copy)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self._cancel())
        line.append(cancel)
        if self.existing is not None and not self.primary:
            delete = Gtk.Button(label="Delete")
            delete.add_css_class("danger")
            delete.connect("clicked", lambda *_: self._delete())
            line.append(delete)
        for b in line:
            buttons.append(b)
        win.modal_card.append(buttons)
        groups.append(NavGroup(line))
        if self.focus_key == "save":
            focus = save
        if self.primary and self.focus_key == "name":
            focus = None  # Default cannot be changed: start on the channel
        win._modal_groups = groups
        win._modal_back = self._cancel
        (focus or groups[1 if self.primary else 0][0]).grab_focus()

    def _default_description(self):
        app = self.application
        if self.primary:
            return ((app.comment or app.generic_name) if app else "") or "None"
        shown = (
            profile_detail(self.draft.profile(), app)
            if not self.draft.channel.strip() or self.draft.channel.strip().isdigit()
            else ""
        )
        return f"Shows its launch options{': '+shown if shown else ''}"

    # ---- the fields
    def _edit_name(self):
        def got(text):
            self.draft.name = text.strip() or self.draft.name
            self.show()

        self.win.ask_text(
            "Profile name",
            got,
            self.draft.name,
            f"Shown after the application's name: {self.application.name if self.application else ''} {self.draft.name}.",
            back=self.show,
            max_len=60,
        )

    def _edit_channel(self):
        def got(text):
            t = text.strip()
            self.draft.channel = str(int(t)) if t.isdigit() else t  # "002" is the same channel as "2": not a change
            self.show()

        self.win.ask_channel("Channel number", got, self.draft.channel, back=self.show)

    def _edit_hotkey(self):
        def got(spec):
            self.draft.hotkey = spec
            self.show()

        self.win.assign_hotkey(("profile", self.draft.id), self._title(), got, back=self.show)

    def _edit_action(self):
        options = [("", "None set")] + list(self.application.desktop_actions)

        def got(k):
            self.draft.action = k
            self.show()

        self.win.choose_option("Desktop Action", options, self.draft.action, got, back=self.show)

    def _edit_command(self):
        def got(text):
            self.draft.command = text.strip()
            self.show()

        self.win.ask_text(
            "Custom command",
            got,
            self.draft.command,
            "Runs instead of the application's own launcher, without a shell. Leave empty to use the launcher.",
            back=self.show,
        )

    def _edit_description(self):
        def got(text):
            self.draft.description = " ".join(text.split())
            self.show()

        self.win.ask_text(
            "Description",
            got,
            self.draft.description,
            "Shown beside the name in Applications. Leave empty for "
            + ("the application's own." if self.primary else "its launch options."),
            back=self.show,
            max_len=MAX_DESCRIPTION,
        )

    def _edit_pin(self):
        options = [("set", "Change the PIN" if self.draft.pin_hash else "Set a PIN")]
        if self.draft.pin_hash:
            options.append(("remove", "Remove the PIN"))

        def got(k):
            if k == "remove":
                self.draft.pin_hash = ""
                self.error = ""
                self.show()
                return
            self._ask_new_pin()

        self.win.choose_option("PIN lock", options, None, got, back=self.show)

    def _ask_new_pin(self):
        def first(new):
            def second(again):
                try:
                    self.draft.set_pin(new, again)
                    self.error = ""
                except ValueError as exc:
                    self.error = str(exc)
                self.show()

            self.win.ask_text("Repeat the new PIN", second, "", back=self.show, digits=True, secret=True, max_len=8)

        self.win.ask_text(
            "New PIN",
            first,
            "",
            "4 to 8 digits. This keeps others on a shared TV out; it is not strong security.",
            back=self.show,
            digits=True,
            secret=True,
            max_len=8,
        )

    def _edit_scope(self):
        def got(k):
            self.draft.pin_scope = k
            self.show()

        self.win.choose_option(
            "Ask for the PIN", [(k, PIN_SCOPE_LABELS[k]) for k in PIN_SCOPES], self.draft.pin_scope, got, back=self.show
        )

    # ---- storing
    def _stored_draft(self):
        """The draft as it is stored: the default profile keeps the application's name."""
        d = replace(self.draft)
        if self.primary and self.existing is not None:
            d.name = self.existing.name
        return d

    def _save(self):
        self.focus_key = "save"
        try:
            self.app.store.set_profile(self._stored_draft().profile())
        except (ValueError, TypeError) as exc:
            self.error = str(exc)
            self.show()
            return
        self.app.apply_hotkeys()
        self.win.close_modal()
        self.app.refresh_data(rebuild=True)
        if self.back:
            self.back()

    def _copy(self):
        """A new profile from what is shown, saved and opened: the original is not changed. A channel and a hotkey belong
        to one profile, so the copy has neither."""
        d = ProfileDraft.new(self.draft.desktop_id, next_label(self._labels()))
        for field in ("command", "action", "description", "pin_hash", "pin_scope"):
            setattr(d, field, getattr(self.draft, field))
        try:
            self.app.store.set_profile(d.profile())
        except (ValueError, TypeError) as exc:
            self.error = str(exc)
            self.show()
            return
        self.app.refresh_data(rebuild=True)
        ProfileEditor(self.win, self.app.store.get(d.id), self.application, back=self.back).show()

    def _delete(self):
        def gone():
            self.app.store.delete(self.existing.id)
            self.app.apply_hotkeys()
            self.app.refresh_data(rebuild=True)
            if self.back:
                self.back()

        self.win.confirm(
            "Delete profile?",
            f"Delete “{self._title().split(' · ',1)[-1]}”? This cannot be undone.",
            "Delete",
            gone,
            back=self.show,
        )
