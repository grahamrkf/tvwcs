"""Settings > System information: the computer, TVWCS's version and SSH. Back ends: settings/sysinfo.py, settings/ssh.py."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

from tvwcs.settings import ssh, sysinfo
from tvwcs.system import servermode
from tvwcs.core.model import ConfigStore
from tvwcs.settings.pages.base import Page


# ====================================================================== System information
class SystemPage(Page):
    key = "system"
    title = "System information"
    icon = "computer-symbolic"
    fallback = "🖥"

    def read(self):
        return sysinfo.read_sections(), ssh.read_state()

    def summary(self):
        return ""

    def draw(self, state):
        sections, remote = state
        displays = self.displays()
        if displays:
            sections = sections[:2] + [("DISPLAYS", displays)] + sections[2:]
        for title, rows in sections:
            self.section(title)
            for i, (label, value) in enumerate(rows):
                self.row(label, value, None, ident=f"{title}:{label}:{i}")
        self.draw_ssh(remote)

    # ---------------------------------------------------------- SSH: signing in to this computer from another one
    def draw_ssh(self, s):
        self.section("REMOTE ACCESS (SSH)")
        admin = not servermode.active()  # server mode: shown, not changed here
        if not s.installed:
            self.row(
                "SSH server",
                "Not installed",
                self.install_ssh if admin and ssh.install_argv() else None,
                detail="Install it to sign in to this computer from another one" if admin else "",
                ident="ssh:server",
            )
            return
        self.row(
            "SSH server",
            "On" if s.active else "Off",
            (lambda: self.switch_ssh(s)) if admin else None,
            detail=(
                ("Starts with the computer" if s.enabled else "Stopped at the next restart")
                if s.active
                else ("Starts with the computer" if s.enabled else "Turn it on to sign in from another computer")
            ),
            ident="ssh:server",
            value_css="state-on" if s.active else "setting-value",
        )
        self.row(
            "Sign in with",
            "Keys only" if not s.passwords else "Password or key",
            (lambda: self.choose_sign_in(s)) if admin else None,
            detail=f"{s.keys} key{'s' if s.keys!=1 else ''} added for {s.user}",
            ident="ssh:auth",
        )
        if s.passwords and s.active and ConfigStore().settings["password_keyboard"] == "digits":
            self.note(
                "Your password keyboard is the number pad, so your password may be only digits, which is easy to guess. "
                "Keys only is recommended: then nobody can sign in over the network with a password.",
                "error",
            )
        self.row("Connect with", f"ssh {s.user}@{s.address}", None, ident="ssh:command")
        self.row("User", s.user, None, ident="ssh:user")
        self.row(
            "Local name",
            s.local_name if s.mdns else f"{s.local_name} (not announced)",
            None,
            detail="" if s.mdns else "Install avahi-daemon to reach this computer by name",
            ident="ssh:name",
        )
        for i, (iface, address) in enumerate(s.addresses):
            self.row("IP address" if i == 0 else "", address, None, detail=iface, ident=f"ssh:ip:{i}")
        if not s.addresses:
            self.row("IP address", "Not connected to a network", None, ident="ssh:ip:0")

    def as_root(self, argv, label, status):
        """Run one of settings.ssh's commands as root, then read the page again; its output is shown if it fails."""
        self.set_status(status)
        lines = []

        def done(code, tail):
            self.set_status("")
            if code:
                self.win.notice("SSH", ("\n".join(lines[-6:]) or tail or f"{label} did not work.").strip())
            self.refresh(quiet=True)

        self.win.run_as_root(argv, label, lines.append, done)

    def install_ssh(self):
        self.win.confirm(
            "Install the SSH server?",
            "This installs OpenSSH's server with the package manager. Turn it on here afterwards.",
            "Install",
            lambda: self.as_root(ssh.install_argv(), "Installing the SSH server", "Installing the SSH server…"),
            danger=False,
        )

    def switch_ssh(self, s):
        if not s.unit:
            self.win.notice(
                "SSH", "The SSH server has no systemd service here (ssh), so Settings cannot start or stop it."
            )
            return
        if s.active:
            self.win.confirm(
                "Turn SSH off?",
                "Nobody can sign in from another computer until it is turned on again. "
                "Connections open now stay open.",
                "Turn off",
                lambda: self.as_root(ssh.service_argv(s, False), "Turning SSH off", "Turning SSH off…"),
            )
        else:
            self.as_root(ssh.service_argv(s, True), "Turning SSH on", "Turning SSH on…")

    def choose_sign_in(self, s):
        def picked(key):
            allow = key == "password"
            if allow == s.passwords:
                return
            if not allow:
                problem = ssh.key_only_problem(s)
                if problem:
                    self.win.notice("Keys only", problem)
                    return
            self.as_root(ssh.passwords_argv(s, allow), "Changing how SSH signs in", "Changing how SSH signs in…")

        self.win.choose_option(
            "Sign in with",
            [
                ("password", "Password or key"),
                ("keys", f"Keys only (safer; {s.keys} key{'s' if s.keys!=1 else ''} added)"),
            ],
            "password" if s.passwords else "keys",
            picked,
        )

    def displays(self):
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None
        rows = []
        for i in range(monitors.get_n_items() if monitors is not None else 0):
            m = monitors.get_item(i)
            g = m.get_geometry()
            f = max(1, m.get_scale_factor())
            hz = m.get_refresh_rate() / 1000 if m.get_refresh_rate() else 0
            name = " ".join(
                x for x in ((m.get_manufacturer() or ""), (m.get_model() or "")) if x and x != "Unknown"
            ).strip() or (m.get_connector() or f"Display {i+1}")
            rows.append((name, f"{g.width*f} × {g.height*f}" + (f" at {hz:.0f} Hz" if hz else "")))
        return rows
