param(
  [ValidateSet("Local", "Vps")][string]$Target = "Local",
  [int]$Minutes = 10,
  [int]$Cycles = 3,
  [int]$Drops = 1
)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Write-Host "Bắt đầu soak ${Target} trong ${Minutes} phút (${Cycles} vòng, ${Drops} lần cắt WS)..." -ForegroundColor Cyan
if ("${Target}" -eq "Vps") {
  Write-Host "Chế độ Vps cần SSH (phiên sau, khi có thông tin VPS). Phiên này chỉ chạy Local." -ForegroundColor Yellow
  exit 2
}
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
& python "${repoRoot}\scripts\py\soak_runner.py" --minutes ${Minutes} --cycles ${Cycles} --drops ${Drops} --report "${repoRoot}\soak-report.json"
Write-Host "Xong. Mã thoát: ${LASTEXITCODE}" -ForegroundColor Green
