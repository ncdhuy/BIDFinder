[CmdletBinding()]
param([string]$Distro = '')

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$supervisor = Join-Path $repoRoot 'infra\windows\bidfinder-wsl-supervisor.ps1'
$binRoot = Join-Path $env:LOCALAPPDATA 'BIDFinder\bin'
$installedSupervisor = Join-Path $binRoot 'bidfinder-wsl-supervisor.ps1'
$taskName = 'BIDFinder WSL Production Supervisor'

if (-not $Distro) {
    $distros = @(& wsl.exe --list --quiet 2>$null | ForEach-Object { ($_ -replace [char]0, '').Trim() } | Where-Object { $_ })
    if ($distros -contains 'Ubuntu') { $Distro = 'Ubuntu' }
    elseif ($distros.Count -eq 1) { $Distro = $distros[0] }
    else { throw "Cannot determine the WSL distro. Pass -Distro with the registered name." }
}

& wsl.exe --distribution $Distro --exec true 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "WSL distro is not available: $Distro"
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
New-Item -ItemType Directory -Force -Path $binRoot | Out-Null
Copy-Item -LiteralPath $supervisor -Destination $installedSupervisor -Force
$arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$installedSupervisor`" -Distro `"$Distro`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output "Installed and started '$taskName' for distro '$Distro' as '$identity'."
Write-Output "Log: $env:LOCALAPPDATA\BIDFinder\logs\wsl-supervisor.log"
