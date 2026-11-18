<#
.SYNOPSIS
    Kiểm tra P1.2 — Data + Regime engine.

.DESCRIPTION
    Các chế độ:
      Test      : pytest engine + mock, ruff check, ruff format --check
      Download  : tải klines 1m từ data.binance.vision (bulk tháng/ngày)
      Replay    : chạy replay 2 lần, so hash để chứng minh tất định
      SpotCheck : tìm ngày crash, tuần range, tuần squeeze trong dữ liệu thật
      All       : chạy lần lượt Test, Download, Replay, SpotCheck

.PARAMETER Mode
    Test | Download | Replay | SpotCheck | All

.PARAMETER Symbol
    Symbol dùng cho Replay và SpotCheck (mặc định BTCUSDT).

.PARAMETER Start
    Ngày bắt đầu, định dạng YYYY-MM-DD.

.PARAMETER End
    Ngày kết thúc, định dạng YYYY-MM-DD.

.PARAMETER DataDir
    Thư mục dữ liệu runtime, tính từ gốc repo (mặc định data).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ps\p1.2-check.ps1 -Mode All
#>
[CmdletBinding()]
param(
    [ValidateSet("Test", "Download", "Replay", "SpotCheck", "All")]
    [string] $Mode = "Test",
    [string] $Symbol = "BTCUSDT",
    [string] $Start = "2026-06-01",
    [string] $End = "2026-11-15",
    [string] $HistoryStart = "2025-01-01",
    [string] $DataDir = "data"
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$engineDir = Join-Path "${repoRoot}" "engine"
$mockDir = Join-Path "${repoRoot}" "mock\binance-demo-server"
$py = Join-Path "${repoRoot}" ".venv\Scripts\python.exe"
$dataRoot = Join-Path "${repoRoot}" $DataDir
$reportDir = Join-Path "${dataRoot}" "reports"

if (-not (Test-Path "${py}")) {
    Write-Host "Không tìm thấy Python trong .venv: ${py}" -ForegroundColor Red
    exit 1
}

function Bao-Dat {
    param([string] $NoiDung)
    Write-Host "[ĐẠT] ${NoiDung}" -ForegroundColor Green
}

function Bao-Loi {
    param([string] $NoiDung)
    Write-Host "[LỖI] ${NoiDung}" -ForegroundColor Red
}

function Chay-Test {
    Write-Host "== Kiểm thử engine ==" -ForegroundColor Cyan
    Push-Location "${engineDir}"
    try {
        & "${py}" -m pytest tests -q
        if ($LASTEXITCODE -ne 0) { throw "pytest engine thất bại" }
        & "${py}" -m ruff check app tests
        if ($LASTEXITCODE -ne 0) { throw "ruff check thất bại" }
        & "${py}" -m ruff format --check app tests
        if ($LASTEXITCODE -ne 0) { throw "ruff format thất bại" }
    } finally {
        Pop-Location
    }
    Bao-Dat "engine: pytest + ruff sạch"

    Write-Host "== Kiểm thử mock ==" -ForegroundColor Cyan
    Push-Location "${mockDir}"
    try {
        & "${py}" -m pytest tests -q
        if ($LASTEXITCODE -ne 0) { throw "pytest mock thất bại" }
    } finally {
        Pop-Location
    }
    Bao-Dat "mock: pytest sạch"
}

function Chay-Download {
    Write-Host "== Tải dữ liệu 1m ==" -ForegroundColor Cyan
    Push-Location "${engineDir}"
    try {
        & "${py}" -m app.data.download --symbols "BTCUSDT,ETHUSDT,SOLUSDT" `
            --start "${Start}" --end "${End}" --data-dir "${dataRoot}"
        $ma = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($ma -eq 2) {
        Write-Host "[CẢNH BÁO] Một số file bulk không tồn tại, xem ${reportDir}\p1.2-download.json" -ForegroundColor Yellow
    } elseif ($ma -ne 0) {
        throw "tải dữ liệu thất bại (mã ${ma})"
    } else {
        Bao-Dat "tải dữ liệu xong"
    }
}

function Chay-Replay {
    Write-Host "== Replay tất định ==" -ForegroundColor Cyan
    if (-not (Test-Path "${reportDir}")) {
        New-Item -ItemType Directory -Force -Path "${reportDir}" | Out-Null
    }
    $rep1 = Join-Path "${reportDir}" "p1.2-replay-${Symbol}-1.json"
    $rep2 = Join-Path "${reportDir}" "p1.2-replay-${Symbol}-2.json"
    Push-Location "${engineDir}"
    try {
        & "${py}" -m app.data.replay --symbol "${Symbol}" --start "${Start}" --end "${End}" `
            --data-dir "${dataRoot}" --no-persist --report "${rep1}"
        if ($LASTEXITCODE -ne 0) { throw "replay lần 1 thất bại" }
        & "${py}" -m app.data.replay --symbol "${Symbol}" --start "${Start}" --end "${End}" `
            --data-dir "${dataRoot}" --no-persist --report "${rep2}"
        if ($LASTEXITCODE -ne 0) { throw "replay lần 2 thất bại" }
    } finally {
        Pop-Location
    }
    $h1 = (Get-FileHash -Algorithm SHA256 -Path "${rep1}").Hash
    $h2 = (Get-FileHash -Algorithm SHA256 -Path "${rep2}").Hash
    $bao = (Get-Content "${rep1}" -Raw -Encoding UTF8 | ConvertFrom-Json)
    if (${h1} -ne ${h2}) {
        throw "replay KHÔNG tất định: ${h1} khác ${h2}"
    }
    Bao-Dat "replay hash ${($bao.hash)} (2 lần giống nhau, báo cáo ${h1})"
}

function Chay-SpotCheck {
    Write-Host "== Spot-check 3 giai đoạn ==" -ForegroundColor Cyan
    $out = Join-Path "${reportDir}" "p1.2-spotcheck.json"
    Push-Location "${engineDir}"
    try {
        & "${py}" -m app.data.spotcheck --symbol "${Symbol}" --start "${Start}" --end "${End}" `
            --history-start "${HistoryStart}" --data-dir "${dataRoot}" --out "${out}"
        $ma = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($ma -eq 2) {
        throw "spot-check không đạt cổng, xem ${out}"
    } elseif ($ma -ne 0) {
        throw "spot-check thất bại (mã ${ma})"
    }
    Bao-Dat "spot-check đạt cổng, báo cáo ${out}"
}

switch (${Mode}) {
    "Test" { Chay-Test }
    "Download" { Chay-Download }
    "Replay" { Chay-Replay }
    "SpotCheck" { Chay-SpotCheck }
    "All" {
        Chay-Test
        Chay-Download
        Chay-Replay
        Chay-SpotCheck
    }
}

Write-Host "Hoàn tất chế độ ${Mode}." -ForegroundColor Green
