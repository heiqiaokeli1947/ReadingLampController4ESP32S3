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
C1:PAVA? DUTY        # read  -> C1:PAVA DUTY,4.96E+01%
```

Supported params: `FREQ`, `DUTY`, `VPP`, `AMP`, `VTOP`, `VBASE`. Amplitude params may return empty when measurement slots are full — reduce enabled measurements if so.

Response values use scientific notation: `2.50E+04` = 25000, `4.96E+01` = 49.6. No signal returns `****` or empty.

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
```
**Note**: coupling query is `CPL?` (not `COUP?` or `COUPLING?`).

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
TRIG:EDGE:LEV 1.65    # trigger level in volts (note: scope may clamp/quantize; verify with ?)
TRIG:EDGE:LEV?        # query -> 1.10E+00
TRIG:EDGE:SLOP POS    # slope: POS or NEG
TRIG:EDGE:SLOP?       # query -> RISing
TRIG:MODE AUTO        # trigger mode: AUTO, NORM, SINGLE
TRIG:MODE?            # query -> AUTO
```

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
C1:PAVA? RMS          # read -> C1:PAVA RMS,1.22E+00V
C1:PAVA? MAX          # read -> C1:PAVA MAX,1.26E+00V
C1:PAVA? MIN          # read -> C1:PAVA MIN,-1.46E-01V
```
**Notes:**
- `PAVA?` requires the `?` before the parameter. `PAVA` (no `?`) returns empty.
- Peak-to-peak parameter is `PKPK`, not `VPP`.
- `VTOP`, `VBASE`, `AMP`, `VMAX`, `VMIN`, `VAVG`, `PW`, `NW` return empty even after `MEAS ...,ON` — cause unknown (possibly measurement slot limits or unsupported via SCPI on this firmware).
- `MEAS?` returns global measurement state (`ON`/`OFF`).

## Invalid / Misleading Commands

- `C1:TURN?`, `C1:SWIT?`, `C1:DISP?` — not valid queries, return empty (but `C1:TURN ON` works for setting)
- `C1:OUTP?` — returns output impedance (`C1:OUTP OFF,LOAD,HZ,PLRT,NOR`), NOT channel display state
- `TRIG:EDGE:LEV` — accepted but value may be clamped/quantized; always verify with `TRIG:EDGE:LEV?`

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
DISP:GRID?            # grid mode -> FULL
DISP:PERS?            # persistence -> OFF
TRIG:STAT?            # trigger status -> Trig'd (or Auto, Ready, Roll, etc.)
ACQ:POIN?             # acquisition memory depth -> 1.00E+05 (100kpts)
*STB?                 # status byte -> 4
```
`TRIG:STAT?` is the quickest way to confirm the scope has a stable trigger before reading measurements.

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

End-to-end sequence to configure the scope for a 25 kHz, ~3 Vpp PWM signal and read measurements:

```
# 1. Reset channel offsets (critical — leftover offsets push signals off-screen)
C1:OFST 0
C2:OFST 0

# 2. Set vertical scale (~1 V/div fits 3.3 V logic with margin)
C1:VDIV 1
C2:VDIV 1

# 3. Set timebase (10 us/div → 40 us period fits in ~4 divisions)
TDIV 1E-5

# 4. Configure trigger on C1, rising edge, auto
TRIG:EDGE:SOUR CHAN1
TRIG:EDGE:SLOP POS
TRIG:MODE AUTO
TRIG:EDGE:LEV 1.65        # midpoint of 3.3 V; verify with TRIG:EDGE:LEV?

# 5. Enable and read measurements
C1:MEAS FREQ,ON
C1:MEAS DUTY,ON
C1:MEAS VPP,ON
C1:PAVA? FREQ             # -> 2.50E+04 Hz
C1:PAVA? DUTY             # -> duty in %
C1:PAVA? PER              # -> period in seconds
```

For fastest stable display, send `ASET` first, then override VDIV/TDIV to desired values.

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
