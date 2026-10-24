param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv-live/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup-live.ps1 first.' }
Push-Location $taskRoot
try {
    & $taskPython -m kbfromyt chat --host 127.0.0.1 --port $Port
    exit $LASTEXITCODE
}
finally { Pop-Location }
