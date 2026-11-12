"""Remote and keyboard navigation: arrows, OK, Back and hotkeys. Part of TVWCSWindow (ui/window.py)."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs.ui.widgets import NavGroup, usable
from tvwcs.ui.widgets import pointer_only

_TYPING_BLOCKED = (
    Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.META_MASK
)


class NavigationMixin:
    """Moving with the remote's arrows, OK and Back, and the keyboard."""

    # ---------------------------------------------------------- remote / keyboard navigation
    def _register(self, pane, *widgets, entry=None):
        pointer_only(*widgets)
        group = NavGroup([w for w in widgets if w is not None], entry)
        if group:
            self._groups[pane].append(group)
            return group
        return None

    def _focus_changed(self, *_):
        w = self.get_focus()
        if w is not None:
            self._last_focus[self._pane_of(w)] = w
        self._fold_options(w)
        self._fold_search(w)

    def _fold_options(self, focused):
        """Fold a Quick Menu row's options (or a status panel) away once the selection has left them and their row (or
        icon). Not while a pop-up or a dialog opened from one of them is up, nor while a panel is redrawn."""
        row = self._open_row
        if (
            row is None
            or focused is None
            or self._popovers
            or self._modal_groups
            or getattr(self, "_keep_panel", False)
        ):
            return
        owns = getattr(row, "owns", None)
        if owns(focused) if owns is not None else any(focused is w for w in row.menu):
            return
        self._open_row = None
        if row.expanded():
            row.collapse()

    def _pane_of(self, widget):
        for name, pane in (("options", self.options_pane), ("guide", self.guide_pane)):
            if widget is not None and pane is not None and (widget is pane or widget.is_ancestor(pane)):
                return name
        return "quick"

    def _ordered_groups(self, pane):
        if self._modal_groups:
            return self._modal_groups
        if pane != "quick":
            return list(self._groups[pane])

        # top to bottom as on screen: the results are listed upwards from the search field, a row's open options are
        # just above it, and an open status panel is between the search field and the status row. In a top corner all of
        # it is the other way up, so the order is too.
        def unfolded(groups):
            out = []
            for g in groups:
                out += getattr(g, "options", None) or []
                out.append(g)
            return out

        order = (
            [self._header_group]
            + unfolded(self._groups["quick"])
            + unfolded(reversed(self._result_groups))
            + [[self.search_entry]]
            + list(getattr(self, "_panel_groups", []))
            + [getattr(self, "_status_group", []), getattr(self, "_clock_group", [])]
        )
        return order[::-1] if self.top else order

    @staticmethod
    def _contains(widget, focused):
        return focused is not None and (focused is widget or focused.is_ancestor(widget))

    def _in_search(self, focused):
        return self._contains(self.search_entry, focused)  # focus sits on the entry's inner text widget

    def _group_index(self, groups, focused):
        # An exact match wins; only then accept "inside" (an entry's inner text widget). Otherwise a button nested in
        # a container that is itself a group would be mistaken for that container.
        for i, g in enumerate(groups):
            if any(w is focused for w in g):
                return i
        for i, g in enumerate(groups):
            if any(self._contains(w, focused) for w in g):
                return i
        return -1

    def _landing(self, group, column=None):
        if column is not None and getattr(group, "column", False):  # a grid row: stay in the same column
            active = [w for w in group if usable(w)]
            if active:
                return active[min(column, len(active) - 1)]
        entry = getattr(group, "entry", None)
        if entry is not None and usable(entry):
            return entry
        return next((w for w in group if usable(w)), None)

    def _focus_first(self, groups):
        for g in groups:
            w = self._landing(g)
            if w is not None and w.grab_focus():
                return True
        return False

    def focus_pane(self, pane):
        """Select something in a pane: where the selection last was in it, else its first row. "search": the Quick
        Menu's search field, whatever was selected before (GTK selects the first button when the window appears)."""
        folded = self.search_folds and not self.search_line.get_visible()
        if pane == "search":
            return self._nearest_row() if folded else self.search_entry.grab_focus()
        last = self._last_focus.get(pane)
        if last is not None and usable(last) and last.grab_focus():
            return True
        if pane == "quick":
            return self._nearest_row() if folded else self.search_entry.grab_focus()
        return self._focus_first(self._groups[pane])

    def focus_pane_soon(self, pane, prefer=None):
        """Focus once a freshly shown panel has been mapped: `prefer` if it is still there, else focus_pane(pane)."""

        def go():
            if prefer is None or not usable(prefer) or not prefer.grab_focus():
                self.focus_pane(pane)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(70, go)

    def _move_group(self, step):
        focused = self.get_focus()
        pane = self._pane_of(focused)
        groups = [g for g in self._ordered_groups(pane) if any(usable(w) for w in g)]
        if not groups:
            return False
        current = self._group_index(groups, focused)
        lane = getattr(groups[current], "lane", None) if current >= 0 else None
        if lane is not None:  # in a column layout ↑/↓ stays in its column (rows outside any column are shared)
            groups = [g for g in groups if getattr(g, "lane", None) in (None, lane)]
            current = self._group_index(groups, focused)
        column = next((k for k, w in enumerate(groups[current]) if w is focused), None) if current >= 0 else None
        start = (current + step) % len(groups) if current >= 0 else (0 if step > 0 else len(groups) - 1)
        for offset in range(len(groups)):
            w = self._landing(groups[(start + step * offset) % len(groups)], column)
            if w is not None and w.grab_focus():
                return True
        return False

    def _move_within_group(self, step):
        focused = self.get_focus()
        pane = self._pane_of(focused)
        groups = self._ordered_groups(pane)
        gi = self._group_index(groups, focused)
        if gi < 0:
            return False
        group = groups[gi]
        active = [w for w in group if usable(w)]
        if not active:
            return False
        i = next((k for k, w in enumerate(active) if w is focused), None)
        if i is None:
            i = next((k for k, w in enumerate(active) if self._contains(w, focused)), 0)
        if getattr(group, "option_item", False) and not self._modal_groups:
            return True  # one option: ←/→ stay on it
        open_options = getattr(group, "open_options", None)
        lead = getattr(group, "lead", None)
        if (
            step < 0
            and pane == "quick"
            and open_options is not None
            and focused is (lead or group.entry)
            and group.expanded is not None
            and not group.expanded()
        ):
            return (
                open_options()
            )  # ← on a Quick Menu row opens its options, next to the application (or its first button after ⋯)
        nxt = i + step
        if 0 <= nxt < len(active):
            return active[nxt].grab_focus()
        if self._modal_groups:
            return active[nxt % len(active)].grab_focus()
        if getattr(group, "lane", None) is not None and self._jump_lane(groups, group, active[i], step):
            return True
        toggle = getattr(group, "toggle", None)
        if step < 0:
            if toggle is not None and active[i] is toggle:
                if any(group is g for g in self._result_groups):
                    self.search_entry.grab_focus()  # back to typing
                return True
            if pane == "guide":
                return self.focus_pane("quick")
            if pane == "options":
                self.app.show_panels(True, False, focus="guide")
                return True
            return active[nxt % len(active)].grab_focus()
        # Past the right-hand end: continue into the next panel, opening it if it is closed.
        if pane == "quick":
            if self.guide_open:
                return self.focus_pane("guide")
            self.app.show_panels(True, False, focus="guide")
            return True
        if pane == "guide" and self.options_open:
            return self.focus_pane("options")
        return True

    def _jump_lane(self, groups, group, focused, step):
        """←/→ past the edge of a row in a column layout: go to the row beside it in the neighbouring column."""
        target = group.lane + step
        candidates = [g for g in groups if getattr(g, "lane", None) == target and self._landing(g) is not None]
        if not candidates:
            return False
        y = self._middle_y(focused)
        best = min(candidates, key=lambda g: abs(self._middle_y(self._landing(g)) - y))
        return self._landing(best).grab_focus()

    def _middle_y(self, widget):
        try:
            ok, rect = widget.compute_bounds(self)
            return rect.get_y() + rect.get_height() / 2 if ok else 0.0
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _result_index(self, focused):
        for i, g in enumerate(self._result_groups):
            if any(w is focused for w in g):
                return i
        return -1

    def _key_pressed(self, _controller, keyval, _keycode, state):
        if self._capture is not None and self._capture_key(keyval, state):
            return True
        focused = self.get_focus()
        editable = isinstance(focused, Gtk.Editable)
        typing = self._in_search(focused)
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Back):
            self._escape()
            return True  # the remote's Back key (XF86Back) is Esc
        if self._pin is not None and self._pin_key(keyval):
            return True
        if self._chan is not None and self._chan_key(keyval):
            return True
        if self._text is not None and not editable and self._text_key(keyval):
            return True
        # Typing anywhere starts a search (not while a dialog is up, in another text field, or with a shortcut modifier held).
        if not self._modal_groups and not editable and not (state & _TYPING_BLOCKED):
            ch = Gdk.keyval_to_unicode(keyval)
            if ch > 32 and chr(ch).isprintable():
                self._type_to_search(chr(ch))
                return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            step = 1 if keyval == Gdk.KEY_Down else -1
            if not self._modal_groups:
                # The results are above the search field, the best one nearest it: ↑ goes on to the next result (below
                # it in a top corner: ↓ does). Keep focus in the search field while arrows change the highlighted result
                # so typing can continue. `away` is +1 for the key that leads away from the search field.
                away = step if self.top else -step
                if typing and self.search_entry.get_text().strip() and self._search_results:
                    nxt = self._selected_result + away
                    if 0 <= nxt < len(self._search_results):
                        self._select_result(nxt)
                        return True
                    if away > 0:
                        self._focus_above_results()
                        return True  # past the last result: on to the lists
                ri = self._result_index(focused)
                if ri >= 0 and not (
                    away > 0 and self._result_groups[ri].expanded()
                ):  # on into its own open options instead
                    nxt = ri + away
                    if 0 <= nxt < len(self._result_groups):
                        self._select_result(nxt)
                        self._landing(self._result_groups[nxt]).grab_focus()
                        return True
                    if nxt < 0:
                        self.search_entry.grab_focus()
                        return True
                    self._focus_above_results()
                    return True
            self._move_group(step)
            return True
        if (
            keyval == Gdk.KEY_Right
            and typing
            and self._search_results
            and not self._modal_groups
            and self.search_entry.get_position() == len(self.search_entry.get_text())
        ):
            g = self._result_groups[
                self._selected_result
            ]  # at the end of the text, Right opens the highlighted result's menu
            if g.open_options is not None:
                g.open_options()
                return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and not editable:
            step = 1 if keyval == Gdk.KEY_Right else -1
            if self.right and not self._modal_groups:
                step = -step  # mirrored: rows run right to left (dialogs do not)
            if self._move_within_group(step):
                return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and typing:
            if not self.search_entry.get_text().strip():
                self.ask_search()
                return True  # Enter on an empty search: the on-screen keyboard
            self._activate_search()
            return True
        return False

    def _focus_above_results(self):
        """↑ past the last search result: the lowest row of the lists above it, else the header (↓ and the highest row of
        the lists below it, in a top corner)."""
        for g in reversed(self._groups["quick"]):
            w = self._landing(g)
            if w is not None and w.grab_focus():
                return
        if self._header_group:
            self._header_group[0].grab_focus()

    def _key_released(self, _controller, keyval, _keycode, state):
        if self._capture is not None:
            spec = self._capture.release(Gdk.keyval_name(keyval))
            if spec:
                self._end_capture(spec)

    def _escape(self):
        if self._modal_groups:
            (self._modal_back or self.close_modal)()
            return
        if self.search_folds and self.search_line.get_visible() and self._in_search(self.get_focus()):
            self.toggle_search()
            return  # Back folds the search bar away first, back onto the search icon
        row = self._open_row
        if row is not None and row.expanded():  # Back folds open options (or a status panel) first, back onto their row
            back = getattr(row, "opener", None) or getattr(row, "entry", None)
            if back is not None and usable(back):
                back.grab_focus()
            self._close_open()
            return
        if self.guide_open:
            self.app.show_panels(False, False, focus="quick")
            return  # then Applications, keep the Quick Menu
        self.app.hide_window()
