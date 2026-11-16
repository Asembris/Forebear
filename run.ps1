# Forebear: one-command local run on Windows (PowerShell 5.1+).
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
# Creates .venv (Python 3.12), installs pinned deps, rebuilds the Relate store only if it is
# missing (offline, from the committed raw cache), then serves http://127.0.0.1:8765
Set-Location $PSScriptRoot

function Find-Python312 {
    foreach ($cand in @(@("py", "-3.12"), @("python"), @("python3"))) {
        try {
            $exe = $cand[0]; $args0 = @($cand | Select-Object -Skip 1)
            $v = & $exe @args0 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -eq "3.12") { return ,$cand }
        } catch { }
    }
    return $null
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $py = Find-Python312
    if ($null -eq $py) {
        Write-Host "Python 3.12 was not found (tried: py -3.12, python, python3)." -ForegroundColor Red
        Write-Host "Install it from https://www.python.org/downloads/ and re-run. (relate-db 1.0.2 is tested on 3.12.)"
        exit 1
    }
    $exe = $py[0]; $rest = @($py | Select-Object -Skip 1)
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not create .venv" -ForegroundColor Red; exit 1 }
}
& .venv\Scripts\python.exe -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed (network/proxy?). See the message above." -ForegroundColor Red; exit 1 }
if (-not (Test-Path "data\forebear.rl")) {
    Write-Host "Building data\forebear.rl from data\raw (no network needed)..."
    & .venv\Scripts\python.exe scripts\build_graph.py | Out-Null
}
if (-not (Test-Path "web\dist\index.html")) {
    Write-Host "web\dist missing: building the UI (needs Node 18+)..."
    Push-Location web; npm install --no-audit --no-fund; npm run build; Pop-Location
}
Write-Host "Forebear on http://127.0.0.1:8765  (Ctrl+C to stop)"
Start-Process "http://127.0.0.1:8765"
& .venv\Scripts\python.exe -m uvicorn forebear.api:app --host 127.0.0.1 --port 8765
