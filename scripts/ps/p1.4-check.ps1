<#
.SYNOPSIS
    Kiểm tra P1.4 — backtest MR + Trend long/short.

.DESCRIPTION
    Chế độ:
      Test     : ruff + pytest engine (không cần mạng, không cần Docker)
      Backtest : chạy backtest 10 symbol trên data/market rồi in tóm tắt + cổng
      All      : Test, Backtest

    Backtest cần data/market đã tải (xem docs/phase1_task.md P1.4). Cổng trượt
    KHÔNG phải lỗi script: đó là kết quả nghiên cứu, script vẫn exit 0.

.PARAMETER Mode
    Test | Backtest | Diagnose | All

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ps\p1.4-check.ps1 -Mode All
#>
[CmdletBinding()]
param(
    [ValidateSet("Test", "Backtest", "Diagnose", "All")]
    [string] $Mode = "Test"
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# Docker/pytest ghi ra stderr -> NativeCommandError; kiểm tra LASTEXITCODE tường minh.
$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$engineDir = Join-Path "${repoRoot}" "engine"
$py = Join-Path "${repoRoot}" ".venv\Scripts\python.exe"
$report = Join-Path "${repoRoot}" "data\reports\p1.4-report.json"

function Bao-Dat {
    param([string] $NoiDung)
    Write-Host "[ĐẠT] ${NoiDung}" -ForegroundColor Green
}

function Bao-Loi {
    param([string] $NoiDung)
    Write-Host "[LỖI] ${NoiDung}" -ForegroundColor Red
}

function Chay-Test {
    if (-not (Test-Path "${py}")) { throw "không tìm thấy .venv\Scripts\python.exe" }
    Push-Location "${engineDir}"
    try {
        $kq = & "${py}" -m pytest tests -q 2>&1
        if ($LASTEXITCODE -ne 0) { throw "pytest engine thất bại" }
        $dong = $kq | Select-Object -Last 1
        $null = & "${py}" -m ruff check app tests 2>&1
        if ($LASTEXITCODE -ne 0) { throw "ruff check thất bại" }
        $null = & "${py}" -m ruff format --check app tests 2>&1
        if ($LASTEXITCODE -ne 0) { throw "ruff format --check thất bại" }
    } finally {
        Pop-Location
    }
    Bao-Dat "test: ${dong}"
}

function Chay-Backtest {
    Push-Location "${engineDir}"
    try {
        $raw = & "${py}" -m app.backtest.run `
            --config (Join-Path "${repoRoot}" "config\mvp.mock.yaml") `
            --data-dir (Join-Path "${repoRoot}" "data") `
            --exchange-info (Join-Path "${repoRoot}" "mock\fixtures\exchangeInfo.json") `
            --start "2024-12-01" --end "2026-11-18" `
            --out "${report}" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "backtest thất bại: $($raw | Select-Object -Last 1)" }
    } finally {
        Pop-Location
    }
    if (-not (Test-Path "${report}")) { throw "không thấy report ${report}" }
    $r = Get-Content -Raw -Encoding UTF8 "${report}" | ConvertFrom-Json
    $mr = ${r}.by_strategy.mean_reversion
    $tr = ${r}.by_strategy.trend_pullback
    $long = ${r}.trend_by_side.LONG
    $short = ${r}.trend_by_side.SHORT
    $dat = @(${r}.gates | Where-Object { ${_}.ok }).Count
    $truot = (${r}.gates | Where-Object { -not ${_}.ok } | ForEach-Object { ${_}.id }) -join ","
    Bao-Dat ("MR n=" + ${mr}.n + " WR=" + ${mr}.win_rate + " E[R]=" + ${mr}.expectancy_r + " | Trend long=" + ${long}.n + " short=" + ${short}.n)
    Bao-Dat ("DD max=" + ${r}.sim.max_dd_pct + "% | cổng đạt " + ${dat} + "/8" + $(if (${truot}) { " — trượt: " + ${truot} } else { "" }))
}

function Chay-ChanDoan {
    Push-Location "${engineDir}"
    try {
        $raw = & "${py}" -m app.backtest.diagnose `
            --config (Join-Path "${repoRoot}" "config\mvp.mock.yaml") `
            --data-dir (Join-Path "${repoRoot}" "data") `
            --exchange-info (Join-Path "${repoRoot}" "mock\fixtures\exchangeInfo.json") `
            --start "2024-12-01" --end "2026-11-18" `
            --out (Join-Path "${repoRoot}" "data\reports\p1.4-diagnose.json") 2>&1
        if ($LASTEXITCODE -ne 0) { throw "chẩn đoán thất bại: $($raw | Select-Object -Last 1)" }
    } finally {
        Pop-Location
    }
    $dong = @($raw | Where-Object { "${_}" -match "^(MR signal|Trend signal|Regime)" })
    foreach ($d in $dong) { Bao-Dat "${d}" }
}

$batDau = Get-Date
try {
    Write-Host "== P1.4: backtest MR + Trend ==" -ForegroundColor Cyan
    if (${Mode} -eq "Test" -or ${Mode} -eq "All") { Chay-Test }
    if (${Mode} -eq "Backtest" -or ${Mode} -eq "All") { Chay-Backtest }
    if (${Mode} -eq "Diagnose") { Chay-ChanDoan }
    $giay = [int]((Get-Date) - ${batDau}).TotalSeconds
    Bao-Dat "P1.4: xong (${giay} giây)"
    exit 0
} catch {
    Bao-Loi $_.Exception.Message
    exit 1
}
