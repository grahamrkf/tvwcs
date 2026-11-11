"""TVWCS in the usual sway session (desktop mode): the one include line in the user's sway config, and where `tvwcs`
was started. No GTK dependency.

Plain `tvwcs` does what fits the place it runs in (main.main): in TVWCS's own session, or a sway session that includes
tvwcs.conf, it is the launcher; in another sway session Settings offers to add the include line; anywhere else (GNOME,
KDE, X11) it opens Settings, with the pages that only work in sway turned off. At a text console the launcher script
starts TVWCS's session instead (package/bin/tvwcs)."""
from __future__ import annotations
import json, os, re, shutil, subprocess
from pathlib import Path

CONF="/usr/share/tvwcs/tvwcs.conf"
INCLUDE=f"include {CONF}"
COMMENT="# TVWCS (desktop mode): its hotkeys, window rules and autostart. Added by TVWCS Settings."
STANDARD="/etc/sway/config"   # what sway reads when the user has no config of their own
_HAS=re.compile(r"^[ \t]*include[ \t]+\S*/usr/share/tvwcs/tvwcs\.conf[ \t]*$",re.M)

def where(env=None) -> str:
    """"tvwcs" (TVWCS's own session), "sway" (another sway session), "other" (another graphical session) or
    "console" (none)."""
    env=os.environ if env is None else env
    if env.get("SWAYSOCK"): return "tvwcs" if env.get("TVWCS_SESSION") else "sway"
    if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"): return "other"
    return "console"

def in_sway(env=None) -> bool:
    """Settings' sway pages work here: TVWCS's session or another sway session."""
    return where(env) in ("tvwcs","sway")

def user_config(env=None) -> Path:
    """The user's sway config, the same file sway reads: ~/.config/sway/config (XDG_CONFIG_HOME), else ~/.sway/config
    when only that one exists. It may not exist yet."""
    env=os.environ if env is None else env
    home=Path(env.get("HOME") or Path.home())
    xdg=Path(env.get("XDG_CONFIG_HOME") or home/".config")/"sway"/"config"
    old=home/".sway"/"config"
    return old if not xdg.exists() and old.exists() else xdg

def has_include(text) -> bool:
    return bool(_HAS.search(text or ""))

def running_config(run=subprocess.run) -> str:
    """The config the running sway loaded (swaymsg -t get_config), or "" when sway cannot be asked."""
    try:
        out=run(["swaymsg","-r","-t","get_config"],capture_output=True,text=True,timeout=3)
        return json.loads(out.stdout).get("config","") if out.returncode==0 else ""
    except (OSError,ValueError,subprocess.SubprocessError,AttributeError): return ""

def active(env=None, run=subprocess.run) -> bool:
    """TVWCS is part of this sway session: it is TVWCS's own session, or the running config or the user's config file
    includes tvwcs.conf."""
    if where(env)=="tvwcs": return True
    if has_include(running_config(run)): return True
    try: return has_include(user_config(env).read_text(encoding="utf-8",errors="replace"))
    except OSError: return False

def add(env=None, standard=STANDARD) -> Path:
    """Add the include line to the user's sway config (made from sway's standard config when there is none yet).
    A copy of the file from before is kept next to it as config.tvwcs-backup. Returns the file."""
    cfg=user_config(env)
    try: text=cfg.read_text(encoding="utf-8")
    except FileNotFoundError:
        cfg.parent.mkdir(parents=True,exist_ok=True)
        try: text=Path(standard).read_text(encoding="utf-8")
        except OSError: text=""
    else:
        backup=cfg.with_name(cfg.name+".tvwcs-backup")
        if not backup.exists(): shutil.copy2(cfg,backup)
    if has_include(text): return cfg
    if text and not text.endswith("\n"): text+="\n"
    tmp=cfg.with_name(cfg.name+".tvwcs-new"); tmp.write_text(f"{text}\n{COMMENT}\n{INCLUDE}\n",encoding="utf-8"); os.replace(tmp,cfg)
    return cfg

def launcher() -> Path:
    """The tvwcs launcher: /usr/bin/tvwcs for the package in /usr/lib/tvwcs, else the script next to the package (the
    repository layout)."""
    here=Path(__file__).resolve().parent          # .../tvwcs (the package)
    if here.parent==Path("/usr/lib/tvwcs"): return Path("/usr/bin/tvwcs")
    for cand in (here.parent/"bin"/"tvwcs", here/"tvwcs", here.parent.parent/"bin"/"tvwcs"):
        if cand.exists(): return cand
    return here.parent/"bin"/"tvwcs"              # sensible default even if missing

def start_launcher(popen=subprocess.Popen) -> bool:
    """Start TVWCS (`tvwcs launcher`) on its own, as sway's exec line would at the next login: sway does not run exec
    lines again when it reloads."""
    try: popen([str(launcher()),"launcher"],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return True
    except OSError: return False

def reload(run=subprocess.run) -> bool:
    """Have sway read its config again (the new hotkeys and window rules); False when it could not."""
    try: return run(["swaymsg","reload"],capture_output=True,timeout=5).returncode==0
    except (OSError,subprocess.SubprocessError): return False

RELOADED_NAME="tvwcs-sway-reloaded"   # in the runtime dir: when TVWCS last had sway read tvwcs.conf again

def conf_is_newer(conf_mtime, sway_started, last_reload=0.0) -> bool:
    """tvwcs.conf changed after sway last read it: after sway started (its IPC socket is made then) and after
    TVWCS's last reload."""
    return conf_mtime>max(sway_started,last_reload or 0.0)

def reload_if_updated(runtime, env=None, conf=CONF, run=subprocess.run, now=None) -> bool:
    """When an update installed a new tvwcs.conf while sway kept running, sway still has the old one's key bindings
    and window rules (the volume keys, say) until it reloads or the next login. The launcher calls this as it starts,
    which an update's restart does too: sway reloads once, and True says it did."""
    import time
    env=os.environ if env is None else env
    sock=env.get("SWAYSOCK")
    if not sock: return False
    mark=Path(runtime)/RELOADED_NAME
    try:
        # ctime: when the file was installed (dpkg, pacman and rpm keep the package's mtime, from when it was built)
        conf_mtime=os.stat(conf).st_ctime; started=os.stat(sock).st_ctime
    except OSError: return False
    try: last=float(mark.read_text(encoding="ascii").strip())
    except (OSError,ValueError): last=0.0
    if not conf_is_newer(conf_mtime,started,last) or not reload(run): return False
    try: mark.write_text(f"{time.time() if now is None else now}\n",encoding="ascii")
    except OSError: pass
    return True
