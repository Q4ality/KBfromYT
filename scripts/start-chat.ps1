param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv-live/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup-live.ps1 first.' }
$taskArguments = @((Join-Path $taskRoot 'scripts/start_chat.py'))
if ($Port -ne 0) { $taskArguments += @('--port', "$Port") }
& $taskPython @taskArguments
exit $LASTEXITCODE
