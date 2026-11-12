"""Settings > Sound: outputs, inputs, volume and HDMI profiles. Back end: settings/sound.py."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from tvwcs.settings import sound
from tvwcs.system import distro
from tvwcs.core.model import ConfigStore
from tvwcs.settings.app import in_background
from tvwcs.ui.widgets import S, glyph
from tvwcs.settings.pages.base import Page, _on_off, _outcome, tell_tvwcs


# ====================================================================== Sound
class SoundPage(Page):
    key = "sound"
    title = "Sound"
    icon = "audio-volume-high-symbolic"
    fallback = "🔊"
    poll = 3

    def read(self):
        return sound.read_state()

    def summary(self):
        return self.state.server if self.state and self.state.available else ""

    def draw(self, state):
        if not state.available:
            self.note(state.message)
            return
        self.section("OUTPUT")
        current = state.output()
        shown, unplugged = sound.split_unplugged(state.outputs, current.name if current else "")
        if current is None:
            self.note(self.no_output_text(state))
        else:
            self.volume_row(current, "out")
            self.device_row(current, True, "audio-speakers-symbolic", "🔈")
        others = [d for d in shown if current is None or d.name != current.name] + unplugged
        self.unplugged_rows(
            "out",
            [lambda d=d: self.device_row(d, False, "audio-speakers-symbolic", "🔈") for d in others]
            + [lambda o=o: self.card_output_row(o) for o in state.other_outputs],
        )
        self.section("INPUT")
        current = state.input()
        shown, unplugged = sound.split_unplugged(state.inputs, current.name if current else "")
        if current is None:
            self.note("No microphone or other input is connected.")
        else:
            self.volume_row(current, "in")
            self.device_row(current, True, "audio-input-microphone-symbolic", "🎤")
        others = [d for d in shown if current is None or d.name != current.name] + unplugged
        self.unplugged_rows(
            "in", [lambda d=d: self.device_row(d, False, "audio-input-microphone-symbolic", "🎤") for d in others]
        )
        self.note("Choosing a device uses it from now on; sound that is already playing moves to it too.")
        self.section("VOLUME")
        boost = bool(ConfigStore().settings["audio_boost"])
        self.row(
            "Allow over-amplification",
            _on_off(boost),
            self.toggle_boost,
            ident="sound:boost",
            value_css="state-on" if boost else "setting-value",
            detail="Up to 150 %. Louder, but the sound can distort. Off, volumes stop at 100 %",
        )

    def toggle_boost(self):
        store = ConfigStore()
        store.settings["audio_boost"] = not store.settings["audio_boost"]
        store.save()
        tell_tvwcs("reload")
        self.redraw()

    def unplugged_rows(self, kind, draws):
        """The inactive outputs or inputs (nothing plugged in, or another profile of the card), folded under one row,
        "3 inactive outputs", that opens and closes them: they can still be tried, but seldom are."""
        if not draws:
            return
        opened = getattr(self, "opened", set())
        self.opened = opened
        is_open = kind in opened

        def toggle():
            opened.symmetric_difference_update({kind})
            self.redraw()

        what = ("output" if kind == "out" else "input") + ("s" if len(draws) != 1 else "")
        self.row(
            f"{len(draws)} inactive {what}",
            "Hide" if is_open else "Show",
            toggle,
            detail="Not in use now, but they can be tried",
            icon="pan-down-symbolic" if is_open else "pan-end-symbolic",
            fallback="▾" if is_open else "▸",
            ident=f"unplugged:{kind}",
        )
        if is_open:
            for draw in draws:
                draw()

    def device_row(self, d, in_use, icon, fallback):
        ports = [p for p in d.ports if p.available]
        port = next((p.label for p in d.ports if p.name == d.active_port), "")
        extra = None
        if len(ports) > 1:
            extra = self.button(
                "view-list-symbolic",
                "⋯",
                f"Choose the connector of {d.label}",
                lambda d=d, ports=ports: self.choose_port(d, ports),
            )
        self.row(
            d.label,
            "In use" if in_use else "",
            (
                (
                    lambda d=d: self.act(
                        lambda: _outcome(sound.make_default(d), "Could not switch to that device."),
                        f"Switching to {d.label}…",
                        "Sound",
                    )
                )
                if not in_use
                else None
            ),
            detail=port if len(ports) > 1 else "",
            icon=icon,
            fallback=fallback,
            ident=f"{d.kind}:{d.name}",
            extras=[extra],
            value_css="state-on",
        )

    @staticmethod
    def no_output_text(state):
        if state.alsa_cards == 0:
            if distro.is_arch():
                return (
                    "The computer has no sound card the system can use: its driver, or the firmware it needs, is missing. "
                    "Install sof-firmware (Intel laptops and mini PCs) and linux-firmware, then restart."
                )
            if distro.is_fedora():
                return (
                    "The computer has no sound card the system can use: its driver, or the firmware it needs, is missing. "
                    "Install alsa-sof-firmware (Intel laptops and mini PCs) and linux-firmware, then restart."
                )
            return (
                "The computer has no sound card the system can use: its driver, or the firmware it needs, is missing. On Debian, "
                "install firmware-sof-signed (Intel laptops and mini PCs) or firmware-misc-nonfree (from non-free-firmware), then restart."
            )
        return "No sound output was found."

    def card_output_row(self, o):
        """An output of a profile the card is not using now (often its HDMI output): choosing it switches the card over."""
        detail = f"{o.card_label} · switches the sound card to this output"

        def use(o=o):
            self.act(
                lambda: _outcome(sound.use_card_output(o), f"Could not switch {o.card_label} to {o.label}."),
                f"Switching to {o.label}…",
                "Sound",
                after=lambda: setattr(self, "focus_after", f"sink:{sound.sink_for(o.card,o.output)}"),
            )

        self.row(
            o.label,
            "",
            use,
            detail=detail,
            icon="video-display-symbolic" if o.hdmi else "audio-speakers-symbolic",
            fallback="🖵" if o.hdmi else "🔈",
            ident=f"card:{o.card}:{o.output}",
        )

    def choose_port(self, d, ports):
        def picked(name):
            self.act(
                lambda: _outcome(sound.set_port(d, name), "Could not switch the connector."), "Switching…", "Sound"
            )

        self.win.choose_option(f"Connector · {d.label}", [(p.name, p.label) for p in ports], d.active_port, picked)

    def volume_row(self, d, ident):
        """− [ level ] + and mute. The bar can be dragged with a mouse; the D-pad uses − and +."""
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=S(6))
        line.set_margin_top(S(2))
        line.set_margin_bottom(S(4))
        minus = self.button("list-remove-symbolic", "−", "Quieter", lambda: step(-1))
        plus = self.button("list-add-symbolic", "+", "Louder", lambda: step(1))
        mute = Gtk.Button()
        boost = bool(ConfigStore().settings["audio_boost"])
        # a volume already above the top (set elsewhere) widens the bar, so it still shows where the volume is
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, max(sound.top(boost), d.volume), 1)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.set_focusable(False)
        scale.set_valign(Gtk.Align.CENTER)
        value = Gtk.Label()
        value.add_css_class("volume-value")
        value.set_xalign(1)
        guard = [False]
        pending = [0]

        def show():
            guard[0] = True
            scale.set_value(d.volume)
            guard[0] = False
            value.set_text(f"{d.volume} %")
            (scale.add_css_class if d.muted else scale.remove_css_class)("muted")
            mute.set_child(
                glyph(
                    "audio-volume-muted-symbolic" if d.muted else "audio-volume-high-symbolic",
                    "🔇" if d.muted else "🔊",
                )
            )
            mute.set_tooltip_text(("Unmute " if d.muted else "Mute ") + d.label)
            (mute.add_css_class if d.muted else mute.remove_css_class)("active")

        def applied(result, what):
            if result.ok:
                return
            self.win.notice("Sound", f"Could not {what} {d.label}: {result.message}")
            self.refresh(quiet=True)

        def apply_volume():
            pending[0] = 0
            level = d.volume
            in_background(lambda: sound.set_volume(d, level, boost), lambda r: applied(r, "change the volume of"))
            return GLib.SOURCE_REMOVE

        def step(direction):
            d.volume = sound.stepped(d.volume, direction, boost)
            show()
            if pending[0]:
                GLib.source_remove(pending[0])
            pending[0] = GLib.timeout_add(120, apply_volume)  # holding the key sends one change, not twenty

        def dragged(*_):
            if guard[0]:
                return
            d.volume = int(scale.get_value())
            value.set_text(f"{d.volume} %")
            if pending[0]:
                GLib.source_remove(pending[0])
            pending[0] = GLib.timeout_add(120, apply_volume)

        def toggle_mute():
            d.muted = not d.muted
            show()
            muted = d.muted
            in_background(lambda: sound.set_muted(d, muted), lambda r: applied(r, "mute" if muted else "unmute"))

        scale.connect("value-changed", dragged)
        mute.connect("clicked", lambda *_: toggle_mute())
        for w in (minus, plus, mute):
            w.add_css_class("square")
        label = Gtk.Label(label="Volume")
        label.set_xalign(0)
        label.set_size_request(S(110), -1)
        for w in (label, minus, scale, value, plus, mute):
            line.append(w)
        show()
        self.add(line)
        self.register(minus, plus, mute, ident=f"volume:{ident}")
