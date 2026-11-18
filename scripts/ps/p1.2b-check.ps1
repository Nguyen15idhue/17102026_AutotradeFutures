<#
.SYNOPSIS
    Kiểm tra P1.2b — trend_dir + khung 4h.

.DESCRIPTION
    Chế độ:
      Test   : ruff + pytest engine (không cần mạng, không cần data/market)
      Replay : chạy replay 2 lần, so hash để chứng minh tất định
      Check  : trên dữ liệu thật — TREND có cả up/down, trend_dir bền >= 3 nến
      All    : Test, Replay, Check

    Lưu ý: script KHÔNG chạy spot-check cổng A/B/C/D của P1.2. Cổng D đang fail
    (50,85% so với ngưỡng 50%) và được giữ nguyên có chủ ý; chạy ở đây sẽ làm
    script đỏ vĩnh viễn. Dùng scripts/ps/p1.2-check.ps1 -Mode SpotCheck khi cần.

.PARAMETER Mode
    Test | Replay | Check | All

.PARAMETER Symbol
    Symbol dùng cho Replay và Check (mặc định BTCUSDT).

.PARAMETER Start
    Ngày bắt đầu, định dạng YYYY-MM-DD.

.PARAMETER End
    Ngày kết thúc, định dạng YYYY-MM-DD.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ps\p1.2b-check.ps1 -Mode All
#>
[CmdletBinding()]
param(
    [ValidateSet("Test", "Replay", "Check", "All")]
    [string] $Mode = "Test",
    [string] $Symbol = "BTCUSDT",
    [string] $Start = "2026-06-01",
    [string] $End = "2026-11-15",
    [string] $DataDir = "data"
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$engineDir = Join-Path "${repoRoot}" "engine"
$py = Join-Path "${repoRoot}" ".venv\Scripts\python.exe"
$dataRoot = Join-Path "${repoRoot}" $DataDir
$marketRoot = Join-Path "${dataRoot}" "market"
$reportDir = Join-Path "${dataRoot}" "reports"

if (-not (Test-Path "${py}")) {
    Write-Host "[LỖI] Không tìm thấy Python trong .venv: ${py}" -ForegroundColor Red
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

function Rut-Gon {
    param([string] $Chuoi, [int] $Dai = 8)
    if ([string]::IsNullOrEmpty($Chuoi)) { return "-" }
    if ($Chuoi.Length -le ${Dai}) { return $Chuoi }
    return $Chuoi.Substring(0, ${Dai}) + "…"
}

function Chay-Test {
    Push-Location "${engineDir}"
    try {
        $kq = & "${py}" -m pytest tests -q 2>&1
        if ($LASTEXITCODE -ne 0) {
            $kq | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
            throw "pytest engine thất bại"
        }
        $dong = $kq | Select-Object -Last 1
        $null = & "${py}" -m ruff check app tests 2>&1
        if ($LASTEXITCODE -ne 0) { throw "ruff check thất bại" }
    } finally {
        Pop-Location
    }
    Bao-Dat "test: ${dong}"
}

function Chay-Replay {
    if (-not (Test-Path "${reportDir}")) {
        New-Item -ItemType Directory -Force -Path "${reportDir}" | Out-Null
    }
    $r1 = Join-Path "${reportDir}" "p1.2b-replay-1.json"
    $r2 = Join-Path "${reportDir}" "p1.2b-replay-2.json"
    Push-Location "${engineDir}"
    try {
        $null = & "${py}" -m app.data.replay --symbol "${Symbol}" --start "${Start}" --end "${End}" `
            --data-dir "${dataRoot}" --no-persist --report "${r1}"
        if ($LASTEXITCODE -ne 0) { throw "replay lần 1 thất bại" }
        $null = & "${py}" -m app.data.replay --symbol "${Symbol}" --start "${Start}" --end "${End}" `
            --data-dir "${dataRoot}" --no-persist --report "${r2}"
        if ($LASTEXITCODE -ne 0) { throw "replay lần 2 thất bại" }
    } finally {
        Pop-Location
    }
    $h1 = (Get-FileHash -Algorithm SHA256 -Path "${r1}").Hash
    $h2 = (Get-FileHash -Algorithm SHA256 -Path "${r2}").Hash
    if (${h1} -ne ${h2}) { throw "replay KHÔNG tất định (${h1} khác ${h2})" }
    $bao = Get-Content "${r1}" -Raw -Encoding UTF8 | ConvertFrom-Json
    $hashNgan = Rut-Gon ([string] $bao.hash)
    $soNen = $bao.bars
    Bao-Dat "replay: hash ${hashNgan} (2 lần giống nhau, ${soNen} nến)"
}

function Chay-Check {
    if (-not (Test-Path "${marketRoot}")) {
        throw "không có dữ liệu tại ${marketRoot} (chạy p1.2-check.ps1 -Mode Download trước)"
    }
    $ma = @'
from datetime import date
import os
import app.data.replay as R

sym = os.environ["P12B_SYMBOL"]
start = date.fromisoformat(os.environ["P12B_START"])
end = date.fromisoformat(os.environ["P12B_END"])
root = os.environ["P12B_MARKET"]

bars_1m, _ = R.load_1m(root, sym, start, end)
if not bars_1m:
    raise SystemExit("khong co du lieu")
bars15 = R.to_15m(bars_1m, sym)
out = R.run_bars(sym, bars15)

up = dn = 0
bad = 0
for i, r in enumerate(out.rows):
    d = r["trend_dir"]
    if not d:
        continue
    if d > 0:
        up += 1
    else:
        dn += 1
    # trend_dir chi duoc phep lo ra khi huong EMA da giu >= 3 nen lien tiep.
    # Kiem tra nguoc tu nen hien tai (dung feature cua tung nen, khong look-ahead).
    lien_tiep = 0
    j = i
    while j >= 0:
        fj = out.rows[j]["feature"]
        if not fj:
            break
        e50, e200 = fj.get("ema50"), fj.get("ema200")
        if e50 is None or e200 is None:
            break
        s = 1 if e50 > e200 else -1
        if s != d:
            break
        lien_tiep += 1
        j -= 1
    if lien_tiep < 3:
        bad += 1

print("up=%d down=%d bad=%d bars=%d" % (up, dn, bad, len(out.rows)))
'@
    $env:P12B_SYMBOL = ${Symbol}
    $env:P12B_START = ${Start}
    $env:P12B_END = ${End}
    $env:P12B_MARKET = ${marketRoot}
    Push-Location "${engineDir}"
    try {
        $kq = $ma | & "${py}" -
        if ($LASTEXITCODE -ne 0) { throw "kiểm tra trend_dir thất bại" }
    } finally {
        Pop-Location
        Remove-Item Env:\P12B_SYMBOL, Env:\P12B_START, Env:\P12B_END, Env:\P12B_MARKET -ErrorAction SilentlyContinue
    }
    $dong = $kq | Select-Object -Last 1
    if (${dong} -notmatch "up=(\d+) down=(\d+) bad=(\d+)") {
        throw "không đọc được kết quả kiểm tra"
    }
    $up = [int]$Matches[1]
    $dn = [int]$Matches[2]
    $bad = [int]$Matches[3]
    if (${up} -le 0) { throw "không có nến TREND tăng (trend_dir=+1)" }
    if (${dn} -le 0) { throw "không có nến TREND giảm (trend_dir=-1)" }
    if (${bad} -ne 0) { throw "có ${bad} nến trend_dir lộ ra khi hướng chưa đủ 3 nến" }
    Bao-Dat "trend_dir: up ${up} / down ${dn}, vi phạm bền 3 nến: ${bad}"
}

$batDau = Get-Date
$soMuc = 0
try {
    Write-Host "== P1.2b: trend_dir + khung 4h ==" -ForegroundColor Cyan
    if (${Mode} -eq "Test" -or ${Mode} -eq "All") { Chay-Test; $soMuc = $soMuc + 1 }
    if (${Mode} -eq "Replay" -or ${Mode} -eq "All") { Chay-Replay; $soMuc = $soMuc + 1 }
    if (${Mode} -eq "Check" -or ${Mode} -eq "All") { Chay-Check; $soMuc = $soMuc + 1 }
    $giay = [int]((Get-Date) - ${batDau}).TotalSeconds
    Bao-Dat "P1.2b: ${soMuc} mục kiểm tra đạt (${giay} giây)"
    exit 0
} catch {
    Bao-Loi $_.Exception.Message
    exit 1
}
