<#
.SYNOPSIS
    Đồng bộ đồng hồ hệ thống và kiểm tra độ lệch với Binance.

.DESCRIPTION
    Bật Windows Time (w32time), cấu hình NTP server, ép đồng bộ, rồi đo lại
    độ lệch so với serverTime của Binance. Cần quyền Administrator.
    Tương thích Windows PowerShell 5.1 (không cần pwsh 7).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\ps\sync-clock.ps1
#>
[CmdletBinding()]
param(
    [string[]] $Peers = @("time.windows.com,0x8", "pool.ntp.org,0x8"),
    [switch] $SkipVerify,
    [switch] $NoElevate
)

$ErrorActionPreference = "Stop"

# Hiển thị tiếng Việt đúng trên console Windows (code page mặc định không phải UTF-8)
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Buoc($so, $tong, $ten, $trangThai) {
    Write-Host ("[{0}/{1}] {2,-30} {3}" -f $so, $tong, $ten, $trangThai)
}

function Format-Lech($ms) {
    if ($ms -ge 0) { return "+$ms ms" }
    return "$ms ms"
}

if (-not (Test-Admin)) {
    if ($NoElevate) {
        Write-Host "Đang chạy quyền thường và có -NoElevate: chỉ kiểm tra, không thay đổi." -ForegroundColor Yellow
    } else {
        Write-Host "Cần quyền Administrator. Đang mở cửa sổ nâng quyền..." -ForegroundColor Yellow
        $exe = $null
        if (Get-Command pwsh -ErrorAction SilentlyContinue) { $exe = "pwsh" } else { $exe = "powershell.exe" }
        $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
        if ($SkipVerify) { $args += "-SkipVerify" }
        Start-Process -FilePath $exe -ArgumentList $args -Verb RunAs
        Write-Host "Đã mở cửa sổ mới. Bấm Yes ở hộp thoại UAC rồi xem kết quả ở cửa sổ đó." -ForegroundColor Cyan
        return
    }
}

$tong = 5

Write-Host ""
Write-Host "=== Đồng bộ đồng hồ hệ thống ===" -ForegroundColor Cyan

Write-Buoc 1 $tong "Đặt w32time tự khởi động" "đang xử lý..."
Set-Service -Name w32time -StartupType Automatic
Write-Buoc 1 $tong "Đặt w32time tự khởi động" "OK (Automatic)"

Write-Buoc 2 $tong "Khởi động dịch vụ" "đang xử lý..."
if ((Get-Service w32time).Status -ne "Running") { Start-Service w32time }
Write-Buoc 2 $tong "Khởi động dịch vụ" "OK (Running)"

Write-Buoc 3 $tong "Cấu hình NTP server" "đang xử lý..."
$dsan = ($Peers -join " ")
& w32tm /config /manualpeerlist:"$dsan" /syncfromflags:manual /reliable:no /update | Out-Null
Write-Buoc 3 $tong "Cấu hình NTP server" "OK ($dsan)"

Write-Buoc 4 $tong "Ép đồng bộ ngay" "đang xử lý..."
& w32tm /resync /force 2>&1 | Out-Null
Start-Sleep -Seconds 1
Write-Buoc 4 $tong "Ép đồng bộ ngay" "OK"

Write-Buoc 5 $tong "Kiểm tra trạng thái" "OK"

Write-Host ""
Write-Host "--- Trạng thái dịch vụ ---" -ForegroundColor Cyan
& w32tm /query /status 2>&1 | Select-Object -First 6 | ForEach-Object { Write-Host "    $_" }
$nguon = (& w32tm /query /source 2>&1) -join " "
Write-Host "    Nguồn: $nguon"

if (-not $SkipVerify) {
    Write-Host ""
    Write-Host "--- Đo lại độ lệch so với Binance ---" -ForegroundColor Cyan
    $mau = @()
    foreach ($i in 1..5) {
        try {
            $t0 = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $r = Invoke-RestMethod -Uri "https://fapi.binance.com/fapi/v1/time" -TimeoutSec 10
            $t1 = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $lech = [int64]$r.serverTime - [int64](($t0 + $t1) / 2)
            $mau += $lech
            Write-Host ("    Mẫu {0}: lệch {1}   (khứ hồi {2} ms)" -f $i, (Format-Lech $lech), ($t1 - $t0))
            Start-Sleep -Milliseconds 400
        } catch {
            Write-Host "    Mẫu $i : không gọi được Binance" -ForegroundColor Yellow
        }
    }
    if ($mau.Count -gt 0) {
        $tb = [int][math]::Round(($mau | Measure-Object -Average).Average)
        Write-Host ""
        Write-Host ("    Trung bình: " + (Format-Lech $tb))
        if ([math]::Abs($tb) -lt 1000) {
            Write-Host "    ĐẠT: dưới ngưỡng 1000 ms của Binance" -ForegroundColor Green
        } else {
            Write-Host "    CHƯA ĐẠT: vẫn trên 1000 ms." -ForegroundColor Red
            Write-Host "    Kiểm tra: tường lửa có chặn UDP 123; thử peer khác bằng -Peers." -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "Hoàn tất." -ForegroundColor Green
