try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Write-Host "Báo cáo soak:" -ForegroundColor Cyan
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$report = Join-Path "${repoRoot}" "soak-report.json"
if (-not (Test-Path "${report}")) { Write-Host "Chưa có soak-report.json." -ForegroundColor Yellow; exit 1 }
Get-Content "${report}" | Write-Host
