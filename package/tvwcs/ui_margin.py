"""Settings > Appearance > Screen edge margin: a full-screen preview of where the Quick Menu and Applications sit, with
a slider and Accept / Cancel. The rectangles move as the slider does, so the edges a TV cuts off (overscan) can be
seen before the margin is saved."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from tvwcs.model import DEFAULT_CORNER, MARGIN_RANGE, compute_layout, corner_right
from tvwcs.widgets import S

STEP = 2  # px a press of ← or → moves the margin


def preview_rects(width, height, margin, quick_width, scale=1.0, corner=DEFAULT_CORNER):
    """The Quick Menu (its usual height, in its corner) and the Applications pane beside it (the full height), as
    (x, y, w, h) on a screen of width × height; margin and quick_width are at desktop scale."""
    m = int(round(margin * scale))
    area = {"x": 0, "y": 0, "width": width, "height": height}
    full = compute_layout(area, m, int(quick_width * scale), True, corner=corner)
    quick = compute_layout(area, m, int(quick_width * scale), False, quick_height=int(height * 0.55), corner=corner)
    rest = max(1, full.width - full.quick_width - full.margin)
    guide = (full.x if corner_right(corner) else full.x + full.quick_width + full.margin, full.y, rest, full.height)
    return (quick.x, quick.y, quick.width, quick.height), guide


class MarginPreview(Gtk.Window):
    """Full screen. on_done(margin) runs with the chosen margin on Accept, or with None on Cancel (or Esc / Back)."""

    def __init__(self, parent, margin, quick_width, scale, accent, on_done, corner=DEFAULT_CORNER):
        super().__init__(title="TVWCS · Screen edge margin")
        self.set_decorated(False)
        if parent is not None:
            self.set_transient_for(parent)
            self.set_modal(True)
        self.margin = int(margin)
        self.quick_width = quick_width
        self.scale = scale
        self.accent = accent
        self.on_done = on_done
        self.corner = corner
        self._done = False
        overlay = Gtk.Overlay()
        self.area = Gtk.DrawingArea()
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        overlay.set_child(self.area)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=S(10))
        card.add_css_class("modal-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        card.set_size_request(S(520), -1)
        title = Gtk.Label(label="Screen edge margin")
        title.add_css_class("pane-title")
        card.append(title)
        hint = Gtk.Label(
            label="Move the slider until both rectangles are fully on screen, with their edges visible. ← and → move it."
        )
        hint.set_wrap(True)
        hint.add_css_class("muted")
        card.append(hint)
        lo, hi = MARGIN_RANGE
        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        self.slider.set_value(self.margin)
        self.slider.set_draw_value(False)
        self.slider.connect("value-changed", self._moved)
        card.append(self.slider)
        self.value = Gtk.Label()
        self.value.add_css_class("pane-title")
        card.append(self.value)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(10))
        row.set_homogeneous(True)
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("big-button")
        cancel.connect("clicked", lambda *_: self._finish(None))
        accept = Gtk.Button(label="Accept")
        accept.add_css_class("big-button")
        accept.add_css_class("active")
        accept.connect("clicked", lambda *_: self._finish(self.margin))
        row.append(cancel)
        row.append(accept)
        card.append(row)
        self.accept = accept
        self.cancel = cancel
        overlay.add_overlay(card)
        self.set_child(overlay)
        self._show_value()
        key = Gtk.EventControllerKey()
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._key)
        self.add_controller(key)
        self.connect("close-request", lambda *_: (self._finish(None), False)[1])
        self.fullscreen()
        self.present()
        accept.grab_focus()

    def _show_value(self):
        self.value.set_text(f"{self.margin} px" + (" (none)" if self.margin == 0 else ""))

    def _moved(self, scale):
        self.margin = int(round(scale.get_value()))
        self._show_value()
        self.area.queue_draw()

    def _key(self, _c, keyval, _code, _state):
        lo, hi = MARGIN_RANGE
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.slider.set_value(max(lo, self.margin - STEP))
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.slider.set_value(min(hi, self.margin + STEP))
            return True
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Back):
            self._finish(None)
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Tab):  # only two buttons: up and down change between them
            (self.cancel if self.get_focus() is self.accept else self.accept).grab_focus()
            return True
        return False

    def _draw(self, _area, cr, width, height):
        cr.set_source_rgb(0.05, 0.05, 0.05)
        cr.paint()
        rgba = Gdk.RGBA()
        rgba.parse(self.accent)
        quick, guide = preview_rects(width, height, self.margin, self.quick_width, self.scale, self.corner)
        for (x, y, w, h), label, alpha in ((guide, "Applications", 0.25), (quick, "Quick Menu", 0.45)):
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, alpha)
            cr.rectangle(x, y, w, h)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(4)
            cr.rectangle(x + 2, y + 2, w - 4, h - 4)
            cr.stroke()
            cr.select_font_face("Sans")
            cr.set_font_size(max(16, height / 40))
            cr.move_to(x + 20, y + 20 + max(16, height / 40))
            cr.show_text(label)

    def _finish(self, margin):
        if self._done:
            return
        self._done = True
        self.destroy()
        self.on_done(margin)
