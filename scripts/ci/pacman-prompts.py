"""CI check on Arch (as root): Settings' step-by-step run answers a real pacman's questions. It installs a small
package without --noconfirm through StreamedRun, answering each question with its default, and fails if pacman never
asked or the install did not finish."""

import gi, subprocess, sys

gi.require_version("Gtk", "4.0")
from gi.repository import GLib
from tvwcs import control_updates as updates
from tvwcs.ui_control import StreamedRun

PACKAGE = sys.argv[1] if len(sys.argv) > 1 else "nano"
loop = GLib.MainLoop()
asked = []
result = {}


def on_prompt(run, question, before):
    p = updates.parse_prompt(question, before)
    asked.append(p)
    print(f"ASKED: {question!r} -> {p and p.answers}")
    run.send(p.answers[0][1] if p else "")


def done(code, tail):
    result["code"] = code
    loop.quit()


StreamedRun(["pacman", "-S", PACKAGE], print, done, on_prompt=on_prompt)
GLib.timeout_add_seconds(300, loop.quit)
loop.run()
installed = subprocess.run(["pacman", "-Q", PACKAGE]).returncode == 0
print("exit", result.get("code"), "questions", len(asked), "installed", installed)
sys.exit(0 if result.get("code") == 0 and asked and all(asked) and installed else 1)
