$ErrorActionPreference = "Stop"
$client = New-Object System.Net.Sockets.TcpClient
$client.ReceiveTimeout = 2000
$client.Connect("192.168.30.105", 5024)
$stream = $client.GetStream()
$buf = New-Object byte[] 4096

Start-Sleep -Milliseconds 800
while ($stream.DataAvailable) { $null = $stream.Read($buf, 0, 4096) }

function Send-Raw($cmd, $wait=500) {
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

Write-Output "=== FULL SINGLE TRIGGER FLOW ==="
Send-Raw "TRIG:EDGE:SOUR CHAN1"
Send-Raw "TRIG:EDGE:SLOP POS"
Send-Raw "TRIG:EDGE:LEV 0.7"
Send-Raw "TRIG:MODE SINGLE"
Send-Raw "TRIG:RUN"          # arm
Start-Sleep -Milliseconds 200
Send-Raw "TRIG:STAT?"          # expect Arm/Ready then Stop after fire
$stat = ""
for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 300
    $stat = Send-Raw "TRIG:STAT?"
    if ($stat -match "Stop") { Write-Output "FIRED after $($i*300)ms"; break }
}
Send-Raw "C1:PAVA? FREQ"
Send-Raw "C1:PAVA? DUTY"

Write-Output "=== RE-ARM WITH TRIG:RUN ==="
Send-Raw "TRIG:RUN"
Start-Sleep -Milliseconds 200
for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 300
    $stat = Send-Raw "TRIG:STAT?"
    if ($stat -match "Stop") { Write-Output "RE-FIRED after $($i*300)ms"; break }
}
Send-Raw "C1:PAVA? FREQ"

Write-Output "=== STOP COMMAND ==="
Send-Raw "TRIG:MODE AUTO"
Send-Raw "TRIG:RUN"
Start-Sleep -Milliseconds 800
Send-Raw "TRIG:STAT?"          # expect Trig'd
Send-Raw "TRIG:STOP"           # freeze
Start-Sleep -Milliseconds 300
Send-Raw "TRIG:STAT?"          # expect Stop
Send-Raw "C1:PAVA? FREQ"       # measurement on frozen waveform

Write-Output "=== RESUME AUTO ==="
Send-Raw "TRIG:RUN"
Start-Sleep -Milliseconds 800
Send-Raw "TRIG:STAT?"

$client.Close()
Write-Output "DONE"
