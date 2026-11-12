"""Settings > Remote and hotkeys: each device's Quick Menu and Last app keys, app hotkeys, the TV remote over HDMI-CEC
(system/cec.py) and adding TVWCS to the usual sway session. Back end: core/hotkeys.py."""

from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from tvwcs.system import cec, sway_include
from tvwcs.core.hotkeys import ACTION_LABELS, DEFAULT_HOTKEYS, DEVICE_ACTIONS, DEVICE_LABELS, DEVICES, describe
from tvwcs.core.model import ConfigStore
from tvwcs.system.session import runtime_dir
from tvwcs.settings.pages.base import _ConfigPage, _on_off


# ====================================================================== Remote and hotkeys
class HotkeysPage(_ConfigPage):
    """The keys that open the Quick Menu and switch to the app used last from a keyboard, a remote or a gamepad (TVWCS
    writes hotkeys.conf when it reads them again), and the apps that have a hotkey of their own."""

    key = "hotkeys"
    title = "Remote and hotkeys"
    icon = "input-keyboard-symbolic"
    fallback = "⌨"
    sway_only = True
    refreshable = True  # ⟳ reads the HDMI-CEC status again
    not_added = False  # this is a sway session without TVWCS's include line: the page offers to add it

    def summary(self):
        return ""

    def read(self):
        self.not_added = sway_include.where() == "sway" and not sway_include.active()
        return ConfigStore()

    def draw(self, store):
        st = store.settings
        if self.not_added:
            self.section("THIS SWAY SESSION")
            self.row(
                "Add TVWCS to sway",
                "",
                self.add_to_sway,
                icon="list-add-symbolic",
                fallback="+",
                ident="key:add-sway",
                detail="TVWCS is not part of this session yet, so these hotkeys do nothing here",
            )
        has_cec = cec.present()
        for name, heading in (("menu", "QUICK MENU HOTKEYS"), ("last", "LAST APP HOTKEYS")):
            self.section(heading)
            for device in DEVICES:
                if name in DEVICE_ACTIONS[device]:
                    self.row(
                        DEVICE_LABELS[device],
                        describe(st["hotkeys"][device][name]),
                        lambda d=device, n=name: self.change_hotkey(store, d, n),
                        ident=f"key:{device}:{name}",
                    )
            if has_cec:
                self.row(
                    CEC_LABEL,
                    cec.button_label(st["cec"][name]) if st["cec"]["enabled"] else "Off",
                    lambda n=name: self.choose_cec_button(store, n),
                    ident=f"key:cec:{name}",
                )
            if name == "menu":
                self.note(
                    "Keyboard: a modifier tapped on its own (such as Super) triggers when it is released, so Super combinations keep working. "
                    "Remote: most remotes send ordinary keys; F2 suits many of them. Gamepad: a mapper such as AntiMicroX turns its buttons into keys."
                    + (" TV remote: a button of the TV's own remote, sent over HDMI-CEC." if has_cec else "")
                )
            else:
                self.note(
                    "Switches to the app you used before the one on screen, like a TV's previous channel button; press it again to go back. "
                    "Over the Quick Menu it switches from the app the menu is shown over."
                    + (
                        " On the TV's remote, Previous channel is often labelled PRE-CH, Recall, Last or ↺."
                        if has_cec
                        else ""
                    )
                )
        if has_cec:
            self.draw_cec(st["cec"])
        self.section("APPLICATION HOTKEYS")
        profiles = store.hotkey_profiles()
        if not profiles:
            self.note("No application has a hotkey. " + APP_HOTKEY_HINT)
        for p in profiles:
            remove = self.button(
                "window-close-symbolic",
                "✕",
                f"Remove the hotkey for {p.name}",
                lambda pid=p.id: self.change(lambda s: s.set_profile_hotkey(pid, "")),
                danger=True,
            )
            self.row(
                p.name,
                describe(p.hotkey),
                lambda pid=p.id, name=p.name: self.change_app_hotkey(store, pid, name),
                ident=f"key:app:{p.id}",
                extras=[remove],
            )
        if profiles:
            self.note(APP_HOTKEY_HINT)
        self.row(
            "Reset all hotkeys",
            "Defaults",
            self.reset_hotkeys,
            ident="key:reset",
            detail="Quick Menu: tap Super, F2 on a remote. Last app: Super+Tab."
            + (
                f" TV remote: {cec.button_label(cec.DEFAULT_MENU_BUTTON)} and {cec.button_label(cec.DEFAULT_LAST_BUTTON)}."
                if has_cec
                else ""
            )
            + " Removes every application hotkey",
        )

    def draw_cec(self, opts):
        """The TV's remote over HDMI-CEC (cec.py): shown only on a computer with a CEC port (a Raspberry Pi 4 or 5, or a
        USB adapter such as Pulse-Eight's)."""
        self.section("TV REMOTE (HDMI-CEC)")
        self.row(
            "Use the TV's remote", _on_off(opts["enabled"]), lambda: self.cec_toggle("enabled"), ident="cec:enabled"
        )
        self.note(
            'The TV lists this computer as "TVWCS" and passes its remote\'s buttons on: the arrows move, OK selects, Back '
            "goes back, and the numbers, play and pause work in apps too. Turn it off if an app such as Kodi uses HDMI-CEC itself."
        )
        if not opts["enabled"]:
            return
        status = cec.read_status(runtime_dir())
        seen = (
            f"Last button: {status.last_button}"
            if status is not None and status.last_button
            else "Press a button on the TV's remote to check it arrives"
        )
        self.row(
            cec.describe(status), "", None, detail=seen, icon="video-display-symbolic", fallback="▭", ident="cec:status"
        )
        self.row(
            "Switch the TV to this computer",
            _on_off(opts["wake_tv"]),
            lambda: self.cec_toggle("wake_tv"),
            ident="cec:wake_tv",
        )
        self.note("When TVWCS starts and when the computer wakes, the TV turns on and changes to this input.")
        self.row(
            "Turn the TV off with the computer",
            _on_off(opts["tv_standby"]),
            lambda: self.cec_toggle("tv_standby"),
            ident="cec:tv_standby",
        )
        self.note("When the computer sleeps or shuts down, the TV goes to standby too.")
        self.row(
            "Sleep when the TV turns off",
            _on_off(opts["follow_tv"]),
            lambda: self.cec_toggle("follow_tv"),
            ident="cec:follow_tv",
        )
        self.note("Turning the TV off with its remote puts this computer to sleep.")
        self.note(
            "Which buttons reach TVWCS depends on the TV: most pass on the arrows, OK, Back and the numbers, fewer the colour "
            "buttons or Home. The TV's own setting may be called Anynet+ (Samsung), SimpLink (LG), Bravia Sync (Sony) or CEC."
        )

    def cec_toggle(self, key):
        self.change(lambda s: s.settings["cec"].update({key: not s.settings["cec"][key]}))

    def choose_cec_button(self, store, action="menu"):
        """The TV remote's button for the Quick Menu ("menu") or the last app ("last"). A button the other one had is
        taken from it."""
        status = cec.read_status(runtime_dir())
        seen = set(status.seen) if status is not None else set()
        other = "last" if action == "menu" else "menu"
        options = [
            (
                b.id,
                b.label
                + ("  (your TV sends it)" if b.id in seen else "")
                + (f"  ({ACTION_LABELS[other]} now)" if b.id == store.settings["cec"][other] else ""),
            )
            for b in cec.HOTKEY_CHOICES
        ] + [("", "None")]

        def chosen(button_id):
            def edit(s):
                if button_id and s.settings["cec"][other] == button_id:
                    s.settings["cec"][other] = ""
                s.settings["cec"].update({action: button_id, "enabled": True})

            self.change(edit)

        self.win.choose_option(
            f"{CEC_LABEL}: {ACTION_LABELS[action]}",
            options,
            store.settings["cec"][action] if store.settings["cec"]["enabled"] else None,
            chosen,
        )

    def change_hotkey(self, store, device, name):
        label = f"{DEVICE_LABELS[device]}: {ACTION_LABELS[name]}"

        def chosen(spec):
            if spec or not store.settings["hotkeys"][device][name] or name != "menu":
                self.change(lambda s: s.set_slot_hotkey(device, name, spec))
                return
            # Clear: without this key the Quick Menu may only open from another device, so ask first
            others = [DEVICE_LABELS[d] for d in DEVICES if d != device and store.settings["hotkeys"][d].get("menu")]
            self.win.confirm(
                "Remove this Quick Menu hotkey?",
                f"{describe(store.settings['hotkeys'][device][name])} will no longer open the Quick Menu from the {DEVICE_LABELS[device].lower()}. "
                + (
                    f"It still opens with the {' or '.join(o.lower() for o in others)} hotkey."
                    if others
                    else "No other Quick Menu hotkey is set, so only the command tvwcs toggle would open it."
                ),
                "Remove",
                lambda: self.change(lambda s: s.set_slot_hotkey(device, name, "")),
            )

        self.win.assign_hotkey(store, ("slot", device, name), label, chosen)

    def add_to_sway(self):
        """Add the include line to the user's sway config, reload sway, start TVWCS, then ask for the Quick Menu's key."""
        cfg = sway_include.user_config()

        def go():
            try:
                sway_include.add()
            except OSError as exc:
                self.win.notice("Add TVWCS to sway", f"Could not change {cfg}: {exc}")
                return
            self.not_added = False
            self.redraw()
            sway_include.reload()
            started = sway_include.start_launcher()
            self.win.notice(
                "TVWCS is part of sway now",
                f"TVWCS starts with sway from now on{'' if started else ' (start it now with: tvwcs launcher)'}. "
                "Next, choose the keyboard key that opens the Quick Menu.",
                lambda: self.change_hotkey(ConfigStore(), "keyboard", "menu"),
            )

        self.win.confirm(
            "Add TVWCS to sway?",
            f"TVWCS adds one line to {cfg}:\n\n    {sway_include.INCLUDE}\n\nWith it, TVWCS starts with sway in "
            "desktop mode, and its hotkeys and window rules work. A copy of the file from before is kept as "
            f"{cfg.name}.tvwcs-backup. To undo it, delete the line.",
            "Add",
            go,
            danger=False,
        )

    def change_app_hotkey(self, store, pid, name):
        self.win.assign_hotkey(
            store, ("profile", pid), name, lambda spec: self.change(lambda s: s.set_profile_hotkey(pid, spec))
        )

    def reset_hotkeys(self):
        def edit(s):
            for device in DEVICES:
                for name in DEVICE_ACTIONS[device]:
                    s.set_slot_hotkey(device, name, DEFAULT_HOTKEYS[device][name])
            for p in s.hotkey_profiles():
                s.set_profile_hotkey(p.id, "")
            s.settings["cec"].update(menu=cec.DEFAULT_MENU_BUTTON, last=cec.DEFAULT_LAST_BUTTON)

        n = len(ConfigStore().hotkey_profiles())
        self.win.confirm(
            "Reset all hotkeys?",
            "The Quick Menu and Last app hotkeys go back to their defaults"
            + (f", and the {n} application hotkey{'s' if n!=1 else ''} are removed." if n else "."),
            "Reset",
            lambda: self.change(edit),
        )


CEC_LABEL = "TV remote (HDMI-CEC)"


APP_HOTKEY_HINT = "Give an app a hotkey with ✎ Edit on it in Applications."
