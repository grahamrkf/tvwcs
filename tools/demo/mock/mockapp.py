"""A mockup application window for the TVWCS demo: draws its static mockup screen at the window's size."""

import sys, os

NAME, TITLE = sys.argv[1], sys.argv[2]
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

GLib.set_prgname(NAME)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], "/nonexistent"]
import importlib.util

spec = importlib.util.spec_from_file_location(
    "mi", os.path.join(os.path.dirname(os.path.abspath(__file__)), "images_lib.py")
)
mi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mi)
import cairo


def draw(area, c, w, h):
    if NAME in ("orbit", "lantern", "pagewright", "gridline"):
        s = mi.render(NAME, w, h)
        c.set_source_surface(s, 0, 0)
        c.paint()
    else:
        s = mi.render(NAME, 1920, 1080)
        k = max(w / 1920, h / 1080)
        c.translate((w - 1920 * k) / 2, (h - 1080 * k) / 2)
        c.scale(k, k)
        c.set_source_surface(s, 0, 0)
        c.paint()


def activate(app):
    win = Gtk.ApplicationWindow(application=app, title=TITLE)
    win.set_default_size(1280, 720)
    a = Gtk.DrawingArea()
    a.set_draw_func(draw)
    win.set_child(a)
    win.present()


app = Gtk.Application(application_id=f"demo.mockup.{NAME}", flags=0)
app.connect("activate", activate)
app.run([])
