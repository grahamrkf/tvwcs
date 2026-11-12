"""Which launch profile opened which window. No GTK dependency.

A window is just "a Firefox window"; TVWCS cannot tell a private-session profile's window from the main profile's. To know
which profile's PIN a window falls under, TVWCS remembers the windows that appear shortly after it launches a profile.
The memory lasts for the current TVWCS session; a window it never saw opened falls back to its application's main profile.
"""

from __future__ import annotations


class WindowOwners:
    def __init__(self):
        self._owner = {}

    def claim(self, known_ids, windows, profile_id, accept=lambda w: True):
        """Give `profile_id` every window that was not there before the launch (`known_ids`), is unclaimed, and `accept`s it."""
        for w in windows:
            cid = int(w["con_id"])
            if cid not in known_ids and cid not in self._owner and accept(w):
                self._owner[cid] = profile_id

    def owner(self, con_id):
        return self._owner.get(int(con_id))

    def forget_closed(self, windows):
        live = {int(w["con_id"]) for w in windows}
        self._owner = {c: p for c, p in self._owner.items() if c in live}
