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

Working params: `FREQ`, `DUTY`, `PER`, `PKPK`, `RISE`, `FALL`. Params `VPP`, `VMAX`, `VMIN`, `VTOP`, `VBASE`, `AMP`, `PW`, `NW`, `VRMS`, `VAVG` return empty via SCPI (use `PKPK` for peak-to-peak). See the Measurements section below for details.

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
```

**Trigger Level Clamping (IMPORTANT):** The firmware clamps the trigger level to approximately **1.1 × VDIV** from center, NOT the 4.1 × VDIV stated in the programming manual. Always verify with `TRIG:EDGE:LEV?` after setting.

| VDIV | Max trigger level |
|------|-------------------|
| 0.5V | ~0.55V |
| 1.0V | ~1.10V |
| 2.0V | ~2.20V |

For a 3.3V logic signal with VDIV=1V, set trigger to ~0.7V (midpoint of typical 0–1.4V swing after probe attenuation). If you need a higher trigger level, increase VDIV first.

### Auto Setup
```
ASET                  # auto-configure timebase, voltage scale, and trigger for the active signal
```
ASET is the fastest way to get a stable display. After ASET, fine-tune VDIV and TDIV manually.

### Measurements
```
C1:MEAS FREQ,ON       # enable measurement type on C1
C1:PAVA? FREQ         # read -> C1:PAVA FREQ,2.50E+04Hz
C1:PAVA? DUTY         # read -> C1:PAVA DUTY,9.40E+01%
C1:PAVA? PER          # read -> C1:PAVA PER,4.00E-05s
C1:MEAS PKPK,ON       # NOTE: peak-to-peak is PKPK, NOT VPP
C1:PAVA? PKPK         # read -> C1:PAVA PKPK,1.41E+00V
C1:MEAS RISE,ON       # rise time
C1:PAVA? RISE         # read -> C1:PAVA RISE,3.40E-09s
C1:MEAS FALL,ON       # fall time
C1:PAVA? FALL         # read -> C1:PAVA FALL,4.70E-09s
```

**Working measurement parameters (confirmed on SDS2204X HD):**
| Param | Description | Example |
|-------|-------------|---------|
| `FREQ` | Frequency | 2.50E+04 Hz |
| `DUTY` | Duty cycle | 9.48E+01 % |
| `PER` | Period | 4.00E-05 s |
| `PKPK` | Peak-to-peak voltage | 1.41E+00 V |
| `RISE` | Rise time (10%-90%) | 3.40E-09 s |
| `FALL` | Fall time (90%-10%) | 4.70E-09 s |

**Parameters that return EMPTY via SCPI** (but may show on screen):
`VPP`, `VMAX`, `VMIN`, `VTOP`, `VBASE`, `AMP`, `PW`, `NW`, `OVER`, `PRES`, `VRMS`, `VAVG`. Use `PKPK` instead of `VPP`. The on-screen display shows VTOP/VBASE/AMP but they cannot be read via `PAVA?`.

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

The scope can return raw waveform samples via SCPI for programmatic analysis. Uses IEEE 488.2 binary block format.

```
WAV:SOUR C1           # set waveform source channel
WAV:SOUR?             # query -> C1
WAV:PRE?              # waveform descriptor (WAVEDESC) - binary block with calibration data
WAV:DATA?             # raw sample data - binary block, e.g. #6100000<100000 bytes>
```

- `WAV:DATA?` returns `#<n><length><data>` where `<n>` is the digit count of `<length>`. 8-bit samples (0–255, 128 = center). Note: response has a leading `0x00` byte before `#`.
- `WAV:PRE?` returns the LeCroy-compatible WAVEDESC descriptor (also leading `0x00`). Key fields:
  - Offset 156 (float): vertical gain in V/count ≈ `VDIV × 25 / 256`
  - Offset 160 (float): vertical offset in V
  - Offset 176 (float): horizontal interval in s/sample
- Voltage conversion: `V = (sample - 128) * vertical_gain + vertical_offset`
- Data is large (~100 KB). Save to a file; do not print to console.

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

## Save / Recall Setup
```
*SAV 1                    # save current setup to slot 1 (slots 1-10)
RCL 1                     # recall setup from slot 1
```

## DVM (Digital Voltmeter)
```
DVM?                      # DVM state -> OFF
DVM ON                    # enable DVM
DVM:MODE?                 # mode -> DCavg (also DC, AC, AC+DC)
DVM:SOUR?                 # source -> C1
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
C1:MEAS RISE,ON
C1:MEAS FALL,ON
C1:PAVA? FREQ             # -> 2.50E+04 Hz
C1:PAVA? DUTY             # -> 9.48E+01 %
C1:PAVA? PER              # -> 4.00E-05 s
C1:PAVA? PKPK             # -> 1.41E+00 V
C1:PAVA? RISE             # -> 3.40E-09 s
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
