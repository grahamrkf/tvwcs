"""The Quick Menu's rows: favorites, channels and open apps, with their ⋯ options. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs.core.model import LAUNCH_NEW_WORKSPACE, LAUNCH_SAME, extract_badge
from tvwcs.ui.widgets import NO_ICON, NavGroup, S, app_icon, clear_box, glyph, Marquee, muted_label, scroll_to_show
from tvwcs.ui.widgets import pointer_only

NAME_SCROLL_DELAY = 3000  # ms a selected Quick Menu row waits before a name too long to fit scrolls by


class QuickMenuMixin:
    """The Quick Menu's rows: favorites, channels and open apps."""

    # ---------------------------------------------------------- Quick Menu rows
    # Each row is the application (or workspace) with one ⋯ button before it. ⋯, ← on the row or a right-click unfolds
    # the row's options above it: every option it has, each with its name (where it opens, its own shortcuts, Close, ...).
    def _favorite_row(self, p):
        app = self.app.catalogue.by_id().get(p.desktop_id)
        main = Gtk.Button()
        main.add_css_class("launch-row")
        main.set_hexpand(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
        self._launch_slot(p, inner, app_icon(app.icon if app else None, p.name, 32), 32)
        if p.channel is not None:
            ch = Gtk.Label(label=self.app.store.channel_text(p.channel))
            ch.add_css_class("channel-number")
            inner.append(ch)
        inner.append(Marquee(self.app.profile_name(p, app), delay=NAME_SCROLL_DELAY).follow(main))
        if p.pin_hash:
            inner.append(self._lock_mark())
        inner.append(self._star_mark())
        main.set_child(inner)
        main.connect("clicked", lambda _b, profile=p: self.app.launch_profile(profile))
        box, group = self._options_row(main, lambda profile=p, a=app: self._profile_items(profile, a))
        self._groups["quick"].append(group)
        return box

    def _window_row(self, w, nested=False):
        """An application on a workspace of its own (or one app inside an expanded workspace)."""
        title, badge = extract_badge(w["title"], w.get("urgent", False))
        app = self.app.match_application_window(w)
        main = Gtk.Button()
        main.add_css_class("launch-row")
        main.add_css_class("open-app")
        main.set_hexpand(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
        inner.append(self.app.window_icon(w, 32, badge))
        inner.append(Marquee(title, delay=NAME_SCROLL_DELAY).follow(main))
        if w["con_id"] in getattr(self, "_starred", ()):
            inner.append(self._star_mark())
        main.set_child(inner)
        main.connect("clicked", lambda _b, con=w["con_id"]: self.app.focus_window(con))
        box, group = self._options_row(main, lambda win=w, a=app: self._window_items(win, a))
        if nested:
            box.set_margin_start(S(28))
        self._groups["quick"].append(group)
        return box

    def _workspace_row(self, entry, outputs):
        """Apps that share a workspace, grouped under a name built from what is in it. Its apps unfold above it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        main = Gtk.Button()
        main.add_css_class("launch-row")
        main.add_css_class("open-app")
        main.set_hexpand(True)
        main.set_tooltip_text("Open this workspace and everything on it")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
        icons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(2))
        for w in entry.windows[:3]:
            icons.append(self.app.window_icon(w, 24, extract_badge(w["title"], w.get("urgent", False))[1]))
        inner.append(icons)
        inner.append(Marquee(entry.label, delay=NAME_SCROLL_DELAY).follow(main))
        count = Gtk.Label(label=f"{len(entry.windows)} apps")
        count.add_css_class("muted")
        inner.append(count)
        main.set_child(inner)
        main.connect("clicked", lambda _b, name=entry.name: self.app.open_workspace(name))
        # the individual apps sit above the workspace, so they are registered first: navigation goes top to bottom
        children = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        children.set_visible(False)
        for w in entry.windows:
            children.append(self._window_row(w, nested=True))
        others = [o["name"] for o in outputs if o["name"] != entry.output]

        def items():
            out = []
            for name in others:  # only offered when there is somewhere else to send it
                out.append(
                    (
                        "video-display-symbolic",
                        "▭",
                        f"Move to monitor {name}",
                        lambda n=name: self.app.move_workspace(entry.name, n),
                        False,
                    )
                )
            out.append(
                (
                    "window-close-symbolic",
                    "✕",
                    "Close this workspace and its apps",
                    lambda: self.confirm(
                        "Close workspace?",
                        f"Close {entry.label} and its {len(entry.windows)} applications? Unsaved work in them may be lost.",
                        "Close workspace",
                        lambda: self.app.close_workspace(entry),
                    ),
                    True,
                )
            )
            return out

        row, group = self._options_row(main, items)
        # Showing or hiding the individual apps is its own square button between ⋯ and the name, shown even when ⋯ is hidden
        expander = Gtk.Button()
        expander.add_css_class("square")

        def show_expander():
            shown = children.get_visible()
            unfold = (
                not shown if self.top else shown
            )  # the arrow points the way its apps fold: away from the row, or back to it
            expander.set_child(glyph("pan-down-symbolic" if unfold else "pan-up-symbolic", "▾" if unfold else "▴"))
            expander.set_tooltip_text(
                "Hide the individual apps" if shown else "Show the individual apps, to open just one"
            )

        def flip(*_):
            self._close_open()
            children.set_visible(not children.get_visible())
            show_expander()
            self._mirror(expander)
            self.app.fit_quick_menu()

        expander.connect("clicked", flip)
        pointer_only(expander)
        show_expander()
        group.line.insert_child_after(expander, group[0])
        group.insert(1, expander)  # group[0] is ⋯, even when hidden
        group.lead = expander  # ← on the name moves onto it; ← on it opens the row's menu
        self._groups["quick"].append(group)
        box.append(children)
        box.append(row)
        self._flip(box)
        self._flip(children)
        return box

    def _options_row(self, main, items):
        """A row: ⋯ then the application, with its options folded away above it. ⋯, ← on the application or a
        right-click unfolds them upwards, a little indented on both sides and close to their row (with a small gap to
        the row above), in the order items() makes them, top to bottom: the last one (Close) is nearest the row.
        items() makes them when they open: (icon, fallback glyph, label, action, dangerous). The ⋯ button can be hidden in Settings.
        -> (the options and the row, the row's NavGroup); the NavGroup's `line` is the row itself."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        panel.add_css_class("row-options")
        panel.set_visible(False)
        panel.set_margin_start(S(16))
        panel.set_margin_end(S(16))
        panel.set_margin_top(S(6))
        panel.set_margin_bottom(S(2))
        self._flip_margins(panel)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        hide = bool(self.app.store.settings.get("hide_options_buttons", False))
        toggle = Gtk.Button()
        toggle.add_css_class("options-toggle")
        toggle.add_css_class("square")
        toggle.set_visible(not hide)
        toggle.set_child(glyph("view-more-symbolic", "⋯"))
        toggle.set_tooltip_text("Options")
        group = NavGroup([toggle, main], entry=main)
        group.toggle = toggle if not hide else None
        group.line = row
        pointer_only(toggle, main)

        def collapse():
            group.options = []
            if panel.get_visible():
                panel.set_visible(False)
                clear_box(panel)
                self.app.fit_quick_menu()

        def run(action):
            main.grab_focus()
            self._close_open()
            action()

        def open_options(*_):
            if panel.get_visible():  # ⋯ (or a right-click) again folds them
                main.grab_focus()
                self._close_open()
                return True
            self._close_open()
            made = items()
            buttons = []
            if not made:
                panel.append(muted_label("Nothing to choose here."))
            for icon, fallback, label, action, danger in made:
                b = self.dialog_button(icon, fallback, label)
                b.add_css_class("menu-item")
                if danger:
                    b.add_css_class("danger")
                b.connect("clicked", lambda _b, a=action: run(a))
                panel.append(b)
                buttons.append(b)
                pointer_only(b)
            self._flip(panel)
            self._mirror(panel)  # in a top corner they unfold downwards, Close still nearest the row
            options = []
            for b in buttons:
                g = NavGroup([b])
                g.option_item = True
                options.append(g)
            group.options = options
            panel.set_visible(True)
            self._open_row = group
            # the selection lands on the option nearest the row that is not Close
            safe = [b for b in buttons if not b.has_css_class("danger")]
            (safe[-1] if safe else buttons[-1] if buttons else main).grab_focus()
            self.app.fit_quick_menu()
            scroll = box.get_ancestor(Gtk.ScrolledWindow)
            if (
                scroll is not None
            ):  # unfolded upwards: bring the top of the options into sight, keeping the row in sight
                GLib.timeout_add(60, lambda: (scroll_to_show(scroll, box), GLib.SOURCE_REMOVE)[1])
            return True

        toggle.connect("clicked", open_options)
        click = Gtk.GestureClick()
        click.set_button(3)
        click.connect("pressed", lambda *_a: open_options())
        main.add_controller(click)
        row.append(toggle)
        row.append(main)
        box.append(panel)
        box.append(row)
        self._flip(box)
        group.expanded = panel.get_visible
        group.expand = open_options
        group.collapse = collapse
        group.open_options = open_options
        group.menu = [toggle]
        group.owns = lambda w: any(w is x for x in group) or self._contains(panel, w)
        return box, group

    def _close_open(self):
        """Fold away the open row options or status panel, if any."""
        row = self._open_row
        self._open_row = None
        if row is not None and row.expanded():
            row.collapse()

    def _launch_slot(self, p, inner, icon, size):
        """Put a profile's icon in its button, with a spinner that takes the icon's place while the profile starts."""
        spinner = Gtk.Spinner()
        spinner.set_size_request(S(size), S(size))
        spinner.set_tooltip_text("Starting…")
        inner.append(icon)
        inner.append(spinner)
        self._launch_slots.append((p.id, icon, spinner))
        self._show_launching(icon, spinner, p.id in self.launching)

    @staticmethod
    def _show_launching(icon, spinner, on):
        icon.set_visible(not on and not icon.has_css_class(NO_ICON))
        spinner.set_visible(on)
        (spinner.start if on else spinner.stop)()

    def set_launching(self, profile_id, on):
        """Show (or stop) the spinner on every button of a profile that is starting. -> whether one is on screen."""
        (self.launching.add if on else self.launching.discard)(profile_id)
        self._launch_slots = [s for s in self._launch_slots if s[1].get_root() is self]  # rows rebuilt since are gone
        shown = False
        for pid, icon, spinner in self._launch_slots:
            if pid != profile_id:
                continue
            self._show_launching(icon, spinner, on)
            shown = shown or spinner.is_visible()  # it and every container it is in
        return shown

    def launching_slow(self, profile_id, name):
        for pid, _icon, spinner in self._launch_slots:
            if pid == profile_id:
                spinner.set_tooltip_text(
                    f"{name} has not opened a window yet. It may still be starting, or it may not have started."
                )

    @staticmethod
    def _star_mark():
        """The grey ★ of a favorite in the Quick Menu (an open one also has the band of an open app)."""
        star = Gtk.Label(label="★")
        star.add_css_class("favorite-mark")
        star.set_tooltip_text("A favorite")
        return star

    @staticmethod
    def _lock_mark():
        mark = glyph("changes-prevent-symbolic", "🔒", 16)
        mark.set_tooltip_text("Protected by a PIN")
        return mark

    def _action_items(self, app):
        """The application's own shortcuts (its .desktop actions), such as a browser's New private window."""
        if not app:
            return []
        return [
            ("view-list-bullet-symbolic", "≡", name, lambda a=app, aid=action_id: self.app.launch_action(a, aid), False)
            for action_id, name in app.desktop_actions
        ]

    def _one_time_item(self, run):
        """This once, the other way: in desktop mode in a new workspace; in TV mode alongside the apps on screen now
        (none when nothing is). run(mode) opens it."""
        if not self.app.tv:
            return [
                ("view-fullscreen-symbolic", "▣", "Open in new workspace", lambda: run(LAUNCH_NEW_WORKSPACE), False)
            ]
        names = self.app.alongside_names()
        if not names:
            return []
        shown = ", ".join(names[:2]) + (f" and {len(names)-2} more" if len(names) > 2 else "")
        return [("view-dual-symbolic", "◫", f"Open alongside {shown}", lambda: run(LAUNCH_SAME), False)]

    def _profile_items(self, p, app):
        """A favorite's (or search result's) menu, top to bottom: its shortcuts, open it the other way this once, and
        Close (nearest the row) when it is open."""
        items = self._action_items(app)
        items += self._one_time_item(lambda mode: self.app.launch_profile(p, mode=mode))
        if not p.command.strip() and not p.desktop_action:
            w = self.app.wm.find_matching(p, app)
            if w is not None:
                items.append(
                    (
                        "window-close-symbolic",
                        "✕",
                        f"Close {p.name}",
                        lambda con=w["con_id"]: self._close_open_window(con),
                        True,
                    )
                )
        return items

    def _window_items(self, w, app):
        """An open application's menu, top to bottom: its shortcuts, open it the other way this time, then Close
        (nearest the row)."""
        items = self._action_items(app)
        if not (self.app.tv and w.get("workspace_visible")):
            items += self._one_time_item(lambda mode: self.app.focus_window(w["con_id"], mode))
        items.append(
            ("window-close-symbolic", "✕", "Close this application", lambda: self._close_open_window(w["con_id"]), True)
        )
        return items

    def _popup(self, anchor, child):
        pop = Gtk.Popover()
        pop.set_parent(anchor)
        pop.set_child(child)
        self._popovers += 1

        def closed(p):
            self._popovers = max(0, self._popovers - 1)
            GLib.idle_add(p.unparent)

        pop.connect("closed", closed)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", lambda _c, kv, _kc, _st: (pop.popdown(), True)[1] if kv == Gdk.KEY_Back else False)
        pop.add_controller(key)
        pop.popup()
        return pop

    def _close_open_window(self, con_id):
        if not self.app.wm.close_window(con_id):
            self.app.notify_message("Could not close that application window.")
        # its row is gone once the list is rebuilt: the selection goes back to the search field, not to the header
        GLib.timeout_add(
            250, lambda: (self.app.refresh_data(rebuild=True), self.focus_pane_soon("search"), GLib.SOURCE_REMOVE)[2]
        )
