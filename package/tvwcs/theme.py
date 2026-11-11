"""TVWCS's three themes. Modern is the Metro / Modern UI look: flat, square, high-contrast; every corner radius is 0.
Retro is an old CRT television's menus: green, amber or white pixel text on black, buttons without borders until
the mouse is over one (dashed) or one is selected (solid), the TVWCS Pixel fonts (5 x 7 for small text, the thinner
8 x 16 for the text of lists and buttons, 8 x 8 for large) at whole multiples of their pixels, and pixel icons (widgets.glyph).
Media is a dark, rounded look like a media server app's, in colours that go with Jellyfin, Emby or Plex (MEDIA_PALETTES):
TVWCS's own colours and shapes, nothing taken from those apps' logos or artwork."""
from __future__ import annotations
import re
from tvwcs.model import METRO_COLORS, RETRO_WALLPAPERS, WALLPAPERS
from tvwcs.retro import STATIC_PICTURE

CSS="""
window.tvwcs-window, .tvwcs-root { background: @BG@; color: @FG@; font-family: "Segoe UI", "Selawik", "Open Sans", "Noto Sans", "Cantarell", sans-serif; border-radius: 0; box-shadow: none; }
.pane { background: @PANE@; }
.brand { font-size: 26px; font-weight: 300; letter-spacing: 2px; }
.pane-title { font-size: 34px; font-weight: 200; }
.muted { color: @MUTED@; font-size: 14px; }
.section-title { font-size: 13px; font-weight: 700; letter-spacing: 2px; color: @ACCENT@; margin-top: 12px; margin-bottom: 2px; }
.channel-number { font-weight: 700; color: @ACCENT@; }
.favorite-mark { color: @MUTED@; font-size: 18px; }
button:focus .favorite-mark { color: #ffffff; }
/* a Quick Menu row that is open now: a thin band down its left side (white while selected) */
button.launch-row.open-app { box-shadow: inset 3px 0 @ACCENT@; }
button.launch-row.open-app:focus, button.launch-row.open-app:focus-visible { box-shadow: inset 6px 0 #ffffff; }
button.launch-row.open-app:dir(rtl) { box-shadow: inset -3px 0 @ACCENT@; }   /* mirrored: down its right side */
button.launch-row.open-app:dir(rtl):focus, button.launch-row.open-app:dir(rtl):focus-visible { box-shadow: inset -6px 0 #ffffff; }
.child-marker { color: @FAINT@; font-size: 22px; }
button { min-height: 44px; min-width: 44px; padding: 0 14px; border: none; border-radius: 0; background: @RAISED@; background-image: none; color: @FG@; box-shadow: none; text-shadow: none; font-size: 15px; }
window.pointer button:hover { background: @HOVER@; }
button:focus, button:focus-visible, button:active { background: @ACCENT@; color: #ffffff; outline: 3px solid #ffffff; outline-offset: -3px; }
button:focus .channel-number, button:focus .muted, button:focus .child-marker { color: #ffffff; }
button:focus label { font-weight: 700; }
button.active { box-shadow: inset 0 -4px @ACCENT@; }   /* on, or the main choice: a bar, so it never looks selected */
button.active:focus, button.active:focus-visible { box-shadow: none; }
button.dialog-button { padding: 0 16px; }
button.danger:focus, button.danger:focus-visible { background: #e81123; }
button.square { min-width: 44px; min-height: 44px; padding: 0; }
button.close-button { background: #c50f1f; color: #ffffff; }
window.pointer button.close-button:hover { background: #e81123; }
button.close-button:focus, button.close-button:focus-visible, button.close-button:active { background: #e81123; outline: 3px solid #ffffff; outline-offset: -3px; }
.mode-button { min-width: 44px; padding: 0; }
button.options-toggle { min-width: 22px; padding: 0; }   /* ⋯ is half as wide as it is tall: ← or a right-click opens the same menu */
button.category-header { background: @HEADER@; font-size: 18px; font-weight: 300; margin-top: 6px; }
window.pointer button.category-header:hover { background: @HOVER@; }
button.category-header:focus, button.category-header:focus-visible { background: @ACCENT@; outline: 3px solid #ffffff; outline-offset: -3px; }
.description { color: @MUTED@; font-size: 13px; }
button:focus .description, .tvwcs-selected .description { color: #e3eefa; }
.pin-display { font-size: 34px; font-weight: 300; letter-spacing: 4px; }
button.pin-key { font-size: 24px; min-height: 64px; }
button.pin-key.kb-key { font-size: 18px; min-height: 46px; min-width: 0; padding: 0 2px; }
.text-display { font-size: 22px; min-height: 48px; }
.field-value { color: @MUTED@; font-size: 14px; }
button.field-row { padding-top: 6px; padding-bottom: 6px; }
button.field-row:focus .field-value { color: inherit; }
.setting-value { color: @ACCENT@; font-weight: 700; }
button:focus .setting-value { color: #ffffff; }
.tvwcs-selected { background: @ACCENT@; color: #ffffff; outline: 3px solid #ffffff; outline-offset: -3px; }
.tvwcs-selected label { font-weight: 700; color: #ffffff; }
entry, entry.search, entry.password { min-height: 46px; padding: 0 10px; border: 2px solid @BORDER@; border-radius: 0; background: @RAISED@; background-image: none; color: @FG@; box-shadow: none; font-size: 17px; }
entry:focus-within { background: #ffffff; color: #000000; border-color: @ACCENT@; }
entry:focus-within text, entry:focus-within image { color: #000000; }
.icon-tile { color: #ffffff; font-weight: 700; font-size: 15px; }
.badge { background: #e81123; color: #ffffff; font-size: 10px; font-weight: 700; min-width: 16px; min-height: 16px; padding: 0 3px; border-radius: 0; }
.modal-scrim { background: @SCRIM@; }
.modal-card { background: @CARD@; padding: 22px; border: 2px solid @ACCENT@; border-radius: 0; }
.error { color: @ERROR@; }
popover > contents, popover contents { background: @CARD@; color: @FG@; border: 2px solid @ACCENT@; border-radius: 0; box-shadow: none; padding: 6px; }
scrollbar slider { background: #6e6e6e; border-radius: 0; min-width: 8px; min-height: 8px; }
scrollbar trough { background: transparent; border-radius: 0; }
separator { background: @LINE@; min-height: 1px; }
checkbutton check { border-radius: 0; background: @RAISED@; border: 2px solid @BORDER@; box-shadow: none; background-image: none; -gtk-icon-source: none; min-width: 22px; min-height: 22px; }
checkbutton check:checked { background: @ACCENT@; border-color: @ACCENT@; -gtk-icon-source: -gtk-icontheme("object-select-symbolic"); color: #ffffff; }
dropdown > button, dropdown button { border-radius: 0; }
.quick-status { background: @STATUS@; padding: 6px 14px 8px 14px; }
button.clock-button, button.status-icon { background: transparent; }
button.clock-button { padding: 4px 8px; }
window.pointer button.clock-button:hover, window.pointer button.status-icon:hover { background: @RAISED@; }
button.clock-button:focus, button.clock-button:focus-visible, button.status-icon:focus, button.status-icon:focus-visible { background: @ACCENT@; outline: 3px solid #ffffff; outline-offset: -3px; }
.clock-time { font-size: 22px; font-weight: 300; }
.clock-date { color: @MUTED@; font-size: 15px; }
button:focus .clock-date { color: #ffffff; }
button.status-wide { padding: 0 8px; }
.status-count { font-size: 14px; font-weight: 700; }
button.status-off { color: @FAINT@; }
/* the Quick Menu's channel hint and the "Starting …" card */
.channel-hint { color: @MUTED@; font-size: 15px; }
entry.channel-entry { font-size: 24px; }
entry.channel-entry text { letter-spacing: 2px; }
entry.tv-search { border-color: @RAISED@; }
entry.tv-search > image { -gtk-icon-size: 0; min-width: 0; margin: 0; padding: 0; opacity: 0; }
entry.tv-search text placeholder { color: @ACCENT@; opacity: 1; }
.digit-box { min-width: 56px; min-height: 64px; font-size: 34px; font-weight: 300; background: @RAISED@; border: 2px solid @BORDER@; }
.digit-box.current { border-color: @ACCENT@; }
button.menu-item { padding: 0 16px; }
/* a Quick Menu row's options, unfolded above it, and a status icon's panel */
.row-options button.menu-item { min-height: 40px; }
.row-options button.menu-item:not(:focus):not(:active) { background: @HEADER@; }
.status-panel { background: @HEADER@; padding: 10px 12px; }
.panel-title { font-size: 15px; font-weight: 700; margin-top: 2px; }
.status-panel button { min-height: 40px; }
.status-panel scale { padding: 0 6px; }
.status-panel scale trough { background: @TROUGH@; border: none; border-radius: 0; min-height: 8px; }
.status-panel scale highlight { background: @ACCENT@; border: none; border-radius: 0; min-height: 8px; margin: 0; }
.status-panel scale slider { background: @FG@; border: none; border-radius: 0; min-width: 12px; min-height: 20px; margin: -6px 0; box-shadow: none; }
"""

# The two looks (Settings > Appearance > Theme). The selection stays a solid accent block with white text in both.
PALETTES={
    "dark":{"BG":"#000000","FG":"#ffffff","PANE":"#1b1b1b","RAISED":"#2d2d2d","HOVER":"#3f3f3f","HEADER":"#262626","CARD":"#262626",
            "STATUS":"#141414","MUTED":"#b5b5b5","FAINT":"#7d7d7d","BORDER":"#5a5a5a","LINE":"#333333","SCRIM":"rgba(0, 0, 0, 0.78)",
            "ERROR":"#ff5a67","ON":"#6ccb5f","TROUGH":"#3a3a3a"},
    "light":{"BG":"#d6d6d6","FG":"#000000","PANE":"#f2f2f2","RAISED":"#e1e1e1","HOVER":"#cdcdcd","HEADER":"#e8e8e8","CARD":"#fafafa",
             "STATUS":"#e4e4e4","MUTED":"#4a4a4a","FAINT":"#767676","BORDER":"#8a8a8a","LINE":"#c8c8c8","SCRIM":"rgba(255, 255, 255, 0.72)",
             "ERROR":"#c50f1f","ON":"#107c10","TROUGH":"#c4c4c4"},
}

# The Retro theme's phosphors (Settings > Appearance > Colour). Nothing is filled in: buttons, fields and panels are
# drawn on the black, so the "raised" colours are transparent. GLOW is the soft light around the text.
_RETRO_BASE={"RAISED":"transparent","HOVER":"transparent","HEADER":"transparent","SCRIM":"rgba(0, 0, 0, 0.86)"}
RETRO_PALETTES={
    "green":{**_RETRO_BASE,"BG":"#020a04","FG":"#39ff6a","MUTED":"#1fa845","FAINT":"#137a30","LINE":"#0f5c24","GLOW":"rgba(57, 255, 106, 0.45)"},
    "amber":{**_RETRO_BASE,"BG":"#0a0600","FG":"#ffb000","MUTED":"#b57a00","FAINT":"#855a00","LINE":"#5c3f00","GLOW":"rgba(255, 176, 0, 0.4)"},
    "white":{**_RETRO_BASE,"BG":"#05060a","FG":"#e8eef8","MUTED":"#97a0ae","FAINT":"#6b7380","LINE":"#3a404a","GLOW":"rgba(220, 230, 255, 0.35)"},
}
for _p in RETRO_PALETTES.values():
    _p.update(PANE=_p["BG"],CARD=_p["BG"],STATUS=_p["BG"],BORDER=_p["MUTED"],TROUGH=_p["LINE"],ERROR=_p["FG"],ON=_p["FG"])

SMALL_FONT='"TVWCS Pixel 5x7", monospace'
TEXT_FONT='"TVWCS Pixel 8x16", "TVWCS Pixel 5x7", monospace'   # what 8 x 16 lacks (★, ✓, ⋯) is in 5 x 7
LARGE_FONT='"TVWCS Pixel 8x8", monospace'
LARGE_FROM=20   # px at desktop size: text this big or bigger is in the 8 x 8 font
PIXEL_GRID=8    # the 5 x 7 and 8 x 8 fonts are 8 pixels to the em: their sizes are rounded to a multiple of 8 px
TEXT_FROM=12    # px at desktop size: text this big (and under LARGE_FROM) is in the thinner 8 x 16 font, smaller text in 5 x 7
TEXT_GRID=16    # the 8 x 16 font is 16 pixels to the em: a multiple of 16 px (and so of 8, for what 5 x 7 draws in it)

# Drawn after the Modern rules (and the Settings app's), overriding them: no fills, the selection a solid border.
RETRO_CSS="""
window.tvwcs-window, .tvwcs-root { font-family: @SMALL@; text-shadow: 0 0 4px @GLOW@; }
button:focus, button:focus-visible, button:active, .tvwcs-selected,
button.category-header:focus, button.category-header:focus-visible, button.tab-button:focus, button.tab-button:focus-visible,
button.clock-button:focus, button.clock-button:focus-visible, button.status-icon:focus, button.status-icon:focus-visible,
button.danger:focus, button.danger:focus-visible, button.close-button:focus, button.close-button:focus-visible, button.close-button:active
  { background: transparent; color: @FG@; outline: 3px solid @FG@; outline-offset: -3px; }
window.pointer button:hover { background: transparent; outline: 2px dashed @MUTED@; outline-offset: -2px; }
window.pointer button:hover:focus, window.pointer button:hover:focus-visible, window.pointer button.tvwcs-selected:hover { outline: 3px solid @FG@; outline-offset: -3px; }
window.pointer button.category-header:hover, window.pointer button.clock-button:hover, window.pointer button.status-icon:hover,
window.pointer button.tab-button:hover, window.pointer button.close-button:hover { background: transparent; }
button.close-button { background: transparent; color: @FG@; }
button.tab-button.active { background: transparent; }
entry, entry.search, entry.password { background: transparent; border-width: 0 0 2px 0; outline: none; }
entry:focus-within { background: transparent; color: @FG@; border-color: @FG@; }
entry:focus-within text, entry:focus-within image { color: @FG@; }
entry.tv-search { border-color: @FAINT@; }
.digit-box { background: transparent; border-width: 0 0 2px 0; }
.badge { background: @FG@; color: @BG@; text-shadow: none; }
.status-panel { border: 2px solid @LINE@; }
scrollbar slider { background: @FAINT@; }
scale.muted highlight { background: @FAINT@; }
checkbutton check { background: transparent; border-color: @MUTED@; }
checkbutton check:checked { background: transparent; border-color: @FG@; color: @FG@; -gtk-icon-source: -gtk-icontheme("@CHECK@"); }
.display-box, .display-box.primary { background: transparent; border: 2px solid @MUTED@; }
.display-box.primary { border-color: @FG@; }
textview.console, textview.console text { background: @BG@; color: @FG@; font-family: @SMALL@; }
"""

def _large_fonts(css):
    """Give every rule with large text (LARGE_FROM px or more) the 8 x 8 font, and the text of lists, buttons and their
    notes (TEXT_FROM up to LARGE_FROM px) the 8 x 16 one; the smallest text (badges) keeps the 5 x 7 font."""
    def rule(m):
        size=re.search(r"font-size:\s*(\d+)px",m.group(1))
        if not size or int(size.group(1))<TEXT_FROM: return m.group(0)
        font=LARGE_FONT if int(size.group(1))>=LARGE_FROM else TEXT_FONT
        return "{"+m.group(1).rstrip().rstrip(";")+f"; font-family: {font}; }}"
    return re.sub(r"\{([^{}]*)\}",rule,css)

# Settings > Appearance > Font (model.RETRO_FONTS): the pixel fonts above, VT323, or Inter. VT323 is drawn 40 %
# larger, its letters being small for their size; it and Inter are smoothed and sized freely (render_css).
RETRO_FAMILIES={"vt323":'"VT323", monospace',"readable":'"Inter", "Open Sans", sans-serif'}
NO_LIGATURES="""
window.tvwcs-window, .tvwcs-root, textview.console text { font-feature-settings: "liga" 0, "clig" 0; }
"""   # VT323 joins "fi" and "ff" into one cell, so "Jellyfin" read as "Jellyfn"
FONT_GROWTH={"vt323":1.4}

def retro_css(css, font="pixel"):
    """The Modern rules made Retro, before the palette is filled in: what was white on the selection is the phosphor
    colour, every weight is regular (a pixel font has one; Inter keeps Modern's), with the pixel fonts large text is
    in the 8 x 8 font and lists in the 8 x 16 one, then RETRO_CSS."""
    css=css.replace("#ffffff","@FG@").replace("#e3eefa","@MUTED@").replace("#000000","@FG@").replace("text-shadow: none; ","")   # buttons keep the glow
    if font!="readable": css=re.sub(r"font-weight:\s*\d+","font-weight: 400",css)
    rules=RETRO_CSS.replace("@CHECK@",{"vt323":"tvwcs-vt-check-symbolic","readable":"object-select-symbolic"}.get(font,"tvwcs-retro-check-symbolic"))
    if font in RETRO_FAMILIES: return css+rules.replace("@SMALL@",RETRO_FAMILIES[font])+(NO_LIGATURES if font=="vt323" else "")
    return _large_fonts(css)+rules.replace("@SMALL@",SMALL_FONT)

SMALL_BELOW=15  # px at desktop size: notes and details, a step smaller than the text they explain

def snap_font_size(px, scale=1.0):
    """A pixel font's size in screen px, for `px` at desktop size: the nearest whole multiple of its pixels (16 for the
    8 x 16 font, else 8), or for notes and details the multiple below (but never under 16 px for text that is 12 px or
    more once scaled), so they stay a step smaller than the labels around them."""
    scaled=px*scale
    if px>=LARGE_FROM: return max(PIXEL_GRID,round(scaled/PIXEL_GRID)*PIXEL_GRID)
    if px>=SMALL_BELOW: return max(TEXT_GRID,round(scaled/TEXT_GRID)*TEXT_GRID)
    if px>=TEXT_FROM: return max(TEXT_GRID,int(scaled//TEXT_GRID)*TEXT_GRID)
    return max(2*PIXEL_GRID if scaled>=12 else PIXEL_GRID,int(scaled//PIXEL_GRID)*PIXEL_GRID)

# The Media theme's looks (Settings > Appearance > Look, model.MEDIA_LOOKS): Modern's dark colours tinted to match, the
# accent the app's colour, FILL what a selection is filled with (Jellyfin's a purple to blue gradient), ON the text on
# it (dark on Plex's gold), RADIUS the corners of buttons and fields and CARD_RADIUS those of dialogs and panels.
# BG and FG are repeated in lockscreen.MEDIA (a test keeps them the same).
MEDIA_PALETTES={
    "jellyfin":{"BG":"#101018","FG":"#ffffff","PANE":"#181824","RAISED":"#232333","HOVER":"#30304a","HEADER":"#1d1d2b","CARD":"#1f1f2e",
                "STATUS":"#13131c","MUTED":"#b1b1c8","FAINT":"#7a7a94","BORDER":"#4b4b66","LINE":"#2c2c40","SCRIM":"rgba(6, 6, 12, 0.8)",
                "ERROR":"#ff6b78","ON":"#6fd3a8","TROUGH":"#35354d","ACCENT":"#8e5ad8","ONACCENT":"#ffffff","ONMUTED":"#ece4fa",
                "FILL":"linear-gradient(100deg, #9b5de5, #2a9fe0)","RADIUS":"6px","CARD_RADIUS":"12px",
                "FONT":'"Noto Sans", "Open Sans", "Cantarell", sans-serif'},
    "emby":{"BG":"#0f0f0f","FG":"#ffffff","PANE":"#191919","RAISED":"#262626","HOVER":"#333333","HEADER":"#1f1f1f","CARD":"#202020",
            "STATUS":"#141414","MUTED":"#b8b8b8","FAINT":"#7e7e7e","BORDER":"#555555","LINE":"#2e2e2e","SCRIM":"rgba(0, 0, 0, 0.8)",
            "ERROR":"#ff5a67","ON":"#5cc254","TROUGH":"#383838","ACCENT":"#4caf50","ONACCENT":"#ffffff","ONMUTED":"#e4f5e3",
            "FILL":"#43a047","RADIUS":"4px","CARD_RADIUS":"8px",
            "FONT":'"Roboto", "Noto Sans", "Open Sans", sans-serif'},
    "plex":{"BG":"#16181a","FG":"#eeeeee","PANE":"#1f2124","RAISED":"#2b2e32","HOVER":"#383c41","HEADER":"#25282b","CARD":"#26292d",
            "STATUS":"#1a1c1e","MUTED":"#b4b6b9","FAINT":"#7c8085","BORDER":"#56595e","LINE":"#323539","SCRIM":"rgba(8, 9, 10, 0.82)",
            "ERROR":"#ff6b6b","ON":"#e8a90f","TROUGH":"#3a3d42","ACCENT":"#e8a90f","ONACCENT":"#1a1a1a","ONMUTED":"#3d3000",
            "FILL":"#e8a90f","RADIUS":"18px","CARD_RADIUS":"10px",
            "FONT":'"Open Sans", "Noto Sans", "Cantarell", sans-serif'},
}

# Drawn after the Modern rules (and the Settings app's): rounded corners, a slim ring round the selection, headings in
# a heavier weight, and what stays white whatever is on the selection (application tiles, the red close button, badges).
MEDIA_CSS="""
window.tvwcs-window, .tvwcs-root { font-family: @FONT@; border-radius: 0; }
.brand { font-weight: 700; letter-spacing: 0; }
.pane-title { font-weight: 600; }
button.category-header { font-weight: 600; }
.section-title { letter-spacing: 1px; }
.clock-time { font-weight: 500; }
button.tab-button label { font-weight: 500; }
button:focus, button:focus-visible, button:active, .tvwcs-selected, button.category-header:focus, button.category-header:focus-visible,
button.clock-button:focus, button.clock-button:focus-visible, button.status-icon:focus, button.status-icon:focus-visible,
button.close-button:focus, button.close-button:focus-visible, button.close-button:active
  { outline: 2px solid alpha(#ffffff, 0.85); outline-offset: -2px; }
button.tab-button.active { box-shadow: inset 4px 0 0 @ACCENT@; }
button.tab-button:focus, button.tab-button:focus-visible { box-shadow: none; }
button.launch-row.open-app { box-shadow: inset 4px 0 @ACCENT@; }
button.launch-row.open-app:focus, button.launch-row.open-app:focus-visible { box-shadow: inset 5px 0 @ONACCENT@; }
.modal-card, popover > contents, popover contents, .status-panel { border-radius: @CARD_RADIUS@; }
.modal-card, popover > contents, popover contents { border: 1px solid @LINE@; }
.icon-tile, .icon-tile label { color: #ffffff; border-radius: @RADIUS@; }
button.close-button, button.close-button label, .badge, .display-number, .display-name { color: #ffffff; }
.badge { border-radius: 8px; }
.digit-box { border-radius: @RADIUS@; }
.accent-swatch { border-radius: 50%; }
scrollbar slider { border-radius: 4px; }
scale trough, scale highlight, .status-panel scale trough, .status-panel scale highlight { border-radius: 5px; }
scale slider, .status-panel scale slider { border-radius: 50%; min-width: 20px; min-height: 20px; margin: -6px 0; }
"""

def media_css(css):
    """The Modern rules made Media, before the palette is filled in: rounded corners, selections filled with FILL and
    their text in ONACCENT (dark on Plex's gold), then MEDIA_CSS."""
    css=css.replace("border-radius: 0;","border-radius: @RADIUS@;").replace("border-radius: 0 ","border-radius: @RADIUS@ ").replace("border-radius: 0}","border-radius: @RADIUS@}")
    css=re.sub(r"background: @ACCENT@(?=[;}\s])","background: @FILL@",css)
    css=css.replace("color: #ffffff","color: @ONACCENT@").replace("#e3eefa","@ONMUTED@").replace("inset 6px 0 #ffffff","inset 5px 0 @ONACCENT@")
    return css+MEDIA_CSS

def render_css(accent, scale=1.0, extra="", theme="dark", style="modern", phosphor="green", retro_font="pixel", media="jellyfin"):
    """The theme (plus `extra` rules, such as the Settings app's) with the accent colour and the look's colours filled in
    and every pixel measure multiplied by `scale`. Hover colours apply only while the mouse is in use (the window has
    the "pointer" class, see widgets.PointerWatch): a pointer hidden after a few seconds would otherwise keep marking
    whatever happens to be under it, next to the remote's real selection. The Retro theme's phosphor colour takes the
    accent's place, and in its pixel fonts its text sizes are rounded to their grid after scaling. The Media theme's look
    has its own accent (MEDIA_PALETTES)."""
    retro=style=="retro"; media_look=style=="media"
    if retro: palette=RETRO_PALETTES.get(phosphor,RETRO_PALETTES["green"])
    elif media_look: palette=MEDIA_PALETTES.get(media,MEDIA_PALETTES["jellyfin"])
    else: palette=PALETTES.get(theme,PALETTES["dark"])
    if retro_font not in RETRO_FAMILIES: retro_font="pixel"
    css=retro_css(CSS+extra,retro_font) if retro else media_css(CSS+extra) if media_look else CSS+extra
    for key in ("FILL","ONACCENT","ONMUTED","RADIUS","CARD_RADIUS","FONT"):   # these hold other tokens' names: filled in first
        if key in palette: css=css.replace(f"@{key}@",palette[key])
    css=css.replace("@ACCENT@",palette["FG"] if retro else palette.get("ACCENT",accent))
    for key,value in palette.items(): css=css.replace(f"@{key}@",value)
    if retro and retro_font in FONT_GROWTH:
        css=re.sub(r"font-size:\s*(\d+)px",lambda m:f"font-size: {round(int(m.group(1))*FONT_GROWTH[retro_font])}px",css)
    elif retro and retro_font=="pixel":   # sized here, already scaled: "PX" is passed over by the scaling below
        css=re.sub(r"font-size:\s*(\d+)px",lambda m:f"font-size: {snap_font_size(int(m.group(1)),scale)}PX",css)
    if scale!=1.0:
        css=re.sub(r"(?<![\w.#-])(\d+)px",lambda m:f"{0 if m.group(1)=='0' else max(1,round(int(m.group(1))*scale))}px",css)
    css=css.replace("PX;","px;").replace("PX }","px }")
    tiles="\n".join(f".tile-{i} {{ background: {c}; }}" for i,c in enumerate(METRO_COLORS))
    walls="\n".join(f".wall-{i}, button.wall-{i}:focus, button.wall-{i}:hover {{ background: {c}; }}" for i,c in enumerate(WALLPAPERS))
    retro_walls="\n".join(f".retro-wall-{k}, button.retro-wall-{k}:focus, button.retro-wall-{k}:hover {{ "
                          +(f'background: #000000 url("{STATIC_PICTURE.as_uri()}"); background-size: cover; }}' if c=="static" else f"background: {c}; }}")
                          for k,c in RETRO_WALLPAPERS.items())
    return css+"\n"+tiles+"\n"+walls+"\n"+retro_walls
