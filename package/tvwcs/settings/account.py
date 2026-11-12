"""Settings > User: this user's account. No GTK dependency.

Changing the password goes through passwd, as typing it in a terminal would: passwd checks the current password itself
(through PAM) and that the new one is good enough. It insists on a terminal, so it runs in a pseudo-terminal and its
questions are answered in turn; no root is needed. The full name needs root (chfn, see full_name_argv)."""

from __future__ import annotations
import os, pty, pwd, re, select, signal, termios, time
from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    login: str
    full_name: str
    uid: int
    home: str
    shell: str
    admin: bool  # in the sudo (or wheel / admin) group


ADMIN_GROUPS = ("sudo", "wheel", "admin")


def read(uid=None) -> Account:
    import grp

    e = pwd.getpwuid(os.getuid() if uid is None else uid)
    try:
        groups = {g.gr_name for g in grp.getgrall() if e.pw_name in g.gr_mem} | {grp.getgrgid(e.pw_gid).gr_name}
    except KeyError:
        groups = set()
    return Account(
        e.pw_name,
        (e.pw_gecos or "").split(",")[0].strip(),
        e.pw_uid,
        e.pw_dir,
        e.pw_shell,
        bool(groups & set(ADMIN_GROUPS)),
    )


def password_status(run=None) -> str:
    """`passwd -S`'s verdict on this user's password: "P" (has one), "NP" (none) or "L" (locked, as for an account that
    only ever logs in automatically); "" when it cannot tell. No root needed for one's own account."""
    import subprocess

    try:
        out = (run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout))(
            ["passwd", "-S"]
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    parts = (out or "").split()
    return parts[1] if len(parts) > 1 and parts[1] in ("P", "NP", "L") else ""


def valid_full_name(name) -> str:
    """ "" when chfn would take it as a full name, else why not."""
    if len(name) > 80:
        return "That name is too long."
    if any(c in name for c in ":,=\n\\") or any(ord(c) < 32 for c in name):
        return "A name cannot contain : , = or \\."
    return ""


# ---------------------------------------------------------------------- talking to passwd and chfn
PROMPT = re.compile(r"(password|passwort|mot de passe|contraseña)[^:\n]*:\s*$", re.I)


def converse(argv, answers, timeout=30, env=None):
    """Run argv in a pseudo-terminal, giving answers[i] at its i-th password prompt. Returns (exit code, everything it
    printed, prompts seen). A prompt beyond the answers (passwd asking for a new password again because the last one was
    refused) stops it: code -2."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            attrs = termios.tcgetattr(0)
            attrs[3] &= ~termios.ECHO
            termios.tcsetattr(0, termios.TCSANOW, attrs)  # answers are not shown back
        except termios.error:
            pass
        try:
            os.execvpe(argv[0], argv, {**(env or os.environ), "LC_ALL": "C", "LANG": "C", "LANGUAGE": ""})
        finally:
            os._exit(127)
    out = ""
    pending = ""
    asked = 0
    deadline = time.monotonic() + timeout
    code = None
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                code = -3
                break
            r, _w, _x = select.select([fd], [], [], min(left, 0.5))
            if not r:
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    code = os.waitstatus_to_exitcode(status)
                    break
                continue
            try:
                chunk = os.read(fd, 1024).decode(errors="replace")
            except OSError:
                chunk = ""
            if not chunk:
                _p, status = os.waitpid(pid, 0)
                code = os.waitstatus_to_exitcode(status)
                break
            out += chunk
            pending += chunk
            if PROMPT.search(pending):
                pending = ""
                if asked >= len(answers):
                    code = -2
                    break
                os.write(fd, (answers[asked] + "\n").encode())
                asked += 1
    finally:
        if code in (-2, -3, None):
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
    return code, out, asked


def _why(out, fallback):
    """passwd's and chfn's own explanation, without the prompts."""
    out = out.replace("\r", "").replace("BAD PASSWORD:", "\0")  # passwd's verdict, not a question
    out = re.sub(
        r"[^\n:\0]*(password|passwort|mot de passe|contraseña)[^\n:\0]*:[ \t]*(?=\S|$)", "\n", out, flags=re.I | re.M
    ).replace("\0", "BAD PASSWORD:")
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    lines = [
        l
        for l in lines
        if not re.match(
            r"(changing (the )?password for|changing the user information for|enter the new value)", l, re.I
        )
        and "updated successfully" not in l.lower()
    ]
    return " ".join(lines[-3:]) or fallback


def change_password(current, new, argv=("passwd",), run=converse) -> str:
    """ "" when the password was changed, else why not (for people)."""
    if not new:
        return "The new password is empty."
    code, out, _asked = run(list(argv), [current, new, new])
    if code == 0:
        return ""
    low = out.lower()
    if code == -2:
        return _why(out, "passwd did not accept the new password.")
    if "authentication token manipulation error" in low or "authentication failure" in low:
        return "Your current password is not right."
    if code == -3:
        return "passwd did not finish."
    return _why(out, "The password could not be changed.")


def run_as_admin(admin, password, argv, run=converse):
    """Run argv as root for a standard account, which sudo would refuse: as the administrator `admin`, through su and
    then sudo, both given their password. Returns (exit code, why it failed or "")."""
    import shlex

    if not re.fullmatch(r"[a-z_][a-z0-9_.-]*\$?", admin or ""):
        return 1, "Unexpected user name."
    inner = shlex.join(["sudo", "-S", "-k", "-p", "Password:", "--", *argv])
    code, out, _asked = run(["su", admin, "-c", inner], [password, password], timeout=120)
    if code == 0:
        return 0, ""
    low = out.casefold()
    if code == -2 or "authentication failure" in low or "incorrect password" in low:
        return 1, f"That is not {admin}'s password."
    if "not in the sudoers" in low or "not allowed" in low:
        return 1, f"{admin} is not allowed to use sudo."
    return code or 1, _why(out, "It did not work.")


def full_name_argv(login, full_name) -> list:
    """The full name is changed as root (Debian lets users change only their phone numbers and room with chfn)."""
    return ["chfn", "-f", full_name, login]
