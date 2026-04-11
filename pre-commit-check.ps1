# pre-commit-check.ps1
# This script enforces basic code quality gates before committing.
# It checks for syntax errors, basic linting issues, and runs the test suite.

$env:PYTHONPATH='.'
$env:PYTHONDONTWRITEBYTECODE=1

Write-Host "--- Stage 1: Syntax & Lint Check ---" -ForegroundColor Cyan
# Using ruff for fast linting. If ruff is missing, skip but warn.
if (Get-Command ruff -ErrorAction SilentlyContinue) {
    ruff check backend/app --select E,W,F --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Linter failed. Please fix issues before committing." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Ruff not found. Skipping lint stage." -ForegroundColor Yellow
}

Write-Host "--- Stage 2: Fast Test Suite ---" -ForegroundColor Cyan
# Run tests, ignoring slow e2e tests, stop at first failure.
pytest backend\tests --ignore=backend/tests/e2e -q --tb=line -x
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed. Fix regressions before committing." -ForegroundColor Red
    exit 1
}

Write-Host "All checks passed! Ready to commit." -ForegroundColor Green
exit 0
