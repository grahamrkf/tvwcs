"""Settings > Software updates: the system's updates and TVWCS's own. Back ends: settings/updates.py, system/selfupdate.py."""

from __future__ import annotations
import os, time
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from tvwcs.settings import ubuntu, updates
from tvwcs import __version__
from tvwcs.system import privilege, selfupdate
from tvwcs.core.model import ConfigStore
from tvwcs.system.system_actions import command_for
from tvwcs.settings.app import StreamedRun, in_background
from tvwcs.ui.widgets import S
from tvwcs.settings.pages.base import Page, _on_off, tell_tvwcs


# ====================================================================== TVWCS's own updates (on the Software updates page)
class _SelfUpdate:
    """TVWCS updates: a newer release from GitHub (or a vendor's release list), prereleases, and the way back to the
    latest release. Shown only when TVWCS's package turns its updater on (vendor.py): TVWCS packaged by a distribution
    is updated with the rest of the system."""

    update_text = ""
    updating = False

    def draw_self_update(self):
        updates = selfupdate.source()
        if not selfupdate.self_updates(updates):
            vendor = ConfigStore().vendor
            if updates.source == "system":
                self.section("TVWCS")
                self.row(
                    "TVWCS",
                    f"Version {__version__}",
                    None,
                    ident="opt:update",
                    icon="view-refresh-symbolic",
                    fallback="⟳",
                )
                self.note(
                    (
                        "This copy runs from a source checkout: update it with git pull."
                        if not selfupdate.packaged()
                        else f"TVWCS is updated with this system's other software{' from '+vendor.name if vendor.name else ''}: Check for updates below installs a new version with the rest."
                    )
                )
            return
        self.section("TVWCS UPDATES")
        self.row(
            "Check for TVWCS updates",
            self.update_text or f"Version {__version__}",
            None if self.updating else self.check_updates,
            ident="opt:update",
            icon="view-refresh-symbolic",
            fallback="⟳",
        )
        if selfupdate.builds_itself():
            self.note(
                f"Looks for a newer release of TVWCS on {selfupdate.where(updates)}. This copy was built from TVWCS's "
                "Arch package: install a new release by running TVWCS's installer again in a terminal (or with makepkg -si, as in docs/INSTALL-ARCH.md)."
            )
            return
        self.note(f"Looks for a newer release of TVWCS on {selfupdate.where(updates)} and offers to install it.")
        pre = ConfigStore().settings["update_prereleases"]
        self.row("Include prereleases", _on_off(pre), self.toggle_prereleases, ident="opt:update_prereleases")
        self.note(
            "Every change is released as a prerelease first, and marked as the latest release once it has been tested "
            "on a TV computer. On: Check for TVWCS updates offers prereleases too."
        )
        self.row("Roll back to the latest release", "", None if self.updating else self.roll_back, ident="opt:rollback")
        self.note(
            "Installs the release marked latest, even when it is older than this version: the way back from a prerelease."
        )

    def toggle_prereleases(self):
        store = ConfigStore()
        store.settings["update_prereleases"] = not store.settings["update_prereleases"]
        store.save()
        tell_tvwcs("reload")
        self.redraw()

    def check_updates(self):
        self.updating = True
        self.update_text = "Checking…"
        self.redraw()

        def failed(exc):
            self.updating = False
            self.update_text = "Check failed"
            self.redraw()
            self.win.notice("TVWCS updates", f"Could not check for updates: {exc}")

        prereleases = bool(ConfigStore().settings["update_prereleases"]) and not selfupdate.builds_itself()
        in_background(lambda: selfupdate.latest_release(prereleases), self.checked, failed)

    def roll_back(self):
        self.updating = True
        self.update_text = "Checking…"
        self.redraw()

        def failed(exc):
            self.updating = False
            self.update_text = "Check failed"
            self.redraw()
            self.win.notice("TVWCS updates", f"Could not check for updates: {exc}")

        def found(release):
            self.updating = False
            self.update_text = ""
            self.redraw()
            if selfupdate.parse_version(release.version) == selfupdate.parse_version(__version__):
                self.win.notice("TVWCS updates", f"This is already the latest release, TVWCS {__version__}.")
                return
            if not selfupdate.packaged():
                self.win.notice("TVWCS updates", "This copy runs from a source checkout: change its version with git.")
                return
            self.win.confirm(
                "Roll back TVWCS?",
                f"Install TVWCS {release.version}, the latest release, in place of {__version__}? It asks for your password. "
                "TVWCS restarts afterwards; your channels, favorites, options and hotkeys are kept.",
                "Install " + release.version,
                lambda: self.install(release),
                danger=False,
            )

        in_background(selfupdate.latest_release, found, failed)

    def checked(self, release):
        self.updating = False
        if not selfupdate.is_newer(release.version, __version__):
            self.update_text = f"Up to date ({__version__})"
            self.redraw()
            return
        self.update_text = f"{release.version} available"
        self.redraw()
        if selfupdate.builds_itself():
            self.win.notice(
                "TVWCS updates",
                f"TVWCS {release.version} is available (you have {__version__}). Install it by running TVWCS's "
                f"installer again in a terminal:\n\ncurl -fsSL {selfupdate.installer_url()} | bash",
            )
            return
        if not selfupdate.packaged():
            self.win.notice(
                "TVWCS updates",
                f"TVWCS {release.version} is available. This copy runs from a source checkout: update it with git pull.",
            )
            return
        kind = " prerelease" if release.prerelease else ""
        self.win.confirm(
            "Update TVWCS?",
            f"TVWCS {release.version}{kind} is available (you have {__version__}). Download and install it now? "
            "It asks for your password. TVWCS restarts afterwards; your channels, favorites, options and hotkeys are kept.",
            "Install update",
            lambda: self.install(release),
            danger=False,
        )

    def install(self, release):
        """Download the release's packages (those installed here), then install them as root with apt (or dnf)."""
        self.updating = True
        self.update_text = "Downloading…"
        self.redraw()

        def failed(exc):
            self.updating = False
            self.update_text = "Update failed"
            self.redraw()
            self.win.notice("TVWCS updates", f"The update failed: {exc}")

        def downloaded(result):
            folder, files = result
            lines = []
            self.update_text = "Installing…"
            self.redraw()

            def done(code, tail):
                selfupdate.discard(folder)
                self.updating = False
                if code:
                    self.update_text = "Update failed"
                    self.redraw()
                    self.win.notice(
                        "TVWCS updates",
                        "The update failed:\n"
                        + ("\n".join(lines[-4:]) or tail or "The package manager did not finish.").strip(),
                    )
                    return
                self.update_text = f"Installed {release.version}"
                self.redraw()
                restarted = tell_tvwcs("restart /usr/bin/tvwcs")
                self.win.notice(
                    "TVWCS updated",
                    f"TVWCS {release.version} is installed"
                    + (" and has restarted." if restarted else ".")
                    + " Close Settings and open it again to use the new version.",
                )

            self.win.run_as_root(
                selfupdate.install_argv(files, current=__version__, version=release.version),
                "Installing TVWCS " + release.version,
                lines.append,
                done,
            )

        in_background(lambda: selfupdate.download(release, selfupdate.installed_packages()), downloaded, failed)


# ====================================================================== Software updates
class _Console:
    """A read-only console under a page's rows, showing the output of what the page runs."""

    def console(self):
        if self.log is None:
            self.log = Gtk.TextView()
            self.log.set_editable(False)
            self.log.set_cursor_visible(False)
            self.log.set_focusable(False)
            self.log.add_css_class("console")
            self.log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.log.set_monospace(True)
            self.log_scroll = Gtk.ScrolledWindow()
            self.log_scroll.set_child(self.log)
            self.log_scroll.set_min_content_height(S(280))
            self.log_scroll.add_css_class("console-frame")
            self.log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        if self.log_scroll.get_parent() is not None:
            self.log_scroll.get_parent().remove(self.log_scroll)
        return self.log_scroll

    def _append(self, line):
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")
        if buf.get_line_count() > 2000:
            buf.delete(buf.get_start_iter(), buf.get_iter_at_line(buf.get_line_count() - 2000)[1])
        GLib.idle_add(
            lambda: (
                self.log_scroll.get_vadjustment().set_value(self.log_scroll.get_vadjustment().get_upper()),
                GLib.SOURCE_REMOVE,
            )[1]
        )


class UpdatesPage(_SelfUpdate, _Console, Page):
    """TVWCS's own updates, then the system's packages."""

    key = "updates"
    title = "Software updates"
    icon = "software-update-available-symbolic"
    fallback = "⇩"
    server_off = True
    MAX_ROWS = 300

    def __init__(self, win):
        super().__init__(win)
        self.running = None
        self.log = None
        self.fetched = None
        self.asker = "pacman"
        self.echo = None
        self.finished = None
        self.outcome = None  # the run that just ended, until the page is read again; then what came of it

    def read(self):
        state = updates.read_state()
        state.reboot = updates.reboot_needed()
        state.extras = ubuntu.installed_extras()
        state.news = []
        state.pacnew = []
        state.news_unknown = False
        if (
            state.manager is not None and state.manager.id == "pacman"
        ):  # Arch: its news since the last full upgrade, and .pacnew files
            items = updates.read_news()
            state.news_unknown = items is None
            state.news = updates.news_since(items or [], updates.last_upgrade())
            state.pacnew = updates.pacnew_files()
        if self.fetched and (state.checked or 0) < self.fetched:
            state.checked = self.fetched  # unchanged lists keep their old date
        return state

    def summary(self):
        s = self.state
        if not s or not s.available or s.manager is None:
            return ""
        age = updates.age_text(s.checked)
        return s.manager.label + (f" · package lists from {age}" if age else "")

    def draw(self, s):
        if self.running:
            self.row(
                self.running, "Working…", None, icon="emblem-synchronizing-symbolic", fallback="⟳", ident="running"
            )
            self.note("Leave this running until it finishes. Settings can be closed; the update carries on.")
            self.add(self.console())
            return
        self.draw_self_update()
        self.section("SYSTEM")
        if not s.available:
            self.note(s.message)
            return
        self.row(
            "Check for updates",
            f"{s.all_total} available" if s.all_total else "Up to date",
            self.refresh,
            ident="check",
            icon="view-refresh-symbolic",
            fallback="⟳",
        )
        m = s.manager
        if m is not None and m.refresh_argv:
            self.row(
                "Download the latest package lists",
                "",
                lambda: self.run_steps("Downloading package lists", [(list(m.refresh_argv), True)], fetch=True),
                detail="Asks for your password, then checks again.",
                icon="folder-download-symbolic",
                fallback="⇩",
                ident="lists",
            )
        if s.total:
            self.row(
                f"Install {s.total} update{'s' if s.total!=1 else ''}",
                "",
                self.confirm_install,
                ident="install",
                detail="Installs everything listed below." + (" Asks for your password." if s.updates else ""),
                icon="software-update-available-symbolic",
                fallback="⇩",
            )
        if m is not None and m.step_argv and s.total:
            self.row(
                "Update step by step",
                "",
                self.confirm_step_by_step,
                ident="step",
                detail="Installs them showing each question pacman asks, with buttons to answer it.",
                icon="dialog-question-symbolic",
                fallback="?",
            )
        if m is not None and m.id == "pacman":
            where = (
                ", below."
                if getattr(s, "news", [])
                else (
                    " (archlinux.org/news), which has nothing new since your last update."
                    if not getattr(s, "news_unknown", False)
                    else " (archlinux.org/news)."
                )
            )
            self.note(
                "pacman updates everything at once, as Arch expects. Now and then an update needs a step by hand: Arch "
                "announces those in its news"
                + where
                + (
                    ""
                    if s.aur_helper
                    else " Packages from the AUR are not included: "
                    "with yay or paru installed, Settings updates them too."
                )
            )
            self.draw_arch_news(s)
            self.draw_aur(s)
        if getattr(s, "reboot", False):
            self.row(
                "Restart to finish updating",
                "",
                self.confirm_reboot,
                detail="Some updates are only used after a restart.",
                icon="system-reboot-symbolic",
                fallback="↻",
                ident="reboot",
            )
        for label, problem in s.problems:
            self.note(f"{label}: {problem}", "error")
        if self.finished:
            label, self.finished = self.finished, None
            self.outcome = self.outcome_text(label, s)
            self._append(f"\n✓ {self.outcome}")
            if (
                getattr(s, "reboot", False) and label != "Downloading package lists"
            ):  # say so now, not only in the row above
                GLib.idle_add(
                    lambda: (
                        self.confirm_reboot(
                            "Restart to finish updating?",
                            "Some of the updates (a new kernel, for "
                            "one) are only used after the computer restarts. Restart now? Unsaved work in open applications "
                            "may be lost.",
                            "Restart now",
                        ),
                        GLib.SOURCE_REMOVE,
                    )[1]
                )
        if self.outcome:
            self.note(self.outcome, "state-on")
        self.draw_pacnew(getattr(s, "pacnew", []))
        if self.log is not None and self.log.get_buffer().get_char_count():
            self.section("LAST RUN")
            self.add(self.console())
        self.draw_ubuntu_extras(getattr(s, "extras", []))
        for title, items in ((f"{m.label.upper()} PACKAGES" if m else "PACKAGES", s.updates),):
            if not items:
                continue
            self.section(f"{title} ({len(items)})")
            for u in items[: self.MAX_ROWS]:
                self.row(
                    u.name,
                    f"{u.old} → {u.new}" if u.old else u.new,
                    lambda u=u: self.details(u),
                    detail=u.source,
                    ident=f"pkg:{title}:{u.name}",
                )
            if len(items) > self.MAX_ROWS:
                self.note(f"… and {len(items)-self.MAX_ROWS} more.")

    @staticmethod
    def outcome_text(label, s):
        """The line that says a run has finished and what it found, such as: Package lists downloaded at 23:05. Everything is up to date."""
        done = {
            "Downloading package lists": "Package lists downloaded",
            "Installing updates": "Updates installed",
            "Updating step by step": "Updates installed",
            "Updating AUR packages": "AUR packages updated",
        }.get(label, f"{label}: finished")
        n = getattr(s, "all_total", s.total)
        found = f"{n} update{'s' if n!=1 else ''} available." if n else "Everything is up to date."
        return f"{done} at {time.strftime('%H:%M')}. {found}"

    def details(self, u):
        lines = (
            [f"Version {u.new}"]
            + ([f"Installed now: {u.old}"] if u.old else [])
            + ([f"From: {u.source}"] if u.source else [])
        )
        self.win.notice(u.name, "\n".join(lines))

    def confirm_install(self):
        s = self.state
        parts = []
        if s.updates:
            parts.append(f"{len(s.updates)} package{'s' if len(s.updates)!=1 else ''} from {s.manager.label}")
        steps = []
        if s.updates:
            steps.append((list(s.manager.install_argv), True))
        self.win.confirm(
            "Install updates?",
            f"Install {' and '.join(parts)} now? Apps being updated may need to be restarted afterwards."
            + self.news_warning(),
            "Install",
            lambda: self.run_steps("Installing updates", steps),
            danger=False,
        )

    def news_warning(self):
        n = len(getattr(self.state, "news", []))
        return (
            f"\n\nArch has posted {'a news item' if n==1 else f'{n} news items'} since your last update (on this page). "
            "Read it first: it says when an update needs a step by hand."
            if n
            else ""
        )

    # -------------------------------------------------------------- Arch: step by step, its news, .pacnew files
    def confirm_step_by_step(self):
        self.win.confirm(
            "Update step by step?",
            "pacman installs the updates and stops at each question it asks (go ahead, replace a "
            "package, remove one that conflicts, choose between packages), with a button for each answer. Back answers No."
            + self.news_warning(),
            "Start",
            self.update_step_by_step,
            danger=False,
        )

    def update_step_by_step(self):
        m = self.state.manager
        self.asker = "pacman"
        self.run_steps("Updating step by step", [(list(m.step_argv), True)], prompts=True)

    def answer_prompt(self, run, question, before):
        p = updates.parse_prompt(question, before)
        if p is None:
            return
        if p.kind == "password":  # an AUR helper's sudo, reading from the pipe (--sudoflags=-S)
            self.win.ask_text(
                "Administrator password",
                "Installing the built packages needs administrator rights. Enter your password "
                "(the one sudo asks for). It is used once and never stored.",
                lambda pw: (self.win.close_modal(), run.send(pw)),
                secret=True,
                ok_label="Continue",
                back=lambda: (self.win.close_modal(), run.stop()),
            )
            return

        def answer(text):
            self._append(f"→ {text or '(default)'}")
            self.echo = text or None
            run.send(text)

        title = f"{self.asker} asks"
        if len(p.answers) > 4:  # a long choice between packages: a list
            self.win.choose_option(
                title,
                [(a, label) for label, a in p.answers],
                p.answers[0][1],
                answer,
                back=lambda: (self.win.close_modal(), answer(p.back)),
            )
        else:
            self.win.ask_choice(
                title, p.question, [(label, lambda a=a: answer(a)) for label, a in p.answers], lambda: answer(p.back)
            )

    def draw_aur(self, s):
        if not s.aur:
            return
        self.section(f"AUR PACKAGES ({len(s.aur)})")
        self.row(
            f"Update {len(s.aur)} AUR package{'s' if len(s.aur)!=1 else ''}",
            "",
            self.confirm_aur,
            ident="aur",
            detail=f"With {s.aur_helper}, step by step: it shows what changed in each package's build script first.",
            icon="software-update-available-symbolic",
            fallback="⇩",
        )
        for u in s.aur[: self.MAX_ROWS]:
            self.row(
                u.name,
                f"{u.old} → {u.new}" if u.old else u.new,
                lambda u=u: self.details(u),
                detail="AUR",
                ident=f"aurpkg:{u.name}",
            )

    def confirm_aur(self):
        h = self.state.aur_helper
        n = len(self.state.aur)
        self.win.confirm(
            "Update AUR packages?",
            f"{h} downloads and builds the new version of {'this package' if n==1 else f'these {n} packages'} "
            "here, as you. AUR packages are written by their users, not checked by Arch, so it first shows what changed in each "
            "build script (choose Show all), and you can stop there. It asks for your password before installing them.",
            "Start",
            self.update_aur,
            danger=False,
        )

    def update_aur(self):
        h = self.state.aur_helper
        self.asker = h
        self.run_steps(
            "Updating AUR packages", [(updates.aur_update_argv(h), False)], prompts=True, env=updates.AUR_ENV
        )

    def draw_arch_news(self, s):
        news = getattr(s, "news", [])
        if news:
            self.section(f"ARCH NEWS SINCE YOUR LAST UPDATE ({len(news)})")
            for n in news:
                self.row(
                    n.title,
                    time.strftime("%d %b %Y", time.localtime(n.date)),
                    lambda n=n: self.win.notice(n.title, f"{n.text}\n\n{n.link}"),
                    ident=f"news:{n.link}",
                    icon="dialog-information-symbolic",
                    fallback="i",
                )
        elif getattr(s, "news_unknown", False):
            self.note("Arch's news could not be read (archlinux.org/news). Check it before a big update.")

    def draw_pacnew(self, files):
        if not files:
            return
        self.section(f"NEW DEFAULT SETTINGS FILES ({len(files)})")
        for f in files:
            self.row(
                f,
                "",
                lambda f=f: self.win.notice(os.path.basename(f), self.pacnew_text(f)),
                ident=f"pacnew:{f}",
                icon="document-edit-symbolic",
                fallback="✎",
            )
        self.note(
            "An update brought a new default version of these settings files, but the old ones had been changed, so pacman kept "
            "them and put the new version next to each as .pacnew. Compare each pair and merge them by hand, then delete the .pacnew file."
        )

    @staticmethod
    def pacnew_text(f):
        old = f[: -len(".pacnew")]
        return (
            f"New default: {f}\nIn use: {old}\n\nCompare them in a terminal with  diff {old} {f}  and copy over what you want "
            "to keep, then delete the .pacnew file. pacdiff (from pacman-contrib) goes through every such file for you: sudo pacdiff"
        )

    def run_steps(self, label, steps, fetch=False, prompts=False, env=None):
        """Run each (argv, as root) in turn, showing their output; stop at the first that fails. prompts: answer the
        questions they ask with buttons (pacman step by step)."""
        self.running = label
        self.outcome = None
        self.console()
        self.log.get_buffer().set_text("")
        self.redraw()
        self.set_status(label + "…")
        self.win._focus_first(self.groups)

        def finish(problem=""):
            self.running = None
            self.set_status("")
            self.redraw()
            if problem:
                self._append(f"\n✗ Stopped: {problem}")
                m = self.state.manager if self.state else None
                if (
                    label == "Installing updates" and m is not None and m.step_argv
                ):  # often a question --noconfirm answered No
                    self.win.confirm(
                        label,
                        f"{problem}\n\nUpdating step by step shows each question pacman asks, so you can answer "
                        "it yourself.",
                        "Update step by step",
                        self.update_step_by_step,
                        danger=False,
                    )
                else:
                    self.win.notice(label, problem)
            else:
                self.finished = label  # said once the page has been read again, with what it found
            self.refresh()
            tell_tvwcs("status")  # the Quick Menu's updates icon counts again

        def next_step(i):
            if i >= len(steps):
                if fetch:
                    self.fetched = time.time()
                finish()
                return
            argv, root = steps[i]
            self._append("$ " + " ".join(argv))

            def out(line):  # pacman writes the answer it read from a pipe; it is already shown as → answer
                echo, self.echo = self.echo, None
                if echo is None or line.strip() != echo:
                    self._append(line)

            def done(code, tail):
                if code != 0:
                    finish(tail.strip().splitlines()[-1] if tail.strip() else f"It stopped with exit status {code}.")
                    return
                next_step(i + 1)

            if root:
                self.win.run_as_root(argv, label, out, done, on_prompt=self.answer_prompt if prompts else None)
            else:
                StreamedRun(
                    argv,
                    out,
                    done,
                    env=privilege.c_locale_env({**os.environ, **(env or {})}),
                    on_prompt=self.answer_prompt if prompts else None,
                )

        next_step(0)

    def draw_ubuntu_extras(self, extras):
        """Ubuntu's Snap, cloud-init and Ubuntu Pro client, each offered for removal while it is installed (settings.ubuntu)."""
        if not extras:
            return
        self.section("UBUNTU EXTRAS")
        for e, pkgs in extras:
            self.row(
                f"Remove {e.name}",
                "",
                lambda e=e, pkgs=pkgs: self.remove_ubuntu_extra(e, pkgs),
                icon="user-trash-symbolic",
                fallback="✕",
                ident=f"ubuntu:{e.key}",
                detail=", ".join(pkgs),
            )
        self.note(
            "Ubuntu comes with these, and a TV computer does without them. "
            + " ".join(f"{e.name}: {e.what}" for e, _p in extras)
            + " Each is removed with its settings (purged). Nothing stops a package that needs one of them from installing it again."
        )

    def remove_ubuntu_extra(self, e, pkgs):
        also = ubuntu.would_remove(pkgs)
        apps = ubuntu.snap_apps() if e.key == "snap" else []
        text = e.what
        if apps:
            text += f"\n\nSnap apps removed with it: {', '.join(apps)}."
        if also:
            text += f"\n\nAlso removed, as they need it: {', '.join(also)}."
        text += " It asks for your password."
        self.win.confirm(
            f"Remove {e.name}?",
            text,
            "Remove",
            lambda: self.run_steps(f"Removing {e.name}", [(ubuntu.purge_argv([e.key]), True)]),
        )

    def confirm_reboot(
        self,
        title="Restart now?",
        text="Restart the computer now? Unsaved work in open applications may be lost.",
        button="Restart",
    ):
        command = command_for("reboot")
        if not command:
            self.win.notice("Restart", "Nothing on this system can restart it from here.")
            return

        def go():
            if privilege.needs_root(command):
                self.win.run_as_root(
                    command, "Restart", lambda _l: None, lambda code, tail: code and self.win.notice("Restart", tail)
                )
            else:

                def done(code, tail):
                    if code and privilege.polkit_refused(tail):
                        self.win.run_as_root(
                            command, "Restart", lambda _l: None, lambda c, t: c and self.win.notice("Restart", t)
                        )
                    elif code:
                        self.win.notice("Restart", tail)

                StreamedRun(command, lambda _l: None, done)

        self.win.confirm(title, text, button, go)
