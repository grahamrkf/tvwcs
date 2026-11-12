"""Remote-navigation logic of the main window, exercised without GTK: `gi` is replaced by a stub and the
window's methods run against fake widgets. (Appearance and real focus behaviour still need a real desktop.)"""

import sys, types, unittest
from unittest.mock import MagicMock

_SAVED = {k: sys.modules.get(k) for k in ("gi", "gi.repository")}


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = MagicMock()
        setattr(self, name, value)
        return value


def _install_stub():
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a, **k: None
    repo = types.ModuleType("gi.repository")
    Gdk = _Stub("Gdk")

    class ModifierType:
        CONTROL_MASK = 4
        ALT_MASK = 8
        SUPER_MASK = 16
        META_MASK = 32
        SHIFT_MASK = 1

    Gdk.ModifierType = ModifierType
    for n, v in dict(
        KEY_Escape=1,
        KEY_Down=2,
        KEY_Up=3,
        KEY_Left=4,
        KEY_Right=5,
        KEY_Return=6,
        KEY_KP_Enter=7,
        KEY_Back=8,
        KEY_BackSpace=9,
    ).items():
        setattr(Gdk, n, v)
    Gdk.keyval_to_unicode = lambda k: k if k >= 32 else 0
    Gtk = _Stub("Gtk")

    class Editable:
        pass

    Gtk.Editable = Editable
    Gtk.ApplicationWindow = type("ApplicationWindow", (), {})
    Gtk.Application = type("Application", (), {})
    Gtk.Window = type("Window", (), {})
    repo.Gdk = Gdk
    repo.Gtk = Gtk
    repo.Gio = _Stub("Gio")
    repo.GLib = _Stub("GLib")
    repo.Graphene = _Stub("Graphene")
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repo
    gi.repository = repo


_install_stub()
import importlib

_REAL = {k: v for k, v in sys.modules.items() if k.startswith("tvwcs.")}
for m in [m for m in sys.modules if m == "tvwcs.ui" or m.startswith("tvwcs.ui.")]:
    sys.modules.pop(m, None)  # the launcher's GTK modules load again, against the stub
ui_window = importlib.import_module("tvwcs.ui.window")
NavGroup = sys.modules["tvwcs.ui.widgets"].NavGroup
for k, v in _SAVED.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v
# the modules loaded against the stub stay with this file: later tests import their own, with the real GTK or none
for k in sorted((k for k in sys.modules if k.startswith("tvwcs.")), key=len):
    if k in _REAL:
        sys.modules[k] = _REAL[k]
    else:
        sys.modules.pop(k, None)
    parent, leaf = k.rsplit(".", 1)
    if parent in sys.modules and hasattr(sys.modules[parent], leaf):
        if k in _REAL:
            setattr(sys.modules[parent], leaf, _REAL[k])
        else:
            delattr(sys.modules[parent], leaf)
Editable = ui_window.Gtk.Editable


class W:
    focus = None

    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.focused = 0

    def get_visible(self):
        return True

    def get_mapped(self):
        return True

    def get_sensitive(self):
        return True

    def is_ancestor(self, other):
        p = self.parent
        while p is not None:
            if p is other:
                return True
            p = p.parent
        return False

    def grab_focus(self):
        W.focus = self
        self.focused += 1
        return True


class Entry(W, Editable):
    pass


def make_window(**state):
    win = ui_window.TVWCSWindow.__new__(ui_window.TVWCSWindow)
    win.app = MagicMock()
    win._groups = {"quick": [], "guide": [], "options": []}
    win._header_group = []
    win._result_groups = []
    win._modal_groups = []
    win.guide_open = False
    win.options_open = False
    win.guide_pane = None
    win.options_pane = None
    win._last_focus = {}
    win._search_results = []
    win._selected_result = 0
    win._capture = None
    win._pin = None
    win._password = None
    win._chan = None
    win._text = None
    win._focus_tip = None
    win._focus_tip_source = 0
    win.search_entry = Entry("search")
    win.get_focus = lambda: W.focus
    win._type_to_search = MagicMock()
    win._escape = MagicMock()
    for k, v in state.items():
        setattr(win, k, v)
    return win


def options_row(win, expanded=False, pane="quick", results=False):
    toggle, opt, main = W("toggle"), W("opt"), W("main")
    state = {"open": expanded}
    g = NavGroup([toggle, opt, main], entry=main)
    g.toggle = toggle
    g.expanded = lambda: state["open"]
    g.expand = MagicMock(side_effect=lambda: state.update(open=True))
    (win._result_groups if results else win._groups[pane]).append(g)
    if not expanded:
        opt.get_mapped = lambda: False  # collapsed options are not on screen
    return g, toggle, opt, main


class NavigationTests(unittest.TestCase):
    def test_exact_match_beats_container_match(self):
        # A category header whose rows sit inside it: focus on a row must not be read as focus on the header.
        win = make_window()
        container = W("container")
        row = W("row", parent=container)
        groups = [NavGroup([container]), NavGroup([row])]
        self.assertEqual(win._group_index(groups, row), 1)
        self.assertEqual(win._group_index(groups, container), 0)
        self.assertEqual(
            win._group_index(groups, W("elsewhere", parent=container)), 0
        )  # inside-match still works as a fallback

    def test_left_on_a_quick_menu_row_opens_its_menu(self):
        win = make_window()
        g, toggle, opt, main = options_row(win)
        W.focus = main
        g.open_options = MagicMock(return_value=True)
        g.expanded = lambda: False
        self.assertTrue(win._move_within_group(-1))
        g.open_options.assert_called_once()

    def test_left_again_when_expanded_stays_put(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True)
        W.focus = toggle
        win._move_within_group(-1)
        g.expand.assert_not_called()
        self.assertIs(W.focus, toggle)

    def test_left_on_expanded_search_result_options_returns_to_typing(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True, results=True)
        W.focus = toggle
        win._move_within_group(-1)
        self.assertIs(W.focus, win.search_entry)

    def test_right_moves_through_the_row(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True)
        W.focus = toggle
        win._move_within_group(1)
        self.assertIs(W.focus, opt)
        win._move_within_group(1)
        self.assertIs(W.focus, main)

    def test_right_past_the_end_of_the_quick_menu_opens_the_guide(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True)
        W.focus = main
        win._move_within_group(1)
        win.app.show_panels.assert_called_once_with(True, False, focus="guide")

    def test_right_goes_into_an_already_open_guide(self):
        guide = W("guide_pane")
        win = make_window(guide_open=True, guide_pane=guide)
        g, toggle, opt, main = options_row(win, expanded=True)
        inner = W("g1", parent=guide)
        win._groups["guide"].append(NavGroup([inner]))
        W.focus = main
        win._move_within_group(1)
        win.app.show_panels.assert_not_called()
        self.assertIs(W.focus, inner)

    def test_right_past_the_end_of_the_guide_stays_put(self):
        guide = W("guide_pane")
        win = make_window(guide_open=True, guide_pane=guide)
        last = W("star", parent=guide)
        win._groups["guide"].append(NavGroup([W("main", parent=guide), last]))
        W.focus = last
        self.assertTrue(win._move_within_group(1))
        win.app.show_panels.assert_not_called()
        self.assertIs(W.focus, last)

    def test_left_from_settings_closes_it_and_returns_to_the_guide(self):
        guide, options = W("guide"), W("options")
        win = make_window(guide_open=True, options_open=True, guide_pane=guide, options_pane=options)
        row = W("row", parent=options)
        win._groups["options"].append(NavGroup([row]))
        W.focus = row
        win._move_within_group(-1)
        win.app.show_panels.assert_called_once_with(True, False, focus="guide")

    def test_right_in_settings_goes_nowhere(self):
        guide, options = W("guide"), W("options")
        win = make_window(guide_open=True, options_open=True, guide_pane=guide, options_pane=options)
        row = W("row", parent=options)
        win._groups["options"].append(NavGroup([row]))
        W.focus = row
        win._move_within_group(1)
        win.app.show_panels.assert_not_called()

    def test_left_on_a_quick_menu_row_opens_its_options(self):
        win = make_window()
        g, toggle, opt, main = options_row(win)
        g.open_options = MagicMock(return_value=True)
        W.focus = main
        self.assertTrue(win._move_within_group(-1))
        g.open_options.assert_called_once()

    def test_left_on_a_row_whose_options_are_open_moves_into_them(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True)
        g.open_options = MagicMock()
        W.focus = main
        win._move_within_group(-1)
        g.open_options.assert_not_called()
        self.assertIs(W.focus, opt)

    def fold_window(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True)
        g.menu = [toggle, opt]
        g.collapse = MagicMock()
        win._open_row = g
        win._popovers = 0
        return win, g, toggle, opt, main

    def test_options_fold_when_the_selection_leaves_them(self):
        win, g, toggle, opt, main = self.fold_window()
        win._fold_options(opt)
        g.collapse.assert_not_called()
        win._fold_options(main)
        g.collapse.assert_called_once()
        self.assertIsNone(win._open_row)

    def test_options_stay_open_while_a_popup_or_dialog_from_them_is_up(self):
        win, g, toggle, opt, main = self.fold_window()
        win._popovers = 1
        win._fold_options(W("popup item"))
        g.collapse.assert_not_called()
        win._popovers = 0
        win._modal_groups = [NavGroup([W("cancel")])]
        win._fold_options(W("cancel"))
        g.collapse.assert_not_called()

    def test_open_options_sit_just_above_their_row_in_the_navigation_order(self):
        win = make_window()
        a = options_row(win, expanded=True)
        b = options_row(win, expanded=True)
        o1, o2 = W("option 2"), W("option 1")
        b[0].options = [NavGroup([o1]), NavGroup([o2])]
        order = win._ordered_groups("quick")
        self.assertEqual([order.index(g) for g in (a[0], *b[0].options, b[0])], [1, 2, 3, 4])
        W.focus = b[3]
        win._move_group(-1)
        self.assertIs(W.focus, o2)  # ↑ from the row: its nearest option
        win._move_group(-1)
        self.assertIs(W.focus, o1)
        win._move_group(-1)
        self.assertIs(W.focus, a[3])

    def test_a_top_corner_reverses_the_navigation_order(self):
        win = make_window()
        options_row(win, expanded=True)
        b = options_row(win, expanded=True)
        o1, o2 = W("option 2"), W("option 1")
        b[0].options = [NavGroup([o1]), NavGroup([o2])]
        bottom = win._ordered_groups("quick")
        win.app.store.settings = {"quick_corner": "top-left"}
        self.assertEqual(win._ordered_groups("quick"), bottom[::-1])
        W.focus = b[3]
        win._move_group(1)
        self.assertIs(W.focus, o2)  # ↓ from the row: its nearest option, below it

    def test_down_goes_through_the_results_in_a_top_corner(self):
        win = make_window()
        win.app.store.settings = {"quick_corner": "top-right"}
        win._search_results = [1, 2, 3]
        win._select_result = MagicMock()
        win.search_entry.get_text = lambda: "fire"
        W.focus = win.search_entry
        win._key_pressed(None, ui_window.Gdk.KEY_Down, 0, 0)
        win._select_result.assert_called_once_with(1)

    def test_right_hand_corner_swaps_left_and_right(self):
        win = make_window()
        win.app.store.settings = {"quick_corner": "bottom-right"}
        win._move_within_group = MagicMock(return_value=True)
        W.focus = W("row")
        win._key_pressed(None, ui_window.Gdk.KEY_Right, 0, 0)
        win._move_within_group.assert_called_once_with(-1)
        win._modal_groups = [NavGroup([W("key")])]
        win._move_within_group.reset_mock()  # a dialog keeps its order
        win._key_pressed(None, ui_window.Gdk.KEY_Right, 0, 0)
        win._move_within_group.assert_called_once_with(1)

    def test_left_and_right_stay_on_an_option(self):
        win = make_window()
        g = options_row(win, expanded=True)[0]
        opt = W("option")
        item = NavGroup([opt])
        item.option_item = True
        g.options = [item]
        W.focus = opt
        self.assertTrue(win._move_within_group(1))
        self.assertTrue(win._move_within_group(-1))
        win.app.show_panels.assert_not_called()
        self.assertIs(W.focus, opt)

    def test_an_open_status_panel_is_between_search_and_the_status_row(self):
        win = make_window()
        p = W("wifi")
        win._panel_groups = [NavGroup([p])]
        status = NavGroup([W("wifi icon"), W("power")])
        win._status_group = status
        clock = NavGroup([W("clock"), W("settings"), W("guide")])
        win._clock_group = clock  # the clock, ⚙ and ⊞: a row below the status icons
        order = win._ordered_groups("quick")
        self.assertEqual(order[-3:], [win._panel_groups[0], status, clock])
        self.assertEqual(order[-4], [win.search_entry])

    def test_a_panel_stays_open_while_the_selection_is_on_what_it_owns(self):
        win = make_window()
        collapse = MagicMock()
        opener = W("power")
        inside = W("lock")
        win._open_row = types.SimpleNamespace(
            owns=lambda w: w is opener or w is inside, expanded=lambda: True, collapse=collapse
        )
        win._popovers = 0
        win._fold_options(inside)
        win._fold_options(opener)
        collapse.assert_not_called()
        win._keep_panel = True
        win._fold_options(W("elsewhere"))
        collapse.assert_not_called()  # being redrawn
        win._keep_panel = False
        win._fold_options(W("elsewhere"))
        collapse.assert_called_once()
        self.assertIsNone(win._open_row)

    def test_back_folds_open_options_onto_their_row(self):
        win = make_window()
        g, toggle, opt, main = options_row(win, expanded=True)
        g.collapse = MagicMock()
        win._open_row = g
        W.focus = opt
        ui_window.TVWCSWindow._escape(win)
        g.collapse.assert_called_once()
        self.assertIs(W.focus, main)
        win.app.hide_window.assert_not_called()

    def folding_search(self, shown=True, text=""):
        win = make_window(search_folds=True, _popovers=0)
        line = W("line")
        line.visible = shown
        line.get_visible = lambda: line.visible
        line.set_visible = lambda v: setattr(line, "visible", v)
        win.search_line = line
        win.search_button = MagicMock()
        win.search_entry.parent = line
        win.search_entry.get_text = lambda: text
        win.search_entry.set_text = MagicMock()
        win.search_entry.set_position = MagicMock()
        return win, line

    def test_the_search_bar_folds_away_when_left_empty(self):
        win, line = self.folding_search()
        win._fold_search(win.search_entry)
        self.assertTrue(line.visible)  # still typing
        win._modal_groups = [[W("key")]]
        win._fold_search(W("key"))
        self.assertTrue(line.visible)  # its on-screen keyboard
        win._modal_groups = []
        win._fold_search(W("row"))
        self.assertFalse(line.visible)
        win, line = self.folding_search(text="fire")
        win._fold_search(W("result"))
        self.assertTrue(line.visible)  # a search stays open

    def test_typing_unfolds_the_search_bar_with_the_key_typed(self):
        win, line = self.folding_search(shown=False)
        del win._type_to_search
        win._type_to_search("f")
        self.assertTrue(line.visible)
        win.search_entry.set_text.assert_called_with("f")
        self.assertIs(W.focus, win.search_entry)

    def test_the_quick_menu_opens_beside_a_folded_search_bar(self):
        win, line = self.folding_search(shown=False)
        row = W("fav")
        win._groups["quick"].append(NavGroup([row]))
        win.focus_pane("search")
        self.assertIs(W.focus, row)
        line.visible = True
        win.focus_pane("search")
        self.assertIs(W.focus, win.search_entry)

    def test_back_folds_the_search_bar_onto_its_icon(self):
        win, line = self.folding_search(text="fi")
        W.focus = win.search_entry
        win._open_row = None
        ui_window.TVWCSWindow._escape(win)
        self.assertFalse(line.visible)
        win.search_entry.set_text.assert_called_with("")
        win.search_button.grab_focus.assert_called_once()
        win.app.hide_window.assert_not_called()

    def lanes(self):
        guide = W("guide_pane")
        win = make_window(guide_open=True, guide_pane=guide)
        rows = {}
        for lane in (0, 1):
            for n in range(2):
                b = W(f"l{lane}r{n}", parent=guide)
                grp = NavGroup([b])
                grp.lane = lane
                win._groups["guide"].append(grp)
                rows[lane, n] = b
        shared = W("system", parent=guide)
        win._groups["guide"].append(NavGroup([shared]))
        return win, rows, shared

    def test_left_and_right_jump_between_settings_columns(self):
        win, rows, _ = self.lanes()
        W.focus = rows[0, 1]
        win._move_within_group(1)
        self.assertIn(W.focus, (rows[1, 0], rows[1, 1]))
        win._move_within_group(-1)
        self.assertIn(W.focus, (rows[0, 0], rows[0, 1]))
        win.app.show_panels.assert_not_called()

    def test_up_down_stays_in_its_settings_column(self):
        win, rows, shared = self.lanes()
        W.focus = rows[0, 0]
        win._move_group(1)
        self.assertIs(W.focus, rows[0, 1])
        win._move_group(1)
        self.assertIs(W.focus, shared)

    def test_up_down_lands_on_the_main_button(self):
        win = make_window()
        a = options_row(win, expanded=True)
        b = options_row(win, expanded=True)
        W.focus = a[3]
        win._move_group(1)
        self.assertIs(W.focus, b[3])


class TypingTests(unittest.TestCase):
    def press(self, win, key, state=0):
        return win._key_pressed(None, key, 0, state)

    def test_typing_anywhere_goes_to_search(self):
        win = make_window()
        W.focus = W("button")
        self.assertTrue(self.press(win, ord("f")))
        win._type_to_search.assert_called_once_with("f")

    def test_space_and_control_keys_are_left_alone(self):
        win = make_window()
        W.focus = W("button")
        self.assertFalse(self.press(win, ord(" ")))
        self.assertFalse(self.press(win, ord("c"), ui_window.Gdk.ModifierType.CONTROL_MASK))
        win._type_to_search.assert_not_called()

    def test_typing_in_a_text_field_is_not_hijacked(self):
        win = make_window()
        W.focus = Entry("password")
        self.press(win, ord("x"))
        win._type_to_search.assert_not_called()

    def test_typing_during_a_dialog_is_not_hijacked(self):
        win = make_window()
        win._modal_groups = [NavGroup([W("ok")])]
        W.focus = W("ok")
        self.press(win, ord("x"))
        win._type_to_search.assert_not_called()

    def test_escape_is_handled_first(self):
        win = make_window()
        W.focus = W("b")
        self.assertTrue(self.press(win, 1))
        win._escape.assert_called_once()

    def test_back_key_does_the_same_as_escape(self):
        win = make_window()
        W.focus = W("b")
        self.assertTrue(self.press(win, ui_window.Gdk.KEY_Back))
        win._escape.assert_called_once()

    def test_back_key_cancels_hotkey_capture(self):
        win = make_window()
        win._capture = MagicMock()
        win._end_capture = MagicMock()
        win.get_focus = lambda: W.focus
        self.assertTrue(self.press(win, ui_window.Gdk.KEY_Back))
        win._end_capture.assert_called_once_with(None)


class PinPadTests(unittest.TestCase):
    def pad(self, pin="1234"):
        from tvwcs.core.pinlock import PinGate, make_hash
        from tvwcs.core.model import LaunchProfile

        win = make_window()
        profile = LaunchProfile("p", "a.desktop", "Kids", pin_hash=make_hash(pin))
        win.app.pin_gate = PinGate()
        win._pin = {"profile": profile, "on_ok": MagicMock(), "digits": "", "shown": MagicMock()}
        win.close_modal = MagicMock()
        win.ask_pin = MagicMock()
        return win

    def test_digits_build_up_and_are_capped_at_eight(self):
        win = self.pad()
        for d in "123456789":
            win._pin_press(d)
        self.assertEqual(win._pin["digits"], "12345678")
        win._pin_back()
        self.assertEqual(win._pin["digits"], "1234567")

    def test_keyboard_digits_and_backspace_work_on_the_keypad(self):
        win = self.pad()
        W.focus = W("button")
        for ch in "12":
            self.assertTrue(win._key_pressed(None, ord(ch), 0, 0))
        self.assertEqual(win._pin["digits"], "12")
        win._key_pressed(None, ui_window.Gdk.KEY_BackSpace, 0, 0)
        self.assertEqual(win._pin["digits"], "1")

    def test_typing_on_the_keypad_does_not_start_a_search(self):
        win = self.pad()
        win._modal_groups = [NavGroup([W("key")])]
        W.focus = W("button")  # ask_pin always has the modal groups set
        win._key_pressed(None, ord("x"), 0, 0)
        win._type_to_search.assert_not_called()

    def test_right_pin_runs_the_action(self):
        win = self.pad()
        on_ok = win._pin["on_ok"]
        win._pin["digits"] = "1234"
        win._pin_submit()
        win.close_modal.assert_called_once()
        on_ok.assert_called_once()
        win.ask_pin.assert_not_called()

    def test_wrong_pin_asks_again_with_a_message(self):
        win = self.pad()
        win._pin["digits"] = "9999"
        win._pin_submit()
        win.ask_pin.assert_called_once()
        self.assertEqual(win.ask_pin.call_args[0][2], "Wrong PIN.")
        win._pin["on_ok"].assert_not_called()

    def test_too_many_wrong_pins_lock_the_keypad(self):
        win = self.pad()
        for _ in range(5):
            win._pin["digits"] = "9999"
            win._pin_submit()
        self.assertIn("Too many wrong tries", win.ask_pin.call_args[0][2])

    def test_up_down_keeps_the_keypad_column(self):
        win = self.pad()
        rows = []
        for r in range(3):
            g = NavGroup([W(f"r{r}c{c}") for c in range(3)])
            g.column = True
            rows.append(g)
        win._modal_groups = rows
        W.focus = rows[0][2]
        win._move_group(1)
        self.assertIs(W.focus, rows[1][2])
        win._move_group(1)
        self.assertIs(W.focus, rows[2][2])
        win._move_group(-1)
        self.assertIs(W.focus, rows[1][2])


if __name__ == "__main__":
    unittest.main()
