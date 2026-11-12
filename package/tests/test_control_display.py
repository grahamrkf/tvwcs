"""The Settings app's Displays page without a display: swaymsg output parsed from saved samples, the arrangement kept
when a resolution changes, the commands it would run, and the settings saved for the next login."""

import json, tempfile, unittest
from pathlib import Path

from tvwcs import control_display as disp


def out(
    name,
    x,
    y,
    w,
    h,
    active=True,
    scale=1.0,
    transform="normal",
    modes=((1920, 1080, 60000),),
    make="Unknown",
    model="Unknown",
):
    return {
        "name": name,
        "make": make,
        "model": model,
        "active": active,
        "scale": scale,
        "transform": transform,
        "rect": {"x": x, "y": y, "width": w, "height": h},
        "current_mode": {"width": modes[0][0], "height": modes[0][1], "refresh": modes[0][2]} if active else {},
        "modes": [{"width": a, "height": b, "refresh": r} for a, b, r in modes],
    }


SWAY = json.dumps(
    [
        out(
            "HDMI-A-1",
            0,
            0,
            1920,
            1080,
            scale=2.0,
            make="Samsung Electric Company",
            model="QN55",
            modes=((3840, 2160, 60000), (3840, 2160, 30000), (1920, 1080, 60000)),
        ),
        out("eDP-1", 0, 0, 0, 0, active=False, modes=((1366, 768, 60059),)),
    ]
)
ROW = json.dumps(
    [
        out("DP-1", 0, 0, 1920, 1080, modes=((1920, 1080, 60000), (1280, 720, 60000))),
        out("DP-2", 1920, 0, 1920, 1080),
        out("DP-3", 3840, 0, 1920, 1080),
    ]
)


def by(outs, name):
    return next(o for o in outs if o.name == name)


class ParseTests(unittest.TestCase):
    def test_reads_outputs_modes_rates_and_scale(self):
        outs = disp.parse_sway(SWAY)
        tv = by(outs, "HDMI-A-1")
        self.assertEqual(
            (tv.label, tv.enabled, tv.width, tv.height, tv.rate, tv.scale),
            ("Samsung Electric Company QN55", True, 3840, 2160, 60.0, 2.0),
        )
        self.assertEqual(tv.size, (1920, 1080))
        self.assertEqual(tv.modes[0].rates, [60.0, 30.0])
        self.assertTrue(tv.modes[0].preferred)
        lap = by(outs, "eDP-1")
        self.assertFalse(lap.enabled)
        self.assertEqual(lap.label, "")
        self.assertEqual(lap.scale, 1.0)
        self.assertEqual(disp.parse_sway("not json"), [])

    def test_a_rotated_display_covers_its_turned_size(self):
        o = disp.parse_sway(json.dumps([out("DP-1", 0, 0, 1080, 1920, transform="90")]))[0]
        self.assertTrue(o.rotated)
        self.assertEqual(o.size, (1080, 1920))

    def test_read_state_needs_sway(self):
        self.assertFalse(disp.read_state({}).available)

    def test_texts(self):
        self.assertEqual(
            (disp.rate_text(60.0), disp.rate_text(59.94), disp.scale_text(1.5)), ("60 Hz", "59.94 Hz", "150 %")
        )
        self.assertEqual(disp.mode_text(disp.Mode(1920, 1080, True)), "1920 × 1080 (interlaced)")


class ScaleTests(unittest.TestCase):
    def test_choices_leave_enough_pixels(self):
        tv = by(disp.parse_sway(SWAY), "HDMI-A-1")
        self.assertEqual(disp.scale_choices([tv]), list(disp.SCALES))  # 2160 high: every scale leaves 1080 or more
        small = disp.Output("X", enabled=True, width=1366, height=768)
        self.assertEqual(disp.scale_choices([small]), [0.75, 1.0, 1.25])  # 768/1.5 is below 540
        self.assertEqual(disp.scale_choices([small], 1.6), [0.75, 1.0, 1.25, 1.6])  # the one in use is always offered


class ArrangeTests(unittest.TestCase):
    def test_reads_the_arrangement(self):
        outs = disp.parse_sway(ROW)
        self.assertEqual(disp.placements(outs), {"DP-2": ("right", "DP-1"), "DP-3": ("right", "DP-2")})
        self.assertEqual(disp.choices(outs, by(outs, "DP-2"))[0], ("right:DP-1", "Right of DP-1"))

    def test_a_smaller_resolution_keeps_the_neighbour_against_it(self):
        new = disp.edited(disp.parse_sway(ROW), "DP-1", mode=(1280, 720, False))
        self.assertEqual([(o.name, o.x) for o in new], [("DP-1", 0), ("DP-2", 1280), ("DP-3", 3200)])

    def test_a_row_of_three_closes_up_when_the_middle_one_goes_off(self):
        new = disp.edited(disp.parse_sway(ROW), "DP-2", enabled=False)
        self.assertEqual((by(new, "DP-3").x, by(new, "DP-2").enabled), (1920, False))

    def test_switching_a_display_on_puts_it_at_the_right_end(self):
        outs = disp.parse_sway(SWAY)
        new = disp.edited(outs, "eDP-1", enabled=True)
        lap = by(new, "eDP-1")
        self.assertEqual((lap.enabled, lap.width, lap.x, lap.y), (True, 1366, 1920, 0))

    def test_a_scale_change_moves_the_neighbour(self):
        new = disp.edited(disp.parse_sway(ROW), "DP-1", scale=2.0)
        self.assertEqual((by(new, "DP-1").size, by(new, "DP-2").x), ((960, 540), 960))

    def test_moving_the_reference_moves_the_other_instead(self):
        new = disp.edited(disp.parse_sway(ROW), "DP-1", place=("below", "DP-2"))
        self.assertEqual(
            ((by(new, "DP-1").x, by(new, "DP-1").y), (by(new, "DP-2").x, by(new, "DP-2").y)), ((0, 1080), (0, 0))
        )  # DP-2 above DP-1
        self.assertEqual(disp.placements(new)["DP-2"], ("above", "DP-1"))

    def test_keeps_the_rate_when_the_new_mode_has_it_else_takes_the_highest(self):
        m = disp.Mode(1920, 1080, rates=[144.0, 60.0])
        self.assertEqual((disp.best_rate(m, 60.0), disp.best_rate(m, 75.0)), (60.0, 144.0))


class CommandTests(unittest.TestCase):
    def test_sway_command(self):
        outs = disp.parse_sway(SWAY)
        self.assertEqual(
            disp.sway_command(outs),
            'output "HDMI-A-1" enable mode 3840x2160@60.000Hz scale 2 position 0 0; output "eDP-1" disable',
        )

    def test_never_switches_every_display_off(self):
        outs = disp.edited(disp.parse_sway(SWAY), "HDMI-A-1", enabled=False)
        self.assertIn("stay on", disp.apply(disp.DisplayState(True, "", outs), outs))


class SavedTests(unittest.TestCase):
    def test_saved_settings_come_back_only_for_the_same_displays(self):
        outs = disp.parse_sway(ROW)
        changed = disp.edited(outs, "DP-1", mode=(1280, 720, False))
        saved = disp.to_saved(changed)
        state = disp.DisplayState(True, "", outs)
        back = disp.from_saved(state, saved)
        self.assertEqual((by(back, "DP-1").width, by(back, "DP-2").x), (1280, 1280))
        self.assertIsNone(disp.from_saved(disp.DisplayState(True, "", disp.parse_sway(SWAY)), saved))

    def test_scale_is_kept(self):
        outs = disp.parse_sway(SWAY)
        saved = disp.to_saved(disp.edited(outs, "HDMI-A-1", scale=1.5))
        self.assertEqual(by(disp.from_saved(disp.DisplayState(True, "", outs), saved), "HDMI-A-1").scale, 1.5)

    def test_modes_kept_under_i3_before_5_0_are_used_once(self):
        outs = disp.parse_sway(SWAY)
        old = {
            "xrandr": {
                "outputs": {
                    "HDMI-1": {
                        "enabled": True,
                        "x": 0,
                        "y": 0,
                        "width": 1920,
                        "height": 1080,
                        "rate": 60.0,
                        "scale": 1.0,
                    },
                    "eDP-1": {"enabled": False},
                }
            }
        }
        tv = by(disp.from_saved(disp.DisplayState(True, "", outs), old), "HDMI-A-1")
        self.assertEqual((tv.width, tv.scale), (1920, 2.0))  # the mode, not X11's scale
        self.assertNotIn("xrandr", disp.to_saved(outs, old))

    def test_a_file_from_before_3_0_1_still_loads(self):
        outs = disp.parse_sway(ROW)
        old = {"backend": "sway", "outputs": disp.to_saved(outs)["sway"]["outputs"]}
        self.assertIsNotNone(disp.from_saved(disp.DisplayState(True, "", outs), old))

    def test_save_writes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "displays.json"
            disp.save(disp.parse_sway(ROW), p)
            self.assertEqual(sorted(json.loads(p.read_text())["sway"]["outputs"]), ["DP-1", "DP-2", "DP-3"])

    def test_connector_names(self):
        self.assertEqual(disp.connector_key("HDMI-A-2"), "HDMI-2")


if __name__ == "__main__":
    unittest.main()
