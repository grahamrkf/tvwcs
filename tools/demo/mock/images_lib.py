"""Draw the static mockup screens and icons (cairo). Every screen carries a large MOCKUP label."""

import cairo, math, random, sys, os

W, H = 1920, 1080


def rr(c, x, y, w, h, r):
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    c.close_path()


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def text(c, s, x, y, size, col=(1, 1, 1), bold=False, align="l"):
    c.select_font_face(
        "Open Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
    )
    c.set_font_size(size)
    e = c.text_extents(s)
    if align == "c":
        x -= e.x_advance / 2
    if align == "r":
        x -= e.x_advance
    c.set_source_rgb(*col)
    c.move_to(x, y)
    c.show_text(s)


def banner(c, label, w=W, h=H):
    # diagonal-free, unmistakable label: a yellow strip across the bottom and a corner tag
    c.set_source_rgba(1, 0.82, 0.1, 0.95)
    c.rectangle(0, h - 90, w, 90)
    c.fill()
    text(
        c,
        f"MOCKUP  ·  {label} is not a real application",
        w / 2,
        h - 32,
        max(18, min(36, w / 38)),
        (0.1, 0.1, 0.1),
        True,
        "c",
    )
    c.set_source_rgba(1, 0.82, 0.1, 0.95)
    c.rectangle(w - 330, 0, 330, 70)
    c.fill()
    text(c, "MOCKUP APP", w - 165, 48, 36, (0.1, 0.1, 0.1), True, "c")


def tiles(c, x0, y0, cols, rows, tw, th, gap, palette, seed, labels=None, radius=10):
    rnd = random.Random(seed)
    i = 0
    for r in range(rows):
        for k in range(cols):
            x = x0 + k * (tw + gap)
            y = y0 + r * (th + gap)
            a = hexc(rnd.choice(palette))
            b = hexc(rnd.choice(palette))
            g = cairo.LinearGradient(x, y, x + tw, y + th)
            g.add_color_stop_rgb(0, *a)
            g.add_color_stop_rgb(1, *b)
            rr(c, x, y, tw, th, radius)
            c.set_source(g)
            c.fill()
            if labels:
                text(c, labels[i % len(labels)], x + 16, y + th - 18, 24, (1, 1, 1), True)
            i += 1


def surface():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    return s, cairo.Context(s)


def streamly():
    s, c = surface()
    c.set_source_rgb(*hexc("#06070c"))
    c.paint()
    text(c, "Streamly", 60, 80, 52, hexc("#e0103f"), True)
    for i, t in enumerate(["Home", "Movies", "Series", "Live", "My list"]):
        text(c, t, 420 + i * 170, 78, 28, (0.85, 0.85, 0.9))
    g = cairo.LinearGradient(0, 120, W, 560)
    g.add_color_stop_rgb(0, *hexc("#12002e"))
    g.add_color_stop_rgb(0.55, *hexc("#3c096c"))
    g.add_color_stop_rgb(1, *hexc("#9d0208"))
    rr(c, 60, 120, W - 120, 420, 18)
    c.set_source(g)
    c.fill()
    text(c, "The Long Orbit", 110, 380, 84, (1, 1, 1), True)
    text(c, "Season 2 · New episodes every Friday", 112, 440, 32, (1, 1, 1))
    rr(c, 112, 470, 210, 56, 8)
    c.set_source_rgb(1, 1, 1)
    c.fill()
    text(c, "Play", 150, 508, 30, (0.1, 0.1, 0.1), True)
    text(c, "Continue watching", 60, 610, 34, (1, 1, 1), True)
    tiles(
        c,
        60,
        635,
        6,
        1,
        280,
        158,
        24,
        ["#9d0208", "#3c096c", "#03045e", "#023e8a", "#6a040f", "#0b3d2e"],
        1,
        ["Episode 4", "Night Shift", "Deep Blue", "Harbor", "Ridge", "Signals"],
    )
    text(c, "Trending", 60, 850, 34, (1, 1, 1), True)
    tiles(c, 60, 875, 6, 1, 280, 100, 24, ["#14213d", "#5a0f2e", "#240046", "#0a2463", "#1b4332"], 2)
    banner(c, "Streamly")
    return s


def gameshelf():
    s, c = surface()
    c.set_source_rgb(*hexc("#070b14"))
    c.paint()
    c.set_source_rgb(*hexc("#0d1626"))
    c.rectangle(0, 0, 360, H)
    c.fill()
    text(c, "GameShelf", 40, 80, 48, hexc("#2fa4e7"), True)
    for i, t in enumerate(["Library", "Store", "Downloads", "Friends", "Settings"]):
        if i == 0:
            c.set_source_rgb(*hexc("#123a5c"))
            c.rectangle(0, 130 + i * 70, 360, 64)
            c.fill()
        text(c, t, 48, 172 + i * 70, 30, (0.9, 0.93, 1))
    text(c, "Library  ·  48 games", 410, 80, 40, (1, 1, 1), True)
    tiles(
        c,
        410,
        120,
        6,
        3,
        230,
        290,
        22,
        ["#0b3c5d", "#1d2d50", "#3a5a07", "#6b2d00", "#4a1068", "#0b5345", "#7b1e1e"],
        3,
        [
            "Starfall",
            "Mudlarks",
            "Pixel Run",
            "Ironwood",
            "Sky Rails",
            "Driftwood",
            "Hollow",
            "Q-Bits",
            "Ember",
            "Canopy",
            "Tidal",
            "Rookery",
            "Cinder",
            "Moss",
            "Quarry",
            "Lumen",
            "Harbor",
            "Vale",
        ],
        6,
    )
    banner(c, "GameShelf")
    return s


def retrobox():
    s, c = surface()
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, *hexc("#07020f"))
    g.add_color_stop_rgb(1, *hexc("#240a3d"))
    c.set_source(g)
    c.paint()
    text(c, "RetroBox Console", W / 2, 140, 80, hexc("#f4a300"), True, "c")
    text(c, "Choose a system", W / 2, 200, 32, (0.9, 0.85, 1), False, "c")
    names = ["8-Bit Home", "16-Bit Classic", "Handheld", "Arcade", "Disc Era"]
    cols = ["#a4133c", "#007f5f", "#0353a4", "#b5651d", "#5a189a"]
    for i, (n, col) in enumerate(zip(names, cols)):
        x = 170 + i * 330
        y = 330
        sel = i == 1
        rr(c, x, y, 290, 380, 20)
        c.set_source_rgb(*hexc(col))
        c.fill()
        if sel:
            rr(c, x - 8, y - 8, 306, 396, 24)
            c.set_source_rgb(1, 1, 1)
            c.set_line_width(6)
            c.stroke()
        rr(c, x + 45, y + 70, 200, 130, 14)
        c.set_source_rgba(0, 0, 0, 0.35)
        c.fill()
        c.set_source_rgba(1, 1, 1, 0.9)
        c.arc(x + 95, y + 135, 18, 0, 2 * math.pi)
        c.fill()
        c.arc(x + 195, y + 135, 18, 0, 2 * math.pi)
        c.fill()
        text(c, n, x + 145, y + 300, 34, (1, 1, 1), True, "c")
    text(c, "A  Start      B  Back      Menu  Options", W / 2, 870, 30, (0.9, 0.85, 1), False, "c")
    banner(c, "RetroBox Console")
    return s


def browser(name, accent, page, seed, w=W, h=H):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    c = cairo.Context(s)
    c.set_source_rgb(*hexc("#f4f5f7"))
    c.paint()
    c.set_source_rgb(*hexc(accent))
    c.rectangle(0, 0, w, 54)
    c.fill()
    rr(c, 14, 10, 300, 44, 8)
    c.set_source_rgb(*hexc("#f4f5f7"))
    c.fill()
    text(c, page["tab"], 30, 40, 20, (0.2, 0.2, 0.2))
    c.set_source_rgb(1, 1, 1)
    c.rectangle(0, 54, w, 56)
    c.fill()
    text(c, "<   >   o", 20, 92, 24, (0.4, 0.4, 0.4))
    rr(c, 150, 64, w - 300, 36, 18)
    c.set_source_rgb(*hexc("#eceff3"))
    c.fill()
    text(c, page["url"], 175, 90, 20, (0.3, 0.3, 0.3))
    text(c, name, w - 20, 92, 20, hexc(accent), True, "r")
    text(c, page["title"], 60, 190, 48, (0.12, 0.12, 0.15), True)
    rnd = random.Random(seed)
    y = 240
    for _ in range(12):
        ww = rnd.randint(int(w * 0.4), int(w * 0.85))
        c.set_source_rgb(0.78, 0.8, 0.84)
        rr(c, 60, y, ww, 16, 8)
        c.fill()
        y += 34
    tiles(c, 60, y + 20, 3, 1, int((w - 180) / 3), 180, 30, [accent, "#90be6d", "#f9c74f", "#577590", "#f3722c"], seed)
    banner(c, name, w, h)
    return s


def docs(name, accent, kind, seed, w=W, h=H):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    c = cairo.Context(s)
    c.set_source_rgb(*hexc("#e9ebee"))
    c.paint()
    c.set_source_rgb(*hexc(accent))
    c.rectangle(0, 0, w, 60)
    c.fill()
    text(c, name, 24, 42, 26, (1, 1, 1), True)
    c.set_source_rgb(1, 1, 1)
    c.rectangle(0, 60, w, 60)
    c.fill()
    for i, t in enumerate(["File", "Edit", "View", "Insert", "Format", "Tools"]):
        text(c, t, 24 + i * 100, 100, 20, (0.3, 0.3, 0.3))
    rnd = random.Random(seed)
    if kind == "doc":
        pw = min(900, w - 120)
        x = (w - pw) / 2
        c.set_source_rgb(1, 1, 1)
        c.rectangle(x, 150, pw, h - 150)
        c.fill()
        text(c, "Quarterly Plan", x + 70, 240, 44, (0.1, 0.1, 0.15), True)
        y = 300
        for _ in range(16):
            ww = rnd.randint(int(pw * 0.5), pw - 140)
            c.set_source_rgb(0.72, 0.74, 0.78)
            rr(c, x + 70, y, ww, 14, 7)
            c.fill()
            y += 36
    else:
        x0, y0 = 60, 150
        cw, ch = 170, 44
        for r in range(int((h - y0) / ch)):
            for k in range(int((w - x0) / cw)):
                c.set_source_rgb(1, 1, 1) if r else c.set_source_rgb(*hexc("#dfe7f3"))
                c.rectangle(x0 + k * cw, y0 + r * ch, cw - 1, ch - 1)
                c.fill()
                if r and k < 5 and r < 14:
                    text(
                        c,
                        f"{rnd.randint(10,9999):,}",
                        x0 + k * cw + cw - 12,
                        y0 + r * ch + 30,
                        20,
                        (0.2, 0.2, 0.25),
                        False,
                        "r",
                    )
                if r == 0:
                    text(c, "ABCDEFGHIJKL"[k % 12], x0 + k * cw + cw / 2, y0 + 30, 20, (0.2, 0.2, 0.3), True, "c")
    banner(c, name, w, h)
    return s


def icon(path, letter, a, b):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 256, 256)
    c = cairo.Context(s)
    g = cairo.LinearGradient(0, 0, 256, 256)
    g.add_color_stop_rgb(0, *hexc(a))
    g.add_color_stop_rgb(1, *hexc(b))
    rr(c, 8, 8, 240, 240, 48)
    c.set_source(g)
    c.fill()
    text(c, letter, 128, 170, 130, (1, 1, 1), True, "c")
    c.set_source_rgb(1, 0.82, 0.1)
    c.rectangle(8, 196, 240, 44)
    c.fill()
    text(c, "MOCKUP", 128, 230, 34, (0.1, 0.1, 0.1), True, "c")
    s.write_to_png(path)


def render(name, w, h):
    if name == "streamly":
        return streamly()
    if name == "gameshelf":
        return gameshelf()
    if name == "retrobox":
        return retrobox()
    if name == "orbit":
        return browser(
            "Orbit Browser",
            "#5a4fcf",
            {"tab": "Weather · Orbit", "url": "https://weather.example", "title": "This week's weather"},
            4,
            w,
            h,
        )
    if name == "lantern":
        return browser(
            "Lantern Browser",
            "#e36414",
            {"tab": "Recipes · Lantern", "url": "https://recipes.example", "title": "Easy weeknight dinners"},
            5,
            w,
            h,
        )
    if name == "pagewright":
        return docs("Pagewright Writer", "#2b579a", "doc", 6, w, h)
    if name == "gridline":
        return docs("Gridline Sheets", "#217346", "sheet", 7, w, h)
