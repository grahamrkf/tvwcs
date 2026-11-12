"""Fedora: its package names and commands (distro.py), dnf in Software updates, TVWCS's own .rpm updates, greetd, and
the .rpm's removal script."""

import os, re, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from tvwcs import control_updates as upd, distro, features, loginscreen, selfupdate, control_ssh
from tvwcs.selfupdate import Release, UpdateError

REPO = Path(__file__).resolve().parents[2]


def fedora():
    return mock.patch.dict(os.environ, {"TVWCS_FAMILY": "fedora"})


class FedoraPackageTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(distro.packages("bluetooth", "fedora"), ("bluez",))  # bluetoothctl is in bluez itself
        self.assertIn("pipewire-pulseaudio", distro.packages("sound", "fedora"))
        self.assertIn("pulseaudio-utils", distro.packages("sound", "fedora"))
        self.assertEqual(distro.packages("ssh", "fedora"), ("openssh-server",))

    def test_install_and_remove_with_dnf(self):
        argv = distro.install_argv(["bluez"], "fedora", enable=("bluetooth.service",))
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertTrue(argv[2].startswith('dnf install -y "$@"'))
        self.assertIn("systemctl enable --now bluetooth.service", argv[2])
        self.assertEqual(argv[-1], "bluez")
        self.assertEqual(distro.remove_argv(["bluez"], "fedora"), ["dnf", "remove", "-y", "bluez"])
        self.assertEqual(distro.install_script("fedora"), "dnf install -y $packages")
        with self.assertRaises(ValueError):
            distro.install_argv(["x; reboot"], "fedora")

    def test_states_from_rpm(self):
        out = "bluez\npackage bluez-obexd is not installed\n"
        self.assertEqual(
            distro.parse_states(out, ["bluez", "bluez-obexd"], "fedora"), {"bluez": True, "bluez-obexd": False}
        )

    def test_features_and_ssh(self):
        with fedora(), mock.patch.object(distro.shutil, "which", lambda n: "/usr/bin/" + n):
            self.assertEqual(features.packages_for(features.BY_KEY["bluetooth"]), ("bluez",))
            self.assertIn(
                "enable --now bluetooth.service", features.install_argv(["bluez"], features.BY_KEY["bluetooth"])[2]
            )
            self.assertEqual(control_ssh.install_argv()[-1], "openssh-server")
            self.assertTrue(distro.can_install())

    def test_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            mark = Path(d, "ostree-booted")
            with mock.patch.dict(os.environ, {"TVWCS_OSTREE": str(mark)}):
                self.assertFalse(distro.atomic())
                mark.write_text("")
                self.assertTrue(distro.atomic())


class DnfUpdatesTests(unittest.TestCase):
    DNF5 = """Updating and loading repositories:
Repositories loaded.
bash.x86_64                     5.2.37-1.fc43        updates
kernel-core.x86_64              6.17.7-300.fc43      updates
python3-gobject.x86_64          3.54.5-1.fc43        updates
tzdata.noarch                   2025c-1.fc43         updates
Obsoleting packages
grub2-tools.x86_64              1:2.12-40.fc43       updates
    grub2-tools-efi.x86_64      1:2.12-39.fc43       @System
"""
    DNF4 = """Last metadata expiration check: 0:12:01 ago on Tue 04 Nov 2026 10:00:00 GMT.

firefox.x86_64                     145.0-1.fc42                     updates
"""

    def test_parse(self):
        found = upd.parse_dnf(self.DNF5)
        self.assertEqual([u.name for u in found], ["bash", "kernel-core", "python3-gobject", "tzdata"])
        self.assertEqual((found[0].new, found[0].source), ("5.2.37-1.fc43", "updates"))
        self.assertEqual([(u.name, u.new) for u in upd.parse_dnf(self.DNF4)], [("firefox", "145.0-1.fc42")])
        self.assertEqual(upd.parse_dnf(""), [])

    def test_manager(self):
        m = next(m for m in upd.MANAGERS if m.id == "dnf")
        self.assertIn(100, m.ok_codes)
        self.assertEqual(m.install_argv[:3], ("dnf", "upgrade", "-y"))
        self.assertTrue(m.refresh_argv)
        self.assertFalse(m.step_argv)

    def test_family_picks_its_own_manager(self):
        with fedora():
            self.assertEqual(upd.detect(which=lambda c: "/usr/bin/" + c if c in ("dnf", "apt-get") else None).id, "dnf")

    def test_atomic_is_left_to_rpm_ostree(self):
        with (
            tempfile.TemporaryDirectory() as d,
            fedora(),
            mock.patch.dict(os.environ, {"TVWCS_OSTREE": str(Path(d, "booted"))}),
        ):
            Path(d, "booted").write_text("")
            with mock.patch.object(upd, "have", lambda c, **_k: c == "dnf"):
                s = upd.read_state()
            self.assertFalse(s.available)
            self.assertIn("rpm-ostree", s.message)

    def test_reboot_from_needs_restarting(self):
        from tvwcs.control_cmd import Result

        exists = lambda p: p in ("/usr/lib/modules", "/usr/lib/modules/6.1")
        for code, want in ((1, True), (0, False)):
            with mock.patch.object(upd, "run", lambda argv, timeout=0, code=code: Result(code == 0, code, "", "")):
                self.assertEqual(upd.reboot_needed("6.1", exists=exists, dnf=True), want)
        with mock.patch.object(
            upd, "run", lambda argv, timeout=0: Result(False, 127, "", "")
        ):  # no plugin: the kernel's modules decide
            self.assertFalse(upd.reboot_needed("6.1", exists=exists, dnf=True))


class RpmSelfUpdateTests(unittest.TestCase):
    def rel(self, names):
        return selfupdate.release_from_json(
            {
                "tag_name": "v5.15.0",
                "assets": [{"name": n, "browser_download_url": "https://example/" + n} for n in names],
            }
        )

    def test_release_has_the_rpm(self):
        r = self.rel(("tvwcs_5.15.0_all.deb", "tvwcs-5.15.0-1.noarch.rpm", "tvwcs-5.15.0-src.tar.gz"))
        self.assertEqual(r.rpm, "https://example/tvwcs-5.15.0-1.noarch.rpm")
        self.assertEqual(self.rel(("tvwcs_5.15.0_all.deb",)).rpm, "")

    def test_a_release_without_an_rpm_is_not_installed_on_fedora(self):
        with self.assertRaises(UpdateError):
            selfupdate.download(Release("5.14.1", "v5.14.1", {"tvwcs": "x"}, ""), ["tvwcs"], kind="fedora")

    def test_download_checks_it_is_an_rpm(self):
        r = Release("5.15.0", "v5.15.0", {"tvwcs": "d"}, "", rpm="https://example/r")
        with mock.patch.object(selfupdate, "_download", lambda _u, t: Path(t).write_bytes(b"\xed\xab\xee\xdbrest")):
            folder, files = selfupdate.download(r, ["tvwcs"], kind="fedora")
        try:
            self.assertEqual([f.name for f in files], ["tvwcs-5.15.0-1.noarch.rpm"])
            self.assertEqual(oct(files[0].stat().st_mode & 0o777), "0o644")
        finally:
            selfupdate.discard(folder)
        with mock.patch.object(selfupdate, "_download", lambda _u, t: Path(t).write_bytes(b"<html>")):
            with self.assertRaises(UpdateError):
                selfupdate.download(r, ["tvwcs"], kind="fedora")

    def test_install_upgrade_downgrade_reinstall(self):
        f = ["/tmp/x/tvwcs-5.15.0-1.noarch.rpm"]
        self.assertEqual(
            selfupdate.install_argv(f, kind="fedora", current="5.14.1", version="5.15.0"), ["dnf", "install", "-y", *f]
        )
        self.assertEqual(selfupdate.install_argv(f, kind="fedora", current="5.16.0", version="5.15.0")[1], "downgrade")
        self.assertEqual(selfupdate.install_argv(f, kind="fedora", current="5.15.0", version="5.15.0")[1], "reinstall")
        self.assertEqual(
            selfupdate.install_argv(["a.deb"], kind="")[:4],
            ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install"],
        )

    def test_only_arch_builds_itself(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(selfupdate.builds_itself(d))
            Path(d, "PACKAGE").write_text("fedora\n")
            self.assertFalse(selfupdate.builds_itself(d))
            self.assertEqual(selfupdate.other_package(d), "fedora")
            Path(d, "PACKAGE").write_text("arch\n")
            self.assertTrue(selfupdate.builds_itself(d))

    def test_installed_from_rpm(self):
        class Done:
            stdout = "tvwcs\n"

        self.assertEqual(selfupdate.installed_packages(lambda *a, **k: Done(), kind="fedora"), ["tvwcs"])

        class Missing:
            stdout = "package tvwcs is not installed\n"

        self.assertEqual(selfupdate.installed_packages(lambda *a, **k: Missing(), kind="fedora"), [])


class FedoraGreetdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"TVWCS_ROOT": str(self.root), "TVWCS_FAMILY": "fedora"})
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

    def test_greetd_uses_fedora_user_and_agreety(self):
        self.c.use_greetd("tv")
        cfg = loginscreen.greetd_config()
        self.assertEqual(cfg["default_session"]["user"], "greetd")
        self.assertEqual(str(cfg["terminal"]["vt"]), "1")
        self.assertTrue(cfg["default_session"]["command"].startswith("/usr/bin/agreety --cmd "))
        self.assertFalse((self.root / "etc" / "X11" / "default-display-manager").exists())

    def test_root_command_installs_with_dnf(self):
        argv = loginscreen.root_command(["greetd", "tv"], ("greetd",))
        self.assertIn("dnf install -y $packages", argv[2])


class SpecTests(unittest.TestCase):
    """The .rpm's spec: its removal script matches the Arch package's (only on removal, not on upgrade)."""

    spec = (REPO / "packaging" / "fedora" / "tvwcs.spec.in").read_text()

    def section(self, name):
        m = re.search(rf"^%{name}\n(.*?)(?=^%[a-z]+\b)", self.spec, re.S | re.M)
        return m.group(1) if m else ""

    def test_preun_only_on_removal(self):
        body = self.section("preun")
        self.assertIn('[ "$1" -eq 0 ] || exit 0', body)

    def test_preun_takes_only_tvwcs_out_of_greetd(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d, "etc", "greetd", "config.toml")
            conf.parent.mkdir(parents=True)
            conf.write_text(
                '[terminal]\nvt = 2\n\n[default_session]\ncommand = "tuigreet --cmd sway"\nuser = "greetd"\n\n'
                '[initial_session]\ncommand = "/usr/bin/tvwcs-session"\nuser = "tv"\n'
            )
            script = self.section("preun")
            for real in ("/etc/", "/run/"):
                script = script.replace(real, f"{d}{real}")
            subprocess.run(["sh", "-c", script, "preun", "0"], check=True, capture_output=True)
            out = conf.read_text()
            self.assertIn('command = "tuigreet --cmd sway"', out)
            self.assertNotIn("initial_session", out)
            conf.write_text('[initial_session]\ncommand = "/usr/bin/tvwcs-session"\nuser = "tv"\n')
            subprocess.run(
                ["sh", "-c", script, "preun", "1"], check=True, capture_output=True
            )  # an upgrade changes nothing
            self.assertIn("initial_session", conf.read_text())

    def test_requires_are_fedora_names(self):
        req = " ".join(re.findall(r"^Requires:\s*(.+)$", self.spec, re.M))
        for name in ("sway", "gtk4", "python3-gobject", "pulseaudio-utils", "NetworkManager", "polkit", "sudo"):
            self.assertIn(name, req.split())
        self.assertIn("echo fedora", self.spec)


if __name__ == "__main__":
    unittest.main()
