"""`tvwcs help`: what the tvwcs command does. No GTK, so it prints at once (and at a text console).

The older spellings still work (start, -s/--server-mode, --no-server-mode, --start, control) but are no longer shown."""

from __future__ import annotations
import sys

USAGE = """Usage: tvwcs [COMMAND]

  tvwcs                          what fits where you type it: at a text console, TVWCS's session; in a
                                 sway session with TVWCS, the Quick Menu; in another sway session or
                                 desktop, Settings; over SSH, a menu of the server mode commands
  tvwcs session                  start TVWCS's session (sway in TV mode) here, at a text console
  tvwcs settings [PAGE]          open TVWCS Settings, optionally on one page (such as sound or user)
  tvwcs lock                     lock the screen
  tvwcs server-mode on [--user=NAME]
                                 turn on server mode: NAME (you, by default) uses the TV, logs in
                                 automatically into TVWCS and has no administrator settings
  tvwcs server-mode off          turn server mode off (the automatic login stays)
  tvwcs server-mode status       say whether server mode is on, and for whom
  tvwcs start-session [--user=NAME]
                                 start TVWCS for NAME on this computer's screen now (for example over SSH)
  tvwcs vendor                   show the vendor and system presets TVWCS read (vendor.json,
                                 defaults.json) and anything in them it skipped
  tvwcs --version                print TVWCS's version
  tvwcs help                     print this

Server mode and start-session ask for an administrator's password (sudo).

Used by TVWCS's sway config, hotkeys and idle timer (not usually typed):
  tvwcs launcher                 run TVWCS itself (tvwcs.conf starts it as sway starts)
  tvwcs toggle | guide           show or hide the Quick Menu, or open the applications guide
  tvwcs reload | stop            reload TVWCS's settings, or quit TVWCS
  tvwcs launch PROFILE_ID        start an application profile (its hotkey)
  tvwcs last-app                 switch to the app used before the one in use (Super+Tab)
  tvwcs volume up|down|mute      the volume keys: one step, stopping at 100 % (150 % with
                                 Settings > Sound > Allow over-amplification), or mute; each shows
                                 the volume on screen for a moment
  tvwcs idle screen_off|lock|sleep|resume
                                 what swayidle runs when a Power and sleep time is reached
  tvwcs lock-at-start            lock straight away if Settings > User asks for it"""


def main(argv=None, out=None) -> int:
    print(USAGE, file=out or sys.stdout)
    return 0


def wrong(out=None) -> int:
    """An unknown command: the usage on stderr, exit status 2."""
    print(USAGE, file=out or sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
