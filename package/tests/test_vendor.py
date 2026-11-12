import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from tvwcs.system import selfupdate
from tvwcs.core import vendor
from tvwcs.core.applications import Application
from tvwcs.core.model import ConfigStore
from tvwcs.system.selfupdate import UpdateError


def app(desktop_id, name):
    return Application(desktop_id, name, None, None, None, (), "/fake", name.lower())


class Files:
    """Preset files in a temporary folder, put where vendor.py reads them."""

    def __init__(self, package=None, vendor_=None, admin=None):
        self.d = tempfile.TemporaryDirectory()
        self.env = {}
        for key, data in (
            ("TVWCS_PACKAGE_FILE", package),
            ("TVWCS_VENDOR_FILE", vendor_),
            ("TVWCS_DEFAULTS_FILE", admin),
        ):
            path = Path(self.d.name, key.lower() + ".json")
            if data is not None:
                path.write_text(data if isinstance(data, str) else json.dumps(data))
            self.env[key] = str(path)
        self.config = Path(self.d.name, "config.json")

    def __enter__(self):
        self.p = patch.dict(os.environ, self.env)
        self.p.start()
        return self

    def __exit__(self, *a):
        self.p.stop()
        self.d.cleanup()


class VendorFileTests(unittest.TestCase):
    def test_no_files_means_the_system_updates_tvwcs(self):
        with Files():
            v = vendor.load(report=False)
            self.assertEqual((v.updates.source, v.name, v.files, v.problems), ("system", "", [], []))
            self.assertFalse(selfupdate.self_updates())
            with self.assertRaises(UpdateError):
                selfupdate.latest_release()

    def test_tvwcs_own_package_turns_github_updates_on_and_a_vendor_wins(self):
        own = json.loads((Path(__file__).resolve().parents[2] / "packaging/common/updates.json").read_text())
        with Files(package=own):
            self.assertTrue(selfupdate.self_updates())
            self.assertEqual(selfupdate.repo(), "grahamrkf/tvwcs")
        with Files(package=own, vendor_={"updates": {"source": "system"}}):
            self.assertFalse(selfupdate.self_updates())
        with Files(package=own, vendor_={"updates": {"source": "github", "repo": "example/tvwcs"}}):
            self.assertEqual((selfupdate.repo(), selfupdate.where()), ("example/tvwcs", "GitHub (example/tvwcs)"))
            self.assertEqual(
                selfupdate.installer_url(), "https://github.com/example/tvwcs/releases/latest/download/install.sh"
            )
        with Files(package=own, vendor_={"updates": {"source": "github"}}, admin={"updates": {"source": "off"}}):
            self.assertEqual(vendor.load(report=False).updates.source, "off")  # the administrator's file wins

    def test_bad_values_are_skipped_and_named(self):
        with Files(
            vendor_={
                "name": "  Example   TV ",
                "support_url": "http://example.org",
                "updates": {"source": "url", "url": "ftp://x"},
                "channels": [{"desktop_id": "nope"}, {"desktop_id": "org.example.Player.desktop", "channel": "one"}],
                "colour": "red",
            }
        ):
            v = vendor.load(report=False)
            self.assertEqual((v.name, v.support_url, v.updates.source), ("Example TV", "", "system"))
            self.assertEqual(v.channels, {"org.example.Player.desktop": {"channel": None, "favorite": False}})
            self.assertEqual(len(v.problems), 5)
        with Files(vendor_="{not json"):
            v = vendor.load(report=False)
            self.assertEqual(v.files, [])
            self.assertIn("not valid JSON", v.problems[0])

    def test_describe_names_unknown_and_invalid_settings(self):
        with Files(vendor_={"settings": {"style": "media", "quick_corner": "middle", "wobble": True}}):
            text = vendor.describe()
            self.assertIn('setting style = "media"', text)
            self.assertIn("“wobble”", text)
            self.assertIn("“quick_corner”", text)


class PresetTests(unittest.TestCase):
    def test_presets_are_the_defaults_and_only_changes_are_saved(self):
        with Files(
            vendor_={
                "settings": {
                    "style": "media",
                    "media_look": "plex",
                    "clock_24h": True,
                    "hotkeys": {"remote": {"menu": "F9"}},
                    "idle": {"screen_off": 600},
                }
            }
        ) as f:
            store = ConfigStore(f.config)
            s = store.settings
            self.assertEqual(
                (
                    s["style"],
                    s["media_look"],
                    s["clock_24h"],
                    s["hotkeys"]["remote"]["menu"],
                    s["hotkeys"]["keyboard"]["menu"],
                    s["idle"]["screen_off"],
                ),
                ("media", "plex", True, "F9", "Mod4", 600),
            )
            store.settings["clock_24h"] = False
            store.settings["hotkeys"]["gamepad"]["menu"] = "BTN_MODE"
            store.save()
            saved = json.loads(f.config.read_text())["settings"]
            self.assertEqual(saved, {"clock_24h": False, "hotkeys": {"gamepad": {"menu": "BTN_MODE"}}})
            # the vendor changes its preset: a user who never changed that setting follows it
            Path(f.env["TVWCS_VENDOR_FILE"]).write_text(json.dumps({"settings": {"style": "retro", "clock_24h": True}}))
            s = ConfigStore(f.config).settings
            self.assertEqual((s["style"], s["clock_24h"], s["hotkeys"]["remote"]["menu"]), ("retro", False, "F2"))

    def test_an_old_full_config_keeps_its_values(self):
        with Files(vendor_={"settings": {"theme": "light"}}) as f:
            f.config.write_text(json.dumps({"settings": {"theme": "dark", "channel_digits": 3}, "profiles": []}))
            s = ConfigStore(f.config).settings
            self.assertEqual((s["theme"], s["channel_digits"]), ("dark", 3))

    def test_old_single_hotkey_set_still_becomes_the_remote_set(self):
        with Files(vendor_={"settings": {"hotkeys": {"keyboard": {"menu": "F12"}}}}) as f:
            f.config.write_text(json.dumps({"settings": {"hotkeys": {"menu": "F9"}}}))
            hk = ConfigStore(f.config).settings["hotkeys"]
            self.assertEqual((hk["remote"]["menu"], hk["keyboard"]["menu"]), ("F9", "F12"))

    def test_channel_digits_preset_and_old_three_digit_channels(self):
        with Files(vendor_={"settings": {"channel_digits": 1}}) as f:
            self.assertEqual(ConfigStore(f.config).settings["channel_digits"], 1)
            f.config.write_text(
                json.dumps({"settings": {}, "profiles": [{"id": "a", "desktop_id": "x.desktop", "channel": 120}]})
            )
            store = ConfigStore(f.config)
            self.assertEqual((store.settings["channel_digits"], store.get("a").channel), (3, 120))

    def test_vendor_channels_and_startup_app_are_given_once(self):
        with Files(
            vendor_={
                "channels": [
                    {"desktop_id": "org.example.Player.desktop", "channel": 1, "favorite": True},
                    {"desktop_id": "org.example.Games.desktop", "channel": 1},
                ],
                "startup_app": "org.example.Player.desktop",
            }
        ) as f:
            store = ConfigStore(f.config)
            store.ensure_defaults(
                [app("org.example.Player.desktop", "Player"), app("org.example.Games.desktop", "Games")]
            )
            player = store.for_app("org.example.Player.desktop")[0]
            games = store.for_app("org.example.Games.desktop")[0]
            self.assertEqual(
                (player.channel, player.favorite, games.channel), (1, True, None)
            )  # channel 1 was taken by then
            self.assertEqual(store.settings["startup"]["mode"], "app")
            self.assertEqual(store.settings["startup"]["profile_id"], player.id)
            # the user moves it and turns the startup app off: kept
            player.channel = 5
            store.settings["startup"]["mode"] = "none"
            store.save()
            store = ConfigStore(f.config)
            store.ensure_defaults(
                [app("org.example.Player.desktop", "Player"), app("org.example.Games.desktop", "Games")]
            )
            self.assertEqual(
                (store.for_app("org.example.Player.desktop")[0].channel, store.settings["startup"]["mode"]), (5, "none")
            )


class ReleaseListTests(unittest.TestCase):
    def rel(self, tag, pre=False, url="https://example.org/dl/"):
        v = tag.lstrip("v")
        return {
            "tag_name": tag,
            "prerelease": pre,
            "assets": [{"name": f"tvwcs_{v}_all.deb", "browser_download_url": f"{url}tvwcs_{v}_all.deb"}],
        }

    def test_a_vendor_release_list(self):
        u = vendor.Updates("url", url="https://example.org/tvwcs/releases.json")
        listing = {"releases": [self.rel("v6.1.0", pre=True), self.rel("v6.0.0"), self.rel("v5.9.0")]}
        with patch.object(selfupdate, "_get_json", lambda url: listing):
            self.assertEqual(selfupdate.latest_release(updates=u).version, "6.0.0")
            self.assertEqual(selfupdate.latest_release(True, updates=u).version, "6.1.0")
            self.assertEqual(selfupdate.where(u), "example.org")
        with patch.object(selfupdate, "_get_json", lambda url: [self.rel("v6.0.0", url="http://example.org/")]):
            with self.assertRaises(UpdateError):
                selfupdate.latest_release(updates=u)  # only https:// downloads
        with patch.object(selfupdate, "_get_json", lambda url: {"message": "nope"}):
            with self.assertRaises(UpdateError):
                selfupdate.latest_release(updates=u)

    def test_a_fork_on_github(self):
        seen = []
        with patch.object(selfupdate, "_get_json", lambda url: seen.append(url) or self.rel("v6.0.0")):
            selfupdate.latest_release(updates=vendor.Updates("github", "example/tvwcs"))
        self.assertEqual(seen, ["https://api.github.com/repos/example/tvwcs/releases/latest"])


if __name__ == "__main__":
    unittest.main()
