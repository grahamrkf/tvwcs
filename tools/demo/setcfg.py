import sys, json, uuid

p = sys.argv[2]
use = sys.argv[3]
d = json.load(open(p))
d["settings"]["theme"] = "light" if use == "desktop" else "dark"
d["settings"]["keyboard"] = "hidden"
chans = (
    {"mockup-streamly.desktop": 4, "mockup-gameshelf.desktop": 12, "mockup-retrobox.desktop": 21} if use == "tv" else {}
)
names = {
    "mockup-streamly.desktop": "Streamly (Mockup)",
    "mockup-gameshelf.desktop": "GameShelf (Mockup)",
    "mockup-retrobox.desktop": "RetroBox Console (Mockup)",
    "mockup-orbit.desktop": "Orbit Browser (Mockup)",
    "mockup-lantern.desktop": "Lantern Browser (Mockup)",
    "mockup-pagewright.desktop": "Pagewright Writer (Mockup)",
    "mockup-gridline.desktop": "Gridline Sheets (Mockup)",
}
fav = {
    "tv": ["mockup-streamly.desktop", "mockup-gameshelf.desktop"],
    "desktop": ["mockup-orbit.desktop", "mockup-pagewright.desktop"],
}[use]
keep = [
    x for x in d["profiles"] if x["desktop_id"] not in names and x["desktop_id"] != "com.tvwcs.ControlPanel.desktop"
]
for x in keep:
    x["favorite"] = False
settings = [x for x in d["profiles"] if x["desktop_id"] == "com.tvwcs.ControlPanel.desktop"]
for x in settings:
    x["favorite"] = False
    x["channel"] = 0
d["profiles"] = (
    settings
    + keep
    + [
        {
            "id": str(uuid.uuid4()),
            "desktop_id": k,
            "name": v,
            "command": "",
            "channel": chans.get(k),
            "favorite": k in fav,
            "launch_mode": "same",
            "desktop_action": "",
            "pin_hash": "",
            "pin_scope": "launch",
            "description": "",
            "hotkey": "",
        }
        for k, v in names.items()
    ]
)
json.dump(d, open(p, "w"), indent=2)
print(use, d["settings"]["theme"])
import os

if True:
    d = json.load(open(p))
    d["settings"]["style"] = os.environ.get("DEMO_STYLE", "modern")
    d["settings"]["media_look"] = os.environ.get("DEMO_LOOK", "jellyfin")
    json.dump(d, open(p, "w"), indent=2)
