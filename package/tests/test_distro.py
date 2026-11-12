"""distro.py: Debian's family and Arch's, and what Settings does differently on Arch."""

import os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from tvwcs.system import distro, features, loginscreen, selfupdate
from tvwcs.settings import ssh


def arch():
    return mock.patch.dict(os.environ, {"TVWCS_FAMILY": "arch"})


class FamilyTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ)
        self.env.start()
        os.environ.pop("TVWCS_FAMILY", None)

    def tearDown(self):
        self.env.stop()

    def test_family_from_os_release(self):
        none = lambda _n: None
        for text, fam in (
            ("ID=arch\n", "arch"),
            ("ID=endeavouros\nID_LIKE=arch\n", "arch"),
            ('ID="cachyos"\nID_LIKE="arch"\n', "arch"),
            ("ID=manjaro\nID_LIKE=arch\n", "arch"),
            ("ID=ubuntu\nID_LIKE=debian\n", "debian"),
            ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "debian"),
            ("ID=fedora\n", "fedora"),
            ('ID=nobara\nID_LIKE="rhel centos fedora"\n', ""),
            ("ID=nobara\nID_LIKE=fedora\n", "fedora"),
            ('ID="rocky"\nID_LIKE="rhel centos fedora"\n', ""),
            ("ID=opensuse-tumbleweed\n", ""),
        ):
            self.assertEqual(distro.family(distro.parse_os_release(text), which=none), fam, text)

    def test_package_manager_when_os_release_says_nothing(self):
        self.assertEqual(distro.family({}, which=lambda n: "/usr/bin/pacman" if n == "pacman" else None), "arch")

    def test_override(self):
        os.environ["TVWCS_FAMILY"] = "arch"
        self.assertEqual(distro.family({"ID": "debian"}), "arch")


class ArchPackageTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(distro.packages("bluetooth", "arch"), ("bluez", "bluez-utils"))
        self.assertIn("libpulse", distro.packages("sound", "arch"))
        self.assertIn("pulseaudio-utils", distro.packages("sound", "debian"))
        self.assertEqual(distro.packages("ssh", "arch"), ("openssh",))
        self.assertEqual(distro.packages("ssh", "debian"), ("openssh-server",))

    def test_install_never_refreshes_alone(self):
        argv = distro.install_argv(["bluez", "bluez-utils"], "arch", enable=("bluetooth.service",))
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertIn("pacman -S --needed --noconfirm", argv[2])
        self.assertNotIn("-Sy", argv[2])
        self.assertIn("systemctl enable --now bluetooth.service", argv[2])
        self.assertEqual(argv[-2:], ["bluez", "bluez-utils"])
        with self.assertRaises(ValueError):
            distro.install_argv(["x; reboot"], "arch")
        self.assertEqual(distro.remove_argv(["bluez"], "arch"), ["pacman", "-R", "--noconfirm", "bluez"])

    def test_debian_install_is_unchanged(self):
        self.assertEqual(
            distro.install_argv(["bluez"], "debian"),
            [
                "env",
                "DEBIAN_FRONTEND=noninteractive",
                "sh",
                "-c",
                'apt-get update -q && apt-get install -y "$@"',
                "sh",
                "bluez",
            ],
        )

    def test_states(self):
        self.assertEqual(
            distro.parse_states("bluez 5.79-1\n", ["bluez", "bluez-utils"], "arch"),
            {"bluez": True, "bluez-utils": False},
        )
        self.assertEqual(
            distro.parse_states("bluez\tii \nbluez-obexd\trc \n", ["bluez", "bluez-obexd"], "debian"),
            {"bluez": True, "bluez-obexd": False},
        )

    def test_features_and_ssh_on_arch(self):
        with arch(), mock.patch.object(distro.shutil, "which", lambda n: "/usr/bin/" + n):
            self.assertEqual(features.packages_for(features.BY_KEY["bluetooth"]), ("bluez", "bluez-utils"))
            self.assertIn(
                "enable --now bluetooth.service", features.install_argv(["bluez"], features.BY_KEY["bluetooth"])[2]
            )
            self.assertNotIn("enable", features.install_argv(["pipewire"], features.BY_KEY["sound"])[2])
            self.assertEqual(ssh.install_argv()[-1], "openssh")
        self.assertNotIn(
            "enable", features.install_argv(["bluez"], features.BY_KEY["bluetooth"])[4]
        )  # Debian starts it itself


class ArchGreetdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"TVWCS_ROOT": str(self.root), "TVWCS_FAMILY": "arch"})
        self.env.start()
        ws = self.root / "usr" / "share" / "wayland-sessions"
        ws.mkdir(parents=True)
        (ws / "tvwcs-sway.desktop").write_text("[Desktop Entry]\nName=TVWCS\nExec=/usr/bin/tvwcs-session\n")
        units = self.root / "usr" / "lib" / "systemd" / "system"
        units.mkdir(parents=True)
        (units / "greetd.service").write_text("[Unit]\n")
        (self.root / "etc" / "systemd" / "system").mkdir(parents=True)
        (self.root / "etc" / "greetd").mkdir()
        self.c = loginscreen.Changer(out=lambda _t: None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_greetd_uses_arch_user_agreety_and_console(self):
        self.c.use_greetd("tv")
        cfg = loginscreen.greetd_config()
        self.assertEqual(cfg["default_session"]["user"], "greeter")
        self.assertEqual(str(cfg["terminal"]["vt"]), "1")
        self.assertTrue(cfg["default_session"]["command"].startswith("/usr/bin/agreety --cmd "))
        self.assertEqual(cfg["initial_session"]["user"], "tv")
        self.assertFalse((self.root / "etc" / "X11" / "default-display-manager").exists())  # Debian's file only
        self.assertTrue((self.root / "etc" / "systemd" / "system" / "display-manager.service").is_symlink())

    def test_an_existing_config_keeps_its_console(self):
        (self.root / "etc" / "greetd" / "config.toml").write_text(
            '[terminal]\nvt = 2\n\n[default_session]\ncommand = "tuigreet --cmd sway"\nuser = "greeter"\n'
        )
        self.c.write_greetd(("tv", "tvwcs-sway"))
        cfg = loginscreen.greetd_config()
        self.assertEqual(str(cfg["terminal"]["vt"]), "2")
        self.assertEqual(cfg["default_session"]["command"], "tuigreet --cmd sway")

    def test_root_command_installs_with_pacman(self):
        argv = loginscreen.root_command(["greetd", "tv"], ("greetd",))
        self.assertIn("pacman -S --needed --noconfirm $packages", argv[2])
        self.assertNotIn("apt-get", argv[2])


REPO = Path(__file__).resolve().parents[2]


class RemoveGreetdTests(unittest.TestCase):
    """The .deb's prerm and the Arch package's pre_remove take only TVWCS's part out of greetd's config."""

    def remove(self, text, arch_pkg):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d, "etc", "greetd", "config.toml")
            conf.parent.mkdir(parents=True)
            conf.write_text(text)
            script = (REPO / ("packaging/arch/tvwcs.install" if arch_pkg else "packaging/tvwcs/prerm")).read_text()
            for real in (
                "/etc/",
                "/usr/lib/",
                "/run/",
            ):  # nothing outside the folder: the prerm also removes bytecode in /usr/lib/tvwcs
                script = script.replace(real, f"{d}{real}")
            if arch_pkg:
                argv = ["sh", "-c", script + "\npre_remove"]
            else:
                argv = ["sh", "-c", script, "prerm", "remove"]
            subprocess.run(argv, check=True, capture_output=True)
            self.assertEqual(sorted(p.name for p in conf.parent.iterdir()), ["config.toml"])
            return conf.read_text()

    def test_another_greeter_stays(self):
        text = (
            '[terminal]\nvt = 2\n\n[default_session]\ncommand = "tuigreet --cmd sway"\nuser = "greeter"\n\n'
            '[initial_session]\ncommand = "/usr/bin/tvwcs-session"\nuser = "tv"\n'
        )
        for arch_pkg in (True, False):
            out = self.remove(text, arch_pkg)
            self.assertIn('command = "tuigreet --cmd sway"', out)
            self.assertIn("vt = 2", out)
            self.assertNotIn("initial_session", out)

    def test_agreety_starting_tvwcs_starts_a_shell(self):
        for arch_pkg, agreety in ((True, "agreety"), (False, "/usr/sbin/agreety")):
            out = self.remove(
                f'[default_session]\ncommand = "{agreety} --cmd /usr/bin/tvwcs-session"\nuser = "x"\n', arch_pkg
            )
            self.assertIn(f'command = "{agreety} --cmd /bin/sh"', out)
            self.assertIn('user = "x"', out)

    def test_someone_elses_autologin_stays(self):
        text = '[default_session]\ncommand = "tuigreet"\nuser = "greeter"\n\n[initial_session]\ncommand = "sway"\nuser = "tv"\n'
        self.assertEqual(self.remove(text, True), text)


class SelfUpdateTests(unittest.TestCase):
    def test_arch_package_is_not_updated_from_github(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(selfupdate.other_package(d), "")
            Path(d, "PACKAGE").write_text("arch\n")
            self.assertEqual(selfupdate.other_package(d), "arch")


if __name__ == "__main__":
    unittest.main()
