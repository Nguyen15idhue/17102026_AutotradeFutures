<#
.SYNOPSIS
    Chạy checklist tự động của từng bước Phase 0.

.DESCRIPTION
    M0.1..M0.11 chạy bộ test tương ứng. M0.2 kiểm tra thêm container qua HTTP.

.PARAMETER Step
    M0.1 | M0.2 | ... | M0.11 | all

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\ps\step-verify.ps1 -Step M0.7
#>
[CmdletBinding()]
param(
    [string] $Step = "all",
    [string] $BaseUrl = "http://127.0.0.1:8081"
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$ErrorActionPreference = "Continue"
$py = ".venv\Scripts\python.exe"
$mockDir = "mock\binance-demo-server"

$map = @{
    "M0.1"  = @{ Ten = "Hợp đồng và fixtures";   Test = "tests/test_contracts.py" }
    "M0.2"  = @{ Ten = "Khung container";         Test = "tests/test_auth.py";     Http = $true }
    "M0.3"  = @{ Ten = "Xác thực và giới hạn";    Test = "tests/test_auth.py" }
    "M0.4"  = @{ Ten = "Dữ liệu thị trường";      Test = "tests/test_market.py" }
    "M0.5"  = @{ Ten = "Trạng thái tài khoản";    Test = "tests/test_account.py" }
    "M0.6"  = @{ Ten = "Bộ máy đặt lệnh";         Test = "tests/test_orders.py" }
    "M0.7"  = @{ Ten = "Bộ máy SL/TP";            Test = "tests/test_algo.py" }
    "M0.8"  = @{ Ten = "Luồng dữ liệu người dùng";Test = "tests/test_streams.py" }
    "M0.9"  = @{ Ten = "Bơm lỗi";                 Test = "tests/test_chaos.py" }
    "M0.10" = @{ Ten = "Lưu trữ và khởi động lại";Test = "tests/test_persist.py" }
    "M0.11" = @{ Ten = "Bộ test tổng";            Test = "tests";                  E2E = $true }
}

function Kiem-Tra-Http {
    $loi = 0
    foreach ($path in @("/fapi/v1/ping", "/_debug", "/_debug/json", "/healthz")) {
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl$path" -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) {
                Write-Host "  [ĐẠT ] $path" -ForegroundColor Green
            } else {
                Write-Host "  [HỎNG] $path (HTTP $($r.StatusCode))" -ForegroundColor Red
                $loi++
            }
        } catch {
            Write-Host "  [HỎNG] $path (không kết nối được)" -ForegroundColor Red
            $loi++
        }
    }
    return $loi
}

function Chay-Buoc($ma) {
    $m = $map[$ma]
    if (-not $m) { Write-Host "Không có bước $ma" -ForegroundColor Red; return 1 }

    Write-Host ""
    Write-Host "=== Kiểm tra $ma — $($m.Ten) ===" -ForegroundColor Cyan
    $loi = 0

    if ($m.Http) {
        Write-Host "-- Kiểm tra HTTP (container) --"
        $loi += Kiem-Tra-Http
    }

    Write-Host "-- Bộ test --"
    Push-Location $mockDir
    try {
        $out = & "..\..\$py" -m pytest $m.Test -q 2>&1
        $code = $LASTEXITCODE
        $out | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }
        if ($code -eq 0) {
            Write-Host "  [ĐẠT ] pytest $($m.Test)" -ForegroundColor Green
        } else {
            Write-Host "  [HỎNG] pytest $($m.Test)" -ForegroundColor Red
            $loi++
        }
    } finally {
        Pop-Location
    }

    if ($m.E2E) {
        Write-Host "-- Invariant E2E --"
        if (Select-String -Path "$mockDir\tests\test_e2e.py" -Pattern "assert_invariants" -Quiet) {
            Write-Host "  [ĐẠT ] test_e2e có kiểm tra bất biến" -ForegroundColor Green
        } else {
            Write-Host "  [HỎNG] thiếu kiểm tra bất biến" -ForegroundColor Red
            $loi++
        }
    }

    if ($loi -eq 0) {
        Write-Host "Kết quả ${ma}: ĐẠT" -ForegroundColor Green
        return 0
    }
    Write-Host "Kết quả ${ma}: $loi mục hỏng" -ForegroundColor Red
    return $loi
}

if ($Step -eq "all") {
    $tongLoi = 0
    foreach ($ma in @("M0.1","M0.2","M0.3","M0.4","M0.5","M0.6","M0.7","M0.8","M0.9","M0.10","M0.11")) {
        $tongLoi += (Chay-Buoc $ma)
    }
    Write-Host ""
    if ($tongLoi -eq 0) {
        Write-Host "TỔNG KẾT: tất cả bước ĐẠT" -ForegroundColor Green
        exit 0
    }
    Write-Host "TỔNG KẾT: $tongLoi mục hỏng" -ForegroundColor Red
    exit 1
}

$kq = Chay-Buoc $Step
exit $(if ($kq -eq 0) { 0 } else { 1 })
