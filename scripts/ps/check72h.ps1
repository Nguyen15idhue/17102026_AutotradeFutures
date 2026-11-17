param(
  [ValidateSet("Local", "Vps")][string]$Target = "Local"
)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$keyFile = "C:\Users\ADMIN\.ssh\CS-Linux-20261103230212929.pem"
$raw = ""
if ("${Target}" -eq "Vps") {
  $raw = ssh -i "${keyFile}" -p 24700 -o ConnectTimeout=15 root@43.240.117.54 "docker exec bot-soak cat /app/data/soak-status.json" 2>$null
} else {
  $p1 = Join-Path "${repoRoot}" "soak-status.json"
  if (Test-Path "${p1}") { $raw = Get-Content "${p1}" -Raw }
}
if (-not "${raw}") { Write-Host "Chưa có file trạng thái soak." -ForegroundColor Yellow; exit 1 }
$st = "${raw}" | ConvertFrom-Json
$vi = @{ pending = "CHƯA BẮT ĐẦU"; running = "ĐANG THỰC HIỆN"; done = "HOÀN THÀNH"; error = "LỖI" }
Write-Host "Soak 72h: $($vi["$($st.state)"])" -ForegroundColor Cyan
Write-Host ("Vòng: {0}/{1} · Orphan: {2} · Reconcile diff: {3}" -f $st.cycles, $st.planned_cycles, $st.orphans, $st.reconcile_diffs)
Write-Host ("WS drop/reconnect: {0}/{1} · Trùng ID: {2} · Chaos: {3} · Restart: {4}" -f $st.ws_drops, $st.reconnect_ok, $st.dup_ok, $st.chaos_backoff_ok, $st.restart_ok)
if ($st.final) { Write-Host ("Cuối kỳ: openOrders={0} openAlgo={1} positions={2}" -f $st.final.openOrders, $st.final.openAlgo, $st.final.positions) }
if ($st.pass -ne $null) { Write-Host ("Kết quả: {0}" -f $(if ($st.pass) { "ĐẠT" } else { "CHƯA ĐẠT" })) }
$errs = @($st.errors)
if ($errs.Count -gt 0) { Write-Host ("Lỗi cuối: {0}" -f $errs[-1]) -ForegroundColor Red } else { Write-Host "Lỗi: không" }
