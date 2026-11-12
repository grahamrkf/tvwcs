"""A launch profile being edited (the profile editor's state, no GTK)."""

from __future__ import annotations
import uuid
from dataclasses import dataclass

from tvwcs.model import LAUNCH_NEW_WORKSPACE, LAUNCH_SAME, MAX_DESCRIPTION, PIN_LAUNCH, LaunchProfile
from tvwcs.pinlock import make_hash, valid_pin


@dataclass
class ProfileDraft:
    """A launch profile being edited (no GTK, unit-tested). `channel` is the text typed on the keypad."""

    id: str
    desktop_id: str
    name: str
    channel: str = ""
    command: str = ""
    action: str = ""
    description: str = ""
    new_workspace: bool = False
    hotkey: str = ""
    pin_hash: str = ""
    pin_scope: str = PIN_LAUNCH
    favorite: bool = False

    @classmethod
    def of(cls, p):
        return cls(
            p.id,
            p.desktop_id,
            p.name,
            "" if p.channel is None else str(p.channel),
            p.command,
            p.desktop_action,
            p.description,
            p.launch_mode == LAUNCH_NEW_WORKSPACE,
            p.hotkey,
            p.pin_hash,
            p.pin_scope,
            p.favorite,
        )

    @classmethod
    def new(cls, desktop_id, name):
        return cls(str(uuid.uuid4()), desktop_id, name)

    def set_pin(self, new, again):
        if not valid_pin(new):
            raise ValueError("A PIN is 4 to 8 digits.")
        if new != again:
            raise ValueError("The two PINs do not match. The PIN was not changed.")
        self.pin_hash = make_hash(new)

    def profile(self):
        """The LaunchProfile to store. Raises ValueError for a channel that is not a number (the store checks the rest)."""
        raw = self.channel.strip()
        if raw and not raw.isdigit():
            raise ValueError("The channel must be a number.")
        return LaunchProfile(
            id=self.id,
            desktop_id=self.desktop_id,
            name=self.name.strip(),
            command=self.command.strip(),
            channel=int(raw) if raw else None,
            favorite=self.favorite,
            launch_mode=LAUNCH_NEW_WORKSPACE if self.new_workspace else LAUNCH_SAME,
            desktop_action=self.action,
            pin_hash=self.pin_hash,
            pin_scope=self.pin_scope,
            description=self.description[:MAX_DESCRIPTION],
            hotkey=self.hotkey,
        )
