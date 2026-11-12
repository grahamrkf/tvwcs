S=${DEMO_DIR:-/tmp/demo}
export HOME=$S/home PATH=$S/bin:/usr/bin:/bin XDG_RUNTIME_DIR=$S/run LANG=C.UTF-8 \
  XDG_DATA_DIRS=$S/home/.local/share:/usr/local/share:/usr/share \
  WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 WLR_HEADLESS_OUTPUTS=1
export WAYLAND_DISPLAY=wayland-1
