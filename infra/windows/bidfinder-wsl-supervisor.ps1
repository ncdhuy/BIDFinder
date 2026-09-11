[CmdletBinding()]
param(
    [string]$Distro = 'Ubuntu',
    [int]$IntervalSeconds = 30
)

$ErrorActionPreference = 'Stop'
$logRoot = Join-Path $env:LOCALAPPDATA 'BIDFinder\logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$logPath = Join-Path $logRoot 'wsl-supervisor.log'
$mutex = [Threading.Mutex]::new($false, 'Local\BIDFinder-Wsl-Production-Supervisor')
if (-not $mutex.WaitOne(0)) { exit 0 }

function Write-Log([string]$Message) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) $Message"
}

function Invoke-Wsl([string]$Command) {
    (& wsl.exe -d $Distro -- bash -lc $Command 2>&1 | Out-String).Trim()
}

function Ensure-Services {
    $script = @'
set -u
systemctl --user start bidfinder-typesense.service bidfinder-api.service bidfinder-incremental.timer bidfinder-snapshot.timer bidfinder-log-prune.timer 2>&1 || true
if systemctl --user is-enabled --quiet bidfinder-ingress.service 2>/dev/null; then
  systemctl --user start bidfinder-ingress.service 2>&1 || true
fi
'@
    $result = Invoke-Wsl $script
    if ($result) { Write-Log "service ensure: $result" }
}

try {
    Write-Log "supervisor started distro=$Distro"
    $keepAlive = $null
    while ($true) {
        if ($null -eq $keepAlive -or $keepAlive.HasExited) {
            if ($null -ne $keepAlive) { Write-Log 'WSL keepalive exited; restarting it' }
            $keepAlive = Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', $Distro, '--exec', 'sleep', 'infinity') -PassThru -WindowStyle Hidden
            Start-Sleep -Seconds 3
            Ensure-Services
        }

        $health = Invoke-Wsl 'curl --fail --silent --max-time 5 http://127.0.0.1:8108/health && printf " typesense"; curl --fail --silent --max-time 10 http://127.0.0.1:8001/ready && printf " api"'
        if ($health -match 'true' -and $health -match 'ready') {
            Write-Log 'health PASS'
        } else {
            Write-Log "health WARN: $health"
            Ensure-Services
        }
        Start-Sleep -Seconds ([Math]::Max(10, $IntervalSeconds))
    }
}
catch {
    Write-Log "supervisor ERROR: $($_.Exception.Message)"
    throw
}
finally {
    if ($null -ne $keepAlive -and -not $keepAlive.HasExited) { Stop-Process -Id $keepAlive.Id -Force -ErrorAction SilentlyContinue }
    $mutex.ReleaseMutex() | Out-Null
    $mutex.Dispose()
}
