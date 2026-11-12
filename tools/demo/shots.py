"""README screenshots in TV mode: assets/quick-menu.png, guide-menu.png and options.png (into out/)."""

import sys, os, json, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo import *


def rect():
    t = json.loads(sh("swaymsg -t get_tree"))

    def walk(n):
        if n.get("name") == "TVWCS" and n.get("visible"):
            return n["rect"]
        for c in n.get("nodes", []) + n.get("floating_nodes", []):
            r = walk(c)
            if r:
                return r

    return walk(t)


if __name__ == "__main__":
    restart("tv")
    # open three apps (one wtype run: a new one takes the focus from TVWCS), then show the Quick Menu with the newest selected
    e = env()
    seq = [
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
        "1500",
        "1",
        "-s",
        "300",
        "2",
        "-s",
        "400",
        "-k",
        "Return",
        "-s",
        "5000",
        "-k",
        "F2",
        "-s",
        "1500",
        "retro",
        "-s",
        "1200",
        "-k",
        "Return",
        "-s",
        "7000",
        "-k",
        "F2",
        "-s",
        "2000",
        "-k",
        "Up",
        "-s",
        "2000",
        "-k",
        "Right",
        "-s",
        "5000",
    ]
    wt = subprocess.Popen(["wtype"] + seq, env=e)
    time.sleep(26.3)
    r = rect()
    shot(f"{S}/out/full.png")  # the Quick Menu, before Right
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            f"{S}/out/full.png",
            "-vf",
            f"crop={r['width']}:{r['height']}:{r['x']}:{r['y']}",
            f"{S}/out/quick-menu.png",
        ],
        check=True,
    )
    time.sleep(3.5)
    shot(f"{S}/out/guide-menu.png")
    wt.wait()
    restart("tv")
    sh("swaymsg exec '/usr/bin/tvwcs settings appearance'")
    time.sleep(5)
    shot(f"{S}/out/options.png")
