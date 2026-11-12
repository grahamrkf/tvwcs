"""Settings > User: the account, logging in automatically, the start-up app, idle times and server mode.
The system side is system/loginscreen.py, system/servermode.py and settings/account.py; the changes that need
root go through the window's run_as_root (or, to turn server mode off from a standard account, an
administrator's su)."""

from __future__ import annotations

from tvwcs.settings import account
from tvwcs.system import loginscreen, power, servermode, sway_include
from tvwcs.core.model import STARTUP_LABELS, STARTUP_MODES, ConfigStore, startup_choices
from tvwcs.settings.app import in_background


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from tvwcs.settings.pages.base import Page

# ====================================================================== User


def me() -> str:
    return account.read().login


def run_root(page, args, label, done, packages=()):
    """Run `python3 -m tvwcs.system.loginscreen args` as root (installing `packages` first), then done(problem or "")."""
    lines = []

    def finished(code, tail):
        page.set_status("")
        if code:
            done(("\n".join(lines[-6:]) or tail or f"{label} did not work.").strip())
            return
        done("")

    page.set_status(f"{label}…")
    page.win.run_as_root(loginscreen.root_command(args, packages), label, lines.append, finished)


# ====================================================================== User
def role(a) -> str:
    return "Administrator" if a.admin else "Standard User"


def read_user():
    return (account.read(), loginscreen.status(), loginscreen.profile_starts(), servermode.server_user())


def draw_user(page, state):
    a, st, _profile, server = state
    page.section("ACCOUNT")
    page.row(
        "Name",
        a.full_name or "Not set",
        None if server else lambda: change_name(page, a),
        detail="Shown on the login screen",
        ident="user:name",
    )
    page.row(
        "User name",
        a.login,
        None,
        detail="Used to log in and for the home folder; it cannot be changed here",
        ident="user:login",
    )
    page.row(
        "Password",
        "Change",
        lambda: change_password(page),
        detail="Asks for the current one first",
        ident="user:password",
    )
    page.section("LOGGING IN")
    if sway_include.in_sway():
        draw_logging_in(page, state)
    else:
        page.draw_off(
            lambda: draw_logging_in(page, state)
        )  # GNOME, KDE...: what starts TVWCS's session is changed from it
    draw_server_mode(page, a, server)


def draw_logging_in(page, state):
    a, st, profile, server = state
    cur = st["current"]
    who, _sid = st["autologin"]
    if server:  # the automatic login and the login screen are the administrator's
        page.row(
            "Log in automatically after startup",
            f"On for {who}" if who else "Off",
            None,
            ident="user:auto",
            detail="Set with server mode",
            value_css="state-on" if who == a.login else "setting-value",
        )
    elif loginscreen.autologin_supported(cur):
        console = (
            cur == ""
        )  # no login screen: the first text console logs in, and the shell profile starts TVWCS's session
        mine = who == a.login and (profile or not console)
        page.row(
            "Log in automatically after startup",
            "On" if mine else f"On for {who}" if who else "Off",
            lambda: toggle_autologin(page, a, mine, console),
            detail=(
                "On the first text console, straight into TVWCS"
                if console
                else "Straight into TVWCS, without the login screen"
            ),
            ident="user:auto",
            value_css="state-on" if mine else "setting-value",
        )
    elif cur:
        page.row(
            "Log in automatically after startup",
            "Not here",
            None,
            detail=f"Set it in {loginscreen.name(cur)}'s own settings",
            ident="user:auto",
        )
    on = ConfigStore().settings["lock_at_start"]
    page.row(
        "Lock the screen when TVWCS starts",
        "On" if on else "Off",
        lambda: toggle_lock_at_start(page, on),
        detail="Your password unlocks it. For the automatic login, so the computer is never left open",
        ident="user:lock-start",
        value_css="state-on" if on else "setting-value",
    )
    others = [u for u in st["installed"] if u != cur] if not server else []
    page.row(
        "Login screen",
        loginscreen.name(cur) if cur else "None (text console)",
        (lambda: change_login_screen(page, cur, others)) if others else None,
        detail="Choose this to switch to another one installed here" if others else "",
        ident="user:screen",
    )
    if cur and not loginscreen.wayland_ok(cur):
        page.note(f"{loginscreen.name(cur)} cannot start sway reliably. greetd or SDDM can.", "error")


def toggle_autologin(page, a, mine, console=False):
    """Turn the automatic login into TVWCS's session on or off. Without a login screen (console) the user's shell
    profile starts the session too: added first, and taken out again if the automatic login could not be set."""
    args = ["autologin", a.login, loginscreen.SESSION] if not mine else ["autologin", "--off"]
    if console and not mine:
        problem = loginscreen.set_profile(True)
        if problem:
            page.win.notice("Log in automatically", problem)
            return

    def done(problem):
        if console and (bool(problem) != mine):
            loginscreen.set_profile(False)  # on failed, or off worked
        if problem:
            page.win.notice("Log in automatically", problem)
            return
        page.refresh(quiet=True)

    run_root(page, args, "Turning off the automatic login" if mine else "Turning on the automatic login", done)


def toggle_lock_at_start(page, on):
    """The "lock_at_start" setting (lockscreen.lock_at_start). Never turned on for an account swaylock could not unlock."""
    from tvwcs.system import lockscreen

    if not on:
        if not lockscreen.available():
            page.win.notice(
                "Lock the screen when TVWCS starts",
                "TVWCS's lock screen needs swaylock. Install it first, with your package manager.",
            )
            return
        if not lockscreen.can_unlock(account.password_status()):
            page.win.notice(
                "Lock the screen when TVWCS starts",
                "Your account has no password (or a locked one), so the lock screen "
                f"could not be unlocked. Give it one first: in a terminal, run  sudo passwd {me()}",
            )
            return
    store = ConfigStore()
    store.settings["lock_at_start"] = not on
    store.save()
    page.redraw()  # not in read_user()'s state, so a quiet refresh would not redraw


def change_login_screen(page, cur, others):
    def picked(unit):
        def done(problem):
            if problem:
                page.win.notice("Login screen", problem)
                return
            page.win.notice(
                "Login screen",
                f"From the next start, the computer uses {loginscreen.name(unit)}.",
                lambda: page.refresh(quiet=True),
            )

        page.win.confirm(
            f"Switch to {loginscreen.name(unit)}?",
            f"From the next start the computer uses {loginscreen.name(unit)}. It asks for your password.",
            "Switch",
            lambda: run_root(page, ["switch", unit], "Changing the login screen", done),
            danger=False,
        )

    page.win.choose_option("Login screen", [(u, f"Switch to {loginscreen.name(u)}") for u in others], None, picked)


# ---------------------------------------------------------------------- server mode
def draw_server_mode(page, a, server):
    """Server mode's row: on (choosing who uses the TV) asks for this user's password, which needs an administrator;
    off asks for an administrator's, named first when this is a standard account."""
    page.section("SERVER MODE")
    page.row(
        "Server mode",
        f"On for {server}" if server else "Off",
        lambda: (turn_server_off if server else turn_server_on)(page, a),
        detail=(
            "No power, update, network or other administrator settings on the TV"
            if not server
            else "Turning it off needs an administrator"
        ),
        ident="user:server",
        value_css="state-on" if server else "setting-value",
    )
    if server and sway_include.in_sway():
        draw_idle_times(page)
    page.note(
        "For a computer that is a server first: the account that uses the TV logs in automatically into TVWCS, "
        "and nobody can put the computer to sleep, restart or shut it down, update it, change its network or unmount "
        "its drives from TVWCS. Also from a terminal or over SSH: tvwcs server-mode on --user=NAME."
    )


def draw_idle_times(page):
    """Power and sleep is turned off in server mode, so the times there that keep the server safe and do not need an
    administrator, turning off the screen and locking the TV when nobody uses it, are here instead. Each sets both of
    Power's times (plugged in and on battery)."""
    idle = ConfigStore().settings["idle"]
    for action in ("screen_off", "lock"):
        page.row(
            power.LABELS[action],
            power.duration_text(idle[action]),
            lambda a=action: choose_idle_time(page, a, idle[a]),
            detail="When nothing is touched, in place of Power and sleep's time",
            ident=f"user:{action}",
        )


def choose_idle_time(page, action, current):
    def picked(key):
        store = ConfigStore()
        for option in ("idle", "idle_battery"):
            store.settings[option][action] = int(key)
        store.save()
        from tvwcs.settings.pages.base import tell_tvwcs

        tell_tvwcs("reload")
        page.refresh(quiet=True)

    page.win.choose_option(
        power.LABELS[action], [(str(v), power.duration_text(v)) for v in power.CHOICES], str(current), picked
    )


def turn_server_on(page, a):
    if not a.admin:
        page.win.notice(
            "Server mode",
            "Turning server mode on needs an administrator. Ask one to turn it on here, or to run: tvwcs server-mode on --user="
            + a.login,
        )
        return
    names = servermode.accounts() or [a.login]

    def picked(user):
        def done(problem):
            if problem:
                page.win.notice("Server mode", problem)
                return
            _everywhere(page)
            page.win.notice(
                "Server mode",
                f"Server mode is on. From the next start {user} is logged in automatically into TVWCS, "
                "without power, update, network or other administrator settings.",
            )

        page.win.confirm(
            "Turn server mode on?",
            f"{user} uses the TV: they log in automatically into TVWCS, and nobody can put the "
            "computer to sleep, restart or shut it down, update it or change its network from TVWCS. Turning it off "
            "again needs an administrator. It asks for your password.",
            "Turn on",
            lambda: _run_server(page, ["on", user], "Turning server mode on", done),
            danger=False,
        )

    if len(names) == 1:
        picked(names[0])
        return
    page.win.choose_option(
        "Who uses the TV?",
        [(n, n + (" (you)" if n == a.login else "")) for n in names],
        a.login if a.login in names else None,
        picked,
    )


def turn_server_off(page, a):
    def done(problem):
        if problem:
            page.win.notice("Server mode", problem)
            return
        _everywhere(page)

    if a.admin:
        page.win.confirm(
            "Turn server mode off?",
            "Every setting comes back on the TV, and it can sleep, restart and shut the computer "
            "down again. The automatic login stays as it is. It asks for your password.",
            "Turn off",
            lambda: _run_server(page, ["off"], "Turning server mode off", done),
        )
        return
    admins = servermode.admins()
    if not admins:
        page.win.notice(
            "Server mode",
            "No account here may use sudo, so nobody can turn server mode off from here. As root, run: tvwcs server-mode off",
        )
        return

    def with_admin(admin):
        def got(password):
            if not password:
                return
            page.set_status("Turning server mode off…")

            def finished(result):
                page.set_status("")
                code, why = result
                done(why if code else "")

            argv = loginscreen.root_command(["off"], module="tvwcs.system.servermode")
            in_background(
                lambda: account.run_as_admin(admin, password, argv), finished, lambda exc: finished((1, str(exc)))
            )

        page.win.ask_text(
            f"{admin}'s password",
            f"Turning server mode off needs an administrator. Type {admin}'s password. "
            "It is used once and never stored.",
            got,
            secret=True,
            ok_label="Turn off",
        )

    if len(admins) == 1:
        with_admin(admins[0])
        return
    page.win.choose_option("Which administrator?", [(n, n) for n in admins], None, with_admin)


def _everywhere(page):
    """Server mode changed: every page read so far is drawn again (some turn off or on), and TVWCS reads its options
    again (its idle times: no sleep in server mode)."""
    from tvwcs.settings.pages.base import tell_tvwcs

    for p in page.win.pages:
        if p is page:
            p.refresh(quiet=True)
        elif p.state is not None:
            p.redraw()
    tell_tvwcs("reload")


def _run_server(page, args, label, done):
    lines = []

    def finished(code, tail):
        page.set_status("")
        done(("\n".join(lines[-6:]) or tail or f"{label} did not work.").strip() if code else "")

    page.set_status(f"{label}…")
    page.win.run_as_root(
        loginscreen.root_command(args, module="tvwcs.system.servermode"), label, lines.append, finished
    )


# ---------------------------------------------------------------------- the application to open at login
def draw_startup(page):
    store = ConfigStore()
    st = store.settings
    mode = st["startup"]["mode"]
    names = {p.id: p.name for p in store.profiles}
    page.row(
        "Application to open at login",
        STARTUP_LABELS[mode],
        lambda: page.win.choose_option(
            "Application to open at login",
            [(m, STARTUP_LABELS[m]) for m in STARTUP_MODES],
            mode,
            lambda m: pick_startup(page, m),
        ),
        ident="user:startup",
    )
    if mode == "app":
        page.row(
            "Application",
            names.get(st["startup"]["profile_id"], "Not chosen"),
            lambda: choose_startup_app(page),
            ident="user:startup-app",
            indent=44,
        )
    page.note(
        "Some applications, such as Steam, have their own option to start at login. If you use one of those, choose None here, "
        "so the two do not both open something."
    )


def _save_startup(page, **changes):
    from tvwcs.settings.pages.base import tell_tvwcs

    store = ConfigStore()
    store.settings["startup"].update(changes)
    store.save()
    tell_tvwcs("reload")
    page.redraw()


def pick_startup(page, mode):
    store = ConfigStore()
    if mode == "app" and store.get(store.settings["startup"]["profile_id"]) is None:
        choose_startup_app(page)
        return  # pick which one first
    _save_startup(page, mode=mode)


def choose_startup_app(page):
    store = ConfigStore()
    options = []
    for _heading, profiles in startup_choices(store.profiles):
        for p in profiles:
            options.append(
                (
                    p.id,
                    (f"{store.channel_text(p.channel)}  " if p.channel is not None else "")
                    + p.name
                    + ("  ★" if p.favorite else ""),
                )
            )
    if not options:
        page.win.notice("Application to open at login", "There are no applications to choose from yet.")
        return
    page.win.choose_option(
        "Application to open at login",
        options,
        store.settings["startup"]["profile_id"],
        lambda pid: _save_startup(page, profile_id=pid, mode="app"),
    )


def change_name(page, a):
    def got(name):
        name = " ".join(name.split())
        why = account.valid_full_name(name)
        if why:
            page.win.notice("Name", why)
            return
        if name == a.full_name:
            return
        lines = []

        def done(code, tail):
            page.set_status("")
            if code:
                page.win.notice("Name", ("\n".join(lines[-4:]) or tail or "The name could not be changed.").strip())
            page.refresh(quiet=True)

        page.set_status("Changing the name…")
        page.win.run_as_root(account.full_name_argv(a.login, name), "Changing your name", lines.append, done)

    page.win.ask_text(
        "Name",
        "Your full name, as the login screen shows it. Changing it asks for your password.",
        got,
        a.full_name,
        ok_label="Save",
    )


def change_password(page):
    def ask_current(error=""):
        page.win.ask_text(
            "Current password", "Type the password you use now.", ask_new, secret=True, ok_label="Next", error=error
        )

    def ask_new(current, error=""):
        if not current:
            return
        page.win.ask_text(
            "New password",
            "Type the new password.",
            lambda new: ask_again(current, new),
            secret=True,
            ok_label="Next",
            error=error,
        )

    def ask_again(current, new):
        if not new:
            return

        def again(repeat):
            if repeat != new:
                ask_new(current, "The two did not match. Type the new password again.")
                return
            page.set_status("Changing the password…")

            def done(problem):
                page.set_status("")
                if not problem:
                    page.win.notice(
                        "Password", "Your password is changed. Use the new one from now on (also for sudo)."
                    )
                    return
                if "current password" in problem:
                    ask_current(problem)
                else:
                    ask_new(current, problem)

            in_background(lambda: account.change_password(current, new), done, lambda exc: done(str(exc)))

        page.win.ask_text(
            "New password, again", "Type the new password once more.", again, secret=True, ok_label="Change"
        )

    ask_current()


class UserPage(Page):
    """This user's account (name, password) and logging in: the login screen in use and the automatic login."""

    key = "user"
    title = "User"
    icon = "avatar-default-symbolic"
    fallback = "☺"

    def read(self):
        return read_user()

    def summary(self):
        return (
            role(self.state[0]) if self.state else ""
        )  # "Administrator" or "Standard User", small and grey beside "User"

    def draw(self, state):
        draw_user(self, state)
