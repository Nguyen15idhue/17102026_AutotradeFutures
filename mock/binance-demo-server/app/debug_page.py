"""Trang debug read-only — FE cua Phase 0.

Chi hien thi trang thai. KHONG co form ghi, KHONG goi endpoint lam thay doi state.
Tu dong refresh moi 2 giay bang cach goi /_debug/json.
"""

HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mock Binance — Debug</title>
<style>
  :root{--bg:#0f1115;--panel:#171a21;--line:#252a34;--fg:#dfe4ec;--dim:#8b94a5;--ok:#3fb950;--warn:#d29922;--err:#f85149}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}
  header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  h1{font-size:14px;margin:0;font-weight:600;letter-spacing:.3px}
  .pill{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:2px 10px;color:var(--dim)}
  main{padding:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
  section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
  h2{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--dim);margin:0 0 8px}
  table{width:100%;border-collapse:collapse}
  td{padding:3px 0;vertical-align:top}
  td:first-child{color:var(--dim);width:44%}
  .ok{color:var(--ok)} .warn{color:var(--warn)} .err{color:var(--err)}
  .empty{color:var(--dim);font-style:italic}
</style>
</head>
<body>
<header>
  <h1>MOCK BINANCE · USDⓈ-M FUTURES</h1>
  <span class="pill" id="mode">mode…</span>
  <span class="pill" id="speed">speed…</span>
  <span class="pill" id="uptime">uptime…</span>
  <span class="pill" id="clock">server…</span>
</header>
<main>
  <section><h2>Cấu hình</h2><table id="cfg"></table></section>
  <section><h2>Tài khoản</h2><table id="acct"></table></section>
  <section><h2>Vị thế</h2><table id="pos"></table></section>
  <section><h2>Lệnh đang mở</h2><table id="orders"></table></section>
  <section><h2>Lệnh điều kiện</h2><table id="algo"></table></section>
  <section><h2>Sự kiện gần nhất</h2><table id="events"></table></section>
</main>
<script>
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function rows(id, obj, cls) {
  const el = document.getElementById(id);
  const ks = Object.keys(obj || {});
  if (!ks.length) { el.innerHTML = '<tr><td class="empty">trống</td></tr>'; return; }
  el.innerHTML = ks.map(k => `<tr><td>${esc(k)}</td><td class="${cls||''}">${esc(obj[k])}</td></tr>`).join('');
}
function list(id, arr, fmt) {
  const el = document.getElementById(id);
  if (!arr || !arr.length) { el.innerHTML = '<tr><td class="empty">trống</td></tr>'; return; }
  el.innerHTML = arr.map(fmt).join('');
}
async function tick() {
  try {
    const r = await fetch('/_debug/json', {cache:'no-store'});
    const d = await r.json();
    document.getElementById('mode').textContent = 'mode: ' + d.market_mode;
    document.getElementById('speed').textContent = 'speed: ' + d.speed + 'x';
    document.getElementById('uptime').textContent = 'uptime: ' + d.uptime_s + 's';
    document.getElementById('clock').textContent = 'server: ' + new Date(d.server_time).toISOString().slice(11,19) + 'Z';
    rows('cfg', d.config);
    rows('acct', d.account);
    list('pos', d.positions, p => `<tr><td>${esc(p.symbol)}</td><td>${esc(p.amt)} @ ${esc(p.entry)} · uPnL ${esc(p.upnl)}</td></tr>`);
    list('orders', d.orders, o => `<tr><td>${esc(o.symbol)} ${esc(o.side)} ${esc(o.type)}</td><td>${esc(o.qty)} @ ${esc(o.price)} · ${esc(o.status)}</td></tr>`);
    list('algo', d.algo_orders, a => `<tr><td>${esc(a.symbol)} ${esc(a.type)}</td><td>trigger ${esc(a.trigger)} · ${esc(a.status)}</td></tr>`);
    list('events', d.events, e => `<tr><td>${esc(e.ts)}</td><td>${esc(e.text)}</td></tr>`);
  } catch (e) {
    document.getElementById('mode').textContent = 'MẤT KẾT NỐI';
    document.getElementById('mode').className = 'pill err';
  }
}
tick(); setInterval(tick, 2000);
</script>
</body>
</html>
"""
