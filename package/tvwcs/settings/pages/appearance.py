"""Settings > Appearance: TVWCS's theme, size, Quick Menu corner and channel options."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from tvwcs.core.model import (
    AUTO_SIZE,
    CHANNEL_DIGITS,
    CORNERS,
    MEDIA_LOOKS,
    PHOSPHORS,
    RETRO_FONTS,
    RETRO_WALLPAPER_LABELS,
    RETRO_WALLPAPERS,
    SIZES,
    STYLES,
    THEMES,
    WALLPAPERS,
    ConfigStore,
    accent_name,
    auto_size,
    channel_range,
    corner_right,
    is_4k,
    size_label,
    tv_mode,
)
from tvwcs.ui.widgets import METRO_COLORS, S
from tvwcs.settings.pages.base import _ConfigPage, digits_label


class AppearancePage(_ConfigPage):
    """How TVWCS looks (size, colours) and the few choices left in 4.0: closing when it loses focus and the screen edge
    margin. What depends on the mode is fixed: in TV mode (a TVWCS session) apps open in a workspace of their own, the
    pointer hides after 3 seconds, the bar is off and the Quick Menu stays open; in desktop mode none of that changes
    the desktop. Hotkeys have their own page, the application to open at login is on User, and TVWCS's own updates are
    on Software updates."""

    key = "appearance"
    title = "Appearance"
    icon = "preferences-desktop-appearance-symbolic"
    fallback = "◐"
    sway_only = True

    def draw(self, store):
        st = store.settings
        self.section("LOOK")
        self.size_buttons(st)
        self.row("Theme", STYLES[st["style"]], self.choose_style, ident="opt:style")
        if st["style"] == "retro":
            self.note(
                "Like the menus of an old CRT TV: pixel text in one colour on black, buttons without borders until one is "
                "selected, and no application icons. Applications that follow the desktop's colour scheme are dark."
            )
            self.row("Colour", PHOSPHORS[st["phosphor"]], self.choose_phosphor, ident="opt:phosphor")
            self.row("Font", RETRO_FONTS[st["retro_font"]], self.choose_retro_font, ident="opt:retro_font")
            self.note(
                "Pixel is TVWCS's own pixel fonts, sharp at every size. VT323 is a 1970s computer terminal's font. "
                "Inter is a smooth font made to be easy to read."
            )
            self.row(
                "Background",
                RETRO_WALLPAPER_LABELS[st["retro_wallpaper"]],
                self.choose_retro_wallpaper,
                ident="opt:retro_wallpaper",
                swatch=st["retro_wallpaper"],
            )
        elif st["style"] == "media":
            self.note(
                "Dark with rounded corners, like a media server app. Applications that follow the desktop's colour scheme are dark."
            )
            self.row("Look", MEDIA_LOOKS[st["media_look"]], self.choose_media_look, ident="opt:media_look")
            self.note(
                "Colours that go with the app you watch on: Jellyfin's purple and blue, Emby's green or Plex's gold. "
                "Each look has its own background."
            )
        else:
            self.note("TVWCS's flat look, in the accent colour.")
            self.row("Light or dark", THEMES[st["theme"]], self.choose_theme, ident="opt:theme")
            self.note(
                "For TVWCS and Settings. Applications that follow the desktop's colour scheme (most GTK apps, "
                "and browsers through the desktop portal) switch with it."
            )
            self.row(
                "Accent colour", accent_name(st["accent"]), self.choose_accent, ident="opt:accent", swatch=st["accent"]
            )
            self.row("Background colour", "", self.choose_wallpaper, ident="opt:wallpaper", swatch=st["wallpaper"])
        self.note("The background is shown where no application is open, and behind the Quick Menu.")

        self.section("BEHAVIOR")
        self.option(
            "Close TVWCS when it loses focus",
            "close_on_click_outside",
            "Clicking another window, or another window opening, closes the Quick Menu.",
        )
        self.option(
            "Options buttons (⋯) on Quick Menu rows",
            "hide_options_buttons",
            "Even hidden, a row's options open by pressing "
            + ("→" if corner_right(st["quick_corner"]) else "←")
            + " on it, or by right-clicking it.",
            invert=True,
        )
        self.option(
            "Search bar on the Quick Menu",
            "search_icon",
            "Off: a search icon beside the status icons opens it. Typing "
            "anywhere in the Quick Menu opens it too, with what was typed already in it.",
            invert=True,
        )
        self.row("Quick Menu corner", CORNERS[st["quick_corner"]], self.choose_corner, ident="opt:quick_corner")
        self.note(
            "The corner of the screen the Quick Menu sits in. Its layout mirrors to match: in a right-hand corner it runs "
            "right to left and Applications opens to its left; in a top corner its lists and menus open downwards."
        )
        self.row(
            "Channel number digits",
            digits_label(st["channel_digits"]),
            self.choose_channel_digits,
            ident="opt:channel_digits",
        )
        self.note(
            "How many digits a channel number has. Typing them all in the Quick Menu opens that channel a second later."
        )
        self.row("Screen edge margin", f"{st['margin']} px", self.choose_margin, ident="opt:margin")
        self.note(
            "Many TVs cut off the edges of the picture (overscan). This opens a full-screen preview: move the slider until the "
            "Quick Menu and Applications are fully on screen."
        )

    # ---------------------------------------------------------- choices
    def has_4k(self):
        gd = Gdk.Display.get_default()
        monitors = gd.get_monitors() if gd else None
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m = monitors.get_item(i)
            g = m.get_geometry()
            f = max(1, m.get_scale_factor())
            if is_4k(g.width * f, g.height * f):
                return True
        return False

    def size_buttons(self, st):
        """Interface size: Auto, then 1 to 5 from small to large, the one chosen marked; and, with a 4K display, whether
        it is sized for a 4K screen."""
        tv = tv_mode()
        chosen = st["scale"] or ""
        auto = auto_size(st, tv)
        head = Gtk.Label(label="Interface size")
        head.add_css_class("buttons-head")
        head.set_xalign(0)
        head.set_margin_top(S(6))
        self.add(head)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(4))
        line.set_homogeneous(True)
        buttons = []
        for key, text in [("", "Auto")] + [(str(n), str(n)) for n in SIZES]:
            b = Gtk.Button(label=text)
            b.set_tooltip_text(f"Automatic: size {auto} here" if not key else size_label(int(key)))
            if key == chosen:
                b.add_css_class("active")
            else:
                b.connect("clicked", lambda _b, key=key: self.pick_scale(key))
            line.append(b)
            buttons.append(b)
        self.add(line)
        self.register(*buttons, ident="opt:scale")
        self.note(
            f"From 1 (smallest) to 5 (largest): 3 is the desktop size and 4 the TV size. Auto is size {auto} here: "
            f"{AUTO_SIZE[(True,False)]} in TV mode and {AUTO_SIZE[(False,False)]} in desktop mode, and a size smaller in the "
            f"Retro theme ({AUTO_SIZE[(True,True)]} and {AUTO_SIZE[(False,True)]})."
        )
        if st["scale_4k"] or self.has_4k():
            self.option(
                "Sized for a 4K screen",
                "scale_4k",
                "Makes every size about twice as large, for a 4K TV whose picture isn't scaled up by "
                "Displays (size 4 is then 4K TV Mode from earlier versions).",
            )

    def pick_scale(self, key):
        self.change(lambda s: s.settings.update(scale=key))  # settings_changed redraws Settings at it

    def choose_accent(self):
        current = self.state.settings["accent"].lower()
        options = [(c, accent_name(c)) for c in METRO_COLORS] + (
            [] if current in METRO_COLORS else [(current, f"{current} (set in config.json)")]
        )
        self.win.choose_option(
            "Accent colour",
            options,
            current,
            lambda c: self.change(lambda s: s.settings.update(accent=c)),
            swatches=True,
        )

    def choose_style(self):
        self.win.choose_option(
            "Theme",
            list(STYLES.items()),
            self.state.settings["style"],
            lambda t: self.change(lambda s: s.settings.update(style=t)),
        )

    def choose_phosphor(self):
        self.win.choose_option(
            "Colour",
            list(PHOSPHORS.items()),
            self.state.settings["phosphor"],
            lambda c: self.change(lambda s: s.settings.update(phosphor=c)),
        )

    def choose_media_look(self):
        self.win.choose_option(
            "Look",
            list(MEDIA_LOOKS.items()),
            self.state.settings["media_look"],
            lambda k: self.change(lambda s: s.settings.update(media_look=k)),
        )

    def choose_retro_font(self):
        self.win.choose_option(
            "Font",
            list(RETRO_FONTS.items()),
            self.state.settings["retro_font"],
            lambda f: self.change(lambda s: s.settings.update(retro_font=f)),
        )

    def choose_retro_wallpaper(self):
        self.win.choose_swatch(
            "Background",
            "Gray, blue, or the static of a TV between channels.",
            list(RETRO_WALLPAPERS),
            self.state.settings["retro_wallpaper"],
            lambda k: self.change(lambda s: s.settings.update(retro_wallpaper=k)),
            names=RETRO_WALLPAPER_LABELS,
        )

    def choose_theme(self):
        self.win.choose_option(
            "Light or dark",
            list(THEMES.items()),
            self.state.settings["theme"],
            lambda t: self.change(lambda s: s.settings.update(theme=t)),
        )

    def choose_wallpaper(self):
        self.win.choose_swatch(
            "Background colour",
            "Six greys, six colours and the same colours darker.",
            WALLPAPERS,
            self.state.settings["wallpaper"],
            lambda c: self.change(lambda s: s.settings.update(wallpaper=c)),
        )

    def choose_corner(self):
        self.win.choose_option(
            "Quick Menu corner",
            list(CORNERS.items()),
            self.state.settings["quick_corner"],
            lambda c: self.change(lambda s: s.settings.update(quick_corner=c)),
        )

    def choose_channel_digits(self):
        def chosen(digits):
            if digits == self.state.settings["channel_digits"]:
                return
            lost = ConfigStore().too_long_channels(digits)
            if not lost:
                self.change(lambda s: s.set_channel_digits(digits))
                return
            names = ", ".join(f"{p.channel} ({p.name})" for p in lost[:6]) + (
                f" and {len(lost)-6} more" if len(lost) > 6 else ""
            )
            self.win.confirm(
                "Remove the longer channel numbers?",
                f"With {digits_label(digits).lower()}, channels run from {channel_range(digits)}. "
                f"{'This channel is' if len(lost)==1 else 'These channels are'} too long and will be removed: {names}. "
                f"You can give {'that app a new number' if len(lost)==1 else 'those apps new numbers'} afterwards.",
                "Remove",
                lambda: self.change(lambda s: s.set_channel_digits(digits)),
            )

        self.win.choose_option(
            "Channel number digits",
            [(d, f"{digits_label(d)}: {channel_range(d)}") for d in CHANNEL_DIGITS],
            self.state.settings["channel_digits"],
            chosen,
        )

    def choose_margin(self):
        from tvwcs.ui.margin import MarginPreview

        st = self.state.settings

        def done(margin):
            if margin is not None and margin != st["margin"]:
                self.change(lambda s: s.settings.update(margin=int(margin)))
            GLib.idle_add(
                lambda: (
                    self._ids.get("opt:margin") is not None and self._ids["opt:margin"].grab_focus(),
                    GLib.SOURCE_REMOVE,
                )[1]
            )

        MarginPreview(
            self.win, st["margin"], st["quick_width"], self.win.app.scale, st["accent"], done, corner=st["quick_corner"]
        )
