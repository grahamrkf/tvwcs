"""PIN protection for launch profiles. No GTK dependency.

PINs are stored only as salted PBKDF2 hashes. This is a convenience lock for a shared living-room computer (keep a
child out of a browser profile, say), not a security boundary: anyone who can edit ~/.config/tvwcs/config.json can remove it.
"""

from __future__ import annotations
import hashlib, hmac, os, re, time

PIN_PATTERN = re.compile(r"^\d{4,8}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{32}\$[0-9a-f]{64}$")
_ROUNDS = 120_000


def valid_pin(pin) -> bool:
    return bool(PIN_PATTERN.match(pin or ""))


def valid_hash(stored) -> bool:
    return bool(_HASH_PATTERN.match(stored or ""))


def _derive(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _ROUNDS)


def make_hash(pin) -> str:
    if not valid_pin(pin):
        raise ValueError("A PIN is 4 to 8 digits.")
    salt = os.urandom(16)
    return f"{salt.hex()}${_derive(pin,salt).hex()}"


def check_pin(pin, stored) -> bool:
    if not valid_hash(stored) or not isinstance(pin, str):
        return False
    salt_hex, digest = stored.split("$")
    return hmac.compare_digest(_derive(pin, bytes.fromhex(salt_hex)).hex(), digest)


class PinGate:
    """Checks PINs and slows guessing down: after `limit` wrong tries for one profile it refuses for `lockout` seconds."""

    def __init__(self, limit=5, lockout=30, clock=time.monotonic):
        self.limit = limit
        self.lockout = lockout
        self.clock = clock
        self._fails = {}
        self._until = {}

    def attempt(self, key, pin, stored):
        """-> ('ok'|'wrong'|'locked', seconds_remaining_if_locked)"""
        now = self.clock()
        until = self._until.get(key, 0)
        if until > now:
            return "locked", int(until - now) + 1
        if check_pin(pin, stored):
            self._fails.pop(key, None)
            self._until.pop(key, None)
            return "ok", 0
        self._fails[key] = self._fails.get(key, 0) + 1
        if self._fails[key] >= self.limit:
            self._fails[key] = 0
            self._until[key] = now + self.lockout
            return "locked", self.lockout
        return "wrong", 0
