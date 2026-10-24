param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskVenv = Join-Path $taskRoot '.venv-live'
$taskPython = Join-Path $taskVenv 'Scripts/python.exe'
Push-Location $taskRoot
try {
    if (-not (Test-Path -LiteralPath $taskPython)) {
        & $Python -m venv $taskVenv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the live virtual environment' }
    }
    & $taskPython -m pip install -r requirements/live-windows-py312.txt -e '.[semantic,dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & $taskPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed' }
    New-Item -ItemType Directory -Path 'data/live' -Force | Out-Null
    & $taskPython -m pip freeze | Set-Content -Encoding utf8 'data/live/environment.freeze.txt'
    if ($LASTEXITCODE -ne 0) { throw 'Could not capture the resolved environment' }
    $env:FASTEMBED_CACHE_PATH = Join-Path $taskRoot 'data/models/fastembed'
    Write-Output "Live environment ready: $taskPython"
    Write-Output "Model cache: $env:FASTEMBED_CACHE_PATH"
}
finally {
    Pop-Location
}
