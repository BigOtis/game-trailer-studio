param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot
Push-Location $repoRoot
try {
    & $Python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ is required'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ or pass -Python <executable>.' }
    if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
    }
    $venvPython = Join-Path $repoRoot '.venv/Scripts/python.exe'
    & $venvPython -m ensurepip --upgrade
    & $venvPython -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $venvPython -m trailer_studio doctor
    if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
    Write-Output 'Ready. Run .venv/Scripts/trailer-studio.exe --help'
} finally { Pop-Location }
