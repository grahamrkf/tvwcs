"""Script a TVWCS demo in a headless sway session, record it with wf-recorder and turn it into a captioned GIF.

Every key of a demo goes to ONE wtype run, with its pauses (-s) in between: each wtype run is a new virtual keyboard,
which takes the focus from TVWCS. So a demo is planned first (keys, pauses and captions on one timeline), then played.
The headless session has no pointer, so the demos are driven by keyboard only."""

import subprocess, time, os, sys, json, signal

S = os.path.dirname(os.path.abspath(__file__))
FONT = "/usr/share/fonts/truetype/open-sans/OpenSans-Semibold.ttf"


def env():
    e = dict(os.environ)
    out = subprocess.run(["sh", "-c", f". {S}/env.sh; env"], capture_output=True, text=True).stdout
    e.update(dict(l.split("=", 1) for l in out.splitlines() if "=" in l))
    run = e["XDG_RUNTIME_DIR"]
    socks = [f for f in os.listdir(run) if f.startswith("sway-ipc.")]
    if socks:
        e["SWAYSOCK"] = f"{run}/{socks[0]}"
    return e


def restart(use):
    subprocess.run([f"{S}/restart.sh", use], check=True)
    time.sleep(1)


def sh(cmd):
    return subprocess.run(cmd, shell=True, env=env(), capture_output=True, text=True).stdout


def shot(path):
    sh(f"grim {path}")


def menu_shown():
    return "TVWCS" in sh("swaymsg -t get_tree | jq -r '.. | objects | select(.visible==true) | .name'")


class Demo:
    def __init__(self, name, note_x="(w-text_w)/2"):
        self.name = name
        self.note_x = note_x
        self.t = 0
        self.args = ["-s", "1000"]
        self.t = 1000
        self.caps = []
        os.makedirs(f"{S}/out", exist_ok=True)

    def wait(self, s):
        ms = int(s * 1000)
        self.args += ["-s", str(ms)]
        self.t += ms

    def key(self, k, after=0.0):
        self.args += ["-k", k]
        self.t += 15
        self.wait(after) if after else None

    def combo(self, mod, k, after=0.0):
        self.args += ["-M", mod, k, "-m", mod]
        self.t += 15
        self.wait(after) if after else None

    def typ(self, s, per=0.35):
        for ch in s:
            self.args.append(ch)
            self.t += 15
            self.wait(per)

    def cap(self, text, pos="key"):
        self.end(pos)
        self.caps.append([self.t / 1000, None, text, pos])

    def end(self, pos="key"):
        for c in self.caps:
            if c[3] == pos and c[1] is None:
                c[1] = self.t / 1000

    def play(self):
        for p in ("key", "title", "note"):
            self.end(p)
        raw = f"{S}/out/{self.name}-raw.mkv"
        e = env()
        if os.path.exists(raw):
            os.remove(raw)
        rec = subprocess.Popen(
            ["wf-recorder", "-y", "-c", "libx264", "-p", "preset=ultrafast", "-p", "crf=12", "-f", raw],
            env=e,
            stdout=subprocess.DEVNULL,
            stderr=open(f"{S}/out/{self.name}-rec.log", "w"),
        )
        time.sleep(1.5)
        subprocess.run(["wtype"] + self.args, env=e)
        time.sleep(1.0)
        rec.send_signal(signal.SIGINT)
        try:
            rec.wait(5)
        except subprocess.TimeoutExpired:
            rec.kill()
            rec.wait()  # with -r it can ignore SIGINT; the mkv stays readable
        if not os.path.exists(raw):
            sys.exit(f"wf-recorder made no {raw}: see the -rec.log next to it")
        for c in self.caps:
            c[0] += 1.5
            c[1] += 1.5
        json.dump(self.caps, open(f"{S}/out/{self.name}-caps.json", "w"))
        self.render()

    def render(self):
        caps = json.load(open(f"{S}/out/{self.name}-caps.json"))
        f = []
        for i, (a, b, text, pos) in enumerate(caps):
            tf = f"{S}/out/{self.name}-cap{i}.txt"
            open(tf, "w").write(text)
            if pos == "title":
                geo = "x=(w-text_w)/2:y=(h-text_h)/2:fontsize=54:boxborderw=40"
            elif pos == "note":
                geo = f"x={self.note_x}:y=110:fontsize=40:boxborderw=22"
            else:
                geo = "x=w-text_w-60:y=h-text_h-150:fontsize=46:boxborderw=24"
            f.append(
                f"drawtext=fontfile={FONT}:textfile={tf}:fontcolor=white:box=1:boxcolor=0x000000@0.78:line_spacing=12:{geo}:enable='gte(t,{a:.2f})*lt(t,{b:.2f})'"
            )
        vf = ",".join(
            f
            + [
                "fps=8",
                "scale=800:-1:flags=lanczos",
                "split[a][b]",
                "[a]palettegen=max_colors=128[p]",
                "[b][p]paletteuse=dither=bayer",
            ]
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                f"{S}/out/{self.name}-raw.mkv",
                "-vf",
                vf,
                f"{S}/out/{self.name}.gif",
            ],
            check=True,
        )
