$ErrorActionPreference = "Stop"
$client = New-Object System.Net.Sockets.TcpClient
$client.ReceiveTimeout = 3000
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
    return $clean
}

Write-Output "=== after ASET, check state ==="
Write-Output ("TRIG:STAT? => " + (Send-Raw "TRIG:STAT?"))
Write-Output ("TRIG:MODE? => " + (Send-Raw "TRIG:MODE?"))
Write-Output ("C1:PAVA? FREQ => " + (Send-Raw "C1:PAVA? FREQ"))

Write-Output "`n=== test STOP -> MODE AUTO recovery ==="
Send-Raw "TRIG:STOP" | Out-Null
Start-Sleep -Milliseconds 300
Write-Output ("after STOP: STAT=" + (Send-Raw "TRIG:STAT?") + " MODE=" + (Send-Raw "TRIG:MODE?"))
Send-Raw "TRIG:MODE AUTO" | Out-Null
Start-Sleep -Milliseconds 1000
Write-Output ("after MODE AUTO: STAT=" + (Send-Raw "TRIG:STAT?") + " MODE=" + (Send-Raw "TRIG:MODE?"))

Write-Output "`n=== proper SINGLE sequence: MODE SINGLE -> RUN -> wait Stop ==="
Send-Raw "TRIG:MODE SINGLE" | Out-Null
Start-Sleep -Milliseconds 200
Send-Raw "TRIG:RUN" | Out-Null
Start-Sleep -Milliseconds 200
$s = Send-Raw "TRIG:STAT?"
Write-Output "immediately: $s"
for ($i=0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 300
    $s = Send-Raw "TRIG:STAT?"
    if ($s -match "Stop") { Write-Output "captured at $($i*300)ms"; break }
}
Write-Output ("single result: FREQ=" + (Send-Raw "C1:PAVA? FREQ") + " DUTY=" + (Send-Raw "C1:PAVA? DUTY"))

Write-Output "`n=== restore AUTO ==="
Send-Raw "TRIG:MODE AUTO" | Out-Null
Start-Sleep -Milliseconds 1000
Write-Output ("final: STAT=" + (Send-Raw "TRIG:STAT?") + " MODE=" + (Send-Raw "TRIG:MODE?"))

$client.Close()
Write-Output "DONE"
