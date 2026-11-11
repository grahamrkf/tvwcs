"""Sound for Settings: outputs, inputs and their volume, through `pactl`. No GTK dependency.

`pactl` talks to PulseAudio and to PipeWire (through pipewire-pulse), so this covers every mainstream distribution.
Inputs leave out the "Monitor of …" sources PulseAudio makes for every output: they are not microphones.

A sound card only has outputs for its active profile: a computer whose card is on "Analog Stereo" has no HDMI output
at all until the card is switched to an HDMI profile (and a graphics card's HDMI sound often starts switched off).
So the outputs of every card's other profiles are listed too, and choosing one switches the card to it."""
from __future__ import annotations
import re, subprocess, sys, threading, time
from dataclasses import dataclass, field

from tvwcs import distro
from tvwcs.control_cmd import c_env, have, key_values, run

VOLUME_STEP=5      # percent per press of − / +
MAX_VOLUME=100     # pactl allows more (amplified, distorting): capped here unless Settings > Sound > Over-amplification is on
LOUDEST=150        # the most a volume is ever set to, with over-amplification on
def top(boost=False): return LOUDEST if boost else MAX_VOLUME

@dataclass
class Port:
    name: str
    label: str
    available: bool = True

@dataclass
class Device:
    kind: str            # "sink" (an output) or "source" (an input)
    index: int
    name: str
    description: str
    volume: int          # percent, the average of the channels
    muted: bool
    ports: list = field(default_factory=list)
    active_port: str = ""
    is_monitor: bool = False
    icon: str = ""
    @property
    def label(self): return self.description or self.name
    @property
    def unplugged(self):
        """The device says nothing is plugged into any of its connectors (a headphone jack, an HDMI port without a TV)."""
        return bool(self.ports) and not any(p.available for p in self.ports)

@dataclass
class CardOutput:
    """An output a sound card has in a profile that is not active now, such as its HDMI output."""
    card: str            # the card's name (alsa_card.…)
    card_label: str
    output: str          # the output part of the profile: "output:hdmi-stereo"
    label: str           # "Digital Stereo (HDMI) Output"
    available: bool      # False: the card says nothing is plugged in there (it can still be tried)
    profile: str = ""    # the profile to switch the card to
    @property
    def hdmi(self): return "hdmi" in self.output or "HDMI" in self.label or "DisplayPort" in self.label

@dataclass
class Card:
    name: str
    description: str = ""
    active: str = ""
    profiles: list = field(default_factory=list)   # [(name, label, available)]

@dataclass
class SoundState:
    available: bool
    message: str = ""
    server: str = ""
    outputs: list = field(default_factory=list)
    inputs: list = field(default_factory=list)
    default_output: str = ""
    default_input: str = ""
    other_outputs: list = field(default_factory=list)   # [CardOutput]
    alsa_cards: int = -1  # sound cards the kernel has (-1: unknown); none means a driver or its firmware is missing
    def output(self): return next((d for d in self.outputs if d.name==self.default_output),self.outputs[0] if self.outputs else None)
    def input(self): return next((d for d in self.inputs if d.name==self.default_input),self.inputs[0] if self.inputs else None)

_HEADER=re.compile(r"^(Sink|Source) #(\d+)\s*$")
_PERCENT=re.compile(r"(\d+)%")

def parse_devices(text, kind):
    """`pactl list sinks` or `pactl list sources` (C locale) -> [Device]."""
    devices=[]; cur=None; section=""
    for line in text.splitlines():
        m=_HEADER.match(line)
        if m:
            cur=Device(kind,int(m.group(2)),"","",0,False); devices.append(cur); section=""; continue
        if cur is None or not line.strip(): continue
        depth=len(line)-len(line.lstrip("\t"))
        stripped=line.strip()
        if depth==1:
            key,_,value=stripped.partition(":"); value=value.strip(); section=key
            if key=="Name": cur.name=value
            elif key=="Description": cur.description=value
            elif key=="Mute": cur.muted=value=="yes"
            elif key=="Volume":
                levels=[int(p) for p in _PERCENT.findall(value)]
                cur.volume=round(sum(levels)/len(levels)) if levels else 0
            elif key=="Active Port": cur.active_port=value
            elif key=="Monitor of Sink": cur.is_monitor=value not in ("","n/a")
        elif depth>=2 and section=="Properties":
            key,_,value=stripped.partition("=")
            key=key.strip(); value=value.strip().strip('"')
            if key=="device.class" and value=="monitor": cur.is_monitor=True
            elif key=="device.icon_name": cur.icon=value
        elif depth==2 and section=="Ports":
            name,found,rest=stripped.partition(": ")
            if found:   # "analog-output-speaker: Speakers (type: Speaker, priority: 10000, availability unknown)"
                label,_,details=rest.rpartition(" (") if rest.endswith(")") else (rest,"","")
                cur.ports.append(Port(name,label or rest,"not available" not in details))
    return devices

_CARD=re.compile(r"^Card #(\d+)\s*$")
_PROFILE=re.compile(r"^(\S+): (.*?)(?: \(([^()]*)\))?$")   # the last (…) holds sinks, sources, priority, available

def parse_cards(text):
    """`pactl list cards` (C locale) -> [Card]."""
    cards=[]; cur=None; section=""
    for line in text.splitlines():
        if _CARD.match(line): cur=Card(""); cards.append(cur); section=""; continue
        if cur is None or not line.strip(): continue
        depth=len(line)-len(line.lstrip("\t")); stripped=line.strip()
        if depth==1:
            key,_,value=stripped.partition(":"); value=value.strip(); section=key
            if key=="Name": cur.name=value
            elif key=="Active Profile": cur.active=value
        elif depth==2 and section=="Properties":
            key,_,value=stripped.partition("=")
            if key.strip()=="device.description": cur.description=value.strip().strip('"')
        elif depth==2 and section=="Profiles":
            m=_PROFILE.match(stripped)
            if m: cur.profiles.append((m.group(1),m.group(2),"available: no" not in (m.group(3) or "")))
    return cards

def other_outputs(cards):
    """The outputs each card has in profiles other than its active one: [CardOutput], one per output."""
    found=[]
    for card in cards:
        active=set(card.active.split("+")); names={name for name,_l,_a in card.profiles}
        keep_input=next((part for part in card.active.split("+") if part.startswith("input:")),"")
        seen=set()
        for name,label,available in card.profiles:
            parts=name.split("+")
            out=next((p for p in parts if p.startswith("output:")),"")
            if not out or out in active or out in seen: continue
            seen.add(out)
            plain=next(((l,a) for n,l,a in card.profiles if n==out),None)   # the output alone names it best
            out_label,out_available=plain if plain else (label.split(" + ")[0],available)
            profile=f"{out}+{keep_input}" if keep_input and f"{out}+{keep_input}" in names else out if out in names else name
            found.append(CardOutput(card.name,card.description or card.name,out,out_label,out_available,profile))
    return sorted(found,key=lambda o:(not o.hdmi,not o.available,o.card_label,o.label))

def split_unplugged(devices, in_use=""):
    """(the devices to show, the ones with nothing plugged in). The one in use is always shown."""
    shown=[d for d in devices if d.name==in_use or not d.unplugged]
    return shown,[d for d in devices if d not in shown]

def sink_for(card_name, output):
    """The sink PipeWire and PulseAudio make for a card's output: alsa_card.X + output:hdmi-stereo -> alsa_output.X.hdmi-stereo."""
    base=card_name.split(".",1)[1] if card_name.startswith("alsa_card.") else card_name
    return f"alsa_output.{base}.{output.split(':',1)[1]}"

def count_alsa_cards(path="/proc/asound/cards"):
    try: text=open(path,encoding="utf-8",errors="replace").read()
    except OSError: return -1
    return sum(1 for line in text.splitlines() if re.match(r"^\s*\d+ \[",line))

def parse_info(text):
    """`pactl info` -> (default sink, default source, server name)."""
    info=key_values(text)
    return info.get("Default Sink",""),info.get("Default Source",""),info.get("Server Name","")

def server_label(server):
    """'PulseAudio (on PipeWire 1.0.5)' -> 'PipeWire 1.0.5'; 'pulseaudio' -> 'PulseAudio'."""
    m=re.search(r"on (PipeWire[^)]*)\)",server)
    if m: return m.group(1).strip()
    return "PulseAudio" if server.lower().startswith("pulseaudio") else server

def read_state():
    if not have("pactl"):
        return SoundState(False,"Sound settings need pactl, from PulseAudio or PipeWire (the "
                          +("libpulse" if distro.is_arch() else "pulseaudio-utils or pipewire-pulseaudio" if distro.is_fedora() else "pulseaudio-utils or pipewire-pulse")+" package).")
    info=run(["pactl","info"],timeout=5)
    if not info.ok:
        return SoundState(False,f"No sound server is answering ({info.message}). Is PipeWire or PulseAudio running?")
    sinks=run(["pactl","list","sinks"],timeout=5); sources=run(["pactl","list","sources"],timeout=5)
    default_sink,default_source,server=parse_info(info.out)
    inputs=[d for d in parse_devices(sources.out,"source") if not d.is_monitor]
    cards=run(["pactl","list","cards"],timeout=5)
    return SoundState(True,"",server_label(server),parse_devices(sinks.out,"sink"),inputs,default_sink,default_source,
                      other_outputs(parse_cards(cards.out)),count_alsa_cards())

def stepped(volume, step, boost=False):
    """The next volume a − / + press lands on: a multiple of VOLUME_STEP, within 0..100 % (150 % with
    over-amplification, `boost`). A volume already above that (set by another program) comes down to the top."""
    target=(volume//VOLUME_STEP+1)*VOLUME_STEP if step>0 else max(0,volume-1)//VOLUME_STEP*VOLUME_STEP
    return max(0,min(top(boost),target))

def set_volume(device, percent, boost=False):
    return run(["pactl",f"set-{device.kind}-volume",device.name,f"{max(0,min(top(boost),int(percent)))}%"],timeout=5)

def volume_key(step, boost=False):
    """A volume key on the remote or keyboard (`tvwcs volume up|down`, bound in tvwcs.conf): the output in use one
    step up or down, stopping at the same top as Settings (100 %, or 150 % with over-amplification). Sway's standard
    config binds these keys to a plain `pactl set-sink-volume +5%`, which has no top."""
    from tvwcs.quick_status import parse_volume
    current=run(["pactl","get-sink-volume","@DEFAULT_SINK@"],timeout=3)
    if not current.ok: return current
    volume=parse_volume(current.out,"")[0]
    if volume is None: return current
    return run(["pactl","set-sink-volume","@DEFAULT_SINK@",f"{stepped(volume,step,boost)}%"],timeout=3)

def loud_outputs(text, most):
    """`pactl list sinks` (C locale) -> the names of the outputs with a channel above `most` %."""
    found=[]; name=""
    for line in text.splitlines():
        if _HEADER.match(line): name=""; continue
        if not line.startswith("\t") or line.startswith("\t\t"): continue
        key,_,value=line.strip().partition(":")
        if key=="Name": name=value.strip()
        elif key=="Volume" and name and any(int(p)>most for p in _PERCENT.findall(value)): found.append(name)
    return found

def keep_under_top(boost=False):
    """Bring every output above the top (100 %, or 150 % with over-amplification) back down to it. Returns their names."""
    listed=run(["pactl","list","sinks"],timeout=5)
    if not listed.ok: return []
    loud=loud_outputs(listed.out,top(boost))
    for name in loud: run(["pactl","set-sink-volume",name,f"{top(boost)}%"],timeout=5)
    return loud

_OUTPUT_EVENT=re.compile(r"'(new|change)' on sink #")

class VolumeGuard:
    """Keeps the volume limit whatever raised the volume: a volume key bound by another config, pavucontrol, an app,
    `pactl` in a terminal. It follows `pactl subscribe` and brings an output above the top straight back down (run by
    the launcher; `boost` says whether over-amplification is on now). It restarts `pactl subscribe` when the sound
    server goes away (PipeWire restarted, say)."""
    RETRY=5   # seconds before following the sound server again
    def __init__(self, boost, popen=subprocess.Popen, check=keep_under_top):
        self.boost=boost; self.popen=popen; self.check=check
        self.proc=None; self.thread=None; self.stopping=threading.Event()
    def start(self):
        """Start following the sound server (once), and look at the volumes now (the setting may have changed)."""
        if not have("pactl"): return
        if self.thread is None or not self.thread.is_alive():
            self.stopping.clear(); self.thread=threading.Thread(target=self._follow,daemon=True); self.thread.start()
        else: threading.Thread(target=self._check,daemon=True).start()
    def stop(self):
        self.stopping.set()
        proc=self.proc
        if proc is not None:
            try: proc.terminate()
            except OSError: pass
    def _check(self):
        try: self.check(bool(self.boost()))
        except Exception: pass   # the guard must never take the launcher down
    def _follow(self):
        while not self.stopping.is_set():
            self._check()
            try: self.proc=self.popen(["pactl","subscribe"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,text=True,env=c_env())
            except OSError: self.stopping.wait(self.RETRY*6); continue
            try:
                for line in self.proc.stdout:
                    if self.stopping.is_set(): break
                    if _OUTPUT_EVENT.search(line): self._check()
            finally:
                try: self.proc.terminate(); self.proc.wait(timeout=2)
                except (OSError,subprocess.SubprocessError): pass
                self.proc=None
            self.stopping.wait(self.RETRY)

def main(args):
    """`tvwcs volume up|down` (no GTK, so a held key keeps up)."""
    if len(args)!=2 or args[0]!="volume" or args[1] not in ("up","down"):
        print("Usage: tvwcs volume up|down",file=sys.stderr); return 2
    from tvwcs.model import ConfigStore
    return 0 if volume_key(1 if args[1]=="up" else -1,bool(ConfigStore().settings["audio_boost"])).ok else 1

def set_muted(device, muted):
    return run(["pactl",f"set-{device.kind}-mute",device.name,"1" if muted else "0"],timeout=5)

def set_port(device, port):
    return run(["pactl",f"set-{device.kind}-port",device.name,port],timeout=5)

def use_card_output(o):
    """Switch the card to the profile with this output, then make that output the one in use (moving what plays)."""
    result=run(["pactl","set-card-profile",o.card,o.profile],timeout=10)
    if not result.ok: return result
    wanted=sink_for(o.card,o.output)
    for _ in range(20):   # the new output appears a moment after the switch
        sinks=parse_devices(run(["pactl","list","sinks"],timeout=5).out,"sink")
        sink=next((d for d in sinks if d.name==wanted),None) or next((d for d in sinks if d.name.startswith(wanted)),None)
        if sink is not None: return make_default(sink)
        time.sleep(0.25)
    return result

def parse_short_streams(text):
    """`pactl list short sink-inputs` -> [stream index]."""
    return [int(line.split()[0]) for line in text.splitlines() if line.split() and line.split()[0].isdigit()]

def make_default(device):
    """Use this device from now on. Sound already playing moves too (PipeWire does that by itself; PulseAudio does not)."""
    result=run(["pactl",f"set-default-{device.kind}",device.name],timeout=5)
    if result.ok:
        streams=run(["pactl","list","short","sink-inputs" if device.kind=="sink" else "source-outputs"],timeout=5)
        for index in parse_short_streams(streams.out):
            run(["pactl","move-sink-input" if device.kind=="sink" else "move-source-output",str(index),device.name],timeout=5)
    return result

if __name__=="__main__": raise SystemExit(main(sys.argv[1:]))
