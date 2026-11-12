import unittest
from tvwcs.settings import network as net

# /etc/network/interfaces as Debian's installer writes it (the HTPC's)
INTERFACES = """# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

source /etc/network/interfaces.d/*

# The loopback network interface
auto lo
iface lo inet loopback

# The primary network interface
allow-hotplug enp1s0
iface enp1s0 inet dhcp
"""
NM_CONF = "[main]\nplugins=ifupdown,keyfile\n\n[ifupdown]\nmanaged=false\n"


class IfupdownTests(unittest.TestCase):
    def test_hand_over_uninstalls_ifupdown_and_removes_its_folder(self):
        argv = net.take_over_argv("wlp2s0", "ifupdown")
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertEqual(argv[-1], "wlp2s0")
        self.assertIn("apt-get purge -y ifupdown", argv[2])
        self.assertIn("rm -rf /etc/network\n", argv[2])
        self.assertIn("systemctl restart NetworkManager", argv[2])
        self.assertLess(argv[2].index("apt-get purge"), argv[2].index("rm -rf"))
        self.assertNotIn("apt-get", net.take_over_argv("enp1s0", "config")[2])
        with self.assertRaises(ValueError):
            net.take_over_argv("wl;rm", "ifupdown")

    def test_reason_is_ifupdown_only_where_network_manager_ignores_it(self):
        import os, tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "nm.conf")
            open(conf, "w").write(NM_CONF)
            ifaces = os.path.join(d, "interfaces")
            open(ifaces, "w").write(INTERFACES)
            os.chmod(ifaces, 0o600)
            with (
                mock.patch.object(net, "NM_CONF", conf),
                mock.patch.object(net, "INTERFACES", ifaces),
                mock.patch.object(net, "have", lambda c: True),
                mock.patch.object(net, "NETWORKD_RUN", d),
            ):  # not this computer's own (a CI runner's netplan uses systemd-networkd)
                self.assertEqual(net.unmanaged_reason("wlp2s0"), "ifupdown")
                open(conf, "w").write("[main]\nplugins=keyfile\n")
                self.assertEqual(net.unmanaged_reason("wlp2s0"), "config")

    def test_reason_is_netplan_where_it_gives_the_ports_to_networkd(self):
        import os, tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            run = os.path.join(d, "network")
            os.mkdir(run)
            with (
                mock.patch.object(net, "NETWORKD_RUN", run),
                mock.patch.object(net, "INTERFACES", os.path.join(d, "none")),
                mock.patch.object(net, "have", lambda c: True),
            ):
                self.assertEqual(net.unmanaged_reason("enp1s0"), "config")
                open(os.path.join(run, "10-netplan-enp1s0.network"), "w").write("[Match]\nName=enp1s0\n")
                self.assertEqual(net.unmanaged_reason("enp1s0"), "netplan")
            with (
                mock.patch.object(net, "NETWORKD_RUN", run),
                mock.patch.object(net, "INTERFACES", os.path.join(d, "none")),
                mock.patch.object(net, "have", lambda c: c != "netplan"),
            ):
                self.assertEqual(net.unmanaged_reason("enp1s0"), "config")

    def test_netplan_hand_over_sets_the_renderer_and_can_go_back(self):
        script = net.take_over_argv("enp1s0", "netplan")[2]
        self.assertIn("renderer: NetworkManager\\n' > /etc/netplan/90-tvwcs-network-manager.yaml", script)
        self.assertIn('cp -a /etc/netplan/. "$backup"/', script)
        self.assertLess(script.index("netplan generate || undo"), script.index("netplan apply || undo"))
        self.assertNotIn("apt-get", script)
        self.assertIn("systemctl mask --now systemd-networkd.service", script)  # its other sockets would start it again
        self.assertLess(
            script.index("rm -f /run/systemd/network/zzzz-dracut-default.network"), script.index("systemctl mask")
        )

    def test_network_manager_ignores_ifupdown(self):
        self.assertTrue(net.ifupdown_ignored(NM_CONF))
        self.assertFalse(net.ifupdown_ignored(NM_CONF.replace("managed=false", "managed=true")))
        self.assertFalse(net.ifupdown_ignored("[main]\nplugins=keyfile\n"))


if __name__ == "__main__":
    unittest.main()
