---
name: siglent-scope-control
description: Operate the Siglent SDS2204X HD oscilloscope via SCPI over TCP to measure PWM signals (frequency, duty cycle) for the ReadingLampController4ESP32S3 project. Use when the user asks to measure, verify, or debug PWM output on the oscilloscope, or to operate the scope remotely. Do not use for non-Siglent instruments or for tasks that need only the device API.
---

# Siglent SDS2204X HD Oscilloscope Control

Remote-control the Siglent SDS2204X HD oscilloscope to measure PWM signals from the ESP32-S3 reading lamp controller. Prefer SCPI over TCP (port 5024) over the web VNC interface because it is more reliable for programmatic measurement.

## Device Info

- Scope IP: `192.168.30.105`, web password `12345678`
- DUT IP: `192.168.30.74`, API password `pengping`
- Probe map: CH1=GPIO16(white LED), CH2=GPIO17(yellow LED), CH3=GPIO18(pump), CH4=GPIO8(fan)

## Connection

Use TCP port **5024** (Telnet-style with `>>` prompt). Port 5025 works but hangs after a timeout. Always close and reopen the connection after any read timeout.

```powershell
$client = New-Object System.Net.Sockets.TcpClient
$client.Connect("192.168.30.105", 5024)
$stream = $client.GetStream()
$stream.ReadTimeout = 3000
```

## Read/Write Helpers

```powershell
function Read-UntilPrompt($stream) {
    $buffer = New-Object byte[] 8192
    $all = ""
    try {
        while ($true) {
            $read = $stream.Read($buffer, 0, $buffer.Length)
            if ($read -eq 0) { break }
            $chunk = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $read)
            $all += $chunk
            if ($all -match ">>") { break }
        }
    } catch {}
    return $all
}

function Send-SCPI($stream, $cmd) {
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($cmd + "`r`n")
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
    Start-Sleep -Milliseconds 600
    $raw = Read-UntilPrompt $stream
    $clean = $raw -replace "^\x00", ""
    $lines = $clean -split "`r?`n"
    $result = @()
    foreach ($line in $lines) {
        $t = $line.Trim()
        if ($t -eq "" -or $t -eq ">>" -or $t -eq $cmd) { continue }
        $result += $t
    }
    return ($result -join " | ")
}

$null = Read-UntilPrompt $stream   # consume welcome banner
```

## Measurement Commands

Enable a measurement before reading it. Use one channel per connection to avoid scope hangs.

```
C1:MEAS FREQ,ON      # enable frequency measurement on C1
C1:PAVA? FREQ        # read  -> C1:PAVA FREQ,2.50E+04Hz
C1:MEAS DUTY,ON      # enable duty cycle
C1:PAVA? DUTY        # read  -> C1:PAVA DUTY,9.48E+01%
```

Working params: `FREQ`, `DUTY`, `PER`, `PKPK`, `RMS`, `MAX`, `MIN`, `RISE`, `FALL`. Params `VPP`, `VRMS`, `VMAX`, `VMIN`, `VTOP`, `VBASE`, `AMP`, `PW`, `NW`, `VAVG` return empty via SCPI (use `PKPK`/`RMS`/`MAX`/`MIN` instead). See the Measurements section below for details.

Response values use scientific notation: `2.50E+04` = 25000, `9.48E+01` = 94.8. No signal returns `****` or empty.

## Scope Configuration Commands

All setting commands return empty on success. Query with `?` suffix.

### Channel
```
C1:TURN ON            # turn channel on (C1:TURN OFF to disable)
C1:VDIV 1             # set vertical scale to 1 V/div
C1:VDIV?              # query -> C1:VDIV 1.00E+00V
C1:OFST 0             # set vertical offset to 0 V (CRITICAL: non-zero offset pushes signal off-screen)
C1:OFST?              # query -> C1:OFST 0.00E+00V
C1:COUP DC            # set coupling DC (also AC, GND)
C1:CPL?               # query -> C1:CPL D1M (DC, 1MOhm)
C1:BWL FULL           # bandwidth limit: FULL | 20M | 200M
C1:BWL?               # query -> C1:BWL ON (or FULL)
C1:INVT OFF           # invert waveform: ON | OFF
C1:INVT?              # query -> C1:INVT OFF
C1:UNIT V             # vertical unit: V | A | W
C1:UNIT?              # query -> C1:UNIT V
```
**Note**: coupling query is `CPL?` (not `COUP?` or `COUPLING?`).

### Probe Attenuation
**IMPORTANT**: Probe commands require the full `:CHANn:` prefix — the `Cn:` short form does NOT work.
```
:CHAN1:PROB VAL,1.00E+01   # set probe attenuation to 10X (use NR3 format)
:CHAN1:PROB?               # query -> 1.00E+01 (10X)
:CHAN1:PROB DEF            # reset to default 1X
```
- Probe setting affects displayed VDIV: setting probe from 10X to 1X changes VDIV display from 1V to 0.1V (physical ADC range unchanged).
- For accurate voltage readings, the probe setting MUST match the physical probe attenuation (standard Siglent probes are 10X).
- `C1:PROB?` returns empty — always use `:CHAN1:PROB?`.

### Channel Visible (Display On/Off)
Like probe, requires full `:CHANn:` form:
```
:CHAN1:VIS ON            # show channel 1
:CHAN1:VIS?              # query -> ON
:CHAN2:VIS OFF           # hide channel 2
```

### Vertical Reference Strategy
```
CHAN:REF OFFS            # offset stays fixed when VDIV changes (waveform expands around X-axis)
CHAN:REF POS             # offset stays fixed to grid position when VDIV changes
CHAN:REF?                # query -> OFFSet or POSition
```

### Channel Labels & Deskew (manual pp.46–51)
```
:CHAN1:LAB ON               # show channel 1 label on screen
:CHAN1:LAB:TEXT "WHITE"     # label text, max 20 chars, auto-uppercased
:CHAN1:SKEW 1.52E-09        # probe deskew, range ±100 ns (align multi-channel timing)
```

### Timebase
```
TDIV 1E-5             # set horizontal scale to 10 us/div (scientific notation works)
TDIV?                 # query -> 2.00E-05S
HOR:POS?              # horizontal position (%) -> 50.00 (trigger point at center)
```

### Trigger
```
TRIG:EDGE:SOUR CHAN1  # trigger source (CHAN1..CHAN4)
TRIG:EDGE:SOUR?       # query -> C1
TRIG:EDGE:LEV 1.65    # trigger level in volts
TRIG:EDGE:LEV?        # query -> 1.10E+00
TRIG:EDGE:SLOP POS    # slope: POS or NEG
TRIG:EDGE:SLOP?       # query -> RISing
TRIG:MODE AUTO        # trigger mode: AUTO, NORM, SINGLE
TRIG:MODE?            # query -> AUTO
TRIG:FREQ?            # hardware frequency counter of trigger source (Hz), read-only
TRIG:EDGE:IMP FIFT    # EXT trigger source impedance: ONEMeg|FIFTy (EXT/EXT5 sources only)
FORM:DATA CUSTom,7    # set query response precision: SINGle(7)|DOUBle(14)|CUSTom,1-64 digits
                      # (factory default is 3 significant digits - too coarse for counters)
```

**Trigger Level Clamping (IMPORTANT):** The firmware clamps the trigger level to approximately **1.1 × VDIV** from center, NOT the 4.1 × VDIV stated in the programming manual. Always verify with `TRIG:EDGE:LEV?` after setting.

| VDIV | Max trigger level |
|------|-------------------|
| 0.5V | ~0.55V |
| 1.0V | ~1.10V |
| 2.0V | ~2.20V |

For a 3.3V logic signal with VDIV=1V, set trigger to ~0.7V (midpoint of typical 0–1.4V swing after probe attenuation). If you need a higher trigger level, increase VDIV first.

### Single Trigger & Run Control
Trigger states (`TRIG:STAT?`): `Arm | Ready | Auto | Trig'd | Stop | Roll`.

```
TRIG:MODE SINGLE      # single-shot mode
TRIG:RUN              # arm the single trigger (equivalent to pressing SINGLE/RUN)
TRIG:STAT?            # Arm/Ready while waiting -> Stop after capture
TRIG:STOP             # halt acquisition and freeze waveform (sets MODE to STOP)
TRIG:RUN              # resume from STOP
```

**Verified single-shot flow** (continuous 25kHz PWM):
```
TRIG:MODE SINGLE
TRIG:RUN              # arm
# poll TRIG:STAT? until "Stop" (fires in <300ms with continuous signal)
C1:PAVA? FREQ         # measurements remain readable on frozen waveform
```

**STOP state gotcha (IMPORTANT):** `TRIG:STOP` sets `TRIG:MODE?` to `STOP`. From there, `TRIG:RUN` alone may NOT resume acquisition on this firmware — recovery requires explicitly setting `TRIG:MODE AUTO` again. If the scope gets stuck in `Stop`, send `TRIG:MODE AUTO` then wait ~1s and check `TRIG:STAT?` for `Trig'd`.

### Advanced Trigger Types (manual pp.402–460)
Switch trigger type first, then set type-specific parameters.
```
TRIG:TYPE PULSE           # EDGE|PULSE|SLOPe|INTerval|PATTern|RUNT|WINDow|DROPout|VIDeo|QUALified|NTHEdge|DELay|SETuphold|IIC|SPI|UART|LIN|CAN...
TRIG:TYPE?                # query -> EDGE

# Pulse-width (glitch) trigger — catch anomalous PWM pulses:
TRIG:PULS:SOUR C1         # source
TRIG:PULS:POL POS         # polarity: POSitive|NEGative
TRIG:PULS:LEV 1.65        # level
TRIG:PULS:LIM LESS        # LESSthan|GREATerthan|INNer (between)|OUTer
TRIG:PULS:TLOW 1.0E-6     # lower time bound (s)
TRIG:PULS:TUPP 4.0E-5     # upper time bound (s, used with INNer/OUTer)

# Slope trigger — fires when rise/fall time between two levels is out of range
# (catches slow PWM edges from degraded MOSFET drive):
TRIG:TYPE SLOPE
TRIG:SLOP:SOUR C1         # source (analog channels only)
TRIG:SLOP:SLOP RIS        # RISing|FALLing|ALTernate
TRIG:SLOP:LLEV 0.3        # low level (V)
TRIG:SLOP:HLEV 0.9        # high level (V, must be > LLEV)
TRIG:SLOP:LIM LESS        # LESSthan|GREATerthan|INNer|OUTer (time limits)
TRIG:SLOP:TLOW 2.0E-9     # lower time bound (s; N/A when LIM=LESSthan)
TRIG:SLOP:TUPP 3.0E-8     # upper time bound (s; N/A when LIM=GREATerthan)
TRIG:SLOP:COUP DC         # DC|AC|LFREJect|HFREJect
TRIG:SLOP:HOLD OFF        # holdoff: OFF|EVENts|TIME (+ HLDTime/HLDEVent/HSTart)

# Interval trigger — fires when time between consecutive edges is out of range
# (catches PWM frequency jitter / missing pulses):
TRIG:TYPE INTERVAL
TRIG:INT:SOUR C1          # source
TRIG:INT:SLOP RIS         # edge pair: RISing|FALLing
TRIG:INT:LEV 0.7          # level
TRIG:INT:LIM GREAT        # LESSthan|GREATerthan|INNer|OUTer
TRIG:INT:TLOW 3.9E-5      # lower time bound (s)
TRIG:INT:TUPP 4.1E-5      # upper time bound (s)
TRIG:INT:COUP DC

# Dropout trigger — fires when no edge occurs within a timeout
# (catches a stalled PWM output / firmware hang):
TRIG:TYPE DROPOUT
TRIG:DROP:SOUR C1
TRIG:DROP:SLOP RIS        # edge watched
TRIG:DROP:LEV 0.7
TRIG:DROP:TYPE EDGE       # EDGE (edge timeout) | STATe (state timeout)
TRIG:DROP:TIME 1.0E-4     # timeout, SDS2000X HD range [2E-9, 20] s

# Runt trigger — fires on pulses that cross one level but not the other
# (catches marginal PWM high levels):
TRIG:TYPE RUNT
TRIG:RUNT:SOUR C1
TRIG:RUNT:POL POS         # POSitive|NEGative runt polarity
TRIG:RUNT:LLEV 0.3        # low level (V)
TRIG:RUNT:HLEV 0.9        # high level (V)
TRIG:RUNT:LIM GREAT       # LESSthan|GREATerthan|INNer|OUTer (pulse-width limits)
TRIG:RUNT:TLOW 2.0E-9
TRIG:RUNT:TUPP 2.0E+1

# Window trigger — fires when signal enters or leaves a voltage window:
TRIG:TYPE WINDOW
TRIG:WIND:SOUR C1
TRIG:WIND:TYPE ABS        # ABSolute | RELative window
TRIG:WIND:LLEV 0.2        # window low (V)
TRIG:WIND:HLEV 1.2        # window high (V)

# Pattern trigger — fires on a logic combination across channels
# (e.g. white PWM high AND yellow PWM low):
TRIG:TYPE PATTERN
TRIG:PATT:INP H,L,X,X     # per-channel state H|L|X(don't care), order C1..C4(,D0..D15)
TRIG:PATT:LEV C1,0.7      # per-source level (query: TRIG:PATT:LEV? C1)
TRIG:PATT:LIM GREAT       # optional time qualification: LESSthan|GREATerthan|INNer|OUTer
TRIG:PATT:TLOW 1.0E-6
TRIG:PATT:TUPP 4.0E-5

# Delay trigger — fires when time from edge on source A to edge on source B
# is out of range (measures inter-channel PWM phase shift):
TRIG:TYPE DELAY
TRIG:DEL:SOUR C1          # source A (reference edge)
TRIG:DEL:SOUR2 C2         # source B (delayed edge)
TRIG:DEL:SLOP RIS         # edge on A: RISing|FALLing
TRIG:DEL:SLOP2 RIS        # edge on B
TRIG:DEL:LEV C1,0.7       # level for source A
TRIG:DEL:LEV2 C2,0.7      # level for source B
TRIG:DEL:LIM INN          # LESSthan|GREATerthan|INNer|OUTer
TRIG:DEL:TLOW 0
TRIG:DEL:TUPP 2.0E-5

# Qualified trigger — edge on source E counts only while qualifying source Q
# meets a state/edge condition (e.g. capture white PWM edges only while pump is on):
TRIG:TYPE QUALIFIED
TRIG:QUAL:ES C1           # edge source
TRIG:QUAL:ESL RIS         # edge slope: RISing|FALLing
TRIG:QUAL:ELEV 0.7        # edge level (V)
TRIG:QUAL:QS C3           # qualifying source
TRIG:QUAL:QLEV 0.7        # qualifying level (V)
TRIG:QUAL:TYPE STATE,HIGH # STATe|STATE_DLY (+LOW|HIGH) or EDGE|EDGE_DLY (+RISing|FALLing)
TRIG:QUAL:LIM INN         # delay limits for *_DLY types
TRIG:QUAL:TLOW 3.0E-9
TRIG:QUAL:TUPP 3.0E-8

# Edge trigger extras (holdoff stabilizes complex waveforms):
TRIG:EDGE:HOLDoff TIMe    # holdoff mode: OFF|EVENts|TIMe
TRIG:EDGE:HLDTime 1E-4    # holdoff time (s)
TRIG:EDGE:HLDEVent 3      # holdoff by event count
TRIG:EDGE:NREJ ON         # noise rejection (increases hysteresis)
TRIG:EDGE:COUP DC         # trigger coupling: DC|AC|LFRejet|HFRejet

# Nth-edge trigger — fires on the Nth edge after an idle time (manual pp.538–548).
# Useful to skip a burst preamble and trigger deep inside a PWM train:
TRIG:TYPE NTHEdge
TRIG:NEDG:SOUR C1         # source
TRIG:NEDG:SLOP RIS        # RISing|FALLing
TRIG:NEDG:IDLE 1.00E-4    # idle time before edge counting starts (range 8ns–20s)
TRIG:NEDG:EDGE 100        # fire on this edge number [1, 65535]

# Setup/Hold trigger — fires on setup or hold time violation of data vs clock
# (manual pp.549–558). Needs two channels:
TRIG:TYPE SETuphold
TRIG:SHOL:TYPE SET        # SETup|HOLD violation
TRIG:SHOL:CS C1           # clock source; TRIG:SHOL:CTHR 1.50E+00 = clock threshold
TRIG:SHOL:SLOP RIS        # clock edge
TRIG:SHOL:DS C2           # data source; TRIG:SHOL:DTHR 1.50E+00 = data threshold
TRIG:SHOL:LEV HIGH        # data level to check: LOW|HIGH
TRIG:SHOL:LIM LESS        # LESSthan|GREATerthan|INNer|OUTer
TRIG:SHOL:TUPP 3.00E-08   # time bound [2ns, 20s] (TLOW also available)

# Video trigger (manual pp.442–452) — trigger on analog video sync
# (PAL/NTSC/HDTV or custom). Not used in this project but handy for camera/FPV work:
TRIG:TYPE VIDEO
TRIG:VID:SOUR C1          # source channel
TRIG:VID:LEV 5.00E-01     # trigger level V (range ±(4.1*VDIV-OFST))
TRIG:VID:STAN NTSC        # NTSC|PAL|P720L50|P720L60|P1080L50|P1080L60|I1080L50|I1080L60|CUSTom
TRIG:VID:SYNC SEL         # sync mode: SELect (specific line/field)|ANY (any line)
TRIG:VID:FIEL 1           # field 1|2 (interlaced standards: NTSC/PAL/1080i)
TRIG:VID:LINE 2           # trigger line; range per standard: NTSC f1 [1,263] f2 [1,262],
                          # PAL [1,313]/[1,312], 720p [1,750], 1080p [1,1125], 1080i [1,563]/[1,562]
# Custom standard only:
TRIG:VID:FCNT 1           # fields per frame: 1|2|4|8
TRIG:VID:INT 1            # interlace ratio: 1|2|4|8 (1:1 .. 8:1)
TRIG:VID:LCNT 625         # total lines per frame [300, 2000]
TRIG:VID:FRAT 50Hz        # frame rate: 25Hz|30Hz|50Hz|60Hz
```

### Trigger Cross-Type Details (manual pp.405–548)

These three setting families exist for **every** analog trigger type (EDGE, PULSe, SLOPe,
INTerval, DROPout, RUNT, WINDow, PATTern, NEDGe) with identical syntax — replace `<T>` with
the type prefix (`EDGE|PULS|SLOP|INT|DROP|RUNT|WIND|PATT|NEDG`). DELay has COUPling only.

```
TRIG:<T>:COUP DC          # trigger-path coupling: DC|AC|LFREJect|HFREJect
                          # AC removes dc offset; HFREJect low-passes rf noise;
                          # LFREJect high-passes e.g. power-line hum
TRIG:<T>:NREJ ON          # noise reject ON|OFF (extra hysteresis, rejects glitches)
TRIG:<T>:HOLD TIMe        # holdoff mode: OFF|EVENts|TIMe
TRIG:<T>:HLDT 1.5E-8      # holdoff time, SDS2000X HD range [8ns, 30s]
TRIG:<T>:HLDEV 3          # holdoff event count [1, 100000000]
TRIG:<T>:HST LAST_TRIG    # holdoff reference: LAST_TRIG (from last trigger) |
                          # ACQ_START (from acquisition start)
```

Type-specific extras found only in the manual:

```
# Window trigger — levels can be entered two ways (either pair defines the window):
TRIG:WIND:LLEV 0.2 / TRIG:WIND:HLEV 1.2     # absolute low/high levels (V)
TRIG:WIND:CLEV 0.7 / TRIG:WIND:DLEV 0.5     # OR center level + delta (V), range ±(4.1*VDIV-OFST)

# Pattern trigger — logic combination of the per-channel states:
TRIG:PATT:LOG AND         # AND|OR|NAND|NOR (default AND)

# Delay trigger — trigger-path coupling (no holdoff family on DELay):
TRIG:DEL:COUP DC          # DC|AC|LFREJect|HFREJect

# Nth-edge trigger — has its own level and noise reject:
TRIG:NEDG:LEV 0.5         # trigger level (V), range ±(4.1*VDIV-OFST)
TRIG:NEDG:NREJ ON         # noise reject ON|OFF
```

**SCPI server hang warning:** Do NOT send `ASET` and immediately close the TCP connection — the scope's SCPI server (port 5024) can hang while ASET is processing, refusing new connections (web UI on port 80 stays alive). Wait for ASET to complete (~3-5s, poll `*OPC?`) before disconnecting. If hung, wait several minutes or power-cycle the scope. Note: when the instrument app wedges, BOTH raw 5024 and the HTTP proxy backend report "Device can not be connected" — only a power cycle (or long watchdog timeout) recovers.

## Alternative Channel: HTTP SCPI Proxy
The scope's web server exposes an **unauthenticated** HTTP SCPI proxy — useful as a backup channel or for simple scripts without raw sockets:

```
POST http://192.168.30.105/device_read_write.php
Body: cmd={"cmd":"*idn?","type":"ds","to":"127.0.0.1"}&action=excutescpicmds
Response: {"success":true}\r\n{"retCount":1}\r\n{"cmdrslt":"<scpi response>","from":"127.0.0.1"}
```

PowerShell gotcha: set `[System.Net.ServicePointManager]::Expect100Continue = $false` first, or the embedded web server rejects the request with `417 Expectation Failed`. The proxy routes to the same instrument app as port 5024, so it is equally affected by app-level hangs.

Discovered web UI endpoints (after password login to `/login.php`): `/welcome.php`, `/lan.php`, `/lan_setting.php`, `/SCPI_control.php` (web SCPI console), `/wifi.php`, `/Instrument/novnc/vnc_auto.php`. No remote reboot endpoint exists on the web server; use SCPI `SYST:REB` to reboot when the SCPI server is alive.

### Auto Setup
```
ASET                  # auto-configure timebase, voltage scale, and trigger for the active signal
```
ASET is the fastest way to get a stable display. After ASET, fine-tune VDIV and TDIV manually.
Per the manual (p.23) the official command is `:AUToset` (short `AUT`); `ASET` is also accepted by
this firmware. Autoset is **not recommended for signals below 100 Hz**.

### Measurements
```
C1:MEAS FREQ,ON       # enable measurement type on C1
C1:PAVA? FREQ         # read -> C1:PAVA FREQ,2.50E+04Hz
C1:PAVA? DUTY         # read -> C1:PAVA DUTY,9.48E+01%
C1:PAVA? PER          # read -> C1:PAVA PER,4.00E-05s
C1:MEAS PKPK,ON       # NOTE: peak-to-peak is PKPK, NOT VPP
C1:PAVA? PKPK         # read -> C1:PAVA PKPK,1.40E+00V
C1:PAVA? RMS          # read -> C1:PAVA RMS,1.24E+00V
C1:PAVA? MAX          # read -> C1:PAVA MAX,1.26E+00V
C1:PAVA? MIN          # read -> C1:PAVA MIN,-1.42E-01V
C1:MEAS RISE,ON       # rise time
C1:PAVA? RISE         # read -> C1:PAVA RISE,4.30E-09s
C1:MEAS FALL,ON       # fall time
C1:PAVA? FALL         # read -> C1:PAVA FALL,4.70E-09s
```

**Working measurement parameters (confirmed on SDS2204X HD):**
| Param | Description | Example |
|-------|-------------|---------|
| `FREQ` | Frequency | 2.50E+04 Hz |
| `DUTY` | Duty cycle | 9.48E+01 % |
| `PER` | Period | 4.00E-05 s |
| `PKPK` | Peak-to-peak voltage | 1.40E+00 V |
| `RMS` | RMS voltage | 1.24E+00 V |
| `MAX` | Maximum voltage | 1.26E+00 V |
| `MIN` | Minimum voltage | -1.42E-01 V |
| `RISE` | Rise time (10%-90%) | 4.30E-09 s |
| `FALL` | Fall time (90%-10%) | 4.70E-09 s |

**Parameters that return EMPTY via SCPI** (use alternatives):
`VPP`→use `PKPK`, `VRMS`→use `RMS`, `VMAX`→use `MAX`, `VMIN`→use `MIN`, `VTOP`, `VBASE`, `AMP`, `PW`, `NW`, `OVER`, `PRES`, `VAVG`, `AVG`. The on-screen display shows VTOP/VBASE/AMP/PW/NW but they cannot be read via `PAVA?`. Candidate workaround (unverified): read them through the advanced measurement system (`MEAS:ADV:P<n>:TYPE` + `MEAS:ADV:P<n>:VALue?`) or the simple-mode path (`MEAS:SIMP:ITEM` + `MEAS:SIMP:VALue?`) — see "Advanced Measurement" section.

**Notes:**
- `PAVA?` requires the `?` before the parameter. `PAVA` (no `?`) returns empty.
- Peak-to-peak parameter is `PKPK`, not `VPP`.
- `MEAS?` returns global measurement state (`ON`/`OFF`).

## Invalid / Misleading Commands

- `C1:TURN?`, `C1:SWIT?`, `C1:DISP?` — not valid queries, return empty (but `C1:TURN ON` works for setting)
- `C1:OUTP?` — returns output impedance (`C1:OUTP OFF,LOAD,HZ,PLRT,NOR`), NOT channel display state
- `TRIG:EDGE:LEV` — accepted but value clamped to ~1.1×VDIV; always verify with `TRIG:EDGE:LEV?`
- `C1:PROB?`, `C1:VIS?` — short form returns empty; must use full `:CHAN1:PROB?` / `:CHAN1:VIS?`
- `C1:IMP?` — impedance query returns empty (SDS2204X HD is 1MΩ only, no 50Ω option)
- `DISP:PERS ON` — accepted but `DISP:PERS?` still returns OFF (persistence may not be controllable via SCPI)

## SCPI Response Format Note

All query responses are prefixed with a `0x00` null byte before the actual data. When using `StreamReader.ReadLine()`, this null byte appears as a leading character. Strip it with `$resp.TrimStart([char]0)`. Some responses (like `WAV:DATA?`) use binary block format with the same leading null byte.

## Waveform Data Acquisition

The scope can return raw waveform samples via SCPI for programmatic analysis. Uses IEEE 488.2 binary block format. (Protocol from Programming Guide p663-678; conversion constants for SDS2000X HD confirmed in Table 1 p675.)

```
WAV:SOUR C1           # set waveform source channel (C1-C4, F1-F2 math, D0-D15 digital)
WAV:SOUR?             # query -> C1
WAV:WIDT WORD         # REQUIRED on SDS2000X HD (12-bit ADC); WORD = 16-bit/sample, upper byte first
WAV:STAR 0            # start point (NR1)
WAV:INT 1             # interval between transferred points (decimation)
WAV:POIN 20000        # number of points to transfer (0 = all)
WAV:MAXP?             # max points per transfer piece -> e.g. 10000000
WAV:PRE?              # waveform descriptor (WAVEDESC) - binary block "#9<9digits>" + 346 bytes
WAV:DATA?             # raw sample data - binary block "#N<Ndigits>" + data + trailing 0x0A 0x0A
```

**SDS2000X HD conversion constants** (Programming Guide Table 1, p675):
- `code_per_div = 480`, Center Code = `2047`, Full Code = `4096` (12-bit, left-aligned when WORD)
- For WORD transfers: reconstruct `data_16bit = byte[2i+1]*256 + byte[2i]` (LSB order in practice per guide example), then `code = data_16bit >> (16 - 12)`
- If `code > 2047`: `code = code - 4096` (convert to signed)

**Voltage / time conversion** (p674-675):
- `voltage(V) = code * (vdiv / code_per_div) - voffset`
  - `vdiv` = float at WAVEDESC offset 156 (vertical scale WITHOUT probe attenuation)
  - `voffset` = float at offset 160 (vertical offset without probe attenuation)
  - `code_per_div` = float at offset 164 (should read 480 on this model)
- `time(S) = -delay - (timebase * grid/2) + index * interval`
  - `timebase` = enum short at offset 324 (see enum table p672), `delay` = double at offset 180 (trigger offset, s)
  - `grid = 10` for SDS2000X HD, `interval` = float at offset 176 (sample interval = 1/sampling rate)

**WAVEDESC layout** (starts right after `#9<9-digits>` header; response has leading `0x00`):
| Offset | Type | Field |
|--------|------|-------|
| 0-15 | char[16] | "WAVEDESC" |
| 60-63 | long | WAVE_ARRAY_1: byte count of data array |
| 116-119 | long | wave_array_count: number of data points |
| 156-159 | float | vertical gain (vdiv, no probe atten) |
| 160-163 | float | vertical offset (no probe atten) |
| 164-167 | float | code_per_div (480) |
| 172-173 | short | ADC bits (12) |
| 176-179 | float | horizontal interval (s) |
| 180-187 | double | horizontal offset / trigger delay (s) |
| 324-325 | short | timebase enum |
| 326-327 | short | coupling: 0=DC,1=AC,2=GND |
| 328-331 | float | probe attenuation |
| 334-335 | short | bandwidth limit: 0=OFF,1=20M,2=200M |

- Data is large (~100 KB+). Save to a file; do not print to console. Read raw bytes, not ReadLine().

**Sequence mode frame transfer** (manual p679): when `:ACQuire:SEQuence ON`, select which segment frame `WAV:DATA?` returns:
```
WAV:SEQ 3,0       # transfer frame index 3 only
WAV:SEQ 0,1       # transfer ALL frames starting at index 1 (slice when total exceeds memory)
WAV:SEQ?          # -> <frame>,<start>. Defaults: seq on -> 1; seq+history -> current frame; else 4294967295
```
Frame counts for slicing come from `WAV:PRE?` WAVEDESC fields read_frames (0x90-0x93) and sum_frames (0x94-0x97).

## Display / Status / Acquire
```
DISP:GRID?            # grid mode -> FULL (also HALF, OFF)
DISP:GRID FULL        # set grid mode
DISP:PERS?            # persistence -> OFF
TRIG:STAT?            # trigger status -> Trig'd (or Auto, Ready, Roll, etc.)
ACQ:MODE?             # acquisition mode -> SAMple
ACQ:POIN?             # acquisition memory depth -> 1.00E+05 (100kpts)
ACQ:SRAT?             # sample rate -> 1.00E+09 (1 GSa/s)
*STB?                 # status byte -> 4

# Display extras (manual pp.188–199):
DISP:AXIS ON          # axis labels ON|OFF; DISP:AXIS:MODE FIXed|MOVing
DISP:BACK 100         # backlight brightness 0-100
DISP:COL ON           # color grade ON|OFF (shows waveform density)
DISP:INT 75,100       # intensity: waveform%,grid%
DISP:GRIDS LIGH       # grid style: FULL|LIGHt|NONE
DISP:TRAN 80          # menu transparency 0-100
DISP:CLE              # clear display/persistence
DISP:MENU EMB         # menu style: EMBedded|FLOating
DISP:TYPE VECT        # trace interpolation: VECTor|DOT (DOT draws faster)
```
`TRIG:STAT?` is the quickest way to confirm the scope has a stable trigger before reading measurements.

## Math Operations (FUNCtion)
The scope supports math operations on waveforms. Up to 2 math functions (FUNC1, FUNC2).

```
FUNC1 ON                  # enable math function 1
FUNC1:OPER ADD            # set operation: ADD|SUBTract|MULTiply|DIVision|FFT|INTegrate|DIFF|SQRT|ERES|AVERage|ABSolute|SIGN|IDENtity|NEGation|EXP|TEN|LN|LOG|INTErpolate|MAXHold|MINHold|FILTer
FUNC1:OPER?               # query -> ADD
FUNC1:SOUR1 C1            # source 1 (C1-C4, F1-F2)
FUNC1:SOUR2 C2            # source 2 (for ADD/SUBT/MULT/DIV)
FUNC1:SOUR1?              # query -> C1
FUNC1:SCAL 1              # math vertical scale (V/div)
FUNC1:OFST 0              # math vertical offset
FUNC1 OFF                 # disable math
```

**FFT example:**
```
FUNC1 ON
FUNC1:OPER FFT
FUNC1:SOUR1 C1
FUNC1:FFT:AUT NORM        # autoset: SPAN|PEAK|NORMal
FUNC1:FFT:HCEN?           # center frequency -> 0.00E+00
FUNC1:FFT:HSC?            # horizontal scale -> 5.00E+07 (50 MHz/div)
FUNC1:FFT:SPAN?           # span -> 5.00E+08 (500 MHz)
FUNC1:FFT:MODE AVERage,16 # acquisition: NORMal|MAXHold|AVERage[,4-1024]
FUNC1:FFT:UNIT DBVrms     # vertical unit: DBVrms|Vrms|DBm
FUNC1:FFT:WIND FLATtop    # window: RECTangle|BLACkman|HANNing|HAMMing|FLATtop (FLATtop = best amplitude accuracy)
FUNC1:FFT:SEAR:THR -40    # peak-search threshold (unit follows FFT:UNIT)
FUNC1:FFT:SEAR:EXC 20     # peak-search excursion (dB above neighbors)
FUNC1:FFT:SEAR:RES?       # peak list -> Peaks,1,2.50E+04,1.20E+00;2,... (no,freq,ampl)
FUNC2:FFT:RESET           # command only: restart averaging count when FFT:MODE AVERage
```

**Other math operation extras** (manual pp.209–246):
```
# Digital filter operation (FUNCn:OPER FILTer) — e.g. low-pass a noisy PWM:
FUNC1:FILT:TYP LPAS       # LPASs|HPASs|BPASs|BREJect
FUNC1:FILT:HFR 1.00E+06   # upper freq (BPASs/BREJect)
FUNC1:FILT:LFR 1.00E+03   # lower freq
# ERES resolution enhancement (0.5|1.0|1.5|2.0|2.5|3.0 bits):
FUNC1:ERES:BITS 2.0       # for FUNCn:OPER ERES
# MAXHold/MINHold envelope sweeps [1, 2147483646]:
FUNC1:MAXH:SW 100         # maxhold sweep limit
FUNC1:MINH:SW 100         # minhold sweep limit
# Average count for FUNCn:OPER AVERage (SDS2000X HD: 4|16|32|64|128|256|512|1024):
FUNC1:AVER:NUM 128
# Derivative step size (NR1 integer) for FUNCn:OPER DIFF:
FUNC1:DIFF:DX 4
# Integrate (FUNCn:OPER INTegrate): gate between two time thresholds, DC offset:
FUNC1:INTG:GATE ON        # enable gated integration
FUNC:GVAL -1.00E-07,1.00E-07  # gate A/B time positions (global, GA <= GB; clamps to GA=GB)
FUNC1:INTG:OFFS 1.00E-01  # integrate DC offset, range [-1.67, 1.67]
# Upsample factor for FUNCn:OPER INTErpolate: 2|5|10|20:
FUNC1:INTE:COEF 10
# Invert / reposition / label the math trace:
FUNC1:INV ON              # invert math waveform
FUNC1:POS 5.00E-01        # math vertical position (range depends on operation)
FUNC1:LAB ON              # show math label
FUNC1:LAB:TEXT "PWR"      # label text, max 20 chars; saved to non-volatile label list
```

**FFT extras** (manual pp.211–231):
```
FUNC:FFTD SPL             # FFT display layout: SPLit|FULL|EXCLusive
FUNC1:FFT:POIN 128k       # max FFT points, SDS2000X HD: 1k|2k|...|512k|1M
FUNC1:FFT:RESET           # restart averaging count (MODE AVERage)
FUNC1:FFT:LOAD 50         # external load ohm [1, 1000000], only when UNIT=DBm
FUNC1:FFT:SCAL 2.00E+01   # FFT vertical scale: dBVrms/dBm [0.1,20], Vrms [1E-3,10]
FUNC1:FFT:RLEV 1.00E+01   # FFT reference level (range depends on probe & unit)
FUNC1:FFT:SEAR PEAK       # search tool: OFF|PEAK|MARKer
```

## Cursor Measurements
```
CURS ON                   # enable cursors
CURS?                     # query -> ON
CURS:MODE MAN,X           # mode: TRACk | MANual[,X|Y|XY] | MEASure
CURS:MODE?                # query -> MANual,X
CURS:SOURce1 C1           # cursor source 1
CURS:SOURce2 C1           # cursor source 2
CURS:X1 0                 # X1 position in seconds
CURS:X2 4.00E-05          # X2 position in seconds
CURS:X1?                  # query -> 0.00E+00
CURS:X2?                  # query -> 4.00E-05
CURS:XDEL?                # X2-X1 -> 4.00E-05 (40 us)
CURS:IXD?                 # 1/(X2-X1) -> 2.500E+04 (25 kHz) — great for quick frequency check
CURS OFF                  # disable cursors
```

Additional cursor commands (manual pp.55–70):
```
CURS:MODE MAN,Y           # Y cursors (voltage); XY = both
CURS:Y1 1.20E+00          # Y1 position (V), range ±grid/2×VDIV
CURS:Y2 2.80E+00          # Y2 position (V)
CURS:YDEL?                # Y2-Y1 (query only)
CURS:MODE MEASure         # measure cursors: cursor tracks an ADV measurement item
CURS:MITem PKPK,C2        # set measure-cursor item: <type>,<source1>[,<source2>]
CURS:TAGS FIXed           # value tag style: FIXed | FOLLowing (follows cursor)
CURS:XREF DEL             # X expansion strategy: DELay (value fixed) | POSition (screen pos fixed)
CURS:YREF OFFS            # Y expansion strategy: OFFSet (value fixed) | POSition
```

## Measurement Statistics
```
MEAS:ADV:STAT ON          # enable measurement statistics
MEAS:ADV:STAT?            # query -> ON
C1:PAVA? FREQ,MAX         # max value -> C1:PAVA FREQ,2.50E+04Hz
C1:PAVA? FREQ,MIN         # min value
C1:PAVA? FREQ,AVG         # average value
C1:PAVA? FREQ,DEV         # standard deviation
MEAS:ADV:STAT:RES         # reset statistics
```
Suffix `,MAX|,MIN|,AVG|,DEV` to any `PAVA?` query to get statistics. Only works after `MEAS:ADV:STAT ON`.

## Advanced Measurement (MEASure:ADVanced)

The advanced measurement system (manual pp.256–285) supports up to 12 simultaneous measurement items (P1–P12), each with its own source(s), statistics, and a direct value query. **Candidate workaround for params that return empty via `PAVA?`** (TOP/BASE/AMPL/PWID/NWID etc.) — NOT yet live-verified on this unit.

```
MEAS:MODE ADV             # measurement mode: SIMPle | ADVanced
MEAS:ADV:LIN 12           # total displayed items, range [1,12]
MEAS:ADV:P1 ON            # enable item P1
MEAS:ADV:P1:TYPE TOP      # measurement type (full param list below)
MEAS:ADV:P1:SOUR1 C1      # source 1: C<x>|Z<x>|F<x>|D<m>|REFA-REFD
MEAS:ADV:P1:SOUR2 C2      # source 2 (two-source params only; delay accepts C<x> only)
MEAS:ADV:P1:VAL?          # read value -> 3.30E+00 (NR3)
MEAS:ADV:STAT ON          # enable statistics (PAVA? ,MAX/,MIN suffix also needs this)
MEAS:ADV:P1:STAT? CURR    # statistics: ALL|CURRent|MEAN|MAXimum|MINimum|STDev|COUNt
MEAS:ADV:STAT:MAXC 1024   # max statistics count [0,1024], 0 = unlimited
MEAS:ADV:STAT:HISTOG ON   # per-measurement histogram (M1 style only)
MEAS:ADV:STAT:RES         # reset statistics
MEAS:ADV:STYL M1          # display style: M1 (vertical + histogram) | M2 (horizontal, no histogram)
```

Full TYPE list: `PKPK|MAX|MIN|AMPL|TOP|BASE|LEVELX|CMEAN|MEAN|STDEV|VSTD|RMS|CRMS|MEDIAN|CMEDIAN|OVSN|FPRE|OVSP|RPRE|PER|FREQ|TMAX|TMIN|PWID|NWID|DUTY|NDUTY|WID|NBWID|DELAY|TIMEL|RISE|FALL|RISE10T90|FALL90T10|CCJ|PAREA|NAREA|AREA|ABSAREA|CYCLES|REDGES|FEDGES|EDGES|PPULSES|NPULSES|PHA|SKEW|FRR|FRF|FFR|FFF|LRR|LRF|LFR|LFF|PACArea|NACArea|ACArea|ABSACArea|PSLOPE|NSLOPE|TSR|TSF|THR|THF`.

Two-source params (require SOURce1 + SOURce2): `PHA` (phase difference), `SKEW` (time of A edge minus nearest B edge), `FRR/FRF/FFR/FFF` (first-edge pairs), `LRR/LRF/LFR/LFF` (first→last edge pairs), `DELAY`. These enable PWM phase-shift measurement between channels (e.g. white vs yellow LED PWM).

### Simple-Mode Alternative Read (MEASure:SIMPle)

The simple measurement system has its own SCPI read path — a second candidate workaround for empty `PAVA?` params:

```
MEAS:SIMP:SOUR C1         # simple measurement source
MEAS:SIMP:ITEM TOP,ON     # add TOP to the simple measurement window
MEAS:SIMP:VAL? TOP        # read value -> 3.30E+00
MEAS:SIMP:VAL? ALL        # read all simple measurement values at once (except delay types)
```

Simple-mode param names match `PAVA?` except rise/fall time: simple uses `RISE20T80`/`FALL80T20`, advanced uses `RISE10T90`/`FALL90T10`.

### Measurement Thresholds (MEASure:THReshold)

Thresholds define the reference levels used by timing/duty measurements (manual pp.281–285):

```
MEAS:THR:SOUR C1              # threshold source: C<x>|Z<x>|F<x>|REFA-REFD
MEAS:THR:TYPE PERC            # PERCent | ABSolute
MEAS:THR:PERC 80,45,10        # high,mid,low in percent (default 90,50,10)
MEAS:THR:ABS 3.00,1.00,-1.50  # high,mid,low in volts (when TYPE=ABSolute)
```

Use ABSolute thresholds when measuring PWM between fixed logic levels so PER/PWID/DUTY do not drift with amplitude changes.

## Measurement Gate (MEASure:GATE)
Restrict automatic measurements to a time window between gates A and B (manual pp.275–277). Useful to measure a single PWM pulse inside a long capture.
```
MEAS:GATE ON              # enable measurement gate (query: MEAS:GATE? -> ON)
MEAS:GATE:GA -1.00E-07    # gate A position in seconds (range: ±grid/2 × timebase)
MEAS:GATE:GB 1.00E-07     # gate B position in seconds
```
Note: GA cannot exceed GB — out-of-order values are auto-clamped to the other gate.

## Reference Waveforms (REF)
Save a channel snapshot as a reference overlay for visual comparison (manual pp.316–321). Four slots: REFA–REFD.
```
REFA:DATA SAVE,C1         # save C1 waveform into REFA
REFA:DATA LOAD            # show REFA on screen (UNLoad hides it)
REFA:DATA:SOUR?           # query stored source -> C1
REFA:DATA:SCAL 1.00E-01   # vertical scale of the displayed reference
REFA:DATA:POS 2.00E-01    # vertical offset of the displayed reference
REFA:LAB ON               # show label on screen
REFA:LAB:TEXT "REFA"      # set label text (max 20 chars)
```
Typical flow: capture a known-good 25 kHz PWM → `REFA:DATA SAVE,C1` → later `REFA:DATA LOAD` and compare a suspect signal against the golden reference. Cursor sources accept REFA–REFD (`CURS:SOUR1 REFA`).

## Memory Waveforms (MEMory, M1–M4)
Memory waveforms are independent saved traces (manual pp.285–294). Unlike REF overlays, each M has its own horizontal/vertical scale and position, so a fast zoom of one pulse can be displayed alongside the live waveform.
```
MEM1:IMP C1               # import source into M1: C<x>|Z<x>|F<x>|M<x>|"<path>.bin"
MEM1:SWIT ON              # display M1 (query: MEM1:SWIT? -> ON)
MEM1:HOR:SCAL 1.00E-07    # horizontal scale 100 ns/div (independent of live TDIV)
MEM1:HOR:POS 1.00E-05     # horizontal position vs trigger point
MEM1:HOR:SYNC ON          # sync M1 horizontal params to the imported source
MEM1:VERT:SCAL 1.00E-01   # vertical scale
MEM1:VERT:POS 1.00E-01    # vertical position
MEM1:LAB ON               # show label; MEM1:LAB:TEXT "PWM_ref" (max 20 chars)
```

## Search
Count and navigate edges/pulses in the acquired waveform (manual pp.330–368).
```
SEAR ON                   # enable search
SEAR:MODE EDGE            # search mode: EDGE|SLOPe|PULSE|INTerval|RUNT
SEAR:EDGE:SOUR C1         # search source (C1-C4, D0-D15)
SEAR:EDGE:SLOP POS        # search slope
SEAR:EDGE:LEV 0.7         # search level
SEAR:COUN?                # number of found events on current screen -> 4
SEAR:EVEN?                # event index at screen center (acquisition stopped) -> 3
SEAR:EVEN 1               # go to event 1
SEAR:NAV NEXT             # next event
SEAR:NAV PREV             # previous event
SEAR:COPY FROM            # copy trigger settings INTO search (FROMtrigger|TOTRigger|CANCel)
SEAR OFF                  # disable search
```

Non-edge search modes mirror their trigger counterparts (level range [-4.1*VDIV-OFST, 4.1*VDIV-OFST], time bounds [2E-9, 20] s):
```
# Pulse-width search — find abnormally wide/narrow pulses in captured PWM:
SEAR:MODE PULSE
SEAR:PULS:SOUR C1; SEAR:PULS:POL POS; SEAR:PULS:LEV 0.7
SEAR:PULS:LIM LESS        # LESSthan|GREATerthan|INNer|OUTer
SEAR:PULS:TLOW 1.0E-6; SEAR:PULS:TUPP 4.0E-5
# Interval search — find period jitter / missing pulses:
SEAR:MODE INTERVAL
SEAR:INT:SOUR C1; SEAR:INT:SLOP RIS; SEAR:INT:LEV 0.7
SEAR:INT:LIM GREAT; SEAR:INT:TLOW 3.9E-5; SEAR:INT:TUPP 4.1E-5
# Slope search — find slow edges (two levels + time limit):
SEAR:MODE SLOPE
SEAR:SLOP:SOUR C1; SEAR:SLOP:SLOP RIS
SEAR:SLOP:LLEV 0.3; SEAR:SLOP:HLEV 0.9
SEAR:SLOP:LIM GREAT; SEAR:SLOP:TLOW 2.0E-9; SEAR:SLOP:TUPP 3.0E-8
# Runt search — find pulses that fail to reach full amplitude:
SEAR:MODE RUNT
SEAR:RUNT:SOUR C1; SEAR:RUNT:POL POS
SEAR:RUNT:LLEV 0.3; SEAR:RUNT:HLEV 0.9
SEAR:RUNT:LIM GREAT; SEAR:RUNT:TLOW 2.0E-9; SEAR:RUNT:TUPP 2.0E+1
```

## Horizontal Position
```
HOR:POS?                  # trigger horizontal position (%) -> 50.00 (center)
HOR:POS 30                # set to 30%
TIM:DEL 1.00E-05          # main timebase delay (trigger-to-reference time), range [-5000div, 5div]×TDIV
TIM:REF DELay             # zoom reference strategy: DELay (expand around center) | POSition (fixed grid pos)
```

## Save / Recall Setup
```
*SAV 1                    # save current setup to slot 1 (slots 1-10)
RCL 1                     # recall setup from slot 1
SAVE:WAV C1               # save C1 waveform data to file (on scope storage)
SAVE:IMAG                 # save screen image
SAVE:SET                  # save current setup to file
REC:FDEF                  # recall factory defaults
REC:SET INT,1             # recall internal setup slot 1-10
REC:SET EXT,"U-disk0/SIGLENT/default.xml"   # recall .xml setup from U-disk0/local/net_storage
REC:REF REFD,"U-disk0/SIGLENT/math.ref"     # recall .ref waveform file into REFA-REFD
REC:SER                   # delete ALL user files inside scope (refs, setups, masks, defaults) - destructive
```

## Screenshot via SCPI (Preferred Over Browser Automation)

`PRIN?` captures the scope screen and returns image bytes directly over the SCPI socket (Programming Guide p22, p755). This replaces the fragile browser ScreenShot + Save-As dialog workflow.

```
PRIN? BMP               # screen dump as BMP (returns raw image bytes)
PRIN? PNG               # screen dump as PNG
```

- Response is raw binary image data (read raw bytes until stream end; expect a leading `0x00` byte — strip it before writing to file).
- Python/VISA example from the manual (p755): set `chunk_size = 20*1024*1024`, `write("PRIN? BMP")`, `read_raw()`, write bytes to file.
- Also `:SAVE:IMAGe "<path>",<BMP|JPG|PNG>,<OFF|ON>` saves a screenshot to scope storage (`local/...`, `U-disk0/...`, or `net_storage/...`; invert flag ON = white background for printing).
- `:SAVE:MATLab "<path>",C1` saves channel waveform data as .mat to scope storage.

## System Power Commands

```
SYST:REB                # :SYSTem:REBoot — restart the oscilloscope (use to recover a wedged app)
SYST:SHUT               # :SYSTem:SHUTdown — shut down the OS
SYST:PON ON             # Power-On-Line: auto-boot when mains power is restored (keep ON for remote recovery)
SYST:PON?               # query -> ON|OFF
SYST:TOUC ON|OFF        # enable/disable touch screen
SYST:SELFC              # start self-calibration (DISCONNECT ALL PROBES first; takes several minutes)
SYST:SELFC?             # query -> DOING|DONE
```

If the SCPI server hangs, `SYST:REB` cannot be delivered (server is the hung component) — physical power cycle is required. But for a responsive scope, `SYST:REB` is the clean way to apply license/config changes. With `SYST:PON ON`, a power strip switched remotely is enough to recover a wedged scope.

## System Subsystem (SYSTem, manual pp.370–389)

```
SYST:BUZZ ON            # buzzer on/off (key beep)
SYST:CLOC IN_ON         # clock source: EXT (external 10 MHz ref, 10M out disabled)
                        #   IN_ON  = internal ref + 10 MHz output ON (rear [10M Out] port)
                        #   IN_OFF = internal ref + 10 MHz output OFF
SYST:CLOC?              # query -> EXT|IN_ON|IN_OFF
SYST:REM ON             # remote lock: front panel + touch locked, "Remote" shown on screen
SYST:REM?               # query -> ON|OFF
SYST:LANG ENGL          # UI language: SCHinese|TCHinese|ENGLish|FRENch|JAPanese|KORean|DEUTsch|ESPan|RUSSian|ITALiana|PORTuguese
SYST:MENU ON            # menu bar on/off (models with menu switch only)
SYST:SSAV 10MIN         # screensaver: OFF|1MIN|5MIN|10MIN|30MIN|60MIN
SYST:DATE 20261110      # system date, format YYYYMMDD (8-digit NR1)
SYST:TIME 081040        # system time, 24h format HHMMSS
SYST:EDUM AUTOS,OFF     # education mode: lock AUTOSet|MEASure|CURSor (ON=enabled/unlocked)
SYST:EDUM?              # query all -> AUTOSet,ON;MEASure,ON;CURSor,ON
```

### LAN configuration (SYSTem:COMMunicate)

```
SYST:COMM:LAN:TYPE DHCP        # STATIC|DHCP
SYST:COMM:LAN:IPAD "192.168.30.105"   # IP address (STATIC mode; quoted string)
SYST:COMM:LAN:SMAS "255.255.255.0"    # subnet mask
SYST:COMM:LAN:GAT "192.168.30.1"      # gateway
SYST:COMM:LAN:MAC?             # query -> "00:01:D2:0C:00:A0" (read-only)
SYST:COMM:VNCP 5900            # VNC port, range [5900, 5999]
```

### Network storage (SYSTem:NSTorage)

```
SYST:NST "//server/share","user","pwd",0,1,0,0,0   # path,user,pwd,anon,auto_con,rem_path,rem_user,rem_pwd
SYST:NST?                   # password always returned as "***"
SYST:NST:CONN               # mount now
SYST:NST:DISC               # unmount
SYST:NST:STAT?              # query -> ON|OFF (mounted?)
```

## Timebase Window (Zoom)

```
TIM:SCAL 1.00E-05       # main timebase (same as TDIV; NR3 format)
TIM:DEL 1.00E-05        # main delay: time between trigger and delay reference point
TIM:REF DELay           # expansion strategy: DELay (fixed delay) | POSition (fixed grid pos)
TIM:REF:POS 20          # horizontal reference center 0-100% (when REF=DELay)
TIM:WIND ON             # enable zoomed window
TIM:WIND:SCAL 1.00E-06  # zoom window scale (must be <= main scale, auto-clamped)
TIM:WIND:DEL 1.00E-03   # zoom window delay (auto-clamped to keep window in main sweep)
```

## Built-in Waveform Generator (WGEN)

The scope has a built-in function generator (1 channel, front-panel output). Syntax follows the Siglent SDG series. Useful for self-test signals without the ESP32 DUT (requires FG license — verify `C1:OUTP?` responds; an unlicensed unit rejects WGEN commands).

```
C1:OUTP ON                    # enable generator output (query -> C1:OUTP ON,LOAD,HZ,PLRT,NOR)
C1:OUTP LOAD,50               # set load: 50 (ohm) | HZ (high-Z)
C1:BSWV WVTP,PULSE            # wave type: SINE|SQUARE|RAMP|PULSE|NOISE|ARB|DC|PRBS|IQ
C1:BSWV FRQ,25000             # frequency in Hz (not for NOISE/DC)
C1:BSWV DUTY,50               # duty cycle % (SQUARE/PULSE only)
C1:BSWV AMP,3                 # amplitude in Vpp
C1:BSWV OFST,1.5              # offset in V
C1:BSWV WIDTH,2E-5            # positive pulse width in s (PULSE only)
C1:BSWV SYM,50                # ramp symmetry % (RAMP only)
C1:BSWV?                      # query all params -> C1:BSWV WVTP,SINE,FRQ,100HZ,PERI,0.01S,AMP,2V,OFST,0V,...
C1:SYNC ON                    # enable sync output
C1:ARWV INDEX,0               # arbitrary wave by index (use STL? to list)
STL? BUILDIN                  # list stored arbitrary waveforms (index,name pairs)
VOLTPRT ON                    # over-voltage protection
```

Self-test example — generate a 25 kHz, 3 Vpp, 50% PULSE and measure it on C1 (loop the WGEN output into CH1):
```
C1:BSWV WVTP,PULSE
C1:BSWV FRQ,25000
C1:BSWV DUTY,50
C1:BSWV AMP,3
C1:BSWV OFST,1.5
C1:OUTP ON
```
Note: WGEN amplitude/offset accuracy depends on load setting (50 vs HZ) — set `LOAD,HZ` when probing with a 10X probe into the 1MΩ scope input.


## Decode (Serial Protocol)
Two decode buses (BUS1/BUS2). Protocol syntax per Programming Guide pp.70–120 (manual-exact, field-verified where noted).
```
DEC ON                      # enable decode function (query: DEC?)
DEC:BUS1 ON                 # enable decode bus 1
DEC:BUS1:PROT UART          # protocol: IIC|SPI|UART|CAN|LIN (+FLEXray|CANFd|IIS|M1553 options)
DEC:BUS1:FORM HEX           # display format: HEX|DEC|BIN|ASCII
DEC:BUS1:RES?               # read decoded frames -> header row + comma-separated values, frames separated by ';'
DEC:LIST D1                 # show decode list on digital/list display
DEC:BUS1 OFF                # disable decode bus
```

**UART decode:**
```
DEC:BUS1:UART:BAUD 115200bps    # baud: 600|1200|2400|4800|9600|19200|38400|57600|115200bps or CUSTom,<300-20000000>
DEC:BUS1:UART:DLEN 8            # data bits (5-9)
DEC:BUS1:UART:PAR NONE          # parity: NONE|ODD|EVEN
DEC:BUS1:UART:STOP 1            # stop bits (1|1.5|2)
DEC:BUS1:UART:RXSOUR C1         # RX source: C1-C4 | D0-D15 | DIS
DEC:BUS1:UART:TXSOUR C2         # TX source
DEC:BUS1:UART:RXT 1.65          # RX threshold level (V)
DEC:BUS1:UART:IDLE LOW          # idle level: LOW|HIGH
DEC:BUS1:UART:BITO LSBF         # bit order: LSBF|MSBF
```

**I2C decode:**
```
DEC:BUS1:IIC:SCLS C1            # SCL source
DEC:BUS1:IIC:SDAS C2            # SDA source
DEC:BUS1:IIC:SCLT 1.65          # SCL threshold (V)
DEC:BUS1:IIC:SDAT 1.65          # SDA threshold (V)
DEC:BUS1:IIC:RWBit ADDR         # R/W bit position: ADDR|DATA
```

**Serial triggers** (Programming Guide pp.399+, 561+): `:TRIGger:IIC`, `:TRIGger:SPI`, `:TRIGger:UART`, `:TRIGger:CAN`, `:TRIGger:LIN` subsystems — e.g. `TRIG:IIC:COND ADDR` + `TRIG:IIC:ADDR <addr>` triggers on a specific I2C address. Useful to trigger on ESP32 boot UART output or I2C transactions.

**UART trigger** (manual pp.590–603) — trigger on ESP32 UART TX output (e.g. boot log or a specific log byte):
```
TRIG:TYPE UART
TRIG:UART:TTYP RX         # trigger direction: RX|TX (which source to watch)
TRIG:UART:RXS C2          # RX source channel (TXS for TX)
TRIG:UART:RXT 1.65        # RX threshold V (TXT for TX); range ±(4.1*VDIV-OFST)
TRIG:UART:BAUD 115200bps  # 600-115200bps or CUSTom,<300-20000000>
TRIG:UART:DLEN 8          # data length [5, 8]
TRIG:UART:STOP 1          # stop bits: 1|1.5|2
TRIG:UART:PAR NONE        # parity: NONE|ODD|EVEN|MARK|SPACe
TRIG:UART:BIT LSB         # bit order: LSB|MSB
TRIG:UART:IDLE HIGH       # idle level: LOW|HIGH (TTL UART idle = HIGH; RS-232 = LOW)
TRIG:UART:COND DATA       # condition: STARt|STOP|DATA|ERRor (frame/parity error)
TRIG:UART:LIM EQU         # data compare (COND=DATA): EQUal|GREaterthan|LESSthan
TRIG:UART:DATA 83         # trigger byte value, decimal (0x53='S'); 256 = don't care
```

**IIC trigger** (manual pp.561–571) — trigger on I2C bus activity (e.g. sensor/RTC transactions on the ESP32 I2C bus):
```
TRIG:TYPE IIC
TRIG:IIC:SCLS C1          # SCL source (C<x>|D<n>)
TRIG:IIC:SDAS C2          # SDA source
TRIG:IIC:SCLT 1.65        # SCL threshold V; range ±(4.1*VDIV-OFST) on SDS2000X HD
TRIG:IIC:SDAT 1.65        # SDA threshold V
TRIG:IIC:COND 7ADDRess    # condition: STARt|STOP|RESTart|NACK|EEPRom|7ADDRess|10ADDress|DLENgth
TRIG:IIC:ALEN 7BIT        # address length: 7BIT|10BIT
TRIG:IIC:ADDR 60          # trigger address, decimal [0,127] (0x3C = 60, typical OLED)
TRIG:IIC:RWB ANY          # R/W bit (COND=7ADDRess/10ADDress): WRITe|READ|ANY
TRIG:IIC:DATA 256         # data byte [0,256]; 256 = don't care
TRIG:IIC:DAT2 256         # second data byte [0,256]; 256 = don't care
TRIG:IIC:DLEN 1           # data length in bytes [1,12] (used with COND=DLENgth)
TRIG:IIC:LIM EQU          # data compare for COND=EEPRom: EQUal|GREaterthan|LESSthan
```
Condition notes: `EEPRom` triggers on EEPROM reads (1010xxx address + data compare via LIM); `DLENgth` triggers when the transfer reaches DLEN bytes; `NACK` fires on missing ACK — useful to catch a dead I2C device.

**SPI trigger** (manual pp.573–589) — trigger on SPI bus activity:
```
TRIG:TYPE SPI
TRIG:SPI:TTYP MOSI        # trigger data line: MISO|MOSI
TRIG:SPI:CLKS C1          # CLK source (C<x>|D<n>)
TRIG:SPI:CLKT 1.65        # CLK threshold V
TRIG:SPI:MOSIS C2         # MOSI source; MISOSource/MISOThreshold for MISO
TRIG:SPI:MOSIT 1.65       # MOSI threshold V
TRIG:SPI:CSTY CS          # frame detect: CS|NCS|TIMeout[,<time 1E-7..5E-3 s>]
TRIG:SPI:CSS C3           # CS source (NCSSource/NCSThreshold for NCS type)
TRIG:SPI:CST 1.65         # CS threshold V
TRIG:SPI:LATC RIS         # CLK sampling edge: RISing|FALLing
TRIG:SPI:BIT MSB          # bit order: LSB|MSB (query returns LSB|MSB)
TRIG:SPI:DLEN 8           # data length in bits [4,96]
TRIG:SPI:DATA 1,0,0,0,0,0,1,0   # bit pattern MSB-first, one param per bit; X = don't care
```
Notes: `DATA` is a Command (no query) — bit count must match DLENgth, params listed high-to-low bit. With `CSTY TIMeout`, no CS channel is needed: a frame ends when CLK is idle for the timeout.

**CAN trigger** (manual pp.605–613) — trigger on CAN bus frames:
```
TRIG:TYPE CAN
TRIG:CAN:SOUR C1          # source channel (C<x>|D<n>)
TRIG:CAN:THR 1.65         # threshold V
TRIG:CAN:BAUD 500kbps     # 5k/10k/20k/50k/100k/125k/250k/500k/800k/1Mbps or CUSTom,[5000-1000000]
TRIG:CAN:COND ID          # condition: STARt|REMote|ID|ID_AND_DATA|ERRor
TRIG:CAN:IDL 11BITS       # ID length: 11BITS|29BITS
TRIG:CAN:ID 256           # trigger ID, decimal; 11-bit range [0,2048], 29-bit [0,536870912]; max value = don't care
TRIG:CAN:DATA 256         # data byte [0,256]; 256 = don't care (COND=ID_AND_DATA)
TRIG:CAN:DAT2 256         # second data byte [0,256]; 256 = don't care
```

**LIN trigger** (manual pp.614–627) — trigger on LIN bus frames:
```
TRIG:TYPE LIN
TRIG:LIN:SOUR C1          # source channel
TRIG:LIN:THR 1.65         # threshold V
TRIG:LIN:BAUD 19200bps    # 600/1200/2400/4800/9600/19200bps or CUSTom,[300-20000000]
TRIG:LIN:COND ID          # condition: BReak|ID|ID_AND_DATA|DATA_ERROR
TRIG:LIN:ID 43            # trigger ID, decimal [0,64]; 64 = don't care
TRIG:LIN:DATA 256         # data byte [0,256]; 256 = don't care (COND=ID_AND_DATA)
TRIG:LIN:DAT2 256         # second data byte [0,256]; 256 = don't care
TRIG:LIN:ERR:CHEC 1       # COND=DATA_ERROR: trigger on checksum error (0|1)
TRIG:LIN:ERR:SYNC 1       # ...sync-field error (0|1)
TRIG:LIN:ERR:PAR 1        # ...parity error (0|1)
TRIG:LIN:ERR:ID 1         # ...ID error (0|1)
TRIG:LIN:ERR:DLEN 1       # ...data-length error (0|1)
TRIG:LIN:STAN 1           # LIN standard for checksum: 0=Rev1.3, 1=Rev2.x
```

**CAN FD trigger** (manual pp.637–647) — dual-bit-rate CAN FD frames:
```
TRIG:TYPE CANFD
TRIG:CANF:SOUR C1         # source channel
TRIG:CANF:THR 1.65        # threshold V
TRIG:CANF:FTYP CANF       # frame type: BOTH|CAN|CANFd
TRIG:CANF:BAUDN 500kbps   # nominal (arbitration) rate: 10k/25k/50k/100k/250k/1Mbps or CUSTom,[10000-1000000]
TRIG:CANF:BAUDD 2Mbps     # data rate: 500k/1M/2M/5M/8M/10Mbps or CUSTom,[100000-10000000]
TRIG:CANF:COND ID         # STARt|REMote|ID|ID_AND_DATA|ERRor
TRIG:CANF:IDL 11BITS      # 11BITS|29BITS
TRIG:CANF:ID 256          # decimal; max value = don't care
TRIG:CANF:DATA 256        # [0,256]; 256 = don't care
TRIG:CANF:DAT2 256        # second data byte; 256 = don't care
```

**IIS (I2S audio) trigger** (manual pp.648–663) — trigger on audio bus data/conditions:
```
TRIG:TYPE IIS
TRIG:IIS:AVAR IIS         # audio variant: IIS|LJ|RJ (left-justified|right-justified)
TRIG:IIS:BCLKS C1         # BCLK source; BCLKT = threshold
TRIG:IIS:WSS C2           # WS (word select) source; WSTH = threshold
TRIG:IIS:DS C3            # data source; DTHR = threshold
TRIG:IIS:LATC RIS         # BCLK latch edge: RISing|FALLing
TRIG:IIS:LCH LOW          # WS level meaning "left channel": LOW|HIGH
TRIG:IIS:BIT MSB          # bit order: LSB|MSB
TRIG:IIS:CHAN LEFT        # trigger channel: LEFT|RIGHT
TRIG:IIS:COND DATA        # DATA|MUTE|CLIP|GLITch|RISing|FALLing
TRIG:IIS:DLEN 8           # data bits (range depends on channel-bit width and start bit)
TRIG:IIS:COMP EQU         # data compare (COND=DATA): EQUal|GREaterthan|LESSthan
TRIG:IIS:VAL 86           # compare value, decimal; don't care = 256 @ 8-bit
```
MUTE/CLIP/GLITch conditions catch audio dropouts, clipping and glitches — no VAL needed.

**FlexRay trigger** (manual pp.628–636) — automotive FlexRay bus:
```
TRIG:TYPE FLEXRAY
TRIG:FLEX:SOUR C1         # source channel
TRIG:FLEX:THR 1.65        # threshold V
TRIG:FLEX:BAUD 10Mbps     # 2500kbps|5Mbps|10Mbps or CUSTom,[1000000-20000000]
TRIG:FLEX:COND FRAMe      # TSS (start sequence)|FRAMe|SYMBol|ERRor
TRIG:FLEX:FRAM:ID 1793    # frame ID [0,2048]; 2048 = don't care
TRIG:FLEX:FRAM:CYCL 2     # cycle count [0,63]
TRIG:FLEX:FRAM:COMP EQU   # cycle compare: ANY|EQUal|GREaterthan|LESSthan
TRIG:FLEX:FRAM:REP 8      # cycle repetition (COMP=EQUal): 1|2|4|8|16|32|64
```

Note: `DEC:BUS1:PROT?`/`RXSOUR?` may return empty even though set commands work (observed on this firmware). `DEC:BUS1:RES?` is the reliable way to pull decoded data.

## Digital Channels (DIGital subsystem, manual pp.174–187)

**NOT supported on SDS2204X HD** — this unit has no MSO/digital-channel hardware (unlike SDS2000X Plus + SLA1016 or SDS6000). Commands below are documented for completeness; expect empty or error responses on this scope.

```
DIG:ACT D0                # select active digital channel D0..D15
DIG:D0 ON                 # enable/disable digital channel D<n>
DIG:THR1 TTL              # threshold group 1 = D0-D7, group 2 = D8-D15:
                          #   TTL|CMOS|LVCMOS33|LVCMOS25|CUSTom,[-10..10 V]
DIG:SKEW 1.00E-07         # deskew ±100 ns
DIG:HEIG 6.00E+00         # digital waveform area height [4, 8] div
DIG:POS 4.00E+00          # vertical position (div from top)
DIG:LAB15 "IIC_DATA"      # per-channel label (max 7 chars)
DIG:SRAT?                 # digital sample rate (query only) -> e.g. 1.25E+09
DIG:POIN?                 # digital sample points (query only)

# Digital bus (2 buses, each up to 16 bits):
DIG:BUS1:DISP ON          # show bus on screen
DIG:BUS1:MAP D0,D3,D7,D15 # bus bit composition (LSB order); bit width = param count
DIG:BUS1:DEF              # reset bus map to D0..D15
DIG:BUS1:FORM HEX         # display format: BINary|DECimal|HEX|ASCii
```

## DVM (Digital Voltmeter)
```
DVM ON                    # enable DVM (query: DVM?)
DVM:MODE DCavg            # mode: DCavg|DCRMs|ACRMs|PKPK|AMPLitude (manual p206)
DVM:SOUR C1               # source channel
DVM:CURR?                 # read current DVM value -> 0.98E+00 (NR3)
DVM:ARAN ON               # auto range ON|OFF
DVM:ALAR ON               # overload alarm ON|OFF
DVM:HOLD ON               # hold displayed value ON|OFF
```

## History Mode (Segmented Memory)
Records N frames in sequence; review them after capture (manual pp.249–256).
```
HISTOR ON                 # enable history/record mode
HISTOR?                   # query -> ON
HISTOR:FRAM 100           # max frames to record (more points/frame = fewer frames)
HISTOR:FRAM?              # query current frame count setting
HISTOR:INTER 1.00E-03     # playback interval per frame, [1E-06, 1] seconds
HISTOR:LIST?              # list captured frames with timestamps
HISTOR:PLAY               # start playback
HISTOR:TIME?              # timestamp of current frame
```
Typical flow: set trigger → `HISTOR ON` → let it record → `TRIG:STOP` → `HISTOR:FRAM <n>` to step to a frame → `PRIN? PNG` or measurements on that frame.

## Save Waveform Data to Scope Storage
```
SAVE:BIN "U-disk0/Siglent/c1.bin",C1     # binary waveform, path prefix: local/ | U-disk0/ | net_storage/
SAVE:CSV "U-disk0/c1.csv",C1             # CSV export
SAVE:MATL "local/c1.mat",C1              # MATLAB .mat
SAVE:SET "local/setup1.set"              # instrument setup
SAVE:REF "local/ref1",C1                 # save channel as reference waveform
```
Extension must match the format chosen (not auto-detected). If path type omitted, external saves default to `U-disk0`.

## Mask Test (MTESt, Pass/Fail)
Builds a tolerance mask around the current waveform and counts frames that violate it (manual pp.296–308).
```
MTES:SOUR C1              # test source channel
MTES:MASK:CRE 0.8,0.08    # create mask with X,Y margins in div, range [0.08, 4.00]
MTES ON                   # enable mask test
MTES:OPER ON              # start the test run
MTES:COUN?                # results -> FAIL,<n>,PASS,<n>,TOTAL,<n>
MTES:RES                  # reset counters
MTES:FUNC:BUZZ ON         # buzzer on fail
MTES:FUNC:COF ON          # Capture-on-Fail: save failing frame screenshots to SIGLENT/ dir
MTES:FUNC:FTH ON          # Failure-to-History: failing frames go to history memory
MTES:OPER OFF             # stop test
MTES OFF                  # disable
```
Useful for long-run PWM stability soak: leave mask test running on a 25 kHz PWM channel, then read `MTES:COUN?`.

## Acquisition Modes (ACQuire)
```
ACQ:MODE YT               # display mode: YT | XY (Lissajous) | ROLL (strip chart for slow signals)
ACQ:AMOD FAST             # capture rate: FAST (high wfms/s, catches anomalies) | SLOW
ACQ:MDEPth 12.5M          # memory depth (model-dependent; also 125M etc.)
ACQ:POIN 1E5              # acquisition points
ACQ:MMAN FMDepth          # memory management: FMDepth (fixed) | AMDepth (auto)
ACQ:INT ON                # interpolation ON|OFF
ACQ:NUMA?                 # acquisitions since last setting change -> 350
ACQ:CSW                   # clear sweep
```

## System / Error
```
*OPC?                 # operation complete -> 1
SYST:ERR?             # last error, e.g. -113,"Undefined header;..."
```

## PWM Verification Workflow

1. Get DUT status: `Invoke-RestMethod "http://192.168.30.74/status?devicepwd=pengping&mode=get"`
2. Note `whiteApplied`, `yellowApplied`, `fanSpeed`, `pumpSpeed`
3. For each active channel, enable `FREQ` and `DUTY` then read with `PAVA?`
4. Compare measured duty against expected:
   - `calPct = calibratePower(brightness, TABLE)` (lookup-table interpolation in `domain/LightControllFSM.py`)
   - `actualDuty ≈ minDuty + (maxDuty - minDuty) * calPct / 100`
   - minDuty: white=6, yellow=5, fan=15, pump=15; maxDuty=100 for all

## Complete 25 kHz PWM Measurement Workflow

End-to-end sequence to configure the scope for a 25 kHz PWM signal and read measurements:

```
# 0. Set probe attenuation (MUST match physical probe, standard = 10X)
:CHAN1:PROB VAL,1.00E+01
:CHAN2:PROB VAL,1.00E+01

# 1. Reset channel offsets (critical — leftover offsets push signals off-screen)
C1:OFST 0
C2:OFST 0

# 2. Set vertical scale (1 V/div fits typical 1.4V swing with margin)
C1:VDIV 1
C2:VDIV 1

# 3. Set timebase (10 us/div → 40 us period fits in ~4 divisions)
TDIV 1E-5

# 4. Configure trigger on C1, rising edge, auto
TRIG:EDGE:SOUR CHAN1
TRIG:EDGE:SLOP POS
TRIG:MODE AUTO
TRIG:EDGE:LEV 0.7         # ~0.7V midpoint; max is ~1.1V at VDIV=1V (clamped!)

# 5. Confirm stable trigger
TRIG:STAT?                # -> Trig'd

# 6. Enable and read measurements
C1:MEAS FREQ,ON
C1:MEAS DUTY,ON
C1:MEAS PKPK,ON
C1:MEAS PER,ON
C1:MEAS RMS,ON
C1:MEAS MAX,ON
C1:MEAS MIN,ON
C1:MEAS RISE,ON
C1:MEAS FALL,ON
C1:PAVA? FREQ             # -> 2.50E+04 Hz
C1:PAVA? DUTY             # -> 9.48E+01 %
C1:PAVA? PER              # -> 4.00E-05 s
C1:PAVA? PKPK             # -> 1.40E+00 V
C1:PAVA? RMS              # -> 1.24E+00 V
C1:PAVA? MAX              # -> 1.26E+00 V
C1:PAVA? MIN              # -> -1.42E-01 V
C1:PAVA? RISE             # -> 4.30E-09 s
C1:PAVA? FALL             # -> 4.70E-09 s
```

For fastest stable display, send `ASET` first, then override VDIV/TDIV to desired values.

**Quick cursor frequency check:**
```
CURS ON
CURS:MODE MAN,X
CURS:X1 0
CURS:X2 4.00E-05
CURS:IXD?                # -> 2.500E+04 (25 kHz)
CURS OFF
```

## Crosstalk Check (CH3/CH4)

CH3 (pump) and CH4 (fan) often show 25 kHz crosstalk from the LED PWM traces even when fan/pump are off. To confirm crosstalk: turn the light off (`GET .../light?devicepwd=pengping&mode=set&onOffStatus=0`), wait 3 s, re-measure. If the signal disappears, it is crosstalk, not real PWM output.

## Web VNC Screenshot

**Prefer `PRIN? PNG` over any browser workflow** — see "Screenshot via SCPI" above. The noVNC/browser methods below are fallbacks for when the SCPI channel is unavailable but the web UI is alive.

To capture a screenshot of the live scope display, use the noVNC web interface.

**Do NOT** click the "Instrument Control" sidebar link on `welcome.php` — it does not reliably load the VNC view in automated browsers (the page stays on the Instrument Information panel).

**Do** navigate directly to the VNC URL:

```
http://192.168.30.105/Instrument/novnc/vnc_auto.php
```

- If redirected to `login.php`, enter password `12345678`.
- The noVNC WebSocket connection takes 5–10 s to establish; wait until the live scope screen (grid, waveforms, channel labels C1–C4) appears before taking the screenshot.
- The VNC URL was discovered by reading `welcome.php` HTML, finding the `zone_device_control` click handler in `js/main.js`, which does `window.location.href = "/Instrument/novnc/vnc_auto.php"`.

### Native Scope Screenshot (Recommended, More Comprehensive)

The scope's bottom toolbar has a **ScreenShot** button that generates a full-resolution native screenshot (1024×600) including waveform area, measurement panel, readout bar, timebase, and trigger settings — far more informative than a browser page screenshot. The saved file defaults to `ScreenImg.png`.

The browser opens a Windows "Save As" dialog. The browser agent cannot click system dialogs, so coordinate with PowerShell:

1. Launch a detached PowerShell process that watches for the `#32770` dialog class and sends Enter:
   ```powershell
   $script = @'
   Add-Type @"
   using System;
   using System.Runtime.InteropServices;
   public class Win32 {
       [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string n);
       [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
   }
   "@
   $w = New-Object -ComObject wscript.shell
   $deadline = (Get-Date).AddSeconds(90)
   while ((Get-Date) -lt $deadline) {
       $h = [Win32]::FindWindow("#32770", $null)
       if ($h -ne [IntPtr]::Zero) {
           [Win32]::SetForegroundWindow($h) | Out-Null
           Start-Sleep -Milliseconds 400
           $w.SendKeys("{ENTER}")
           Start-Sleep -Milliseconds 800
           if ([Win32]::FindWindow("#32770", $null) -eq [IntPtr]::Zero) { break }
       }
       Start-Sleep -Milliseconds 300
   }
   '@
   $tmp = "$env:TEMP\handle_save_dialog.ps1"
   $script | Out-File $tmp -Encoding UTF8
   Start-Process powershell.exe -ArgumentList "-ExecutionPolicy","Bypass","-File",$tmp -WindowStyle Hidden
   ```
2. Then have the browser agent click the **ScreenShot** button on the scope's bottom toolbar.
3. The handler detects the dialog and sends Enter, saving the file to the browser's default download directory (typically `C:\Users\<user>\Downloads\ScreenImg.png`).

> **Dialog handler reliability notes:**
> - PowerShell `Start-Job` does NOT persist across separate Shell calls — always use `Start-Process` (or `cmd /c start powershell`) for the dialog handler.
> - If `Start-Process powershell.exe -WindowStyle Hidden` fails silently, wrap with `Start-Process cmd.exe -ArgumentList "/c","powershell",...`.
> - If Enter does not dismiss the dialog, try `Alt+S` (`$wshell.SendKeys("%s")`) which directly activates the "保存(S)" button.
> - Always write a log file from the handler to verify it is actually running.

## Stability Tips

- One channel per TCP connection; close after reading.
- ≥600 ms delay between write and read.
- After any timeout, discard the connection and open a new one.
- Use `\r\n` line terminators.

## App Wedge Diagnosis & Recovery

Observed 2026-11-10: the instrument app wedged (likely during an `ASET` + immediate disconnect); every SCPI path died while the Linux web server stayed up. Diagnosis checklist:

| Probe | Healthy | Wedged app symptom |
|-------|---------|--------------------|
| Port 80 (web) | OPEN | OPEN |
| Port 5024 (SCPI telnet) | OPEN | **connection refused** |
| Port 5025 (SCPI raw) | OPEN | connection refused |
| Port 5900 (VNC) | OPEN | OPEN but stalls: sends `RFB 003.008` banner, completes security handshake, then never sends ServerInit |
| Port 111 (rpcbind) | OPEN | OPEN |
| HTTP proxy `device_read_write.php` `*IDN?` | `{"cmdrslt":"Siglent..."}` | `{"cmdrslt":"Device can not  be connected","err":"Device can not  be connected"}` |
| Ports 22 (SSH), 23 (telnet) | closed | closed |

**Recovery: physical power cycle only.** `SYSTem:REBoot` exists in SCPI but cannot be delivered (proxy reports device-not-connected; no reboot endpoint on the web server). VNC input cannot be delivered either (handshake never completes). When a wedge is suspected, confirm with the table above before blaming the network, then ask the user to power-cycle and poll port 5024 until it reopens (boot takes ~1–2 min).

## Serial Bus Decode (DECode) Subsystem (manual pp.71–172)

Two independent decode buses (BUS1, BUS2). Enable the global decode switch, pick a protocol per bus, configure sources/thresholds, then read results as text.

### Global & bus control
```
:DECode ON                  # master decode switch: ON|OFF
:DECode:LIST D1             # on-screen result list: OFF|D1|D2
:DECode:LIST:LINE 6         # list rows shown [1,7]
:DECode:LIST:SCRoll 3       # selected list row
:DECode:BUS1 ON             # per-bus switch: ON|OFF
:DECode:BUS1:PROTocol IIC   # IIC|SPI|UART|CAN|LIN|FLEXray|CANFd|IIS|M1553
:DECode:BUS1:FORMat HEX     # display format: BINary|DECimal|HEX|ASCii
:DECode:BUS1:COPY FROMtrigger   # sync decode settings from trigger (TOTRigger = reverse)
:DECode:BUS1:RESult?        # decoded frames as text; header row first, frames separated by ';'
                             # e.g. "lin,sync,id,parity,data,checksum;\n0x55,0x06,0,0x54\s0x5F,0x46;"
```
Short form: `DEC`. Note CAN/LIN/FLEXray/CANFd/IIS/M1553 decode may require license options on some models.

### Threshold rule (all protocols)
Threshold range for SDS2000X HD: `[-4.1*VDIV - OFST, +4.1*VDIV - OFST]` (same clamp family as trigger level — verify with the `?` query after setting).

### IIC decode (pp.80–86)
```
:DECode:BUS1:IIC:SCLSource C1      # SCL source: C1..C4 (or D0..D15 with MSO)
:DECode:BUS1:IIC:SCLThreshold 1.00E+00
:DECode:BUS1:IIC:SDASource C2
:DECode:BUS1:IIC:SDAThreshold 1.00E+00
:DECode:BUS1:IIC:RWBit ON          # include R/W bit in result: ON|OFF
```

### SPI decode (pp.87–101)
```
:DECode:BUS1:SPI:CLKSource C1      # CLK source + :CLKThreshold
:DECode:BUS1:SPI:MOSISource C2     # MOSI source + :MOSIThreshold
:DECode:BUS1:SPI:MISOSource C3     # MISO source + :MISOThreshold
:DECode:BUS1:SPI:CSTYpe CS         # framing: NCS|CS|TIMeout[,<time 1E-7..5E-3 s>]
:DECode:BUS1:SPI:CSSource C4       # CS source + :CSThreshold (or NCSSource/NCSThreshold)
:DECode:BUS1:SPI:DLENgth 8         # data word length [4,32]
:DECode:BUS1:SPI:BITorder MSB      # LSB|MSB
:DECode:BUS1:SPI:LATChedge RISing  # sampling edge: RISing|FALLing
```

### UART decode (pp.102–112)
```
:DECode:BUS1:UART:RXSource C1      # RX source + :RXThreshold (TX: TXSource/TXThreshold)
:DECode:BUS1:UART:BAUD 115200bps   # 600..115200bps presets | CUSTom[,300..20000000]
:DECode:BUS1:UART:DLENgth 8        # data bits [5,8]
:DECode:BUS1:UART:STOP 1           # stop bits: 1|1.5|2
:DECode:BUS1:UART:PARity NONE      # NONE|ODD|EVEN|MARK|SPACe
:DECode:BUS1:UART:IDLE HIGH        # idle level: LOW|HIGH
:DECode:BUS1:UART:BITorder LSB     # LSB|MSB
```

### CAN / LIN / FlexRay / CAN FD decode (pp.113–129)
```
:DECode:BUS1:CAN:SOURce C1         # + :CAN:THReshold
:DECode:BUS1:CAN:BAUD 500kbps      # 5k..1M presets | CUSTom[,5000..1000000]
:DECode:BUS1:LIN:SOURce C1         # + :LIN:THReshold
:DECode:BUS1:LIN:BAUD 19200bps     # 600..19200 presets | CUSTom[,300..20000000]
:DECode:BUS1:FLEXray:SOURce C1     # + :FLEXray:THReshold
:DECode:BUS1:FLEXray:BAUD 10Mbps   # 2500k|5M|10M | CUSTom[,1000000..20000000]
:DECode:BUS1:CANFd:SOURce C1       # + :CANFd:THReshold
:DECode:BUS1:CANFd:BAUDNominal 500kbps  # 10k..1M presets | CUSTom[,10000..1000000]
:DECode:BUS1:CANFd:BAUDData 2Mbps       # 500k..10M presets | CUSTom[,100000..10000000]
```

### IIS audio decode (pp.130–143)
```
:DECode:BUS1:IIS:BCLKSource C1     # bit clock + :BCLKThreshold
:DECode:BUS1:IIS:WSSource C2       # word select + :WSTHreshold
:DECode:BUS1:IIS:DSource C3        # data + :DTHReshold
:DECode:BUS1:IIS:AVARiant I2S      # I2S|LJ|RJ (justification)
:DECode:BUS1:IIS:LATChedge RISing  # BCLK sampling edge
:DECode:BUS1:IIS:DLENgth 16        # data bits [1,32]
:DECode:BUS1:IIS:SBIT 0            # start bit [0,31]
:DECode:BUS1:IIS:BITorder MSB
:DECode:BUS1:IIS:LCH LOW           # WS level meaning "left": LOW|HIGH
:DECode:BUS1:IIS:ANNotate ALL      # annotate channels: ALL|LEFT|RIGHt
```

### M1553 decode (pp.144–146, option)
```
:DECode:BUS1:M1553:SOURce C1
:DECode:BUS1:M1553:LTHReshold -1.00E+00   # lower threshold (must be < upper)
:DECode:BUS1:M1553:UTHReshold 1.00E+00    # upper threshold
```

### SENT decode (pp.148–157, option)
```
:DECode:BUS1:SENT:SOURce C1        # + :SENT:THReshold
:DECode:BUS1:SENT:FORMat NIBBles   # NIBBles|FSIGnal|SSERial|ESERial
:DECode:BUS1:SENT:CLOCk 3.00E-06   # tick period [500E-9, 300E-6] s
:DECode:BUS1:SENT:IDLE LOW         # idle level
:DECode:BUS1:SENT:LENGth 6         # data nibbles
:DECode:BUS1:SENT:CRC ON           # ON=2010 CRC, OFF=2008 CRC
:DECode:BUS1:SENT:PPULse ON        # pause pulse present
```

### Manchester decode (pp.159–172, option)
```
:DECode:BUS1:MANChester:SOURce C1  # + :MANChester:THReshold
:DECode:BUS1:MANChester:BAUD 9600  # NR1 [500, 5000000] (plain number, no "bps" suffix)
:DECode:BUS1:MANChester:POLarity RISing  # edge encoding logic-1: RISing|FALLing
:DECode:BUS1:MANChester:IDLE LOW
:DECode:BUS1:MANChester:IBITs 8    # idle bits [2,32]
:DECode:BUS1:MANChester:STARt 1    # start edge index [1,32]
:DECode:BUS1:MANChester:SSIZe 0    # sync size [0,32]
:DECode:BUS1:MANChester:HSIZe 0    # header size [0,32]
:DECode:BUS1:MANChester:TSIZe 0    # trailer size [0,32]
:DECode:BUS1:MANChester:WSIZe 8    # word size [2,8]
:DECode:BUS1:MANChester:DSIZe 16   # words per frame [1,255]
:DECode:BUS1:MANChester:DISPlay WORD   # result display: WORD|BIT
:DECode:BUS1:MANChester:BITorder MSB
```

## Acquisition (ACQuire) Subsystem (manual pp.25–38)

```
:ACQuire:TYPE NORMal          # NORMal|PEAK|AVERage[,times]|ERES[,bits]
                              #   AVERage times: 4|16|32|64|128|256|512|1024
                              #   ERES bits: 0.5|1.0|1.5|2.0|2.5|3.0 (boxcar filter, less noise at slow sweeps)
                              #   NOTE: AVERage/ERES not available when SEQuence is ON
:ACQuire:MODE YT              # YT|XY|ROLL (ROLL = strip-chart, for slow events)
:ACQuire:MMANagement AUTO     # memory mgmt: AUTO (max sample rate) | FSRate (fixed rate) | FMDepth (fixed depth)
:ACQuire:MDEPth 200M          # SDS2000X HD: single-ch {20k|200k|2M|20M|200M}, dual-ch {10k|100k|1M|10M|100M}
                              #   reduced when digital ch on / AVERage/ERES / ROLL mode
:ACQuire:SRATe 5.00E9         # fixed sample rate (FSRate mode); auto-clamped to settable value
:ACQuire:AMODe FAST           # capture rate: FAST|SLOW (FAST helps catch anomalies)
:ACQuire:INTerpolation ON     # ON = sinx/x (sinc), OFF = linear
:ACQuire:RESolution 10Bits    # ADC bits: 8Bits|10Bits (SDS2000X Plus / HD)
:ACQuire:SEQuence ON          # segmented memory mode (fast re-arm, capture bursts)
:ACQuire:SEQuence:COUNt 100   # number of segments (max depends on depth/timebase)
:ACQuire:CSWeep               # command only: clear sweeps & restart acquisition
:ACQuire:NUMAcq?              # query: acquisitions since start (reset on setting change)
:ACQuire:POINts?              # query: sample points of current waveform, e.g. 1.25E+08
```
Short form: `ACQ`.
