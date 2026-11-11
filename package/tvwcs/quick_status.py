"""What the status icons at the bottom of the Quick Menu show: the network (and the Wi-Fi signal), the volume,
Bluetooth, the battery (and whether it is charging) and whether updates are waiting. No GTK dependency; each read is quick and safe to run on a worker thread
(the updates check is slow and is run rarely, see main.StatusWatcher)."""
from __future__ import annotations
import os
from dataclasses import dataclass

from tvwcs.control_cmd import have, run

@dataclass(frozen=True)
class Status:
    network: str="offline"   # "wired", "wifi" or "offline"
    signal: int=0            # Wi-Fi link quality, 0-100
    volume: int|None=None    # the default output's volume in percent; None without a sound server
    muted: bool=False
    bluetooth: str=""        # "" (no adapter), "off", "on" or "connected"
    updates: int=0           # updates waiting (system packages), from the last check
    battery: int|None=None   # the computer's battery in percent; None without one
    power: str=""            # "battery" (running on it), "charging", or "plugged" (plugged in, not charging: full)
    reboot: bool=False       # an update needs a restart to take effect (a new kernel), from the last check

# ---------------------------------------------------------------------- network
def default_interface(route_text):
    """/proc/net/route -> the interface of the default route with the lowest metric, or ""."""
    best=None
    for line in route_text.splitlines()[1:]:
        f=line.split()
        if len(f)<8 or f[1]!="00000000" or f[7]!="00000000": continue
        try: flags=int(f[3],16); metric=int(f[6])
        except ValueError: continue
        if flags&1 and (best is None or metric<best[1]): best=(f[0],metric)   # RTF_UP
    return best[0] if best else ""

def wifi_quality(wireless_text, iface):
    """/proc/net/wireless -> the interface's link quality in percent (out of 70, as Linux drivers report it)."""
    for line in wireless_text.splitlines()[2:]:
        name,_sep,rest=line.partition(":")
        if name.strip()!=iface: continue
        try: q=float(rest.split()[1].rstrip("."))
        except (IndexError,ValueError): return 0
        return max(0,min(100,round(q*100/70)))
    return 0

def _read(path):
    try:
        with open(path,encoding="ascii",errors="replace") as f: return f.read()
    except OSError: return ""

def read_network(route=None, wireless=None, is_wireless=None):
    iface=default_interface(_read("/proc/net/route") if route is None else route)
    if not iface: return "offline",0
    wifi=os.path.isdir(f"/sys/class/net/{iface}/wireless") if is_wireless is None else is_wireless(iface)
    if not wifi: return "wired",0
    return "wifi",wifi_quality(_read("/proc/net/wireless") if wireless is None else wireless,iface)

# ---------------------------------------------------------------------- volume
def parse_volume(volume_text, mute_text):
    """`pactl get-sink-volume @DEFAULT_SINK@` and `get-sink-mute` -> (percent of the first channel, muted)."""
    percent=None
    for word in volume_text.replace("/"," ").split():
        if word.endswith("%"):
            try: percent=int(word[:-1]); break
            except ValueError: pass
    return percent,"yes" in mute_text.lower()

def read_volume():
    if not have("pactl"): return None,False
    v=run(["pactl","get-sink-volume","@DEFAULT_SINK@"],timeout=3)
    if not v.ok: return None,False
    return parse_volume(v.out,run(["pactl","get-sink-mute","@DEFAULT_SINK@"],timeout=3).out)

# ---------------------------------------------------------------------- Bluetooth
def parse_bluetooth(show_text, connected_text):
    """`bluetoothctl show` and `bluetoothctl devices Connected` -> "", "off", "on" or "connected"."""
    if "Controller " not in show_text: return ""
    powered=any(l.strip().lower()=="powered: yes" for l in show_text.splitlines())
    if not powered: return "off"
    return "connected" if any(l.startswith("Device ") for l in connected_text.splitlines()) else "on"

def read_bluetooth():
    if not have("bluetoothctl") or not os.path.isdir("/sys/class/bluetooth"): return ""
    show=run(["bluetoothctl","show"],timeout=3)
    if not show.ok: return ""
    return parse_bluetooth(show.out,run(["bluetoothctl","devices","Connected"],timeout=3).out)

# ---------------------------------------------------------------------- updates (slow: package lists, Flathub)
def count_updates():
    from tvwcs import control_updates
    try: s=control_updates.read_state()
    except Exception: return 0   # a broken package manager never breaks the Quick Menu
    return s.all_total if s.available else 0

def check_updates():
    """-> (updates waiting, whether a restart is needed to finish the last update)."""
    from tvwcs import control_updates
    try: reboot=control_updates.reboot_needed()
    except Exception: reboot=False
    return count_updates(),reboot

# ---------------------------------------------------------------------- battery
def read_battery(root=None):
    """-> (percent or None, "battery" | "charging" | "plugged" | "")."""
    from tvwcs import power
    b=power.read_battery(root)
    if not b.present: return None,""
    return b.percent,("battery" if b.on_battery else "charging" if b.charging else "plugged")

def read(updates=0, reboot=False):
    network,signal=read_network(); volume,muted=read_volume(); battery,power=read_battery()
    return Status(network,signal,volume,muted,read_bluetooth(),updates,battery,power,reboot)

# ---------------------------------------------------------------------- what each icon shows
def network_icon(s):
    """(icon name, text glyph, tooltip)."""
    if s.network=="wired": return "network-wired-symbolic","🖧","Wired network connected"
    if s.network=="wifi":
        level=("none","weak","ok","good","excellent")[max(0,min(4,s.signal//20))]
        bars="▂▄▆█"[:max(1,min(4,(s.signal+24)//25))]
        return f"network-wireless-signal-{level}-symbolic",bars,f"Wi-Fi connected, signal {s.signal}%"
    return "network-offline-symbolic","✕","Not connected to a network"

def volume_icon(s):
    if s.volume is None: return "audio-volume-muted-symbolic","🔇","No sound output"
    if s.muted or s.volume==0: return "audio-volume-muted-symbolic","🔇",f"Muted ({s.volume}%)" if s.muted else "Volume 0%"
    level="low" if s.volume<34 else "medium" if s.volume<67 else "high"
    return f"audio-volume-{level}-symbolic",{"low":"🔈","medium":"🔉","high":"🔊"}[level],f"Volume {s.volume}%"

def bluetooth_icon(s):
    if s.bluetooth=="off": return "bluetooth-disabled-symbolic","ᛒ","Bluetooth is off"
    if s.bluetooth=="connected": return "bluetooth-active-symbolic","ᛒ","Bluetooth: a device is connected"
    return "bluetooth-active-symbolic","ᛒ","Bluetooth is on"

def battery_icon(s):
    """The level in steps of ten (the icon themes' battery-level-N icons), with a charging mark while plugged in."""
    if s.battery is None: return "battery-missing-symbolic","🔋","No battery"
    level=max(0,min(100,round(s.battery/10)*10))
    plugged="battery-level-100-charged-symbolic" if level==100 else f"battery-level-{level}-charging-symbolic"   # there is no 100-charging
    if s.power=="charging": return plugged,"⚡",f"Battery {s.battery}%, charging"
    if s.power=="plugged": return plugged,"🔌",f"Battery {s.battery}%, plugged in"
    return f"battery-level-{level}-symbolic","🔋",f"Battery {s.battery}%, on battery"

def updates_icon(s):
    """Updates waiting, or (after an update that needs it) a restart to finish updating."""
    waiting=f"{s.updates} update{'s' if s.updates!=1 else ''} available"
    if s.reboot: return "system-reboot-symbolic","↻","Restart to finish updating"+(f" ({waiting})" if s.updates else "")
    return "software-update-available-symbolic","⟳",waiting

def updates_shown(s): return s.updates>0 or s.reboot
