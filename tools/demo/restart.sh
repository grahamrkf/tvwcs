#!/bin/sh
# restart.sh tv|desktop: stop any demo session, set the config for that demo, start a fresh headless sway.
. /tmp/demo/env.sh
pkill -f '[m]ockapp.py'; pkill -x sway; sleep 1.5
rm -rf $XDG_RUNTIME_DIR/*
grep -q '^output \* mode 1920x1080' $HOME/.config/tvwcs/sway-session.conf 2>/dev/null ||
    printf 'output * mode 1920x1080\nfocus_follows_mouse no\n' >> $HOME/.config/tvwcs/sway-session.conf
python3 /tmp/demo/setcfg.py - $HOME/.config/tvwcs/config.json "$1"
DEMO_USE=$1 setsid /tmp/demo/session.sh >/dev/null 2>&1 &
sleep 6
