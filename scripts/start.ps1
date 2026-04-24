param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

$pythonExe = (Resolve-Path (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Test-Path $pythonExe)) {
    throw "Cannot find .venv\\Scripts\\python.exe. Create the virtual environment and install dependencies first."
}

Write-Host "Starting service with project virtual environment:" -ForegroundColor Yellow
Write-Host "  $pythonExe -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload" -ForegroundColor Cyan

Push-Location $projectRoot
try {
    & $pythonExe -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
}
finally {
    Pop-Location
}
