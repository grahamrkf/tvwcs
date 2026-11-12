"""Running the command-line tools Settings talks to. No GTK dependency.

Every tool runs with the C locale (in UTF-8, so names like "Taylor’s Wi-Fi" survive), so its output can be parsed whatever language the user reads, and every call
returns a Result instead of raising: a missing tool, a timeout or a refusal is something to show, not a crash."""

from __future__ import annotations
import os, re, shutil, subprocess
from dataclasses import dataclass

C_LOCALE = {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "LANGUAGE": ""}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02|\r")


@dataclass(frozen=True)
class Result:
    ok: bool
    code: int
    out: str
    err: str

    @property
    def message(self):
        """The most useful line to show when the command failed."""
        lines = [l.strip() for l in (self.err or self.out).splitlines() if l.strip()]
        return lines[-1] if lines else f"exit status {self.code}"


def c_env(extra=None):
    return {**os.environ, **C_LOCALE, **(extra or {})}


def have(name, which=shutil.which):
    return bool(which(name))


def run(argv, timeout=15, input=None, env=None) -> Result:
    """Run a command and wait for it. Never raises."""
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input,
            env=c_env(env),
            stdin=None if input is not None else subprocess.DEVNULL,
        )
        return Result(p.returncode == 0, p.returncode, strip_ansi(p.stdout or ""), strip_ansi(p.stderr or ""))
    except subprocess.TimeoutExpired:
        return Result(False, -1, "", f"{argv[0]} did not answer in {timeout} seconds.")
    except (OSError, ValueError) as exc:
        return Result(False, -1, "", f"Could not run {argv[0]}: {exc}")


def strip_ansi(text):
    return _ANSI.sub("", text)


def split_terse(line, maxsplit=-1):
    """Split a line of `nmcli -t` output on its unescaped colons, then unescape each field (\\: is a colon, \\\\ a backslash)."""
    fields = []
    cur = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n:
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":" and (maxsplit < 0 or len(fields) < maxsplit):
            fields.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    fields.append("".join(cur))
    return fields


def key_values(text, sep=":"):
    """`Key: value` lines (bluetoothctl, pactl info) as a dict; later duplicates are ignored."""
    out = {}
    for line in text.splitlines():
        key, found, value = line.strip().partition(sep)
        if found and key and key not in out:
            out[key.strip()] = value.strip()
    return out
