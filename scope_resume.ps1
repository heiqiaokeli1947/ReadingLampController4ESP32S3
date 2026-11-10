$ErrorActionPreference = "Stop"
$client = New-Object System.Net.Sockets.TcpClient
$client.ReceiveTimeout = 2000
$client.Connect("192.168.30.105", 5024)
$stream = $client.GetStream()
$buf = New-Object byte[] 4096

Start-Sleep -Milliseconds 800
while ($stream.DataAvailable) { $null = $stream.Read($buf, 0, 4096) }

function Send-Raw($cmd, $wait=400) {
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

Write-Output "current state:"
Write-Output ("TRIG:STAT? => " + (Send-Raw "TRIG:STAT?"))
Write-Output ("TRIG:MODE? => " + (Send-Raw "TRIG:MODE?"))

Write-Output "`n=== TRIG:RUN then poll 10x ==="
Send-Raw "TRIG:RUN" | Out-Null
for ($i=0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 400
    Write-Output ("poll $i => " + (Send-Raw "TRIG:STAT?"))
}

Write-Output "`n=== try *OPC? sync ==="
Send-Raw "TRIG:RUN" | Out-Null
Write-Output ("*OPC? => " + (Send-Raw "*OPC?"))
Start-Sleep -Seconds 2
Write-Output ("TRIG:STAT? => " + (Send-Raw "TRIG:STAT?"))

Write-Output "`n=== try ASET to force full restart ==="
Send-Raw "ASET" | Out-Null
Start-Sleep -Seconds 3
Write-Output ("TRIG:STAT? => " + (Send-Raw "TRIG:STAT?"))
Write-Output ("C1:PAVA? FREQ => " + (Send-Raw "C1:PAVA? FREQ"))

$client.Close()
Write-Output "DONE"
