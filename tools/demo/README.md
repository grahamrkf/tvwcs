# README demos and screenshots (headless sway)

Makes assets/demo-tv-mode.gif, assets/demo-desktop-mode.gif, quick-menu.png, guide-menu.png and options.png in a cloud
container (Ubuntu 24.04) or any spare Linux machine, not on a real TV computer. Only TVWCS and mockup apps are on screen.

1. `apt-get update && apt-get install -y sway grim wf-recorder wtype jq ffmpeg gir1.2-gtk-4.0 python3-gi python3-gi-cairo papirus-icon-theme fonts-open-sans`
2. Build and install TVWCS from the branch: `./scripts/build-debs.sh && apt-get install -y ./resources/tvwcs_*_all.deb`
3. Copy this folder (tools/demo) to /tmp/demo (the scripts expect it there; env.sh takes DEMO_DIR otherwise), then
   `mkdir -p /tmp/demo/{bin,home,run,out} && chmod 700 /tmp/demo/run && ln -sf /usr/bin/python3.12 /tmp/demo/bin/python3`
   (gi is only built for python3.12 there).
4. Mockups: `. ./env.sh && python3 mock/make_images.py $HOME/.local/share/mockup`, and a `mockup-<id>.desktop` per app in
   `$HOME/.local/share/applications` with `Exec=python3 /tmp/demo/mock/mockapp.py <id> "<Name> (Mockup)"`,
   `Icon=$HOME/.local/share/mockup/icon-<id>.png` and `StartupWMClass=demo.mockup.<id>` (ids: streamly, gameshelf,
   retrobox, orbit, lantern, pagewright, gridline).
5. `python3 tv.py`, `python3 desktop.py`, `python3 shots.py`, `python3 extras.py` (media-theme.png, volume-indicator.png,
   tv-remote.png; 5.21). Results in out/. Copy them to the repo's assets/.
   - Desktop entries: Name without "(Mockup)" (the Applications pane shows it; the Quick Menu shows the profile name
     from setcfg.py), plus Comment and Categories (AudioVideo / Network;WebBrowser / Game / Office) so the
     Applications pane fills Media, Internet, Games and Office.
   - Start one plain `DEMO_USE=tv session.sh` first so ~/.config/tvwcs/config.json exists before setcfg.py runs.
   - extras.py: the volume indicator needs gtk4-layer-shell 1.0.4 .debs from archive.ubuntu.com's pool (universe/g/
     gtk4-layer-shell) and calls tvwcs.ui.osd.show with PYTHONPATH=/usr/lib/tvwcs. The TV remote page needs a fake
     /dev/cec0 (`touch`) and a written tvwcs-cec.json status; the first key of a new wtype run is lost, so it sends
     Shift first. setcfg.py takes DEMO_STYLE/DEMO_LOOK (default modern).

How it works and what to watch for:
- `restart.sh tv|desktop` starts a fresh headless sway (WLR_BACKENDS=headless, WLR_RENDERER=pixman, 1920x1080):
  TV mode is `tvwcs-session`; desktop mode is sway with `desktop-sway.conf` (sway's standard config plus the include
  line). setcfg.py sets the theme (TV dark, desktop light), favorites and channels 04/12/21.
- **All keys of a demo go to one `wtype` run.** Each wtype run is a new virtual keyboard, which takes the focus from
  TVWCS and closes it. demo.py plans keys, pauses and captions on one timeline, then plays it while wf-recorder
  records, and burns the captions in with ffmpeg straight into a GIF (fps 8, 800 px, 128 colours, bayer dither).
- wtype puts a space between separate text arguments: give a word as one argument.
- The headless session has no pointer (wlrctl and `swaymsg seat cursor` clicks don't reach GTK), so the demos use the
  keyboard only. Tapping Super is bound with `bindsym --release Super_L` in desktop-sway.conf, because wtype's
  keycodes don't match TVWCS's `bindcode 133`.
- Keyboard focus in the status rows depends on the column last used, so the desktop demo goes Down Down Left Left
  Right to reach ⊞ for sure (still right with ⚙ added in 5.21: Right Right opens Settings instead). Enter on a power option really runs it (Lock blanks the screen).
- Re-check the key sequences with a contact sheet of frames (`ffmpeg -vf fps=1/4,scale=400:-1,tile=6x4`) after a
  Quick Menu layout change.
