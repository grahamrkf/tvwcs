"""CI check on Arch (as a normal user whose sudo needs a password): Settings' step-by-step run drives an AUR helper.
It reinstalls a package from the AUR with yay through StreamedRun, answering each question with its first answer and
sudo's password prompt with the password given, and fails unless yay asked for the password and finished."""

import gi, sys

gi.require_version("Gtk", "4.0")
from gi.repository import GLib
from tvwcs.settings import updates
from tvwcs.system import privilege
from tvwcs.settings.app import StreamedRun
import os

PASSWORD, PACKAGE = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "yay-bin")
loop = GLib.MainLoop()
asked = []
result = {}


def on_prompt(run, question, before):
    p = updates.parse_prompt(question, before)
    asked.append(p)
    print(f"ASKED: {question!r} -> {p and (p.kind, p.question, p.answers)}")
    if p is None:
        run.send("")
    elif p.kind == "password":
        run.send(PASSWORD)
    else:
        run.send(p.answers[0][1])


def done(code, tail):
    result["code"] = code
    loop.quit()


helper = updates.aur_helper()
StreamedRun(
    [helper, "-S", "--aur", "--sudoflags=-S", PACKAGE],
    print,
    done,
    env=privilege.c_locale_env({**os.environ, **updates.AUR_ENV}),
    on_prompt=on_prompt,
)
GLib.timeout_add_seconds(300, loop.quit)
loop.run()
print("exit", result.get("code"), "questions", [(p.kind, p.question) for p in asked if p])
sys.exit(0 if result.get("code") == 0 and any(p and p.kind == "password" for p in asked) and all(asked) else 1)
