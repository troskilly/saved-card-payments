# Run the app in test/debug mode using .env.test
# Usage: .\run_test.ps1

$envFile = ".env.test"

if (-not (Test-Path $envFile)) {
    Write-Error "Missing $envFile — copy .env.test.example and fill in credentials."
    exit 1
}

# Load .env.test into the current process environment
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*?)\s*=\s*(.*)\s*$') {
        $key = $Matches[1].Trim()
        $val = $Matches[2].Trim()
        [System.Environment]::SetEnvironmentVariable($key, $val, 'Process')
    }
}

$password = [System.Environment]::GetEnvironmentVariable('ST_PASSWORD', 'Process')
if (-not $password) {
    Write-Warning "ST_PASSWORD is not set in $envFile — the app will fail to start."
    Write-Warning "Fill in ST_PASSWORD in $envFile before running."
    exit 1
}

Write-Host "Starting test server at http://localhost:5000" -ForegroundColor Cyan
Write-Host "  /payment?amount=100&...  — payment form" -ForegroundColor Gray
Write-Host "  /test_success            — mock success page (no API call)" -ForegroundColor Gray
Write-Host "  /logs                    — log viewer" -ForegroundColor Gray
Write-Host "  /health                  — health check" -ForegroundColor Gray
Write-Host ""

uv run python app.py
