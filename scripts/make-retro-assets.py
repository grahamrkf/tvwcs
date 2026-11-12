#!/usr/bin/env python3
"""Build the Retro theme's files into package/tvwcs/retro/ (they are committed, so a build needs none of this):

- TVWCSPixel5x7.ttf, the small text: the 5 x 7 font of Adafruit's GFX library (glcdfont.c, BSD licence, in the
  order of code page 437), with the characters in scripts/retro/glyphs.txt added;
- TVWCSPixel8x16.ttf, the text of lists and buttons (thinner, its strokes one pixel wide in a taller cell): Spleen's
  8 x 16 font (Frederic Cambus, BSD licence);
- TVWCSPixel8x8.ttf, the large text: Daniel Hepper's 8 x 8 font (font8x8, public domain, after IBM's VGA font),
  with its Latin-1 and block characters and the same additions;
- icons/hicolor/scalable/actions/tvwcs-retro-<name>-symbolic.svg, the 9 x 9 icons in glyphs.txt and the Wi-Fi
  signal bars (in a hicolor folder: GTK recolours only themed symbolic icons), and tvwcs-vt-<name>-symbolic.svg, the
  same drawn like VT323's letters (for Settings > Appearance > Font: VT323): each row of pixels a bar with rounded
  ends, so the rows meet in small notches;
- static.png, the TV static background: grey noise, small, which sway stretches to fill each screen.

Each font pixel is a square of 125 units, in an em of 8 pixels (16 for the 8 x 16 font), so text drawn at a multiple
of 8 px (16 px) lands on whole screen pixels (theme.py rounds the Retro theme's sizes to those). Needs fontTools (pip install fonttools).
Run it again after changing glyphs.txt: python3 scripts/make-retro-assets.py"""

from __future__ import annotations
import random, re, struct, zlib
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "retro"
OUT = ROOT / "package" / "tvwcs" / "retro"
UNIT = 125  # font units per pixel

CP437_LOW = "\0☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"
# Characters drawn like another one: curly quotes as straight ones, the dashes as a hyphen, ✕ as ×.
ALIASES = {
    "“": '"',
    "”": '"',
    "„": '"',
    "‘": "'",
    "’": "'",
    "‚": ",",
    "–": "-",
    "−": "-",
    "✕": "×",
    "✗": "×",
    "↻": "⟳",
    " ": " ",
}
SMALL_ALIASES = {"▸": "►", "◂": "◄", "▴": "▲", "▾": "▼", "●": "•", "⏵": "►"}


def read_drawings():
    """glyphs.txt -> {("small"|"large"|"icon", key): [rows]}"""
    out = {}
    key = None
    rows = []
    for line in (SRC / "glyphs.txt").read_text(encoding="utf-8").splitlines() + [""]:
        if line.startswith("#") and key is None:
            continue
        if line.startswith("@"):
            kind, name = line[1:].split()
            key = (kind, chr(int(name[2:], 16)) if name.startswith("U+") else name)
            rows = []
        elif not line.strip():
            if key is not None:
                out[key] = rows
            key = None
        elif key is not None:
            rows.append(line.strip())
    return out


def small_font():
    """{char: 8 rows of 5 pixels} from glcdfont.c: 5 bytes a character, one a column, the lowest bit at the top."""
    text = (SRC / "glcdfont.c").read_text(encoding="utf-8")
    values = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", text[text.index("{") + 1 : text.index("};")])]
    chars = {}
    for code in range(1, 256):
        cols = values[code * 5 : code * 5 + 5]
        ch = (
            CP437_LOW[code]
            if code < 32
            else "⌂" if code == 127 else bytes([code]).decode("cp437") if code > 127 else chr(code)
        )
        chars[ch] = ["".join("#" if cols[x] >> r & 1 else "." for x in range(5)) for r in range(8)]
    return chars


def large_font():
    """{char: 8 rows of 8 pixels} from font8x8: 8 bytes a character, one a row, the lowest bit on the left."""
    chars = {}
    for name in ("font8x8_basic.h", "font8x8_ext_latin.h", "font8x8_block.h"):
        for row, code in re.findall(
            r"\{([^}]*)\}\s*,?\s*//\s*U\+([0-9A-Fa-f]{4})", (SRC / name).read_text(encoding="utf-8")
        ):
            values = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", row)]
            if len(values) == 8:
                chars[chr(int(code, 16))] = ["".join("#" if v >> x & 1 else "." for x in range(8)) for v in values]
    return chars


def bdf_font(path):
    """{char: 16 rows of 8 pixels} from a BDF font of 8 x 16 cells (ascent 12): each glyph placed by its bounding box."""
    chars = {}
    code = None
    box = None
    rows = None
    for line in path.read_text(encoding="latin-1").splitlines():
        part = line.split()
        if not part:
            continue
        if part[0] == "ENCODING":
            code = int(part[1])
        elif part[0] == "BBX":
            box = [int(v) for v in part[1:5]]
        elif part[0] == "BITMAP":
            rows = []
        elif part[0] == "ENDCHAR":
            w, h, xo, yo = box
            cell = [["."] * 8 for _ in range(16)]
            top = 12 - (h + yo)
            for r, v in enumerate(rows):
                for x in range(w):
                    if v >> (((w + 7) // 8) * 8 - 1 - x) & 1 and 0 <= top + r < 16 and 0 <= xo + x < 8:
                        cell[top + r][xo + x] = "#"
            if code is not None and code >= 32:
                chars[chr(code)] = ["".join(r) for r in cell]
            rows = None
        elif rows is not None:
            rows.append(int(part[0], 16))
    return chars


def runs(rows):
    """The lit pixels as rectangles: one per horizontal run. -> (x, row, width)"""
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x] == "#":
                start = x
                while x < len(row) and row[x] == "#":
                    x += 1
                yield start, y, x - start
            else:
                x += 1


def build_font(path, family, chars, advance_px, em_px=8, ascent_px=8, descent_px=2):
    names = [".notdef", "space"] + [f"uni{ord(c):04X}" for c in sorted(chars) if c != " "]
    cmap = {32: "space"}
    glyphs = {}
    metrics = {}

    def glyph(rows):
        pen = TTGlyphPen(None)
        base = (
            7 if em_px == 8 else 12
        )  # rows above the baseline: in an 8-row character row 6 stands on it, row 7 hangs below
        for x, y, w in runs(rows):
            x0, x1 = x * UNIT, (x + w) * UNIT
            top = (base - y) * UNIT
            bottom = top - UNIT
            pen.moveTo((x0, bottom))
            pen.lineTo((x0, top))
            pen.lineTo((x1, top))
            pen.lineTo((x1, bottom))
            pen.closePath()
        return pen.glyph()

    box = (
        ["#" * (advance_px - 1)]
        + ["#" + "." * (advance_px - 3) + "#"] * 5
        + ["#" * (advance_px - 1), "." * advance_px]
        + ["." * advance_px] * (em_px - 8)
    )
    glyphs[".notdef"] = glyph(box)
    glyphs["space"] = glyph([])
    metrics[".notdef"] = metrics["space"] = (advance_px * UNIT, 0)
    for c in sorted(chars):
        if c == " ":
            continue
        n = f"uni{ord(c):04X}"
        glyphs[n] = glyph(chars[c])
        cmap[ord(c)] = n
        metrics[n] = (advance_px * UNIT, min((x for x, _y, _w in runs(chars[c])), default=0) * UNIT)
    fb = FontBuilder(em_px * UNIT, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    ascent, descent = (
        ascent_px * UNIT,
        descent_px * UNIT,
    )  # 8 x 8 and 5 x 7: a pixel of space above the capitals and below the descenders
    fb.setupHorizontalHeader(ascent=ascent, descent=-descent, lineGap=0)
    fb.setupNameTable(
        {
            "familyName": family,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"TVWCS:{family}",
            "fullName": family,
            "psName": family.replace(" ", ""),
            "version": "Version 1.000",
            "licenseDescription": "See /usr/share/doc/tvwcs/copyright (font8x8: public domain; glcdfont: BSD, Adafruit Industries; Spleen: BSD, Frederic Cambus)",
        }
    )
    fb.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=-descent,
        sTypoLineGap=0,
        usWinAscent=ascent,
        usWinDescent=descent,
        sxHeight=(5 if em_px == 8 else 7) * UNIT,
        sCapHeight=(7 if em_px == 8 else 10) * UNIT,
        fsType=0,
        achVendID="TVWC",
    )
    panose = fb.font["OS/2"].panose
    panose.bFamilyType = 2
    panose.bProportion = 9  # monospaced
    fb.setupPost(isFixedPitch=1)
    fb.save(str(path))


def with_drawings(chars, drawings, kind, extra_aliases=()):
    chars = dict(chars)
    for (k, c), rows in drawings.items():
        if k == kind:
            chars[c] = rows
    for alias, real in {**ALIASES, **dict(extra_aliases)}.items():
        if real in chars and alias not in chars:
            chars[alias] = chars[real]
    return chars


def wifi_bars(lit):
    """Five signal bars rising left to right, `lit` of them lit; an unlit bar is only its bottom pixel."""
    rows = [["."] * 9 for _ in range(9)]
    for i in range(5):
        height = 2 * i + 1
        x = 2 * i
        for y in range(9 - (height if i < lit else 1), 9):
            rows[y][x] = "#"
    return ["".join(r) for r in rows]


def icon_svg(rows, rounded=False):
    if rounded:  # VT323's look: rounded ends on every run, which leaves a notch where two rows meet
        body = "".join(
            f'<rect x="{x+0.06:g}" y="{y:g}" width="{w-0.12:g}" height="1" rx="0.4"/>' for x, y, w in runs(rows)
        )
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 9 9">'
            f'<g fill="#bebebe">{body}</g></svg>\n'
        )
    d = "".join(f"M{x} {y}h{w}v1h-{w}z" for x, y, w in runs(rows))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 9 9" shape-rendering="crispEdges">'
        f'<path fill="#bebebe" d="{d}"/></svg>\n'
    )


def png_grey(path, width, height, pixels, bits=4):
    """A greyscale PNG of `bits` per pixel from rows of levels 0..2**bits-1."""

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = bytearray()
    per = 8 // bits
    for row in pixels:
        raw.append(0)
        byte = 0
        n = 0
        for v in row:
            byte = (byte << bits) | v
            n += 1
            if n == per:
                raw.append(byte)
                byte = 0
                n = 0
        if n:
            raw.append(byte << (bits * (per - n)))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bits, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def static_png(path):
    """TV static: a 480 x 270 picture of grey noise, stretched to fill the screen (4 x 4 screen pixels a grain at
    1080p, 8 x 8 at 4K, so it looks the same on both). Mostly mid greys with some bright and dark specks, and a few
    rows a little brighter or darker, as a TV between channels shows."""
    rnd = random.Random(1953)
    w, h = 480, 270
    rows = []
    for _y in range(h):
        bias = rnd.choice((0, 0, 0, 0, 0, 0, 1, -1, 2, -2))
        rows.append([max(0, min(15, int(rnd.triangular(0, 15.99, 7)) + bias)) for _x in range(w)])
    png_grey(path, w, h, rows)


def main():
    drawings = read_drawings()
    icons = OUT / "icons" / "hicolor" / "scalable" / "actions"
    icons.mkdir(parents=True, exist_ok=True)
    build_font(
        OUT / "TVWCSPixel5x7.ttf", "TVWCS Pixel 5x7", with_drawings(small_font(), drawings, "small", SMALL_ALIASES), 6
    )
    build_font(
        OUT / "TVWCSPixel8x16.ttf",
        "TVWCS Pixel 8x16",
        with_drawings(bdf_font(SRC / "spleen-8x16.bdf"), drawings, "text"),
        8,
        16,
        12,
        4,
    )
    build_font(OUT / "TVWCSPixel8x8.ttf", "TVWCS Pixel 8x8", with_drawings(large_font(), drawings, "large"), 8)
    for old in icons.glob("*.svg"):
        old.unlink()
    pictures = {name: rows for (kind, name), rows in drawings.items() if kind == "icon"}
    pictures.update({f"wifi-{lit}": wifi_bars(lit) for lit in range(6)})
    for name, rows in pictures.items():
        (icons / f"tvwcs-retro-{name}-symbolic.svg").write_text(icon_svg(rows), encoding="ascii")
        (icons / f"tvwcs-vt-{name}-symbolic.svg").write_text(icon_svg(rows, rounded=True), encoding="ascii")
    static_png(OUT / "static.png")
    print(f"Wrote {OUT.relative_to(ROOT)}: 3 fonts, {len(list(icons.glob('*.svg')))} icons, static.png")


if __name__ == "__main__":
    main()
