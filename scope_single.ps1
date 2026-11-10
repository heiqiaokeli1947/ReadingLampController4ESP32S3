$ErrorActionPreference = "Stop"
$client = New-Object System.Net.Sockets.TcpClient
$client.ReceiveTimeout = 2000
$client.Connect("192.168.30.105", 5024)
$stream = $client.GetStream()
$buf = New-Object byte[] 4096

Start-Sleep -Milliseconds 800
while ($stream.DataAvailable) { $null = $stream.Read($buf, 0, 4096) }

function Send-Raw($cmd, $wait=600) {
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($cmd + "`n")
    $stream.Write($bytes, 0, $bytes.Length)
    Start-Sleep -Milliseconds $wait
    $resp = ""
    try {
        while ($stream.DataAvailable) {
            $n = $stream.Read($buf, 0, 4096)
            $resp += [System.Text.Encoding]::ASCII.GetString($buf, 0, $n)
        }
    } catch {}
    $clean = $resp.TrimStart([char]0).Trim()
    if ($clean -eq "") { $clean = "(empty)" }
    Write-Output "$cmd => $clean"
    return $clean
}

Write-Output "=== SINGLE TRIGGER SETUP ==="
# Channel setup
Send-Raw ":CHAN1:PROB VAL,1.00E+01"
Send-Raw "C1:TURN ON"
Send-Raw "C1:OFST 0"
Send-Raw "C1:VDIV 1"
Send-Raw "C1:COUP DC"
Send-Raw "TDIV 1E-5"
# Trigger: SINGLE mode
Send-Raw "TRIG:EDGE:SOUR CHAN1"
Send-Raw "TRIG:EDGE:SLOP POS"
Send-Raw "TRIG:EDGE:LEV 0.7"
Send-Raw "TRIG:MODE SINGLE"
Start-Sleep -Milliseconds 300

Write-Output "=== ARM & WAIT FOR TRIGGER ==="
# Check status - should be Ready/Wait while armed
Send-Raw "TRIG:STAT?"
# Wait and poll until triggered (signal is continuous 25kHz, should trigger immediately)
$max = 10
for ($i=0; $i -lt $max; $i++) {
    Start-Sleep -Milliseconds 500
    $stat = Send-Raw "TRIG:STAT?"
    if ($stat -match "Stop|Trig") { 
        Write-Output "Trigger completed after $($i*500)ms"
        break 
    }
}

Write-Output "=== POST-TRIGGER MEASUREMENTS ==="
Send-Raw "C1:MEAS FREQ,ON"
Send-Raw "C1:MEAS DUTY,ON"
Send-Raw "C1:MEAS PKPK,ON"
Start-Sleep -Milliseconds 800
Send-Raw "C1:PAVA? FREQ"
Send-Raw "C1:PAVA? DUTY"
Send-Raw "C1:PAVA? PKPK"
Send-Raw "TRIG:STAT?"

Write-Output "=== RE-ARM TEST ==="
# For single mode, sending TRIG:MODE SINGLE again re-arms
Send-Raw "TRIG:MODE SINGLE"
Start-Sleep -Milliseconds 300
Send-Raw "TRIG:STAT?"
Start-Sleep -Milliseconds 800
Send-Raw "TRIG:STAT?"

# Restore AUTO mode
Send-Raw "TRIG:MODE AUTO"
Start-Sleep -Milliseconds 500
Send-Raw "TRIG:STAT?"

$client.Close()
Write-Output "DONE"
