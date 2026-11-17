<#
.SYNOPSIS
    Kiểm tra môi trường trước khi chạy mock. Không thay đổi gì.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\ps\env-check.ps1
#>
[CmdletBinding()]
param()

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$ErrorActionPreference = "Continue"
$dat = 0
$tong = 7

function Kiem-Tra($so, $ten, [scriptblock] $lenh) {
    Write-Host ("[{0}/{1}] {2,-26} " -f $so, $tong, $ten) -NoNewline
    try {
        $kq = & $lenh 2>&1 | Select-Object -First 1
        if ($LASTEXITCODE -ne 0 -and $null -eq $kq) { throw "lỗi" }
        Write-Host "ĐẠT" -ForegroundColor Green -NoNewline
        Write-Host " ($kq)"
        return $true
    } catch {
        Write-Host "THIẾU" -ForegroundColor Red -NoNewline
        Write-Host " ($($_.Exception.Message))"
        return $false
    }
}

Write-Host ""
Write-Host "=== Kiểm tra môi trường ===" -ForegroundColor Cyan

if (Kiem-Tra 1 "Docker Engine" { (docker --version) -replace '^Docker version ','' }) { $dat++ }
if (Kiem-Tra 2 "Docker Compose" { (docker compose version) -replace '^Docker Compose version ','' }) { $dat++ }
if (Kiem-Tra 3 "Python" { (python --version) -replace '^Python ','' }) { $dat++ }
if (Kiem-Tra 4 "Git" { (git --version) -replace '^git version ','' }) { $dat++ }

Write-Host ("[{0}/{1}] {2,-26} " -f 5, $tong, "Docker daemon") -NoNewline
$sv = docker info --format "{{.ServerVersion}}" 2>$null
if ($LASTEXITCODE -eq 0 -and $sv) {
    Write-Host "ĐẠT" -ForegroundColor Green -NoNewline
    Write-Host " ($sv)"
    $dat++
} else {
    Write-Host "CHƯA CHẠY" -ForegroundColor Yellow -NoNewline
    Write-Host " (mở Docker Desktop rồi chạy lại)"
}

Write-Host ("[{0}/{1}] {2,-26} " -f 6, $tong, "Tệp .env") -NoNewline
if (Test-Path ".env") {
    Write-Host "ĐẠT" -ForegroundColor Green
    $dat++
} else {
    Write-Host "THIẾU" -ForegroundColor Yellow -NoNewline
    Write-Host " (chạy: Copy-Item .env.example .env)"
}

Write-Host ("[{0}/{1}] {2,-26} " -f 7, $tong, "Thư mục fixtures") -NoNewline
if (Test-Path "mock\fixtures\exchangeInfo.json") {
    Write-Host "ĐẠT" -ForegroundColor Green
    $dat++
} else {
    Write-Host "THIẾU" -ForegroundColor Red
}

Write-Host ""
if ($dat -eq $tong) {
    Write-Host "Kết quả: $dat/$tong đạt. Sẵn sàng." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Kết quả: $dat/$tong đạt. Cần xử lý $($tong - $dat) mục." -ForegroundColor Yellow
    exit 1
}
