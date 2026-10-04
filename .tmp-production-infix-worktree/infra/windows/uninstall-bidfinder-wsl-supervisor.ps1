[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'BIDFinder WSL Production Supervisor'
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:LOCALAPPDATA 'BIDFinder\bin\bidfinder-wsl-supervisor.ps1') -Force -ErrorAction SilentlyContinue
Write-Output "Removed '$taskName'. WSL, Typesense data, and production state were not changed."
