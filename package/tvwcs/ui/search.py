"""Search, and typing a channel number. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from tvwcs.core.model import search_items
from tvwcs.ui.widgets import S, app_icon, clear_box, Marquee, muted_label, scroll_to_show
from tvwcs.ui.quick_menu import NAME_SCROLL_DELAY

CHANNEL_DELAY = 1000  # a full channel number and nothing else for this many ms launches that channel


class SearchMixin:
    """Search: typing anywhere filters apps, profiles, channels and windows."""

    # ---------------------------------------------------------- search
    def _refresh_search_results(self):
        if not hasattr(self, "results_box"):
            return
        if self._contains(self.results_box, self.get_focus()):
            self.search_entry.grab_focus()  # its row is about to go (the field's ✕ clicked)
        if any(self._open_row is g for g in self._result_groups):
            self._open_row = None
        clear_box(self.results_box)
        self._result_groups = []
        self._result_mains = []
        self._selected_result = 0
        q = self.search_entry.get_text()
        self._results_query = q
        self.results_scroll.set_visible(bool(q.strip()))
        self._shape_search()
        if not q.strip():
            self._search_results = []
            self.app.fit_quick_menu()
            return
        self._search_results = search_items(
            q,
            self.app.store.profiles,
            self.app.catalogue.by_id(),
            self.app.wm.windows(),
            self.app.store.channel_digits(),
        )[:12]
        if not self._search_results:
            self.results_box.append(
                muted_label("No matches. Try an app name, profile name, channel number, or window title.")
            )
            self._mirror(self.results_box)
            self.app.fit_quick_menu()
            return
        for i, result in enumerate(self._search_results):
            main = Gtk.Button()
            main.add_css_class("launch-row")
            main.set_hexpand(True)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
            if result["kind"] == "window":
                w = result["window"]
                row.append(self.app.window_icon(w, 28, result.get("badge")))
                app = self.app.match_application_window(w)
                items = lambda w=w, a=app: self._window_items(w, a)
            else:
                p = result["profile"]
                app = self.app.catalogue.by_id().get(p.desktop_id)
                self._launch_slot(p, row, app_icon(app.icon if app else None, p.name, 28), 28)
                items = lambda p=p, a=app: self._profile_items(p, a)
            row.append(
                Marquee(
                    result["label"] if result["kind"] == "window" else self.app.profile_name(p, app),
                    delay=NAME_SCROLL_DELAY,
                ).follow(main)
            )
            detail = Gtk.Label(label=result["detail"])
            detail.add_css_class("muted")
            detail.set_ellipsize(3)
            row.append(detail)
            main.set_child(row)
            if i == self._selected_result:
                main.add_css_class("tvwcs-selected")
            main.connect("clicked", lambda _b, r=result: self.app.activate_result(r))
            # the best match is nearest the search field, at the bottom; ↑ goes on to the next one
            # (below it in a top corner; ↓ goes on)
            line, group = self._options_row(main, items)
            self._result_groups.append(group)
            self._result_mains.append(main)
            (self.results_box.append if self.top else self.results_box.prepend)(line)
        self._mirror(self.results_box)
        self.app.fit_quick_menu()

    def _activate_search(self, *_):
        if self._channel_source:
            GLib.source_remove(self._channel_source)
            self._channel_source = 0  # Enter launches it now
        # typed and OK'd at once: list the results first (GTK waits a moment), so the launch spinner has its button
        if getattr(self, "_results_query", None) != self.search_entry.get_text():
            self._refresh_search_results()
        q = self.search_entry.get_text().strip()
        if q.isdigit():
            p = next((p for p in self.app.store.profiles if p.channel == int(q)), None)
            if p:
                self.app.launch_profile(p)
                return
        if self._search_results:
            self.app.activate_result(self._search_results[self._selected_result])

    def _search_typed(self, *_):
        """A full channel number (all its digits) left alone for a second launches its channel, without Enter."""
        if self._channel_source:
            GLib.source_remove(self._channel_source)
            self._channel_source = 0
        q = self.search_entry.get_text().strip()
        if (
            len(q) == self.app.store.channel_digits()
            and q.isdigit()
            and any(p.channel == int(q) for p in self.app.store.profiles)
        ):
            self._channel_source = GLib.timeout_add(CHANNEL_DELAY, self._launch_typed_channel, q)

    def _launch_typed_channel(self, q):
        self._channel_source = 0
        if self.is_visible() and not self._modal_groups and self.search_entry.get_text().strip() == q:
            p = next((p for p in self.app.store.profiles if p.channel == int(q)), None)
            if p:
                self.app.launch_profile(p)
        return GLib.SOURCE_REMOVE

    def _select_result(self, index):
        self._selected_result = index
        for i, b in enumerate(self._result_mains):
            b.remove_css_class("tvwcs-selected")
            if i == index:
                b.add_css_class("tvwcs-selected")
        # the highlight moves while the selection stays in the search field, so the list does not follow it by itself
        if 0 <= index < len(self._result_mains):
            scroll_to_show(self.results_scroll, self._result_mains[index])

    def _type_to_search(self, text):
        e = self.search_entry
        value = e.get_text() + text
        self._show_search()
        e.grab_focus()
        e.set_text(value)
        e.set_position(-1)

    def _show_search(self):
        """Unfold the search bar (search_icon setting); it is always there otherwise."""
        if self.search_line.get_visible():
            return
        self.search_line.set_visible(True)
        self.search_button.add_css_class("active")
        self.app.fit_quick_menu()

    def _hide_search(self):
        if not self.search_folds or not self.search_line.get_visible():
            return
        self.search_line.set_visible(False)
        self.search_button.remove_css_class("active")
        self.app.fit_quick_menu()

    def toggle_search(self):
        """The search icon: unfold the search bar and type in it; again, fold it away (and what was typed)."""
        if self.search_line.get_visible():
            self.search_entry.set_text("")
            self._hide_search()
            self.search_button.grab_focus()
            return
        self._show_search()
        self.search_entry.grab_focus()

    def _fold_search(self, focused):
        """Fold the search bar away once the selection has left it with nothing typed (not for a dialog: the on-screen
        keyboard, opened from it, types into it)."""
        if not self.search_folds or focused is None or self._modal_groups or self._popovers:
            return
        if self.search_line.get_visible() and not self._in_search(focused) and not self.search_entry.get_text().strip():
            self._hide_search()

    def _nearest_row(self):
        """The search bar folded away: the row next to where it would be (the lists' lowest row, else the search icon)."""
        for g in reversed(self._groups["quick"]):
            w = self._landing(g)
            if w is not None and w.grab_focus():
                return True
        return self.search_button.grab_focus()
