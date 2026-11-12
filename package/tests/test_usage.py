import io, unittest
from pathlib import Path
from tvwcs import usage

PKG = Path(__file__).resolve().parent.parent


class UsageTests(unittest.TestCase):
    def test_lists_the_commands(self):
        out = io.StringIO()
        self.assertEqual(usage.main([], out), 0)
        for cmd in (
            "tvwcs session",
            "tvwcs settings [PAGE]",
            "tvwcs server-mode on",
            "tvwcs server-mode off",
            "tvwcs server-mode status",
            "tvwcs start-session",
            "tvwcs launcher",
            "tvwcs help",
        ):
            self.assertIn(cmd, out.getvalue())
        self.assertEqual(usage.wrong(io.StringIO()), 2)

    def test_the_sway_config_starts_the_launcher_by_its_new_name(self):
        self.assertIn("exec /usr/bin/tvwcs launcher\n", (PKG.parent / "data" / "tvwcs.conf").read_text())
        main = (PKG / "tvwcs" / "main.py").read_text()
        # "start" stays for an older TVWCS's restart after an update
        self.assertIn('args in (["launcher"], ["start"])', main)


if __name__ == "__main__":
    unittest.main()
