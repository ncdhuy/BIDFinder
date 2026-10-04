[CmdletBinding()]
param([string]$Distro = 'Ubuntu')

$ErrorActionPreference = 'Stop'
$result = (& wsl.exe -d $Distro -- bash -lc '$HOME/.local/share/bidfinder/production/current/infra/runtime/bidfinder-status.sh' 2>&1 | Out-String).Trim()
Write-Output $result
if ($LASTEXITCODE -gt 1) { exit $LASTEXITCODE }
