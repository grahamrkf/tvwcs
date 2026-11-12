"""What every Settings page shares: the Page class (reading the system on a worker thread, then drawing rows),
the pages that edit TVWCS's own options (_ConfigPage), and small helpers. Each page is in its own file here."""

from __future__ import annotations
import os, signal
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk, Pango

from tvwcs import __version__
from tvwcs.system import distro, features, servermode, sway_include
from tvwcs.core.model import ConfigStore
from tvwcs.system.session import runtime_dir
from tvwcs.settings.app import colour_swatch, in_background
from tvwcs.ui.widgets import NavGroup, S, clear_box, glyph, muted_label, section_title, usable


class Page:
    key = ""
    title = ""
    icon = ""
    fallback = ""
    poll = 0  # seconds between quiet re-reads while the page is on screen (0: only when asked)
    refreshable = True  # a ⟳ button at the top right re-reads the page
    sway_only = False  # it changes what TVWCS or sway do: shown turned off outside sway (sway_include.in_sway)
    server_off = False  # an administrator's page: shown turned off in server mode (servermode.py)

    def __init__(self, win):
        self.win = win
        self.state = None
        self.busy = False
        self.status = ""
        self._loaded = False
        self._poll = 0
        self.header = []
        self.groups = []
        self._ids = {}
        self.root = None

    # ---------------------------------------------------------- frame
    def widget(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.root = root
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(14))
        head.set_margin_top(S(12))
        head.set_margin_start(S(24))
        head.set_margin_end(S(24))
        head.set_margin_bottom(S(6))
        title = Gtk.Label(label=self.title)
        title.add_css_class("pane-title")
        title.set_xalign(0)
        head.append(title)
        self.subtitle = Gtk.Label()
        self.subtitle.add_css_class("muted")
        self.subtitle.set_valign(Gtk.Align.END)
        self.subtitle.set_margin_bottom(S(6))
        self.subtitle.set_xalign(0)
        self.subtitle.set_hexpand(True)
        self.subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        head.append(self.subtitle)
        if self.refreshable:
            b = Gtk.Button()
            b.add_css_class("square")
            b.set_valign(Gtk.Align.START)
            b.set_child(glyph("view-refresh-symbolic", "⟳"))
            b.set_tooltip_text("Check again")
            b.connect("clicked", lambda *_: self.refresh())
            head.append(b)
            self.header = [b]
        root.append(head)
        root.append(self.content())
        return root

    def content(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(4))
        self.body.set_margin_start(S(24))
        self.body.set_margin_end(S(24))
        self.body.set_margin_bottom(S(16))
        scroll.set_child(self.body)
        self.scroll = scroll
        return scroll

    def nav_groups(self):
        return ([NavGroup(self.header)] if self.header else []) + self.groups

    # ---------------------------------------------------------- reading
    def shown(self):
        if not self._loaded:
            self._loaded = True
            self.refresh()
        if self.poll and not self._poll:
            self._poll = GLib.timeout_add_seconds(self.poll, self._tick)

    def hidden(self):
        if self._poll:
            GLib.source_remove(self._poll)
            self._poll = 0

    def _tick(self):
        if not self.busy and not self.win.modal_open and self.win.is_visible():
            self.refresh(quiet=True)
        return GLib.SOURCE_CONTINUE

    def read(self):
        return None

    def feature_off(self):
        """The software this page needs (features.py) is not installed: the page only offers to install it."""
        key = features.PAGE_FEATURE.get(self.key)
        return key is not None and not features.installed(features.BY_KEY[key])

    def refresh(self, quiet=False):
        if self.feature_off():
            if not quiet or self.state is not None:
                self.state = None
                self.redraw()
            return
        if self.busy:
            return
        self.busy = True
        if not quiet:
            self.set_status("Checking…")

        def done(state):
            self.busy = False
            if not quiet:
                self.set_status("")
            if quiet and state == self.state:
                return
            self.state = state
            self.redraw()

        def failed(exc):
            self.busy = False
            self.set_status("")
            self.win.notice(f"{self.title}", f"Could not read the settings: {exc}")

        in_background(self.read, done, failed)

    def set_status(self, text):
        self.status = text
        self.subtitle.set_text(text or self.summary())

    def summary(self):
        return ""

    def act(self, work, status, title, after=None):
        """Change something on a worker thread: work() returns "" when it worked, else why not, which is shown.
        The page is read again afterwards."""
        self.set_status(status)

        def done(problem):
            self.set_status("")
            if problem:
                self.win.notice(title, problem)
            if after:
                after()
            self.busy = False
            self.refresh(quiet=True)

        def failed(exc):
            done(str(exc))

        self.busy = True
        in_background(work, done, failed)

    # ---------------------------------------------------------- drawing
    def redraw(self):
        """Draw the rows again from self.state, keeping the selection on the same row (by its id)."""
        focused = self.win.get_focus()
        old = None
        if focused is not None and self.root is not None and (focused is self.root or focused.is_ancestor(self.root)):
            old = next((i for i, w in self._ids.items() if w is focused or focused.is_ancestor(w)), None)
        stale = {id(w): i for i, w in self._ids.items()}
        old_rows = dict(self._ids)

        def row_of(
            w,
        ):  # a row's id from one of its widgets (its own button, or a ✕ beside it that may be gone after the change)
            if w is None:
                return None
            if id(w) in stale:
                return stale[id(w)]
            return next((i for i, ow in old_rows.items() if w.is_ancestor(ow)), None)

        wanted = getattr(self, "focus_after", None)
        self.focus_after = None  # the row a change turns the focused one into
        if wanted is not None and old is not None:
            old = wanted
        scroll = getattr(self, "scroll", None)
        top = scroll.get_vadjustment().get_value() if scroll is not None else 0
        clear_box(self.body)
        self.groups = []
        self._ids = {}
        if self.server_off and servermode.active():
            self.draw_off(lambda: self.draw(self.state), SERVER_OFF)
        elif self.feature_off():
            self.draw_feature_off()
        elif self.sway_only and not sway_include.in_sway():
            self.draw_off(lambda: self.draw(self.state))
        else:
            self.draw(self.state)
        if top and scroll is not None:  # rows drawn again (a dialog open over the page, say) stay where they were
            GLib.idle_add(lambda: (scroll.get_vadjustment().set_value(top), GLib.SOURCE_REMOVE)[1])
            self.subtitle.set_text(self.status or self.summary())
        for widget_ref in ("_return_focus",):  # a dialog open over this page goes back to the row's new button
            w = getattr(self.win, widget_ref, None)
            i = row_of(w)
            if i is not None and i not in self._ids:
                i = i.split("#")[0]
            if i in self._ids:
                setattr(self.win, widget_ref, self._ids[i])
        i = row_of(self.win._last_page_focus.get(self.key))
        if i is not None and i not in self._ids:
            i = i.split("#")[0]
        if i in self._ids:
            self.win._last_page_focus[self.key] = self._ids[i]
        ident = getattr(self, "focus_ident", None)
        if ident is not None and old is None and self._ids.get(ident) is not None:
            self.focus_ident = None
            GLib.idle_add(lambda w=self._ids[ident]: (usable(w) and w.grab_focus(), GLib.SOURCE_REMOVE)[1])
        if old is not None:
            # a row's ✕ (id "row#1") that went with the change: the row itself
            target = (
                self._ids.get(old)
                or self._ids.get(old.split("#")[0])
                or (next((w for i, w in self._ids.items() if i.startswith(old)), None) if old == wanted else None)
            )
            if target is not None and usable(target):
                target.grab_focus()
            elif not self.win._focus_first(self.groups):
                self.win.tab_buttons[self.key].grab_focus()

    def draw(self, state):
        pass

    def draw_feature_off(self):
        f = features.BY_KEY[features.PAGE_FEATURE[self.key]]
        self.section("NOT INSTALLED")
        self.note(f"{f.what} It needs software that is not installed yet.")
        if servermode.active():
            self.note(SERVER_HIDDEN)
            return
        self.row(
            f"Install {f.label}",
            "",
            lambda: install_feature(self, f),
            icon="list-add-symbolic",
            fallback="+",
            ident="feature:on",
            detail=f"Installs {', '.join(features.packages_for(f))}. It asks for your password.",
        )

    def draw_off(self, draw, note=None):
        """The rows draw() adds, shown turned off under a note: outside sway they would change nothing (a GNOME or KDE
        session, say). They cannot be selected."""
        self.note(note or SWAY_ONLY, "error")
        mark = self.body.get_last_child()
        groups = len(self.groups)
        ids = set(self._ids)
        draw()
        w = mark.get_next_sibling()
        while w is not None:
            w.set_sensitive(False)
            w = w.get_next_sibling()
        del self.groups[groups:]
        for i in set(self._ids) - ids:
            del self._ids[i]

    def add(self, widget):
        self.body.append(widget)
        return widget

    def section(self, text):
        return self.add(section_title(text))

    def note(self, text, css=None):
        l = muted_label(text)
        if css:
            l.add_css_class(css)
        return self.add(l)

    def register(self, *widgets, ident=None, column=False):
        g = NavGroup([w for w in widgets if w is not None])
        g.column = column
        if g:
            self.groups.append(g)
        if ident is not None and g:
            self._ids[ident] = g[0]
        for k, w in enumerate(g[1:], 1):
            if ident is not None:
                self._ids[f"{ident}#{k}"] = w
        return g

    def row(
        self,
        label,
        value="",
        on_activate=None,
        detail="",
        icon=None,
        fallback="",
        ident=None,
        extras=(),
        value_css="setting-value",
        swatch=None,
        indent=0,
    ):
        """One row: an optional icon, its name (and a detail line under it), its value on the right (after a square of
        the colour `swatch`); square extra buttons follow it on the same row. ← / → move between them. `indent` (px)
        sets it in under the row before it, as a partition under its drive."""
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        if indent:
            line.set_margin_start(S(indent))
        b = Gtk.Button()
        b.add_css_class("launch-row")
        b.set_hexpand(True)
        if on_activate is None:
            b.add_css_class("info-row")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(14))
        if icon is not None or fallback:
            g = glyph(icon, fallback, 24)
            g.set_size_request(S(32), -1)
            inner.append(g)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        name = Gtk.Label(label=label)
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(name)
        if detail:
            d = Gtk.Label(label=detail)
            d.add_css_class("row-detail")
            d.set_xalign(0)
            d.set_ellipsize(Pango.EllipsizeMode.END)
            text.append(d)
        inner.append(text)
        if swatch:
            inner.append(colour_swatch(swatch))
        if value:
            v = Gtk.Label(label=value)
            v.add_css_class(value_css)
            v.set_xalign(1)
            inner.append(v)
        b.set_child(inner)
        if on_activate is not None:
            b.connect("clicked", lambda *_: on_activate())
        line.append(b)
        extras = [e for e in extras if e is not None]
        for e in extras:
            e.add_css_class("square")
            line.append(e)
        self.add(line)
        self.register(b, *extras, ident=ident)
        return b

    def button(self, icon, fallback, tooltip, handler, danger=False):
        b = Gtk.Button()
        b.set_child(glyph(icon, fallback))
        b.set_tooltip_text(tooltip)
        b.connect("clicked", lambda *_: handler())
        if danger:
            b.add_css_class("close-button")
        return b


SWAY_ONLY = (
    'These settings work in sway only: in TVWCS\'s own session (choose "TVWCS" at the login screen, or type tvwcs at a '
    "text console) or in a sway session TVWCS is added to."
)


SERVER_OFF = (
    "This computer is in server mode, so these settings are left to its administrator. An administrator can turn "
    "server mode off in Settings › User."
)


SERVER_HIDDEN = "This computer is in server mode: changes that need an administrator are left to them."


def digits_label(digits):
    return f"{digits} digit{'s' if digits!=1 else ''}"


def _on_off(flag):
    return "On" if flag else "Off"


def _outcome(result, otherwise):
    """A settings.cmd.Result as act() wants it: "" when it worked, else why not."""
    return "" if result.ok else (result.message or otherwise)


# ====================================================================== Appearance (TVWCS's own)
def tell_tvwcs(request):
    """Ask the running TVWCS to read its options again ("reload") or to restart ("restart PATH"); False when it is not running.
    The same files and signal as main.send_request, written here rather than imported: after an update, main.py on disk
    is the new version, and importing it into this process (with the old versions of the other modules) can fail."""
    runtime = runtime_dir()
    try:
        pid = int((runtime / "tvwcs.pid").read_text(encoding="ascii").strip())
        os.kill(pid, 0)
        with open(runtime / "tvwcs-requests", "a", encoding="utf-8") as f:
            f.write(request + "\n")
        os.kill(pid, signal.SIGWINCH)
        return True
    except (OSError, ValueError):
        return False  # not running: it reads its options when it starts


class _ConfigPage(Page):
    """A page of TVWCS's own options. Each change is saved to TVWCS's config file, read fresh first so nothing TVWCS
    saved meanwhile is lost, and the running TVWCS is asked to read it again; so is this Settings window."""

    refreshable = False

    def read(self):
        return ConfigStore()

    def summary(self):
        return f"TVWCS {__version__}"

    def change(self, edit, notice=""):
        """edit(store) changes a freshly read store; it is saved, and TVWCS reads it again."""
        store = ConfigStore()
        edit(store)
        store.save()
        self.state = store
        self.redraw()
        tell_tvwcs("reload")
        self.win.settings_changed(store.settings)
        if notice:
            self.win.notice(self.title, notice)

    def toggle(self, key):
        def edit(store):
            store.settings[key] = not store.settings[key]

        return lambda: self.change(edit)

    def option(self, label, key, hint="", invert=False):
        on = bool(self.state.settings[key]) != invert
        self.row(label, _on_off(on), self.toggle(key), ident=f"opt:{key}")
        if hint:
            self.note(hint)

    def note(self, text, css=None):
        l = super().note(text, css)
        l.set_margin_bottom(S(6))
        return l


# ====================================================================== installing what a page needs
def install_feature(page, f, after=None):
    """Install the software a page needs (features.py), asking first; then the page reads again. after() runs once it is
    installed (Apps adds Flathub, say)."""

    def installed():
        tell_tvwcs("reload")
        if after:
            after()
        page.refresh(quiet=True)

    if features.installed(f):
        installed()
        return
    missing = features.missing_packages(f) or list(features.packages_for(f))
    if not distro.can_install():
        page.win.notice(
            f.label,
            f"{f.label} needs {', '.join(f.packages)} (the Debian names). Install them with your package manager.",
        )
        return
    lines = []

    def done(code, tail):
        page.set_status("")
        if code:
            page.win.notice(f.label, ("\n".join(lines[-6:]) or tail or "The packages could not be installed.").strip())
            return
        installed()

    def go():
        page.set_status(f"Installing {', '.join(missing)}…")
        page.win.run_as_root(features.install_argv(missing, f), f"Installing {f.label}", lines.append, done)

    page.win.confirm(
        f"Install {f.label}?",
        f"{f.what} It needs {', '.join(missing)}, which will be installed now. It asks for your password.",
        "Install",
        go,
        danger=False,
    )
