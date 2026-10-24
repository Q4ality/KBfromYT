param([string]$Python = 'python', [switch]$Dev, [switch]$Check)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskArguments = @((Join-Path $taskRoot 'scripts/setup_live.py'))
if ($Dev) { $taskArguments += '--dev' }
if ($Check) { $taskArguments += '--check' }
& $Python @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Local runtime setup failed; see the message above.' }
