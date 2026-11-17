<#
.SYNOPSIS
    Kiểm tra ruff + pytest, rồi commit và push nếu đạt.

.PARAMETER Step
    Mã bước, ví dụ M0.7

.PARAMETER Message
    Nội dung commit (tiếng Việt, ngắn)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\ps\release.ps1 -Step M0.7 -Message "bo may SL/TP"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Step,
    [Parameter(Mandatory = $true)][string] $Message,
    [switch] $NoPush
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$ErrorActionPreference = "Stop"
$py = ".venv\Scripts\python.exe"
$mockDir = "mock\binance-demo-server"
$tong = 4

Write-Host ""
Write-Host "=== Phát hành $Step ===" -ForegroundColor Cyan

Write-Host ("[{0}/{1}] {2,-22} " -f 1, $tong, "ruff check") -NoNewline
Push-Location $mockDir
try {
    & "..\..\$py" -m ruff check app tests --output-format concise | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ruff báo lỗi" }
    Write-Host "ĐẠT" -ForegroundColor Green

    Write-Host ("[{0}/{1}] {2,-22} " -f 2, $tong, "pytest") -NoNewline
    $out = & "..\..\$py" -m pytest -q 2>&1
    if ($LASTEXITCODE -ne 0) {
        $out | Select-Object -Last 5 | ForEach-Object { Write-Host ""; Write-Host "  $_" }
        throw "pytest thất bại"
    }
    $soTest = ($out | Select-String -Pattern "(\d+) passed" | Select-Object -First 1).Matches.Groups[1].Value
    Write-Host "ĐẠT" -ForegroundColor Green -NoNewline
    Write-Host " ($soTest test)"
} finally {
    Pop-Location
}

Write-Host ("[{0}/{1}] {2,-22} " -f 3, $tong, "commit") -NoNewline
git add -A | Out-Null
git commit -q -m "feat(mock): $Step $Message" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git commit thất bại" }
$sha = (git rev-parse --short HEAD).Trim()
Write-Host "ĐẠT" -ForegroundColor Green -NoNewline
Write-Host " ($sha)"

Write-Host ("[{0}/{1}] {2,-22} " -f 4, $tong, "push") -NoNewline
if ($NoPush) {
    Write-Host "BỎ QUA" -ForegroundColor Yellow
} else {
    git push -q origin HEAD 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "LỖI (commit đã tạo, push thất bại)" -ForegroundColor Red
        Write-Host "Hoàn tất $Step với cảnh báo push." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "ĐẠT" -ForegroundColor Green
}

Write-Host "Hoàn tất $Step." -ForegroundColor Green
exit 0
