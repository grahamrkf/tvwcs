"""The Applications pane beside the Quick Menu: every installed app by category. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from tvwcs.core.model import row_description
from tvwcs.ui.widgets import S, app_icon, child_marker, clear_box, glyph, Marquee, muted_label, section_title


class ApplicationsPaneMixin:
    """The Applications pane beside the Quick Menu."""

    # ---------------------------------------------------------- Applications pane
    def _build_guide_pane(self):
        """The Applications pane: a title over the applications guide. Its focusable widgets register into pane "guide"."""
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        pane.add_css_class("pane")
        pane.set_hexpand(True)
        pane.set_margin_start(self.app.layout.margin)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(14))
        head.set_margin_top(S(12))
        head.set_margin_start(S(24))
        head.set_margin_end(S(24))
        head.set_margin_bottom(S(2))
        self.apps_title = Gtk.Label(label="Applications")
        self.apps_title.add_css_class("pane-title")
        self.apps_title.set_xalign(0)
        head.append(self.apps_title)
        self.apps_subtitle = Gtk.Label()
        self.apps_subtitle.add_css_class("muted")
        self.apps_subtitle.set_valign(Gtk.Align.END)
        self.apps_subtitle.set_margin_bottom(S(4))
        self.apps_subtitle.set_xalign(0)
        head.append(self.apps_subtitle)
        pane.append(head)
        self.apps_list_scroll = Gtk.ScrolledWindow()
        self.apps_list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.apps_list_scroll.set_vexpand(True)
        self.apps_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        self.apps_content.set_margin_start(S(24))
        self.apps_content.set_margin_end(S(24))
        self.apps_content.set_margin_bottom(S(16))
        self.apps_list_scroll.set_child(self.apps_content)
        pane.append(self.apps_list_scroll)
        self._rebuild_apps_content()
        return pane

    def _rebuild_apps_content(self):
        """Applications: your channels, then every installed application by category."""
        clear_box(self.apps_content)
        assigned = self.app.store.assigned()
        if self.apps_subtitle is not None:
            self.apps_subtitle.set_text(f"{len(assigned)} channel{'s' if len(assigned)!=1 else ''}" if assigned else "")
        self.guide_scroll = self.apps_list_scroll
        self.apps_content.append(section_title("CHANNELS"))
        if not assigned:
            self.apps_content.append(
                muted_label(
                    "No channels yet. Give an app a number with ✎, then type that number in the Quick Menu to open it."
                )
            )
        for profile in assigned:
            self.apps_content.append(self._profile_row(profile, lineup=True))
        self.apps_content.append(section_title("ALL APPLICATIONS"))
        grouped = self.app.catalogue.by_category()
        if not grouped:
            self.apps_content.append(
                muted_label("No graphical applications were found in the XDG application directories.")
            )
        for category, apps in grouped.items():
            self.apps_content.append(self._category_section(category, apps))
        if self._guide_scroll > 0:
            for delay in (30, 200):
                GLib.timeout_add(delay, self._restore_guide_scroll)

    def _category_section(self, category, apps):
        """A focusable header button that folds its applications; open/closed state survives rebuilds."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        head = Gtk.Button()
        head.add_css_class("category-header")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
        arrow = Gtk.Label()
        arrow.set_width_chars(2)
        label = Gtk.Label(label=f"{category}  ({len(apps)})")
        label.set_xalign(0)
        label.set_hexpand(True)
        line.append(arrow)
        line.append(label)
        head.set_child(line)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(2))
        inner.set_margin_top(S(2))
        inner.set_margin_bottom(S(8))

        def apply():
            opened = category in self._expanded
            inner.set_visible(opened)
            arrow.set_text("▾" if opened else "◂" if self.right else "▸")

        def flip(*_):
            self._expanded.symmetric_difference_update({category})
            apply()

        head.connect("clicked", flip)
        apply()
        self._register("guide", head)
        for application in apps:
            default = self.app.default_profile(application)
            if default:
                inner.append(self._profile_row(default))
            for profile in self.app.store.for_app(application.desktop_id):
                if default and profile.id == default.id:
                    continue
                inner.append(self._profile_row(profile))
        box.append(head)
        box.append(inner)
        return box

    def _profile_row(self, p, lineup=False):
        app = self.app.catalogue.by_id().get(p.desktop_id)
        default = self.app.default_profile(app) if app else None
        primary = default is not None and default.id == p.id
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        row.add_css_class("profile-row")
        if not primary and not lineup:
            row.set_margin_start(S(16))  # a secondary profile hangs under its application
        main = Gtk.Button()
        main.set_hexpand(True)
        main.add_css_class("launch-row")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(12))
        self._launch_slot(
            p, inner, app_icon(app.icon if app else None, p.name, 32) if (primary or lineup) else child_marker(32), 32
        )
        ch = Gtk.Label(label=self.app.store.channel_text(p.channel) if p.channel is not None else "")
        ch.set_width_chars(self.app.store.channel_digits() + 1)
        ch.set_xalign(0)
        ch.add_css_class("channel-number")
        inner.append(ch)
        name = Gtk.Label(label=self.app.profile_name(p, app))
        name.set_xalign(0)
        name.set_ellipsize(3)
        inner.append(name)
        # Each profile has its own description; without one the main profile shows its application's, another its launch options.
        description = row_description(p, app, primary, self.app.store.app_descriptions.get(p.desktop_id, ""))
        if description:
            name.set_max_width_chars(32)
            if p.pin_hash:
                inner.append(self._lock_mark())
            # cut with … when it does not fit: it scrolls by while the row is selected, and the pointer shows all of it
            d = Marquee(description, "description").follow(main)
            inner.append(d)
            self._descriptions.append((main, d))
            main.set_has_tooltip(True)
            main.connect("query-tooltip", self._description_tip, d)
        else:
            name.set_hexpand(True)
            if p.pin_hash:
                inner.append(self._lock_mark())
        main.set_child(inner)
        main.connect("clicked", lambda _b, profile=p: self.app.launch_profile(profile))
        row.append(main)
        fav = Gtk.Button()
        fav.add_css_class("square")
        self._style_star(fav, p.favorite)
        self._stars.setdefault(p.id, []).append(fav)
        fav.connect("clicked", lambda _b, profile=p: self.app.toggle_favorite(profile))
        row.append(fav)
        edit = Gtk.Button()
        edit.add_css_class("square")
        edit.set_child(glyph("document-edit-symbolic", "✎"))
        edit.set_tooltip_text("Edit")
        edit.connect("clicked", lambda _b, profile=p: self.app.edit_profile(profile, None))
        row.append(edit)
        self._register("guide", main, fav, edit)
        # Right-clicking the application (or ← while it is selected) opens its options too — Edit and ☆/★ —
        # which also works when the ⋯ buttons are hidden in Settings.
        pop_holder = []

        def open_options(*_):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
            star = Gtk.Button(label="Remove favorite" if p.favorite else "Add to favorites")
            star.connect("clicked", lambda _b: (pop_holder and pop_holder[0].popdown(), self.app.toggle_favorite(p)))
            box.append(star)
            manage = Gtk.Button(label="Edit")
            manage.connect(
                "clicked", lambda _b: (pop_holder and pop_holder[0].popdown(), self.app.edit_profile(p, None))
            )
            box.append(manage)
            pop_holder.append(self._popup(main, box))
            return True

        click = Gtk.GestureClick()
        click.set_button(3)
        click.connect("pressed", lambda *_a: open_options())
        main.add_controller(click)
        group = self._groups["guide"][-1]
        if group:
            group.entry = main
            group.open_options = open_options
            group.expand = lambda: open_options()
            group.expanded = lambda: bool(pop_holder and pop_holder[-1].get_visible())
        return row

    @staticmethod
    def _description_tip(_widget, _x, _y, _keyboard, tooltip, marquee):
        if not marquee.truncated:
            return False
        tooltip.set_text(marquee.text)
        return True

    def apps_width(self):
        """At a desk the Applications pane is only as wide as its rows need: the widest row without its description,
        plus room for most descriptions (four in five) in full. The rest are cut with … (see Marquee)."""
        if self.guide_pane is None:
            self.guide_pane = self._build_guide_pane()
            self.panes.append(self.guide_pane)
            self.guide_pane.set_visible(self.guide_open)
            self._mirror(self.guide_pane)
        rows = []
        texts = []
        for main, d in self._descriptions:
            row = main.get_parent()
            if row is None:
                continue
            rows.append(
                row.measure(Gtk.Orientation.HORIZONTAL, -1)[1] - d.label.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            )
            texts.append(d.label.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
        if not rows:
            return S(640)
        texts.sort()
        most = texts[min(len(texts) - 1, int(len(texts) * 0.8))]
        return max(rows) + most + 2 * S(24) + S(16)  # the list's side margins, and its scroll bar

    def _style_star(self, button, favorite):
        button.set_child(glyph("starred-symbolic" if favorite else "non-starred-symbolic", "★" if favorite else "☆"))
        button.set_tooltip_text("Remove favorite" if favorite else "Add to favorites")

    def refresh_favorites(self, profile_id):
        """A favorite changed: restyle its star(s) and rebuild only the Quick Menu list; Applications stays put."""
        p = self.app.store.get(profile_id)
        for b in self._stars.get(profile_id, []):
            self._style_star(b, bool(p and p.favorite))
        if self.quick_content is not None:
            if any(self._open_row is g for g in self._groups["quick"]):
                self._open_row = None
            self._groups["quick"] = []
            clear_box(self.quick_content)
            self._build_quick_content(self.quick_content)
            self.app.fit_quick_menu()

    def _restore_guide_scroll(self):
        if self.guide_scroll is not None:
            self.guide_scroll.get_vadjustment().set_value(self._guide_scroll)
        return GLib.SOURCE_REMOVE

    def reset_scroll(self):
        self._guide_scroll = 0.0
