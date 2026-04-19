$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Backend virtualenv not found at backend\.venv. Create it first, then rerun bootstrap-dev.ps1."
}

Write-Host "Installing backend package with dev dependencies..." -ForegroundColor Cyan
$editableTarget = $PSScriptRoot + "[dev]"
& $venvPython -m pip install -e $editableTarget

Write-Host "Backend environment is bootstrapped." -ForegroundColor Green
Write-Host "Recommended verification commands:" -ForegroundColor Cyan
Write-Host "  cd $repoRoot"
Write-Host "  .\backend\.venv\Scripts\python.exe -m pytest backend\tests --ignore=backend/tests/e2e -q"
Write-Host "  .\backend\.venv\Scripts\python.exe -m mypy backend\app backend\harness_support.py backend\run_acquire_smoke.py backend\run_browser_surface_probe.py backend\run_extraction_smoke.py backend\run_test_sites_acceptance.py"
