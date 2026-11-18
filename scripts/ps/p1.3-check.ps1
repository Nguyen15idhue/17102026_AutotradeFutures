<#
.SYNOPSIS
    Kiểm tra P1.3 — Risk engine + Executor.

.DESCRIPTION
    Chế độ:
      Test        : ruff + pytest engine (không cần mạng, không cần mock)
      Integration : trên mock — mở lệnh, đo SL sau fill, close, đếm orphan
      KillSwitch  : trên mock — mở lệnh, gửi lệnh "stop", đo tới khi flat + halted
      All         : Test, Integration, KillSwitch

    Khi chạy Integration/KillSwitch, script TẠM DỪNG service engine để tránh hai
    tiến trình cùng ghi SQLite và reconcile HALT oan; xong sẽ bật lại.

.PARAMETER Mode
    Test | Integration | KillSwitch | All

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ps\p1.3-check.ps1 -Mode All
#>
[CmdletBinding()]
param(
    [ValidateSet("Test", "Integration", "KillSwitch", "All")]
    [string] $Mode = "Test"
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# PS 5.1: docker/pytest ghi ra stderr -> NativeCommandError. Dung Continue va
# kiem tra $LASTEXITCODE tuong minh thay vi de ErrorActionPreference nem.
$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$engineDir = Join-Path "${repoRoot}" "engine"
$py = Join-Path "${repoRoot}" ".venv\Scripts\python.exe"

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
    } finally {
        Pop-Location
    }
    Bao-Dat "test: ${dong}"
}

function Chay-Tren-Mock {
    param([string] $CheDo)
    Push-Location "${repoRoot}"
    try {
        $null = docker compose --profile app stop engine 2>&1
        try {
            $raw = docker compose --profile app run --rm --no-deps -T engine `
                python -m app.exec.integration "${CheDo}" 2>&1
            if ($LASTEXITCODE -ne 0) { throw "integration ${CheDo} thất bại" }
        } finally {
            $null = docker compose --profile app start engine 2>&1
        }
    } finally {
        Pop-Location
    }
    $dong = @($raw | Where-Object { "${_}" -like "{*}" }) | Select-Object -Last 1
    if (-not ${dong}) { throw "không đọc được kết quả integration" }
    return (${dong} | ConvertFrom-Json)
}

function Chay-Integration {
    $kq = Chay-Tren-Mock "open-close"
    if (-not ${kq}.ok) { throw "mở/đóng lệnh thất bại: $(${kq}.reason)" }
    if ([int]${kq}.sl_latency_ms -gt 300) { throw "SL sau fill $(${kq}.sl_latency_ms) ms > 300" }
    if ([int]${kq}.algos_after_open -lt 1) { throw "không thấy SL trên sàn sau fill" }
    if ([int]${kq}.orphan_after_close -ne 0) { throw "còn $(${kq}.orphan_after_close) algo sau close" }
    Bao-Dat "integration: SL $(${kq}.sl_latency_ms)ms sau fill, orphan sau close = 0"
}

function Chay-KillSwitch {
    $kq = Chay-Tren-Mock "killswitch"
    if (-not ${kq}.ok) { throw "kill switch không flat được" }
    if ([int]${kq}.kill_ms -ge 2000) { throw "kill switch $(${kq}.kill_ms) ms >= 2000" }
    if (-not ${kq}.halted) { throw "stop không set halted" }
    if ([int]${kq}.orphan_after_stop -ne 0) { throw "còn algo sau stop" }
    Bao-Dat "kill switch: $(${kq}.kill_ms)ms, halted, orphan = 0"
}

$batDau = Get-Date
$soMuc = 0
try {
    Write-Host "== P1.3: risk engine + executor ==" -ForegroundColor Cyan
    if (${Mode} -eq "Test" -or ${Mode} -eq "All") { Chay-Test; $soMuc = $soMuc + 1 }
    if (${Mode} -eq "Integration" -or ${Mode} -eq "All") { Chay-Integration; $soMuc = $soMuc + 1 }
    if (${Mode} -eq "KillSwitch" -or ${Mode} -eq "All") { Chay-KillSwitch; $soMuc = $soMuc + 1 }
    $giay = [int]((Get-Date) - ${batDau}).TotalSeconds
    Bao-Dat "P1.3: ${soMuc} mục kiểm tra đạt (${giay} giây)"
    exit 0
} catch {
    Bao-Loi $_.Exception.Message
    exit 1
}
