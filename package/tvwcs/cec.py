"""HDMI-CEC: the TV's own remote drives TVWCS and the apps (5.20.0).

Linux shows an HDMI port that can talk CEC (a Raspberry Pi 4 or 5's, or a USB adapter such as Pulse-Eight's) as
/dev/cecN. TVWCS claims a playback device address on it, named "TVWCS", so the TV lists it as a source and forwards
its remote's buttons (CEC "User Control Pressed"). Each button becomes an ordinary key press on a virtual keyboard
(/dev/uinput): OK is Enter, Exit or Return is Esc, the arrows, numbers and play/pause keys are themselves. The button
chosen in Settings > Remote and hotkeys opens the Quick Menu instead. TVWCS also switches the TV to itself when it
starts or wakes, turns the TV off when the computer sleeps or shuts down, and can put the computer to sleep when the
TV turns off.

The kernel answers the TV's questions about the device (its address, name, vendor and CEC version); the rest are
answered here, as a CEC follower: power status, menu status, which source is active, and "not supported" (Feature
Abort) for anything else sent to it. Which buttons a TV forwards differs by make; Settings shows the last one received.

The parts that decode and answer messages (CecLogic) have no I/O and are unit-tested; Adapter and VirtualKeyboard are
thin wrappers over the kernel's ioctls; CecService joins them on the GLib main loop of the running TVWCS. The package's
udev rule (70-tvwcs-cec.rules) gives the person at the computer access to /dev/cec* and /dev/uinput, as Steam's rule
does for /dev/uinput.
"""
from __future__ import annotations
import errno, fcntl, glob, json, os, struct, sys, time
from dataclasses import dataclass, field

DEVICE_GLOB="/dev/cec[0-9]*"
UINPUT="/dev/uinput"
OSD_NAME="TVWCS"
STATUS_NAME="tvwcs-cec.json"   # in the runtime dir: what the running TVWCS sees, for Settings

# ---------------------------------------------------------------------- the kernel's interface (linux/cec.h)
# The same numbers on every architecture Linux shares _IOC with (x86, arm, arm64); the structs have no
# pointer-sized fields, so their layouts match too.
CEC_ADAP_G_CAPS=0xc04c6100
CEC_ADAP_G_PHYS_ADDR=0x80026101
CEC_ADAP_G_LOG_ADDRS=0x805c6103
CEC_ADAP_S_LOG_ADDRS=0xc05c6104
CEC_TRANSMIT=0xc0386105
CEC_RECEIVE=0xc0386106
CEC_DQEVENT=0xc0506107
CEC_S_MODE=0x40046109
CEC_MODE_INITIATOR=0x01
CEC_MODE_FOLLOWER=0x10
CEC_EVENT_STATE_CHANGE=1
CEC_EVENT_LOST_MSGS=2
CEC_TX_STATUS_OK=0x01
CEC_RX_STATUS_OK=0x01
CEC_CAP_TRANSMIT=1<<2
PHYS_ADDR_INVALID=0xffff
LOG_ADDR_TV=0
LOG_ADDR_UNREGISTERED=15
LOG_ADDR_BROADCAST=15

CAPS=struct.Struct("=32s32sIII")                    # struct cec_caps (76 bytes)
MSG=struct.Struct("=QQIIII16sBBBBBBBx")              # struct cec_msg (56 bytes)
LOG_ADDRS=struct.Struct("=4sHBBII15s4s4s4s48sx")     # struct cec_log_addrs (92 bytes)
EVENT=struct.Struct("=QII64s")                       # struct cec_event (80 bytes)
STATE_CHANGE=struct.Struct("=HHH")                   # its state_change member
assert (CAPS.size,MSG.size,LOG_ADDRS.size,EVENT.size)==(76,56,92,80)

CEC_VERSION_1_4=5
LOG_ADDR_TYPE_PLAYBACK=3
PRIM_DEVTYPE_PLAYBACK=4
ALL_DEVTYPE_PLAYBACK=0x10
VENDOR_ID_NONE=0xffffffff

# ---------------------------------------------------------------------- messages (CEC 1.4)
FEATURE_ABORT=0x00; IMAGE_VIEW_ON=0x04; STANDBY=0x36; USER_CONTROL_PRESSED=0x44; USER_CONTROL_RELEASED=0x45
ROUTING_CHANGE=0x80; ROUTING_INFORMATION=0x81; ACTIVE_SOURCE=0x82; REQUEST_ACTIVE_SOURCE=0x85; SET_STREAM_PATH=0x86
MENU_REQUEST=0x8D; MENU_STATUS=0x8E; GIVE_DEVICE_POWER_STATUS=0x8F; REPORT_POWER_STATUS=0x90; INACTIVE_SOURCE=0x9D
ABORT=0xFF
ABORT_UNRECOGNIZED=0; ABORT_REFUSED=4
POWER_ON=0; MENU_ACTIVATED=0

def header(initiator, destination): return bytes([(initiator&15)<<4|(destination&15)])
def phys_bytes(pa): return bytes([pa>>8&255,pa&255])
def phys_text(pa):
    """0x2000 -> "2.0.0.0", the TV's HDMI 2 (its first digit is the TV's input)."""
    return "" if pa in (None,PHYS_ADDR_INVALID) else ".".join(str(pa>>s&15) for s in (12,8,4,0))

def image_view_on(la): return header(la,LOG_ADDR_TV)+bytes([IMAGE_VIEW_ON])
def active_source(la, pa): return header(la,LOG_ADDR_BROADCAST)+bytes([ACTIVE_SOURCE])+phys_bytes(pa)
def inactive_source(la, pa): return header(la,LOG_ADDR_TV)+bytes([INACTIVE_SOURCE])+phys_bytes(pa)
def standby(la, destination=LOG_ADDR_TV): return header(la,destination)+bytes([STANDBY])
def report_power_status(la, to, status=POWER_ON): return header(la,to)+bytes([REPORT_POWER_STATUS,status])
def menu_status(la, to, status=MENU_ACTIVATED): return header(la,to)+bytes([MENU_STATUS,status])
def feature_abort(la, to, opcode, reason=ABORT_UNRECOGNIZED): return header(la,to)+bytes([FEATURE_ABORT,opcode,reason])

# ---------------------------------------------------------------------- the remote's buttons
# Linux key codes (linux/input-event-codes.h), all under 248 so every keyboard layout has a key name for them.
KEY_ESC=1; KEY_1=2; KEY_0=11; KEY_BACKSPACE=14; KEY_ENTER=28; KEY_DOT=52; KEY_UP=103; KEY_PAGEUP=104; KEY_LEFT=105
KEY_RIGHT=106; KEY_DOWN=108; KEY_PAGEDOWN=109; KEY_MUTE=113; KEY_VOLUMEDOWN=114; KEY_VOLUMEUP=115; KEY_COMPOSE=127
KEY_NEXTSONG=163; KEY_PLAYPAUSE=164; KEY_PREVIOUSSONG=165; KEY_STOPCD=166; KEY_REWIND=168; KEY_HOMEPAGE=172
KEY_PLAYCD=200; KEY_PAUSECD=201; KEY_FASTFORWARD=208

@dataclass(frozen=True)
class Button:
    code: int        # CEC user control code
    id: str          # how settings name it
    label: str
    key: int|None    # the key it presses; None: it does nothing unless it is a hotkey

BUTTONS=tuple(Button(*b) for b in (
    (0x00,"select","OK",KEY_ENTER),(0x01,"up","Up",KEY_UP),(0x02,"down","Down",KEY_DOWN),(0x03,"left","Left",KEY_LEFT),
    (0x04,"right","Right",KEY_RIGHT),(0x09,"root_menu","Home (Root Menu)",KEY_HOMEPAGE),(0x0A,"setup_menu","Setup Menu",None),
    (0x0B,"contents_menu","Contents Menu",KEY_COMPOSE),(0x0C,"favorite_menu","Favorites",None),(0x0D,"exit","Back (Exit)",KEY_ESC),
    (0x10,"top_menu","Top Menu",None),(0x11,"context_menu","Options (Context Menu)",KEY_COMPOSE),
    *((0x20+n,f"digit_{n}",str(n),KEY_0 if n==0 else KEY_1+n-1) for n in range(10)),
    (0x2A,"dot","Dot",KEY_DOT),(0x2B,"enter","Enter",KEY_ENTER),(0x2C,"clear","Clear",KEY_BACKSPACE),
    (0x30,"channel_up","Channel up",KEY_PAGEUP),(0x31,"channel_down","Channel down",KEY_PAGEDOWN),
    (0x32,"previous_channel","Previous channel",None),(0x35,"info","Info (Display Information)",None),
    (0x37,"page_up","Page up",KEY_PAGEUP),(0x38,"page_down","Page down",KEY_PAGEDOWN),
    (0x41,"volume_up","Volume up",KEY_VOLUMEUP),(0x42,"volume_down","Volume down",KEY_VOLUMEDOWN),(0x43,"mute","Mute",KEY_MUTE),
    (0x44,"play","Play",KEY_PLAYCD),(0x45,"stop","Stop",KEY_STOPCD),(0x46,"pause","Pause",KEY_PAUSECD),
    (0x48,"rewind","Rewind",KEY_REWIND),(0x49,"fast_forward","Fast forward",KEY_FASTFORWARD),
    (0x4B,"next","Next",KEY_NEXTSONG),(0x4C,"previous","Previous",KEY_PREVIOUSSONG),(0x53,"guide","Guide (EPG)",None),
    (0x60,"play_function","Play",KEY_PLAYCD),(0x61,"play_pause","Play/pause",KEY_PLAYPAUSE),(0x64,"stop_function","Stop",KEY_STOPCD),
    (0x71,"blue","Blue",None),(0x72,"red","Red",None),(0x73,"green","Green",None),(0x74,"yellow","Yellow",None),
    (0x76,"data","Data",None),
))
BY_CODE={b.code:b for b in BUTTONS}
BY_ID={b.id:b for b in BUTTONS}
KEYS=sorted({b.key for b in BUTTONS if b.key is not None})
# The ones that move around and choose: never a hotkey, so a TV remote can always get out of Settings.
NAVIGATION=frozenset(("select","up","down","left","right","exit","enter"))
_FIRST=("red","green","yellow","blue","root_menu","info","guide","setup_menu","contents_menu","context_menu","favorite_menu","top_menu",
        "previous_channel","data")   # the buttons a TV most often passes on that do nothing else, first
HOTKEY_CHOICES=tuple(BY_ID[i] for i in _FIRST)+tuple(b for b in BUTTONS if b.id not in NAVIGATION and not b.id.startswith("digit_") and b.id not in _FIRST)
DEFAULT_MENU_BUTTON="red"
REPEAT_GAP=0.6   # s: a TV sends User Control Pressed again about every 0.5 s while a button is held

DEFAULTS={"enabled":True,"wake_tv":True,"tv_standby":True,"follow_tv":False,"menu":DEFAULT_MENU_BUTTON}
def clean_settings(raw):
    """Settings > Remote and hotkeys' CEC options from config.json."""
    s=dict(DEFAULTS)
    if not isinstance(raw,dict): return s
    for k in ("enabled","wake_tv","tv_standby","follow_tv"):
        if isinstance(raw.get(k),bool): s[k]=raw[k]
    menu=raw.get("menu")
    if menu=="" or (isinstance(menu,str) and menu in BY_ID and menu not in NAVIGATION and not menu.startswith("digit_")): s["menu"]=menu
    return s

def button_label(button_id):
    return BY_ID[button_id].label if button_id in BY_ID else "None"

def adapters(pattern=DEVICE_GLOB, globber=glob.glob):
    """The CEC devices, /dev/cec0 first."""
    return sorted(globber(pattern),key=lambda p:(len(p),p))
def present(pattern=DEVICE_GLOB, globber=glob.glob): return bool(adapters(pattern,globber))

# ---------------------------------------------------------------------- deciding what to do (no I/O)
@dataclass
class Actions:
    send: list = field(default_factory=list)     # messages to transmit
    keys: list = field(default_factory=list)     # key codes to tap
    hotkey: str = ""                             # "menu": open the Quick Menu
    tv_off: bool = False                         # the TV went to standby
    button: str = ""                             # the button pressed, for Settings

class CecLogic:
    """One claimed playback device: what to answer and do for each message from the bus."""
    def __init__(self, menu_button=DEFAULT_MENU_BUTTON, clock=time.monotonic):
        self.la=LOG_ADDR_UNREGISTERED; self.pa=PHYS_ADDR_INVALID; self.active=False
        self.menu_button=menu_button; self.clock=clock
        self._held=None; self._held_at=0.0
    @property
    def ready(self): return self.la not in (LOG_ADDR_UNREGISTERED,None) and self.pa!=PHYS_ADDR_INVALID

    def address_changed(self, pa, log_addr_mask):
        self.pa=pa
        self.la=next((n for n in range(15) if log_addr_mask>>n&1),LOG_ADDR_UNREGISTERED)
        if not self.ready: self.active=False

    def become_active(self):
        """Switch the TV on and to this input (Image View On, then Active Source)."""
        if not self.ready: return []
        self.active=True; return [image_view_on(self.la),active_source(self.la,self.pa)]
    def going_away(self, tv_standby):
        """The computer is about to sleep or shut down: turn the TV off, or at least say this input has nothing to show."""
        if not self.ready: return []
        was=self.active; self.active=False
        if tv_standby: return [standby(self.la)]
        return [inactive_source(self.la,self.pa)] if was else []

    def message(self, msg) -> Actions:
        a=Actions()
        if len(msg)<2: return a   # a poll
        src,dst,op,args=msg[0]>>4,msg[0]&15,msg[1],bytes(msg[2:])
        directed=dst==self.la and dst!=LOG_ADDR_BROADCAST
        if src==self.la and src!=LOG_ADDR_UNREGISTERED: return a   # our own, echoed
        if op==USER_CONTROL_PRESSED and args:
            if directed or dst==LOG_ADDR_BROADCAST: self._pressed(args[0],a)
        elif op==USER_CONTROL_RELEASED: self._held=None
        elif op==STANDBY and (directed or dst==LOG_ADDR_BROADCAST):
            self.active=False
            if src==LOG_ADDR_TV: a.tv_off=True
        elif op==GIVE_DEVICE_POWER_STATUS and directed: a.send.append(report_power_status(self.la,src))
        elif op==MENU_REQUEST and directed: a.send.append(menu_status(self.la,src))
        elif op==REQUEST_ACTIVE_SOURCE:
            if self.active and self.ready: a.send.append(active_source(self.la,self.pa))
        elif op==SET_STREAM_PATH and len(args)>=2:
            if int.from_bytes(args[:2],"big")==self.pa and self.ready: self.active=True; a.send.append(active_source(self.la,self.pa))
        elif op in (ACTIVE_SOURCE,ROUTING_CHANGE,ROUTING_INFORMATION) and len(args)>=2:
            new=int.from_bytes(args[-2:],"big") if op!=ACTIVE_SOURCE else int.from_bytes(args[:2],"big")
            if new!=self.pa: self.active=False
            elif op!=ACTIVE_SOURCE and self.ready: self.active=True; a.send.append(active_source(self.la,self.pa))
        elif directed and op!=FEATURE_ABORT:
            a.send.append(feature_abort(self.la,src,op,ABORT_REFUSED if op==ABORT else ABORT_UNRECOGNIZED))
        return a

    def _pressed(self, code, a):
        b=BY_CODE.get(code); now=self.clock()
        repeat=self._held==code and now-self._held_at<REPEAT_GAP
        self._held=code; self._held_at=now
        if b is None: return
        a.button=b.id
        if self.menu_button and b.id==self.menu_button:
            if not repeat: a.hotkey="menu"   # held down, it would open and close the menu over and over
        elif b.key is not None: a.keys.append(b.key)   # held down, it repeats, as a held key would

# ---------------------------------------------------------------------- the kernel device
class Adapter:
    """/dev/cecN opened as an initiator and follower. `ioctl` and `opener` are swappable for the tests."""
    def __init__(self, path, ioctl=fcntl.ioctl, opener=os.open, closer=os.close):
        self.path=path; self._ioctl=ioctl; self._close=closer
        self.fd=opener(path,os.O_RDWR|os.O_NONBLOCK|getattr(os,"O_CLOEXEC",0))
        try:
            driver,name,_avail,self.capabilities,_v=CAPS.unpack(self._ioctl(self.fd,CEC_ADAP_G_CAPS,bytes(CAPS.size)))
            self.driver=driver.split(b"\0")[0].decode(errors="replace"); self.name=name.split(b"\0")[0].decode(errors="replace")
        except OSError: self.close(); raise
    def close(self):
        if self.fd is not None:
            try: self._close(self.fd)
            except OSError: pass
            self.fd=None
    def phys_addr(self):
        return struct.unpack("=H",self._ioctl(self.fd,CEC_ADAP_G_PHYS_ADDR,bytes(2)))[0]
    def log_addrs(self):
        """(log_addr_mask, OSD name, number claimed) as configured now."""
        f=LOG_ADDRS.unpack(self._ioctl(self.fd,CEC_ADAP_G_LOG_ADDRS,bytes(LOG_ADDRS.size)))
        return f[1],f[6].split(b"\0")[0].decode(errors="replace"),f[3]
    def claim(self, osd_name=OSD_NAME):
        """Claim a playback address under our name (the kernel finishes it in the background, then sends a state
        change). An address claimed earlier by TVWCS is let go and claimed again; one another program claimed is
        left alone: PermissionError names it."""
        mask,name,num=self.log_addrs()
        if num:
            if name and name!=osd_name: raise PermissionError(f"another program uses HDMI-CEC here (as \"{name}\")")
            self.release()
        data=LOG_ADDRS.pack(bytes([0xff]*4),0,CEC_VERSION_1_4,1,VENDOR_ID_NONE,0,osd_name.encode()[:14],
                            bytes([PRIM_DEVTYPE_PLAYBACK,0,0,0]),bytes([LOG_ADDR_TYPE_PLAYBACK,0,0,0]),
                            bytes([ALL_DEVTYPE_PLAYBACK,0,0,0]),bytes(48))
        self._ioctl(self.fd,CEC_ADAP_S_LOG_ADDRS,data)
        self._ioctl(self.fd,CEC_S_MODE,struct.pack("=I",CEC_MODE_INITIATOR|CEC_MODE_FOLLOWER))
    def release(self):
        """Give the address up, so the TV no longer lists this computer."""
        self._ioctl(self.fd,CEC_ADAP_S_LOG_ADDRS,bytes(LOG_ADDRS.size))
    def transmit(self, msg):
        data=MSG.pack(0,0,len(msg),0,0,0,bytes(msg).ljust(16,b"\0"),0,0,0,0,0,0,0)
        try: self._ioctl(self.fd,CEC_TRANSMIT,data); return True
        except OSError as exc: print(f"TVWCS: HDMI-CEC could not send {bytes(msg).hex(':')}: {exc}",file=sys.stderr); return False
    def receive(self):
        """The next message, or None."""
        try: f=MSG.unpack(self._ioctl(self.fd,CEC_RECEIVE,bytes(MSG.size)))
        except OSError as exc:
            if exc.errno in (errno.EAGAIN,errno.ETIMEDOUT): return None
            raise
        length=f[2]; rx,tx=f[8],f[9]
        if tx: return b""   # the result of one of ours: nothing to answer
        return f[6][:length] if rx&CEC_RX_STATUS_OK else b""
    def event(self):
        """(phys addr, log addr mask) after a state change, "lost" when messages were dropped, or None."""
        try: ts,kind,flags,body=EVENT.unpack(self._ioctl(self.fd,CEC_DQEVENT,bytes(EVENT.size)))
        except OSError as exc:
            if exc.errno in (errno.EAGAIN,errno.ETIMEDOUT): return None
            raise
        if kind==CEC_EVENT_STATE_CHANGE: return STATE_CHANGE.unpack(body[:STATE_CHANGE.size])[:2]
        return "lost" if kind==CEC_EVENT_LOST_MSGS else ()

# ---------------------------------------------------------------------- the virtual keyboard
UI_SET_EVBIT=0x40045564; UI_SET_KEYBIT=0x40045565; UI_DEV_SETUP=0x405c5503; UI_DEV_CREATE=0x5501; UI_DEV_DESTROY=0x5502
EV_SYN=0; EV_KEY=1; SYN_REPORT=0; BUS_VIRTUAL=0x06
INPUT_EVENT=struct.Struct("@LLHHi")   # struct input_event: its time is two longs on 32-bit and 64-bit Linux alike
UINPUT_SETUP=struct.Struct("=HHHH80sI")

class VirtualKeyboard:
    """A keyboard made with /dev/uinput, that taps the keys the remote's buttons stand for."""
    def __init__(self, keys=KEYS, path=UINPUT, ioctl=fcntl.ioctl, opener=os.open, writer=os.write, closer=os.close):
        self._ioctl=ioctl; self._write=writer; self._close=closer
        self.fd=opener(path,os.O_WRONLY|os.O_NONBLOCK|getattr(os,"O_CLOEXEC",0))
        try:
            self._ioctl(self.fd,UI_SET_EVBIT,EV_KEY)
            for k in keys: self._ioctl(self.fd,UI_SET_KEYBIT,k)
            self._ioctl(self.fd,UI_DEV_SETUP,UINPUT_SETUP.pack(BUS_VIRTUAL,0,0,1,b"TVWCS HDMI-CEC remote",0))
            self._ioctl(self.fd,UI_DEV_CREATE)
        except OSError: self._close(self.fd); self.fd=None; raise
    def tap(self, key):
        if self.fd is None: return
        ev=lambda t,c,v:INPUT_EVENT.pack(0,0,t,c,v)
        try: self._write(self.fd,ev(EV_KEY,key,1)+ev(EV_SYN,SYN_REPORT,0)+ev(EV_KEY,key,0)+ev(EV_SYN,SYN_REPORT,0))
        except OSError as exc: print(f"TVWCS: the HDMI-CEC keyboard could not press key {key}: {exc}",file=sys.stderr)
    def close(self):
        if self.fd is None: return
        try: self._ioctl(self.fd,UI_DEV_DESTROY)
        except OSError: pass
        try: self._close(self.fd)
        except OSError: pass
        self.fd=None

# ---------------------------------------------------------------------- what Settings shows
@dataclass
class Status:
    state: str = "off"       # off, starting, connected, no-tv, busy, no-access, failed
    device: str = ""
    driver: str = ""
    phys_addr: str = ""
    keys: bool = False       # the virtual keyboard works
    message: str = ""
    last_button: str = ""
    seen: list = field(default_factory=list)   # buttons this TV has sent, since TVWCS started

def write_status(status, runtime):
    try:
        tmp=runtime/(STATUS_NAME+".tmp"); tmp.write_text(json.dumps(status.__dict__),encoding="utf-8"); tmp.replace(runtime/STATUS_NAME)
    except OSError: pass
def read_status(runtime):
    try: raw=json.loads((runtime/STATUS_NAME).read_text(encoding="utf-8"))
    except (OSError,ValueError): return None
    if not isinstance(raw,dict): return None
    s=Status()
    for k,v in raw.items():
        if hasattr(s,k) and isinstance(v,type(getattr(s,k))): setattr(s,k,v)
    return s

def describe(status):
    """One line for Settings."""
    if status is None or status.state=="off": return "TVWCS is not using HDMI-CEC" if status is not None else "TVWCS is not running"
    port=f" on input HDMI {status.phys_addr.split('.')[0]}" if status.phys_addr and status.phys_addr[0]!="0" else ""
    return {"starting":"Looking for the TV…","connected":f"Connected to the TV{port}" + ("" if status.keys else ", but its buttons can't press keys"),
            "no-tv":"No TV answers on this HDMI port","busy":status.message or "Another program uses HDMI-CEC",
            "no-access":"TVWCS may not use HDMI-CEC here: log out and in again after installing","failed":status.message or "HDMI-CEC failed"}.get(status.state,status.state)

# ---------------------------------------------------------------------- the service
class CecService:
    """Runs inside TVWCS (main.CecWatcher), on its GLib main loop. `on_hotkey(action)` opens the Quick Menu;
    `on_tv_off()` sleeps the computer when that option is on."""
    NO_TV_AFTER=8   # s without a physical address: no TV (or it is off and cuts the 5 V line)
    def __init__(self, runtime, on_hotkey, on_tv_off):
        self.runtime=runtime; self.on_hotkey=on_hotkey; self.on_tv_off=on_tv_off
        self.options=dict(DEFAULTS); self.adapter=None; self.keyboard=None; self.logic=CecLogic()
        self.status=Status(); self._watch=0; self._timer=0; self._woke=False; self._bus=None; self._subs=[]; self._inhibit=None

    def start(self, options):
        from gi.repository import GLib
        self.options=dict(options); self.logic.menu_button=options["menu"]
        problem=None
        for path in adapters():
            try: a=Adapter(path)
            except PermissionError: problem=problem or "no-access"; continue
            except OSError as exc: problem=problem or f"{path}: {exc.strerror}"; continue
            try:
                pa=a.phys_addr()
                if self.adapter is None or (pa!=PHYS_ADDR_INVALID and self.logic.pa==PHYS_ADDR_INVALID):
                    if self.adapter is not None: self.adapter.close()
                    self.adapter=a; self.logic.pa=pa
                else: a.close()
            except OSError: a.close()
        if self.adapter is None:
            self.status=Status(state="no-access" if problem=="no-access" else "failed",message="" if problem=="no-access" else (problem or "No HDMI-CEC device"))
            self._publish(); return False
        a=self.adapter; self.status=Status(state="starting",device=a.path,driver=a.driver)
        try: a.claim()
        except PermissionError as exc:
            self.status.state="busy"; m=str(exc); self.status.message=m[:1].upper()+m[1:]; self._publish(); a.close(); self.adapter=None; return False
        except OSError as exc:
            self.status.state="failed"; self.status.message=f"Could not claim an HDMI-CEC address: {exc.strerror or exc}"; self._publish()
            a.close(); self.adapter=None; return False
        try: self.keyboard=VirtualKeyboard()
        except OSError as exc: print(f"TVWCS: no virtual keyboard for the TV remote ({UINPUT}: {exc.strerror}); only its hotkey works",file=sys.stderr)
        self.status.keys=self.keyboard is not None
        self._watch=GLib.io_add_watch(a.fd,GLib.PRIORITY_DEFAULT,GLib.IOCondition.IN|GLib.IOCondition.PRI|GLib.IOCondition.ERR|GLib.IOCondition.HUP,self._ready)
        self._timer=GLib.timeout_add_seconds(self.NO_TV_AFTER,self._no_tv)
        self._watch_power(); self._publish(); return True

    def update(self, options):
        """New options from Settings, while running."""
        old=self.options; self.options=dict(options); self.logic.menu_button=options["menu"]
        if old.get("tv_standby")!=options["tv_standby"]: self._inhibit_sleep(options["tv_standby"])

    def stop(self, release=False):
        from gi.repository import GLib
        if self._watch: GLib.source_remove(self._watch); self._watch=0
        if self._timer: GLib.source_remove(self._timer); self._timer=0
        if self._bus is not None:
            for s in self._subs: self._bus.signal_unsubscribe(s)
            self._subs=[]
        self._inhibit_sleep(False)
        if self.keyboard is not None: self.keyboard.close(); self.keyboard=None
        if self.adapter is not None:
            if release:
                if self.logic.active and self.logic.ready: self.adapter.transmit(inactive_source(self.logic.la,self.logic.pa))
                try: self.adapter.release()
                except OSError: pass
            self.adapter.close(); self.adapter=None
        self.status=Status(); self._publish()

    # ---- the bus
    def _ready(self, _fd, condition):
        from gi.repository import GLib
        if self.adapter is None: return GLib.SOURCE_REMOVE
        try:
            while (ev:=self.adapter.event()) is not None:
                if isinstance(ev,tuple) and len(ev)==2: self._address(*ev)
            while (msg:=self.adapter.receive()) is not None:
                if msg: self._handle(self.logic.message(msg))
        except OSError as exc:
            print(f"TVWCS: HDMI-CEC stopped: {exc}",file=sys.stderr); self.status.state="failed"; self.status.message=str(exc); self._publish()
            self._watch=0; return GLib.SOURCE_REMOVE
        if condition&(GLib.IOCondition.ERR|GLib.IOCondition.HUP) and not condition&(GLib.IOCondition.IN|GLib.IOCondition.PRI):
            self._watch=0; return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _address(self, pa, mask):
        before=self.logic.ready; self.logic.address_changed(pa,mask)
        self.status.phys_addr=phys_text(pa)
        if self.logic.ready:
            self.status.state="connected"
            if not before and self.options["wake_tv"] and not self._woke:   # once per start (and again after each wake)
                self._woke=True; self._send(self.logic.become_active())
        elif pa==PHYS_ADDR_INVALID: self.status.state="no-tv"
        self._publish()

    def _no_tv(self):
        self._timer=0
        if self.status.state=="starting": self.status.state="no-tv"; self._publish()
        return False

    def _handle(self, a):
        self._send(a.send)
        for k in a.keys:
            if self.keyboard is not None: self.keyboard.tap(k)
        if a.button:
            label=button_label(a.button)
            changed=self.status.last_button!=label or a.button not in self.status.seen
            self.status.last_button=label
            if a.button not in self.status.seen: self.status.seen.append(a.button)
            if changed: self._publish()
        if a.hotkey: self.on_hotkey(a.hotkey)
        if a.tv_off and self.options["follow_tv"]: self.on_tv_off()

    def _send(self, messages):
        for m in messages:
            if self.adapter is not None: self.adapter.transmit(m)

    def _publish(self): write_status(self.status,self.runtime)

    # ---- sleep and shutdown (logind)
    def _watch_power(self):
        from gi.repository import Gio
        try: self._bus=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
        except Exception as exc: print(f"TVWCS: HDMI-CEC can't follow sleep and shutdown: {exc}",file=sys.stderr); return   # GLib.Error
        for sig in ("PrepareForSleep","PrepareForShutdown"):
            self._subs.append(self._bus.signal_subscribe("org.freedesktop.login1","org.freedesktop.login1.Manager",sig,"/org/freedesktop/login1",
                                                         None,Gio.DBusSignalFlags.NONE,self._power_signal))
        self._inhibit_sleep(self.options["tv_standby"])

    def _inhibit_sleep(self, on):
        """A delay lock, so logind waits (at most InhibitDelayMaxSec, 5 s) for the TV to be told before the computer sleeps."""
        if not on or self._bus is None:
            if self._inhibit is not None:
                try: os.close(self._inhibit)
                except OSError: pass
                self._inhibit=None
            return
        if self._inhibit is not None: return
        from gi.repository import GLib, Gio
        try:
            res,fds=self._bus.call_with_unix_fd_list_sync("org.freedesktop.login1","/org/freedesktop/login1","org.freedesktop.login1.Manager","Inhibit",
                GLib.Variant("(ssss)",("sleep:shutdown","TVWCS","Turn the TV off over HDMI-CEC","delay")),GLib.VariantType("(h)"),Gio.DBusCallFlags.NONE,-1,None,None)
            self._inhibit=fds.get(res.unpack()[0])
        except Exception as exc: print(f"TVWCS: HDMI-CEC could not ask logind to wait before sleeping: {exc}",file=sys.stderr)   # GLib.Error

    def _power_signal(self, _conn, _sender, _path, _iface, signal_name, params):
        from gi.repository import GLib
        going=params.unpack()[0]
        if going:
            self._send(self.logic.going_away(self.options["tv_standby"]))
            # the messages are queued in the kernel; let them go out before the computer sleeps
            GLib.timeout_add(400,lambda:(self._inhibit_sleep(False),False)[1])
        elif signal_name=="PrepareForSleep":   # woken up
            self._inhibit_sleep(self.options["tv_standby"])
            if self.options["wake_tv"]: self._send(self.logic.become_active())
