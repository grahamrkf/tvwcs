"""Extra README screenshots (5.21): the Media theme's three looks, the volume indicator over a full-screen app, and
Settings > Remote and hotkeys with a TV remote (HDMI-CEC). Fakes /dev/cec0 and the CEC status; run as root."""

import sys, os, json, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo import *
from shots import rect

O = f"{S}/out"
if "media" in sys.argv[1:] or len(sys.argv) == 1:
    # Media theme: Streamly open (channel 04), Quick Menu over it with GameShelf selected
    for look in ("jellyfin", "emby", "plex"):
        os.environ["DEMO_STYLE"] = "media"
        os.environ["DEMO_LOOK"] = look
        restart("tv")
        e = env()
        wt = subprocess.Popen(
            [
                "wtype",
                "-s",
                "1000",
                "0",
                "-s",
                "300",
                "4",
                "-s",
                "400",
                "-k",
                "Return",
                "-s",
                "5000",
                "-k",
                "F2",
                "-s",
                "2000",
                "-k",
                "Up",
                "-s",
                "5000",
            ],
            env=e,
        )
        time.sleep(10.5)
        r = rect()
        shot(f"{O}/media-{look}-full.png")
        wt.wait()
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                f"{O}/media-{look}-full.png",
                "-vf",
                f"crop={r['width']}:{r['height']}:{r['x']}:{r['y']}",
                f"{O}/media-{look}.png",
            ],
            check=True,
        )
    os.environ.pop("DEMO_STYLE")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y"]
        + sum([["-i", f"{O}/media-{l}.png"] for l in ("jellyfin", "emby", "plex")], [])
        + ["-filter_complex", "[0][1][2]hstack=inputs=3", f"{O}/media-theme.png"],
        check=True,
    )
# Volume indicator over full-screen Streamly
restart("tv")
e = env()
subprocess.run(["wtype", "-s", "1000", "0", "-s", "300", "4", "-s", "400", "-k", "Return"], env=e)
time.sleep(5)
sh("swaymsg '[app_id=demo.mockup.streamly] fullscreen enable'")
time.sleep(1)
e["PYTHONPATH"] = "/usr/lib/tvwcs"
osd = ["python3", "-c", "from tvwcs.ui.osd import show; show(40,False)"]
subprocess.run(osd, env=e)
time.sleep(3)  # the first call starts the indicator
subprocess.run(osd, env=e)
time.sleep(0.3)
shot(f"{O}/volume-indicator.png")
# TV remote page, with a faked connected TV
restart("tv")
rt = f"{S}/run"
st = {
    "state": "connected",
    "device": "/dev/cec0",
    "driver": "vc4",
    "phys_addr": "2.0.0.0",
    "keys": True,
    "message": "",
    "last_button": "Red",
    "seen": ["red", "up", "down", "select"],
}
for i in range(10):
    json.dump(st, open(f"{rt}/tvwcs-cec.json", "w"))
    time.sleep(0.3)
sh("swaymsg exec '/usr/bin/tvwcs settings hotkeys'")
for i in range(12):
    json.dump(st, open(f"{rt}/tvwcs-cec.json", "w"))
    time.sleep(0.4)
wt = subprocess.Popen(
    ["wtype", "-s", "800", "-k", "Shift_L", "-s", "500", "-k", "Right", "-s", "800"]
    + ["-k", "Down", "-s", "250"] * 11
    + ["-s", "4000"],
    env=env(),
)
for i in range(15):
    json.dump(st, open(f"{rt}/tvwcs-cec.json", "w"))
    time.sleep(0.4)
shot(f"{O}/tv-remote.png")
wt.wait()
