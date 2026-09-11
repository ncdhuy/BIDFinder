[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'BIDFinder WSL Production Supervisor'
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Output "Removed '$taskName'. WSL, Typesense data, and production state were not changed."
