param(
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0"
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtualenv not found at $python. Create it with: python -m venv .venv; .\.venv\Scripts\pip.exe install -r requirements.txt"
}

Write-Host "Starting server on http://${Host}:${Port}/" -ForegroundColor Green
& $python -m waitress --listen=${Host}:${Port} wsgi:app
