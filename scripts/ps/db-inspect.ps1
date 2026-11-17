<#
.SYNOPSIS
    Xem trạng thái mock trong SQLite (chỉ đọc).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\ps\db-inspect.ps1
    powershell -ExecutionPolicy Bypass -File scripts\ps\db-inspect.ps1 -Database "mock\data\mock.db"
#>
[CmdletBinding()]
param(
    [string] $Database = "mock\data\mock.db"
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$ErrorActionPreference = "Stop"
$py = ".venv\Scripts\python.exe"

if (-not (Test-Path $Database)) {
    Write-Host "Không thấy CSDL: $Database" -ForegroundColor Yellow
    Write-Host "Gợi ý: docker compose cp binance-demo-server:/app/data/mock.db .\$Database"
    exit 1
}

$script = @'
import sqlite3, sys
db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
acc = con.execute("SELECT * FROM account WHERE id=1").fetchone()
print(f"Số dư ví      : {acc['wallet_balance']} USDT")
print(f"Vốn ban đầu   : {acc['initial_balance']} USDT")
print()
print("Vị thế:")
rows = [r for r in con.execute("SELECT * FROM positions ORDER BY symbol") if float(r['position_amt']) != 0]
for r in rows:
    print(f"  {r['symbol']:<9} {r['position_amt']:>10}  giá vào {r['entry_price']:>12}  "
          f"leverage {r['leverage']}  margin {r['isolated_wallet']}")
if not rows:
    print("  (không có)")
print()
print("Lệnh đang mở:")
rows = list(con.execute("SELECT * FROM orders WHERE status='NEW' ORDER BY order_id"))
for r in rows:
    print(f"  #{r['order_id']} {r['symbol']:<9} {r['side']:<4} {r['type']:<6} "
          f"{r['orig_qty']} @ {r['price']}")
if not rows:
    print("  (không có)")
print()
print("Lệnh điều kiện đang mở:")
rows = list(con.execute("SELECT * FROM algo_orders WHERE status='NEW' ORDER BY algo_id"))
for r in rows:
    print(f"  #{r['algo_id']} {r['symbol']:<9} {r['side']:<4} {r['type']:<14} "
          f"kích hoạt {r['trigger_price']}")
if not rows:
    print("  (không có)")
print()
print("Sự kiện gần nhất:")
for r in con.execute("SELECT * FROM events_log ORDER BY id DESC LIMIT 5"):
    print(f"  {r['ts_ms']}  {r['kind']:<20} {r['text']}")
'@

$tmp = Join-Path $env:TEMP "db_inspect.py"
Set-Content -Path $tmp -Value $script -Encoding utf8
& $py $tmp $Database
Remove-Item $tmp -ErrorAction SilentlyContinue
