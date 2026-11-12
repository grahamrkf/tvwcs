"""The Settings app's SSH section without an SSH server: reading sshd_config as sshd does, counting keys, and the
commands it would run, including that keys only is refused when it would lock everyone out."""

import subprocess, tempfile, unittest
from pathlib import Path

from tvwcs import control_ssh as ssh, control_sysinfo as info

DEBIAN = (
    "Include /etc/ssh/sshd_config.d/*.conf\n#PasswordAuthentication yes\nKbdInteractiveAuthentication no\nUsePAM yes\n"
)


class SshConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "sshd_config.d").mkdir()

    def config(self, text):
        (self.dir / "sshd_config").write_text(text.replace("/etc/ssh", str(self.dir)))

    def test_debian_default_allows_passwords_and_reads_the_drop_ins_first(self):
        self.config(DEBIAN)
        self.assertEqual(ssh.read_auth(self.dir), (True, True))

    def test_the_first_value_wins_and_drop_ins_count_where_they_are_included(self):
        self.config(DEBIAN)
        (self.dir / "sshd_config.d" / "00-tvwcs.conf").write_text(
            "PasswordAuthentication no\nKbdInteractiveAuthentication no\n"
        )
        (self.dir / "sshd_config.d" / "50-cloud-init.conf").write_text("PasswordAuthentication yes\n")
        self.assertEqual(ssh.read_auth(self.dir), (False, True))

    def test_keyboard_interactive_still_takes_passwords(self):
        self.config("PasswordAuthentication no\n")
        self.assertEqual(ssh.read_auth(self.dir), (True, False))  # OpenSSH's default is yes

    def test_drop_ins_included_after_the_setting_cannot_change_it(self):
        self.config("PasswordAuthentication yes\nInclude sshd_config.d/*.conf\n")
        self.assertEqual(ssh.read_auth(self.dir), (True, False))

    def test_settings_after_match_are_ignored(self):
        self.config(
            "Include /etc/ssh/sshd_config.d/*.conf\nKbdInteractiveAuthentication no\nMatch User guest\n  PasswordAuthentication no\n"
        )
        self.assertTrue(ssh.read_auth(self.dir)[0])

    def test_counts_keys_with_or_without_options(self):
        home = self.dir / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "authorized_keys").write_text(
            '# mine\nssh-ed25519 AAAA laptop\nfrom="10.0.0.0/8" ecdsa-sha2-nistp256 AAAA phone\n\nnonsense\n'
        )
        self.assertEqual(ssh.count_keys(home), 2)
        self.assertEqual(ssh.count_keys(self.dir / "nobody"), 0)

    def test_addresses_of_the_network_cards(self):
        text = (
            '[{"ifname":"lo","link_type":"loopback","flags":["UP"],"addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8}]},'
            '{"ifname":"enp3s0","link_type":"ether","flags":["UP","LOWER_UP"],"addr_info":[{"family":"inet","local":"192.168.1.20","prefixlen":24}]}]'
        )
        self.assertEqual(ssh.parse_addresses(text, physical=lambda _n: True), [("enp3s0", "192.168.1.20")])

    def test_unit_state(self):
        self.assertEqual(
            ssh.parse_unit("LoadState=loaded\nUnitFileState=enabled\nActiveState=active\n"), (True, True, True)
        )
        self.assertEqual(
            ssh.parse_unit("LoadState=not-found\nUnitFileState=\nActiveState=inactive\n"), (False, False, False)
        )


class SshCommandTests(unittest.TestCase):
    def state(self, **kw):
        return ssh.SshState(
            **{
                "installed": True,
                "unit": "ssh",
                "enabled": True,
                "active": True,
                "dropins": True,
                "keys": 1,
                "user": "tv",
                "hostname": "livingroom",
                "mdns": True,
                "addresses": [("eth0", "192.168.1.20")],
                **kw,
            }
        )

    def test_keys_only_is_refused_without_a_key_or_a_drop_in_folder(self):
        self.assertEqual(ssh.key_only_problem(self.state()), "")
        self.assertIn("ssh-copy-id tv@livingroom.local", ssh.key_only_problem(self.state(keys=0)))
        self.assertIn("does not read", ssh.key_only_problem(self.state(dropins=False)))

    def test_address_falls_back_to_the_ip_without_avahi(self):
        self.assertEqual(self.state().address, "livingroom.local")
        self.assertEqual(self.state(mdns=False).address, "192.168.1.20")

    def test_service_commands(self):
        self.assertEqual(ssh.service_argv(self.state(), True), ["systemctl", "enable", "--now", "ssh.service"])
        self.assertEqual(
            ssh.service_argv(self.state(), False), ["systemctl", "disable", "--now", "ssh.service", "ssh.socket"]
        )
        self.assertEqual(
            ssh.service_argv(self.state(unit="sshd"), False), ["systemctl", "disable", "--now", "sshd.service"]
        )
        self.assertIsNone(ssh.service_argv(self.state(unit=""), True))

    def test_drop_in_is_written_checked_and_undone_when_sshd_rejects_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "sshd-ok"
            good.write_text("#!/bin/sh\nexit 0\n")
            good.chmod(0o755)
            bad = Path(tmp) / "sshd-bad"
            bad.write_text("#!/bin/sh\nexit 1\n")
            bad.chmod(0o755)
            argv = ssh.passwords_argv(self.state(active=False), False, ssh_dir=Path(tmp))
            dropin = Path(tmp) / "sshd_config.d" / ssh.DROPIN_NAME
            self.assertEqual(subprocess.run(argv[:-1] + [str(good)]).returncode, 0)
            self.assertIn("PasswordAuthentication no\nKbdInteractiveAuthentication no\n", dropin.read_text())
            r = subprocess.run(
                ssh.passwords_argv(self.state(active=False), True, ssh_dir=Path(tmp))[:-1] + [str(bad)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 1)
            self.assertFalse(dropin.exists())
            self.assertIn("undone", r.stderr)


class DriveTests(unittest.TestCase):
    def test_drives_in_use(self):
        mounts = (
            "/dev/nvme0n1p2 / ext4 rw 0 0\nproc /proc proc rw 0 0\n/dev/nvme0n1p1 /boot/efi vfat rw 0 0\n"
            "/dev/loop3 /snap/core squashfs ro 0 0\n/dev/sda1 /media/tv/USB\\040Stick vfat rw 0 0\n/dev/nvme0n1p2 /var/lib/docker ext4 rw 0 0\n"
        )
        self.assertEqual(
            info.parse_mounts(mounts),
            [("/dev/nvme0n1p2", "/"), ("/dev/nvme0n1p1", "/boot/efi"), ("/dev/sda1", "/media/tv/USB Stick")],
        )

    def test_graphics_from_the_kernel_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            drv = Path(tmp) / "drivers" / "i915"
            drv.mkdir(parents=True)
            dev = Path(tmp) / "drm" / "card0" / "device"
            dev.mkdir(parents=True)
            (dev / "driver").symlink_to(drv)
            (Path(tmp) / "drm" / "card0-HDMI-A-1").mkdir()
            self.assertEqual(info.drm_gpus(str(Path(tmp) / "drm")), ["Intel (i915 driver)"])


if __name__ == "__main__":
    unittest.main()
