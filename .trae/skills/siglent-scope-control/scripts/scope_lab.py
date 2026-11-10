# scope_lab.py — Siglent SDS2204X HD experiment driver (raw socket, port 5024)
# Usage: python scope_lab.py <experiment> [--host IP] [--dut IP] [--dut-pwd PW] [--channels JSON]
# Experiments: idn, single, wgen, pwm, meas, trig <type>, decode_uart, mtest, history, acquire,
#              ref, params, save, runall, vxi11, vsock
# Nothing is hardcoded: the scope is found over LXI (mDNS/SSDP) when --host/SCOPE_IP is absent,
# the DUT comes from --dut/DUT_IP, and the probe map from --channels/SCOPE_CHANNELS.
import socket, sys, time, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scope_discover import find_scope

PORT = int(os.environ.get("SCOPE_PORT", "5024"))
HOST = os.environ.get("SCOPE_IP")          # None => LXI discovery on first connect
OUT = os.path.join(os.environ.get("TEMP", "."), "scope_lab")
os.makedirs(OUT, exist_ok=True)
RUNALL_STEP = "all"
# Screenshots can raise a modal dialog on the scope screen and wedge the instrument app.
# They are therefore opt-in: set SCOPE_ALLOW_SCREENSHOT=1 only when a person is at the scope.
ALLOW_SHOT = os.environ.get("SCOPE_ALLOW_SCREENSHOT") == "1"

class Scope:
    def __init__(self, host=None, port=None, timeout=4.0):
        host, port = find_scope(host or HOST, port or PORT, subnet=os.environ.get("SCOPE_SUBNET"))
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)
        self._read_to_prompt(1.5)

    def _read_to_prompt(self, timeout=None):
        old = self.s.gettimeout()
        if timeout: self.s.settimeout(timeout)
        data = b""
        try:
            while True:
                chunk = self.s.recv(65536)
                if not chunk: break
                data += chunk
                if data.rstrip(b"\x00\r\n ").endswith(b">>"): break
        except socket.timeout:
            pass
        finally:
            self.s.settimeout(old)
        return data

    def cmd(self, c, wait=0.6):
        self.s.sendall(c.encode() + b"\r\n")
        time.sleep(wait)
        raw = self._read_to_prompt()
        txt = raw.decode("ascii", "replace").lstrip("\x00")
        lines = [l.strip() for l in txt.splitlines()
                 if l.strip() and l.strip() != ">>" and l.strip() != c]
        return " | ".join(lines)

    def screenshot(self, path, fmt="PNG"):
        if not ALLOW_SHOT:
            print("[skip] screenshot disabled (set SCOPE_ALLOW_SCREENSHOT=1, attended only)")
            return 0, False
        self.s.sendall(f"PRIN? {fmt}\r\n".encode())
        time.sleep(1.0)
        data = b""
        self.s.settimeout(6.0)
        last = time.time()
        try:
            while time.time() - last < 2.5:
                try:
                    chunk = self.s.recv(262144)
                    if not chunk: break
                    data += chunk
                    last = time.time()
                except socket.timeout:
                    break
        finally:
            self.s.settimeout(4.0)
        # strip leading NUL and trailing prompt
        data = data.lstrip(b"\x00")
        idx = data.rfind(b">>")
        if idx != -1:
            data = data[:idx].rstrip(b"\r\n")
        with open(path, "wb") as f:
            f.write(data)
        ok = data[1:4] == b"PNG" if fmt == "PNG" else data[:2] == b"BM"
        return len(data), ok

    def wait_stop(self, tries=25, delay=0.4):
        for i in range(tries):
            time.sleep(delay)
            st = self.cmd("TRIG:STAT?", wait=0.3)
            print(f"  TRIG:STAT? [{i}] -> {st}")
            if "Stop" in st:
                return True
        return False

    def close(self):
        try: self.s.close()
        except Exception: pass

def exp_idn(sc):
    print("*IDN? ->", sc.cmd("*IDN?"))
    print("TRIG:STAT? ->", sc.cmd("TRIG:STAT?"))
    print("ACQ:SRAT? ->", sc.cmd("ACQ:SRAT?"))

def exp_single(sc):
    """Single-trigger closed loop on CH1 (the task's core requirement)."""
    print("C1 setup:", sc.cmd("C1:TURN ON"), sc.cmd(":CHAN1:VIS ON"),
          sc.cmd("C1:VDIV 0.5"), sc.cmd("C1:OFST 0"), sc.cmd("TDIV 1E-5"))
    print("trig cfg:", sc.cmd("TRIG:TYPE EDGE"), sc.cmd("TRIG:EDGE:SOUR CHAN1"),
          sc.cmd("TRIG:EDGE:SLOP POS"), sc.cmd("TRIG:EDGE:LEV 0.3"))
    print("LEV? ->", sc.cmd("TRIG:EDGE:LEV?"))
    sc.cmd("TRIG:MODE SINGLE"); sc.cmd("TRIG:RUN")
    ok = sc.wait_stop()
    print("captured:", ok)
    sc.cmd("C1:MEAS FREQ,ON"); print("FREQ ->", sc.cmd("C1:PAVA? FREQ"))
    sc.cmd("C1:MEAS DUTY,ON"); print("DUTY ->", sc.cmd("C1:PAVA? DUTY"))
    sc.cmd("C1:MEAS PKPK,ON"); print("PKPK ->", sc.cmd("C1:PAVA? PKPK"))
    n, hdr = sc.screenshot(os.path.join(OUT, "single.png"))
    print(f"screenshot single.png: {n} bytes, header_ok={hdr}")
    sc.cmd("TRIG:MODE AUTO")

def exp_wgen(sc):
    """Built-in waveform generator -> loop back or just verify commands."""
    # WGEN commands are SDG-style: the channel prefix is C1, NOT "WGEN"
    # (manual p.681: "The WGEN commands are the same as that of Siglent SDG series")
    print("WGEN OUTP ON:", sc.cmd("C1:OUTP ON"))
    print("WGEN PULSE 25k:", sc.cmd("C1:BSWV WVTP,PULSE"),
          sc.cmd("C1:BSWV FRQ,25000"), sc.cmd("C1:BSWV AMP,3.3"),
          sc.cmd("C1:BSWV OFST,1.65"), sc.cmd("C1:BSWV DUTY,50"))
    print("WGEN? ->", sc.cmd("C1:BSWV?"), " OUTP? ->", sc.cmd("C1:OUTP?"))

def _dut_cfg():
    """DUT endpoint from --dut/--dut-pwd or DUT_IP/DUT_PWD; never hardcoded."""
    return os.environ.get("DUT_IP"), os.environ.get("DUT_PWD")


def _channel_map():
    """Probe map from --channels / SCOPE_CHANNELS, e.g.
    {"1": {"name": "white", "key": "whiteApplied"}, ...}
    Returns None when not configured, in which case channels are measured generically."""
    raw = os.environ.get("SCOPE_CHANNELS")
    if not raw:
        return None
    try:
        return {int(k): v for k, v in json.loads(raw).items()}
    except (ValueError, TypeError):
        print("SCOPE_CHANNELS is not valid JSON; measuring channels generically")
        return None


def exp_pwm(sc):
    """DUT status vs measured PWM: the project's core verification.
    DUT and probe map must be supplied by the caller (ask the user, or pass --dut/--channels)."""
    import urllib.request
    dut, pwd = _dut_cfg()
    st = {}
    if dut:
        try:
            url = f"http://{dut}/status?devicepwd={pwd or ''}&mode=get"
            with urllib.request.urlopen(url, timeout=8) as r:
                st = json.loads(r.read().decode())
        except Exception as e:
            print("DUT status FAIL:", type(e).__name__, e)
        print(f"DUT {dut}: onOff={st.get('onOffStatus')} brightness={st.get('brightness')} "
              f"colorTemp={st.get('colorTemperature')} whiteApplied={st.get('whiteApplied')} "
              f"yellowApplied={st.get('yellowApplied')} fanSpeed={st.get('fanSpeed')} "
              f"pumpSpeed={st.get('pumpSpeed')}")
        print("PWM config:", {k: st.get(k) for k in
                              ("whitePwmFreq", "yellowPwmFreq", "pumpPwmFreq", "fanPwmFreq",
                               "whitePwmMin", "whitePwmMax", "yellowPwmMin", "yellowPwmMax",
                               "pumpPwmMin", "pumpPwmMax", "fanPwmMin", "fanPwmMax")})
    else:
        print("DUT not configured (--dut / DUT_IP); measuring without a /status cross-check")

    cmap = _channel_map()
    if cmap:
        chans = [(ch, cfg.get("name", f"CH{ch}"), cfg.get("key")) for ch, cfg in sorted(cmap.items())]
    else:
        chans = [(ch, f"CH{ch}", None) for ch in (1, 2, 3, 4)]
        print("probe map not configured (--channels / SCOPE_CHANNELS); assuming C1..C4 are connected")

    sc.cmd("C1:VDIV 0.5"); sc.cmd("C1:OFST 0"); sc.cmd("TDIV 1E-5")
    print(f"{'CH':<3}{'signal':<8}{'duty bound':<14}{'applied':<10}{'FREQ':<22}{'DUTY'}")
    for ch, name, key in chans:
        c = f"C{ch}"
        sc.cmd(f"{c}:TURN ON"); sc.cmd(f":CHAN{ch}:VIS ON")
        sc.cmd(f"{c}:VDIV 0.5"); sc.cmd(f"{c}:OFST 0")
        sc.cmd(f"{c}:MEAS FREQ,ON"); sc.cmd(f"{c}:MEAS DUTY,ON")
        freq = sc.cmd(f"{c}:PAVA? FREQ").split(",")[-1]
        duty = sc.cmd(f"{c}:PAVA? DUTY").split(",")[-1]
        lo, hi = st.get(f"{name}PwmMin"), st.get(f"{name}PwmMax")
        bound = f"{lo}~{hi}%" if lo is not None and hi is not None else "-"
        applied = st.get(key, "?") if key else "-"
        print(f"{c:<3}{name:<8}{bound:<14}{str(applied):<10}{freq:<22}{duty}")
    sc.screenshot(os.path.join(OUT, "pwm.png"))
    print("expected: LED channels use the firmware power-calibration table "
          "(calibratePower in domain/LightControllFSM.py; DO NOT linearise on 'applied'); "
          "fan/pump duty is linear in speed. Confirm the mapping with the user, do not assume it.")

def exp_meas(sc):
    """MEAS:ADV vs MEAS:SIMP comparison."""
    print("MODE ADV:", sc.cmd("MEAS:MODE ADV"))
    print("ADV P1 FREQ:", sc.cmd("MEAS:ADV:P1:TYPE FREQ"), sc.cmd("MEAS:ADV:P1:SOURce1 C1"))
    print("P1 VAL ->", sc.cmd("MEAS:ADV:P1:VALue?"))
    print("ADV stats:", sc.cmd("MEAS:ADV:STAT ON"), sc.cmd("MEAS:ADV:P1:STATistics?"))
    # SIMP:ITEM takes <param>,<ON|OFF>; the channel is set by SIMP:SOUR (manual p.278-280)
    print("SIMP:", sc.cmd("MEAS:SIMP:SOUR C1"), sc.cmd("MEAS:SIMP:ITEM PWID,ON"),
          sc.cmd("MEAS:SIMP:VAL? PWID"))

def exp_trig(sc, t):
    """Exercise one advanced trigger type with project-relevant params."""
    t = t.upper()
    cmds = {
        "PULSE": ["TRIG:TYPE PULSE", "TRIG:PULS:SOUR C1", "TRIG:PULS:POL POS",
                  "TRIG:PULS:LEV 0.7", "TRIG:PULS:LIM LESS",
                  "TRIG:PULS:TLOW 1.0E-6", "TRIG:PULS:COUP DC", "TRIG:PULS:NREJ ON"],
        "SLOPE": ["TRIG:TYPE SLOPE", "TRIG:SLOP:SOUR C1", "TRIG:SLOP:SLOP RIS",
                  "TRIG:SLOP:LLEV 0.3", "TRIG:SLOP:HLEV 0.9",
                  "TRIG:SLOP:LIM GREAT", "TRIG:SLOP:TLOW 3.0E-8"],
        "INTERVAL": ["TRIG:TYPE INTERVAL", "TRIG:INT:SOUR C1", "TRIG:INT:SLOP RIS",
                     "TRIG:INT:LEV 0.7", "TRIG:INT:LIM GREAT", "TRIG:INT:TLOW 4.1E-5"],
        "DROPOUT": ["TRIG:TYPE DROPOUT", "TRIG:DROP:SOUR C1", "TRIG:DROP:SLOP RIS",
                    "TRIG:DROP:LEV 0.7", "TRIG:DROP:TYPE EDGE", "TRIG:DROP:TIME 1.0E-4"],
        "RUNT": ["TRIG:TYPE RUNT", "TRIG:RUNT:SOUR C1", "TRIG:RUNT:POL POS",
                 "TRIG:RUNT:LLEV 0.3", "TRIG:RUNT:HLEV 0.9", "TRIG:RUNT:LIM GREAT"],
        "WINDOW": ["TRIG:TYPE WINDOW", "TRIG:WIND:SOUR C1", "TRIG:WIND:TYPE ABS",
                   "TRIG:WIND:CLEV 0.7", "TRIG:WIND:DLEV 0.4"],
        "PATTERN": ["TRIG:TYPE PATTERN", "TRIG:PATT:INP H,L,X,X", "TRIG:PATT:LOG AND",
                    "TRIG:PATT:LEV C1,0.7", "TRIG:PATT:LEV C2,0.7"],
        "DELAY": ["TRIG:TYPE DELAY", "TRIG:DEL:SOUR C1", "TRIG:DEL:SOUR2 C2",
                  "TRIG:DEL:SLOP RIS", "TRIG:DEL:SLOP2 RIS",
                  "TRIG:DEL:LEV C1,0.7", "TRIG:DEL:LEV2 C2,0.7",
                  "TRIG:DEL:LIM INN", "TRIG:DEL:TLOW 0", "TRIG:DEL:TUPP 2.0E-5"],
        "QUALIFIED": ["TRIG:TYPE QUALIFIED", "TRIG:QUAL:ES C1", "TRIG:QUAL:ESL RIS",
                      "TRIG:QUAL:ELEV 0.7", "TRIG:QUAL:QS C3", "TRIG:QUAL:QLEV 0.7",
                      "TRIG:QUAL:TYPE STATE,HIGH"],
        "NTHEDGE": ["TRIG:TYPE NTHEdge", "TRIG:NEDG:SOUR C1", "TRIG:NEDG:SLOP RIS",
                    "TRIG:NEDG:LEV 0.7", "TRIG:NEDG:IDLE 1.0E-4", "TRIG:NEDG:EDGE 3"],
    }
    if t not in cmds:
        print("unknown type; choose from", ", ".join(cmds)); return
    for c in cmds[t]:
        print(f"{c} ->", sc.cmd(c))
    print("verify:", sc.cmd("TRIG:TYPE?"))
    sc.cmd("TRIG:MODE SINGLE"); sc.cmd("TRIG:RUN")
    ok = sc.wait_stop(tries=12)
    n, hdr = sc.screenshot(os.path.join(OUT, f"trig_{t.lower()}.png"))
    print(f"fired={ok}, screenshot {n} bytes header_ok={hdr}")
    sc.cmd("TRIG:TYPE EDGE"); sc.cmd("TRIG:MODE AUTO")

def exp_history(sc):
    print("HISTOR ON:", sc.cmd("HISTOR ON"))
    print("HISTOR:LIST? ->", sc.cmd("HISTOR:LIST?"))
    print("HISTOR:FRAM 1:", sc.cmd("HISTOR:FRAM 1"))
    print("HISTOR:TIME? ->", sc.cmd("HISTOR:TIME?"))
    print("HISTOR OFF:", sc.cmd("HISTOR OFF"))

def exp_acquire(sc):
    for c in ["ACQ:TYPE?", "ACQ:MODE?", "ACQ:POIN?", "ACQ:SRAT?", "ACQ:MDEP?",
              "ACQ:RES?", "ACQ:INT?", "ACQ:MMAN?", "ACQ:NUMA?"]:
        print(f"{c} ->", sc.cmd(c))

def exp_ref(sc):
    # REF slots REFA-REFD: :REF<r>:DATA <LOAD|UNLoad|SAVE,<src>> (manual pp.316-321)
    print("REFA save C1:", sc.cmd("REFA:DATA SAVE,C1"))
    print("REFA load:", sc.cmd("REFA:DATA LOAD"))
    print("REFA:DATA:SOUR? ->", sc.cmd("REFA:DATA:SOURce?"))
    print("REFA:LAB ON:", sc.cmd("REFA:LAB ON"), "->", sc.cmd("REFA:LAB?"))

def exp_vxi11(_sc):
    import pyvisa
    rm = pyvisa.ResourceManager("@py")
    host, _ = find_scope(HOST, PORT, subnet=os.environ.get("SCOPE_SUBNET"))
    try:
        inst = rm.open_resource(f"TCPIP0::{host}::inst0::INSTR", timeout=8000)
        print("VXI-11 *IDN? ->", inst.query("*IDN?"))
        inst.close()
    except Exception as e:
        print("VXI-11 FAIL:", type(e).__name__, e)

def exp_vsock(_sc):
    """PyVISA SOCKET resource on 5024 — live-verify prompt pollution behavior."""
    import pyvisa
    rm = pyvisa.ResourceManager("@py")
    host, _ = find_scope(HOST, PORT, subnet=os.environ.get("SCOPE_SUBNET"))
    inst = rm.open_resource(f"TCPIP0::{host}::5024::SOCKET", timeout=5000)
    inst.write_termination = "\r\n"
    inst.read_termination = "\n"
    try:
        r1 = inst.query("*IDN?")
        print("query1 raw repr:", repr(r1))
        r2 = inst.query("TRIG:MODE?")
        print("query2 raw repr:", repr(r2), "<- check for leading '>>' pollution")
        r3 = inst.query("TRIG:STAT?")
        print("query3 raw repr:", repr(r3))
        clean = r2.lstrip("> \r\n\x00")
        print("stripped query2:", repr(clean))
    finally:
        inst.close()

def exp_display(sc):
    """DISPlay subsystem (manual pp.188-199)."""
    for c in ["DISP:GRAT 50", "DISP:GRAT?", "DISP:GRID LIGH", "DISP:GRID?",
              "DISP:TRAN 80", "DISP:TRAN?", "DISP:BACK 100", "DISP:BACK?",
              "DISP:INT 75", "DISP:INT?", "DISP:TYPE VECT", "DISP:TYPE?",
              "DISP:COL OFF", "DISP:COL?", "DISP:AXIS ON", "DISP:AXIS?",
              "DISP:MENU EMB", "DISP:MENU?"]:
        print(f"{c} ->", sc.cmd(c))

def exp_cursor(sc):
    """CURSor subsystem (manual pp.55-70)."""
    for c in ["CURS ON", "CURS:MODE MAN,X", "CURS:MODE?", "CURS:SOUR1 C1", "CURS:SOUR1?",
              "CURS:TAGS FIX", "CURS:TAGS?", "CURS:XREF DEL", "CURS:XREF?",
              "CURS:YREF OFFS", "CURS:YREF?", "CURS:X1 0", "CURS:X1?",
              "CURS:X2 2.5E-5", "CURS:X2?", "CURS:Y1 0", "CURS:Y1?", "CURS:Y2 1",
              "CURS:Y2?", "CURS:XDEL?", "CURS:IXD?", "CURS:YDEL?"]:
        print(f"{c} ->", sc.cmd(c))

def exp_dvm(sc):
    """DVM subsystem (manual pp.201-208)."""
    for c in ["DVM ON", "DVM?", "DVM:SOUR C1", "DVM:SOUR?", "DVM:MODE DCavg",
              "DVM:MODE?", "DVM:ARAN ON", "DVM:ARAN?", "DVM:HOLD ON", "DVM:HOLD?",
              "DVM:CURR?", "DVM:ALAR ON", "DVM:ALAR?"]:
        print(f"{c} ->", sc.cmd(c))
    sc.cmd("DVM OFF")

def exp_mask(sc):
    """Mask test (manual pp.300-305) — create a mask, run briefly, read counters."""
    for c in ["MTES:SOUR C1", "MTES:MASK:CRE 0.8,0.08", "MTES:IDIS ON",
              "MTES ON", "MTES:OPER ON"]:
        print(f"{c} ->", sc.cmd(c))
    time.sleep(3)
    print("MTES:COUN? ->", sc.cmd("MTES:COUN?"))
    sc.cmd("MTES:OPER OFF"); sc.cmd("MTES OFF")
    sc.screenshot(os.path.join(OUT, "mask.png"))

def exp_fft(sc):
    """Math FFT chain (manual pp.210-230)."""
    for c in ["FUNC1 ON", "FUNC1:OPER FFT", "FUNC1:SOUR1 C1", "FUNC1:FFT:AUT NORM",
              "FUNC:FFTD SPL", "C1:VDIV 0.5", "C1:OFST 0", "TDIV 1E-5"]:
        print(f"{c} ->", sc.cmd(c))
    time.sleep(1.5)
    for c in ["FUNC1:FFT:HCEN?", "FUNC1:FFT:HSC?", "FUNC1:FFT:SPAN?",
              "FUNC1:FFT:RLEV?", "FUNC1:FFT:UNIT DBV", "FUNC1:FFT:WIND FLAT",
              "FUNC1:FFT:SEAR:THR -40", "FUNC1:FFT:SEAR:RES?"]:
        print(f"{c} ->", sc.cmd(c))
    sc.screenshot(os.path.join(OUT, "fft.png"))
    sc.cmd("FUNC1 OFF")

def exp_save(sc):
    """SAVe/RECall setup round-trip (manual pp.306-314)."""
    for c in ["SAVE:SET INT,1", "REC:SET INT,1",
              "SAVE:IMAGe \"local/SIGLENT/lab.png\",PNG,OFF",
              "REC:FDEF"]:
        print(f"{c} ->", sc.cmd(c))

def exp_histplay(sc):
    """History frames playback (manual pp.251-256)."""
    for c in ["HISTOR ON", "HISTOR:INTER 1.00E-03", "HISTOR:INTER?",
              "HISTOR:PLAY FORWards", "HISTOR:PLAY?",
              "HISTOR:FRAM 2", "HISTOR:TIME?", "HISTOR:LIST?"]:
        print(f"{c} ->", sc.cmd(c))
    sc.cmd("HISTOR OFF")

def exp_params(sc):
    """PAVA type matrix: which measurement parameters return a value on this firmware.
    The type list is the manual's :MEASure:SIMPle:ITEM set plus the wrong names seen in the wild."""
    types = ("PKPK MAX MIN AMPL TOP BASE LEVELX CMEAN MEAN STDEV VSTD RMS CRMS "
             "MEDIAN CMEDIAN OVSN FPRE OVSP RPRE PER FREQ TMAX TMIN PWID NWID DUTY "
             "NDUTY WID NBWID DELAY TIMEL RISE FALL RISE20T80 FALL8020 CCJ PAREA "
             "NAREA AREA ABSAREA CYCLES REDGES FEDGES EDGES PPULSES NPULSES "
             "VPP VRMS VMAX VMIN VTOP VBASE AMP PW NW VAVG").split()
    ok, empty = [], []
    for t in types:
        sc.cmd(f"C1:MEAS {t},ON", wait=0.25)
        v = sc.cmd(f"C1:PAVA? {t}", wait=0.25)
        sc.cmd(f"C1:MEAS {t},OFF", wait=0.2)
        val = v.split(",")[-1].strip() if v else ""
        (ok if val and "****" not in val and val != "?" else empty).append((t, val))
    print(f"WORKS ({len(ok)}):", ", ".join(f"{t}={v}" for t, v in ok))
    print(f"EMPTY ({len(empty)}):", ", ".join(t for t, _ in empty))

def exp_runall(sc):
    """Ordered safe suite for post-recovery validation; logs to scope_lab/runall.log."""
    logp = os.path.join(OUT, "runall.log")
    step = RUNALL_STEP
    seq = [("idn", exp_idn), ("single", exp_single), ("display", exp_display),
           ("cursor", exp_cursor), ("dvm", exp_dvm), ("acquire", exp_acquire),
           ("meas", exp_meas), ("fft", exp_fft), ("history", exp_histplay),
           ("ref", exp_ref), ("mask", exp_mask)]
    with open(logp, "a", encoding="utf-8") as lg:
        lg.write(f"\n===== runall {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        for name, fn in seq:
            if step not in ("all", name):
                continue
            lg.write(f"--- {name} ---\n")
            print(f"--- {name} ---")
            try:
                fn(sc)
            except Exception as e:
                msg = f"{name} FAILED: {type(e).__name__} {e}"
                print(msg); lg.write(msg + "\n")
            lg.flush()
    print("log:", logp)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Siglent SDS2204X HD experiment driver")
    ap.add_argument("name", nargs="?", default="idn", help="experiment name")
    ap.add_argument("args", nargs="*", help="extra args (e.g. trigger type, runall step)")
    ap.add_argument("--host", help="scope IP; default: SCOPE_IP or LXI discovery")
    ap.add_argument("--port", type=int, help="SCPI port; default: SCOPE_PORT or 5024")
    ap.add_argument("--subnet", help="e.g. 192.168.30.0/24 for TCP-scan discovery")
    ap.add_argument("--dut", help="DUT IP for /status cross-check (or DUT_IP)")
    ap.add_argument("--dut-pwd", help="DUT API password (or DUT_PWD)")
    ap.add_argument("--channels", help='probe map JSON, e.g. {"1":{"name":"white","key":"whiteApplied"}}')
    a = ap.parse_args()

    if a.host:
        HOST = a.host
    if a.port:
        PORT = a.port
    if a.dut:
        os.environ["DUT_IP"] = a.dut
    if a.dut_pwd:
        os.environ["DUT_PWD"] = a.dut_pwd
    if a.channels:
        os.environ["SCOPE_CHANNELS"] = a.channels
    if a.subnet:
        os.environ["SCOPE_SUBNET"] = a.subnet
    if a.args and a.name == "runall":
        RUNALL_STEP = a.args[0]

    name = a.name
    if name == "vxi11":
        exp_vxi11(None); sys.exit(0)
    if name == "vsock":
        exp_vsock(None); sys.exit(0)
    try:
        sc = Scope()
    except (RuntimeError, OSError) as e:
        print("scope not reachable:", e)
        sys.exit(2)
    try:
        fn = {"idn": exp_idn, "single": exp_single, "wgen": exp_wgen,
              "pwm": exp_pwm, "meas": exp_meas, "params": exp_params, "history": exp_histplay,
              "acquire": exp_acquire, "ref": exp_ref, "display": exp_display,
              "cursor": exp_cursor, "dvm": exp_dvm, "mask": exp_mask,
              "fft": exp_fft, "save": exp_save, "runall": exp_runall}.get(name)
        if name == "trig":
            exp_trig(sc, a.args[0] if a.args else "PULSE")
        elif fn:
            fn(sc)
        else:
            print("unknown experiment", name)
    finally:
        sc.close()
