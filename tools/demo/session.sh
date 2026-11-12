#!/bin/sh
# Start a headless sway for the demo: DEMO_USE=tv runs TVWCS's own session (TV mode), otherwise sway with the
# include line (desktop mode).
. /tmp/demo/env.sh
if [ "$DEMO_USE" = tv ]; then exec dbus-run-session -- tvwcs-session >$XDG_RUNTIME_DIR/sway.log 2>&1
else exec dbus-run-session -- sway -c /tmp/demo/desktop-sway.conf >$XDG_RUNTIME_DIR/sway.log 2>&1; fi
