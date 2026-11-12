"""Settings > Displays: resolution, scale, rotation and the screen edge margin. Back end: settings/display.py."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from tvwcs.settings import display
from tvwcs.settings.app import in_background
from tvwcs.ui.widgets import S
from tvwcs.settings.pages.base import Page, _on_off


# ====================================================================== Displays
class DisplaysPage(Page):
    """Resolution, refresh rate and scale of each display; with several, which are on and where each one is. A change
    that can leave a screen blank or unreadable goes back by itself unless it is kept."""

    key = "displays"
    title = "Displays"
    icon = "video-display-symbolic"
    fallback = "🖵"
    poll = 5
    sway_only = True
    KEEP_SECONDS = 15

    def read(self):
        s = display.read_state()
        if s.available:
            names = self.monitor_names()
            for o in s.outputs:
                o.label = o.label or names.get(o.name, "")
        return s

    def monitor_names(self):
        """Connector -> the display's own name, from GDK."""
        gd = Gdk.Display.get_default()
        monitors = gd.get_monitors() if gd else None
        names = {}
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m = monitors.get_item(i)
            label = " ".join(
                x for x in ((m.get_manufacturer() or ""), (m.get_model() or "")) if x and x != "Unknown"
            ).strip()
            if m.get_connector() and label:
                names[m.get_connector()] = label
        return names

    def summary(self):
        s = self.state
        if not s or not s.available:
            return ""
        n = len(s.outputs)
        return f"{n} displays connected" if n > 1 else "1 display connected"

    def draw(self, s):
        if not s.available:
            self.note(s.message)
            return
        outs = s.outputs
        on = [o for o in outs if o.enabled]
        where = display.placements(outs)
        ref = display.reference(outs)
        if len(outs) > 1 and on:
            self.add(self.preview(outs))
        for i, o in enumerate(outs, 1):
            self.section(f"{i} · {o.title}".upper() + (f"  ({o.name})" if o.label else ""))
            if len(outs) > 1:
                self.row("Use this display", _on_off(o.enabled), lambda o=o: self.switch(o), ident=f"{o.name}:on")
            if not o.enabled:
                continue
            mode = o.mode()
            self.row(
                "Resolution",
                (display.mode_text(mode) if mode else f"{o.width} × {o.height}")
                + (" (recommended)" if mode and mode.preferred else ""),
                (lambda o=o: self.choose_mode(o)) if len(o.modes) > 1 else None,
                ident=f"{o.name}:mode",
            )
            rates = mode.rates if mode else []
            if o.rate or rates:
                self.row(
                    "Refresh rate",
                    display.rate_text(o.rate) if o.rate else "—",
                    (lambda o=o: self.choose_rate(o)) if len(rates) > 1 else None,
                    ident=f"{o.name}:rate",
                )
            self.scale_buttons(
                f"{o.name}:scale",
                display.scale_choices([o], o.scale),
                o.scale,
                lambda v, o=o: self.change(o, True, scale=v),
                "Makes text and controls bigger",
            )
            if len(on) > 1:
                if o is ref:
                    other = next((x for x in on if where.get(x.name, ("", ""))[1] == o.name), None)
                    value = display.RELATION_TEXT[display.relation(o, other)].format(other.title) if other else ""
                else:
                    rel, anchor = where[o.name]
                    value = display.RELATION_TEXT[rel].format(next(x.title for x in outs if x.name == anchor))
                self.row("Position", value, lambda o=o: self.choose_place(o), ident=f"{o.name}:place")
        notes = [
            f"A new resolution, refresh rate, scale or display switched on or off goes back after {self.KEEP_SECONDS} seconds unless you keep it, "
            "in case a display cannot show it."
        ]
        notes.append("What you keep is used again at the next log-in, as long as the same displays are connected.")
        self.note(" ".join(notes))

    def preview(self, outs):
        """The displays that are on, drawn where they are, each with the number of its section."""
        on = [(i, o) for i, o in enumerate(outs, 1) if o.enabled]
        minx = min(o.x for _i, o in on)
        miny = min(o.y for _i, o in on)
        maxx = max(o.x + o.size[0] for _i, o in on)
        maxy = max(o.y + o.size[1] for _i, o in on)
        k = min(S(560) / max(1, maxx - minx), S(180) / max(1, maxy - miny))
        fixed = Gtk.Fixed()
        fixed.set_halign(Gtk.Align.CENTER)
        fixed.set_margin_top(S(8))
        fixed.set_margin_bottom(S(8))
        fixed.set_size_request(round((maxx - minx) * k) + S(16), round((maxy - miny) * k) + S(16))
        seen = {}
        for i, o in on:
            shift = seen.get((o.x, o.y), 0)
            seen[(o.x, o.y)] = shift + 1  # mirrored displays sit on each other: offset a little
            w, h = o.size
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.add_css_class("display-box")
            box.set_size_request(max(S(24), round(w * k)), max(S(24), round(h * k)))
            box.set_overflow(Gtk.Overflow.HIDDEN)
            number = Gtk.Label(label=str(i))
            number.add_css_class("display-number")
            number.set_vexpand(True)
            box.append(number)
            name = Gtk.Label(label=o.title)
            name.add_css_class("display-name")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_margin_bottom(S(4))
            name.set_margin_start(S(4))
            name.set_margin_end(S(4))
            box.append(name)
            fixed.put(box, round((o.x - minx) * k) + shift * S(8), round((o.y - miny) * k) + shift * S(8))
        return fixed

    def scale_buttons(self, ident, choices, current, pick, detail):
        """Scale: one button per scale (75 % to 200 %), the one in use marked."""
        head = Gtk.Label(label="Scale")
        head.add_css_class("buttons-head")
        head.set_xalign(0)
        head.set_margin_top(S(6))
        self.add(head)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        line.set_homogeneous(True)
        buttons = []
        for v in choices:
            b = Gtk.Button(label=display.scale_text(v))
            if current is not None and abs(v - current) < 0.005:
                b.add_css_class("active")
            else:
                b.connect("clicked", lambda _b, v=v: pick(v))
            line.append(b)
            buttons.append(b)
        self.add(line)
        self.register(*buttons, ident=ident)
        self.note(detail)

    # ---------------------------------------------------------- choosing
    def choose_mode(self, o):
        mode = o.mode()
        self.win.choose_option(
            f"Resolution · {o.title}",
            [(m.key, display.mode_text(m) + (" (recommended)" if m.preferred else "")) for m in o.modes],
            mode.key if mode else None,
            lambda key: self.change(o, True, mode=key),
        )

    def choose_rate(self, o):
        mode = o.mode()
        self.win.choose_option(
            f"Refresh rate · {o.title}",
            [(r, display.rate_text(r)) for r in mode.rates],
            o.rate,
            lambda r: self.change(o, True, rate=r),
        )

    def choose_place(self, o):
        where = display.placements(self.state.outputs).get(o.name)

        def picked(key):
            rel, anchor = key.split(":", 1)
            self.change(o, False, place=(rel, anchor))

        self.win.choose_option(
            f"Position · {o.title}",
            display.choices(self.state.outputs, o),
            f"{where[0]}:{where[1]}" if where else None,
            picked,
        )

    def switch(self, o):
        if o.enabled and sum(x.enabled for x in self.state.outputs) == 1:
            self.win.notice("Displays", "This is the only display that is on, so it stays on.")
            return
        self.change(o, True, enabled=not o.enabled)

    # ---------------------------------------------------------- changing
    def change(self, o, risky, **changes):
        """Apply a change to one display now. A risky one waits to be kept, else goes back; the rest are kept at once."""
        self.change_all(display.edited(self.state.outputs, o.name, **changes), risky)

    def change_all(self, new, risky):
        s = self.state
        old = s.outputs
        self.set_status("Changing the displays…")
        self.busy = True

        def done(problem):
            self.busy = False
            self.set_status("")
            if problem:
                self.win.notice("Displays", problem)
                self.refresh(quiet=True)
            elif risky:
                GLib.timeout_add(
                    600, lambda: (self.ask_keep(s, old, new), GLib.SOURCE_REMOVE)[1]
                )  # let the screen settle first
            else:
                self.keep(s, new)

        in_background(lambda: display.apply(s, new), done, lambda exc: done(str(exc)))

    def ask_keep(self, s, old, new):
        def message(n):
            return f"Keep these display settings? They go back in {n} second{'s' if n!=1 else ''}."

        def undo():
            self.set_status("Going back…")
            self.busy = True

            def done(problem):
                self.busy = False
                self.set_status("")
                if problem:
                    self.win.notice("Displays", f"Could not go back to the earlier settings: {problem}")
                self.refresh(quiet=True)

            in_background(lambda: display.apply(s, old), done, lambda exc: done(str(exc)))

        self.win.countdown("Displays", message, self.KEEP_SECONDS, "Keep", lambda: self.keep(s, new), "Go back", undo)

    def keep(self, s, outputs):
        try:
            display.save(outputs)
        except OSError as exc:
            self.win.notice("Displays", f"The change is in use, but could not be saved for the next log-in: {exc}")
        self.refresh(quiet=True)
