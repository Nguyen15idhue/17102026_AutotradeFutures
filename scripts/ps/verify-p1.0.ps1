try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Write-Host "Bắt đầu xác minh P1.0 trên mock (13 mục §4.3)..." -ForegroundColor Cyan
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
& python "${repoRoot}\scripts\py\verify_env.py"
Write-Host "Xong. Mã thoát: ${LASTEXITCODE}" -ForegroundColor Green
