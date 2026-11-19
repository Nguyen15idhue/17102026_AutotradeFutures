# AGENTS.md

Hướng dẫn cho AI coding agent làm việc trong repo này.

---

## 1. Dự án là gì

Bot tự động giao dịch **Binance USDⓈ-M Futures** (USDT-M, perpetual), viết bằng Python, chạy Docker Compose trên VPS, có dashboard Node.js read-only và cảnh báo Telegram.

Mục tiêu **không phải** tối đa lợi nhuận mà là: **không chết** trong lúc học. Mọi quyết định kỹ thuật ưu tiên "không mất kiểm soát vị thế" hơn "tối ưu PnL".

**Trạng thái hiện tại (19/11/2026): P1.1 xong phần code (soak 72h còn chờ VPS), P1.2/P1.2b xong, P1.3 xong, P1.4 xong — NO-GO. P1.4b/c/d đã thử 6 tín hiệu, 7 chiến lược danh mục, funding carry, funding cực trị, đòn bẩy tới 5x: ứng viên duy nhất dương ở cả 2020-2022 và 2023-2026 là funding-long thr 30%·3 ngày (2–3x) — chưa live, cần paper 4–8 tuần. Chưa có watchdog/dashboard wiring.**

| Có gì | Chưa có gì |
|---|---|
| `mock/binance-demo-server/` — 48 endpoint, WS, SQLite, chaos | `watchdog/`, `dashboard/` (nối dữ liệu) |
| `engine/app/exchange/` — REST, WS, order state machine, reconcile, clock | Live trading (chưa mở) |
| `engine/app/data/` — downloader, bars, features, replay, spotcheck, persist | `trend_dir` nâng cấp cấu trúc HH/HL (mới là proxy) |
| `engine/app/regime/` — 5 nhãn + hysteresis + CRISIS tức thời | |
| `engine/app/risk/` + `exec/` — risk fail-fast, sizing, executor, recovery, kill switch | |
| `engine/app/strategies/` — MR + Trend Pullback (long/short), thuần, không gọi API | |
| `engine/app/backtest/` — event-driven 1m, fill model, funding, walk-forward, report | |
| `config/mvp.mock.yaml`, `config/mvp.live.yaml` | |
| `docker-compose.yml`, CI, script PS, `docs/` | |

---

## 2. Nguồn sự thật (đọc trước khi sửa bất cứ thứ gì)

| File | Nội dung | Sửa khi nào |
|---|---|---|
| `docs/mvp-binance-futures-bot.md` | **Spec gốc, có thẩm quyền cao nhất.** Kiến trúc, risk limits, 2 chiến lược, roadmap, incident playbook | Khi thay đổi thiết kế. Phải bump version + ghi lịch sử |
| `docs/phase0-binance-demo-server.md` | Mock `binance-demo-server`: endpoint, error code, cổng nghiệm thu | Khi implement mock |
| `docs/phase1_task.md` | Phase 1 (MVP): P1.0–P1.8, checklist test, kết quả | Khi làm MVP |
| `docs/phase2_task.md` | Phase 2: AI gate | Khi làm AI gate |
| `docs/phase3_task.md` | Phase 3: funding carry (Trend đã chuyển vào Phase 1 ở v2.0) | Khi mở rộng chiến lược |
| `.env.example` | Danh sách biến môi trường | Khi thêm secret/config mới |

**Thứ tự ưu tiên khi tài liệu mâu thuẫn:** `mvp-binance-futures-bot.md` thắng. Nếu phát hiện mâu thuẫn, **báo cho user** thay vì tự chọn một bên.

---

## 3. Luật cứng — KHÔNG được vi phạm

Đây là các bất biến an toàn. Vi phạm = hệ thống thất bại, dù test xanh hay PnL dương.

1. **Không vị thế nào tồn tại mà không có SL** — kể cả 300ms. SL phải được đặt ngay sau fill.
2. **Risk ≤ 0,5%/lệnh; đòn bẩy ≤ 3x; margin sử dụng ≤ 60% equity.**
3. **CRISIS = không mở lệnh mới.**
4. **Python là bộ não duy nhất.** Dashboard Node.js **không** giữ API key, **không** đặt/hủy lệnh, **không** tính size, **không** sửa position.
5. **`STOP`/`TAKE_PROFIT`/`TRAILING_STOP_MARKET` phải gửi qua `/fapi/v1/algoOrder`**, không qua `/fapi/v1/order` (sẽ nhận `-4120 STOP_ORDER_SWITCH_ALGO`).
6. **REST là nguồn sự thật**, WS chỉ là tín hiệu tăng tốc. Reconcile mỗi 5s; lệch position → HALT, không tự sửa mù.
7. **Không bao giờ** thêm code rút tiền, chuyển tiền nội bộ, hay universal transfer. API key không có quyền withdrawal.
8. **Không commit `.env`**, không `COPY` `.env` vào image, không log secret/token/signature.
9. **Không `docker compose down -v`** trên prod.
10. **Không đổi tham số chiến lược giữa kỳ test** (2 tuần mock / 8 tuần live là một thí nghiệm, không phải một buổi chỉnh tay).
11. **Không có nhánh `if mock:` trong engine.** Mock chỉ đổi `BINANCE_BASE_URL` / `BINANCE_WS_URL`.
12. **Không dời SL ra xa entry** (long), không trung bình giá xuống, không martingale.

---

## 4. Con số thiêng — dùng đúng, đừng "làm tròn cho đẹp"

| Tham số | Mock | Live |
|---|---|---|
| Risk/lệnh | 0,5% | 0,25% (4 tuần đầu) → 0,5% |
| Max positions | 4 | 4 |
| Vị thế/chiến lược | 2 | 2 |
| Portfolio risk | 2,0% | 2,0% |
| Max risk nhóm tương quan | 2,0% | 0,5% |
| Daily / Weekly / DD | 2% / 4% / 6% | 2% / 4% / 6% |
| Max lệnh/ngày | 10 | 5 |
| Leverage | 3x isolated | 3x isolated |
| Margin sử dụng | ≤ 60% equity | ≤ 60% equity |
| Blackout tin | ±45 phút | ±45 phút |
| Stale data | 3s | 3s |

> Đổi 18/11/2026 (duyệt bởi user, ghi ở spec §5.1/§11.1): live max positions 2 → **4**, portfolio 1,0% → **2,0%**, correlated 1,0% → **0,5%**. Hiệu lực risk hiện tại vẫn là 4 × 0,25% = 1,0%; portfolio 2,0% chỉ chạm khi nâng risk/lệnh lên 0,5% ở checkpoint tuần 4.

Chiến lược (không tự đổi nếu chưa có walk-forward + lý do ghi lại):

```
MR:      z ±2.0, stop 1.2×ATR ngoài biên, TP = mid, time stop 12 nến, post-only TTL 2 nến
Trend:   LIVE cả long + short (duyệt 18/11/2026); 1h signal / 4h context;
         entry market tại open nến 1h + guard spread < 2 bps;
         stop 1.5×ATR (short = buy-stop), trail 2×ATR sau 1.5×ATR, time stop 36 nến, KHÔNG TP;
         trend_dir phải giữ 3 nến và khớp EMA50/200 trên 1h, nếu không -> direction_conflict
Squeeze: ĐÃ HUỶ ở v2.0 — nhãn SQUEEZE vẫn tồn tại, không chiến lược nào chạy
Allocation: 0.5 / 0.5 của portfolio cap; tối đa 2 vị thế/chiến lược
Phí:     maker 0,02% · taker 0,05% · tính trên notional
```

**Cấm MR khi `bbw_pct < 15`.** Đây là quy tắc an toàn số 1 của hệ thống.

---

## 5. Cấu trúc repo (đích đến)

```
.
├── AGENTS.md
├── .env.example              # placeholder only
├── .dockerignore
├── docker-compose.yml        # engine + dashboard + binance-demo-server
├── config/
│   ├── mvp.mock.yaml
│   └── mvp.live.yaml         # tách riêng, không override lẫn nhau
├── engine/                   # Python 3.12
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── exchange/         # rest, ws, orders
│       ├── data/             # bars, features
│       ├── regime/
│       ├── risk/
│       ├── strategies/       # mean_reversion, trend_pullback (squeeze_breakout: không triển khai)
│       ├── exec/
│       ├── watchdog/
│       ├── ops/              # log, metric, alert (telegram), report
│       └── db/
├── dashboard/                # Node 22, 1 file server.js, không build step
│   ├── Dockerfile
│   ├── server.js
│   └── public/
├── mock/
│   ├── binance-demo-server/  # FastAPI, xem docs/phase0-binance-demo-server.md
│   ├── contracts/            # response mẫu freeze từ docs
│   └── fixtures/             # exchangeInfo, klines replay
└── docs/
```

Ranh giới module: xem bảng §7.2 của spec. `strategies` **không** gọi API trực tiếp; `exec` **không** bỏ qua risk; `ops` **không** chứa secret.

---

## 6. Lệnh thường dùng

```bash
# Dev local (chỉ test/backtest, không deploy)
python -m venv .venv && .venv\Scripts\Activate.ps1      # Windows
pip install -r engine/requirements.txt

# Compose
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f --tail=100 engine

# Test
pytest engine/tests -q
pytest mock/tests -q
ruff check engine && ruff format --check engine

# Mock offline (không cần internet)
MARKET_MODE=replay docker compose up -d binance-demo-server

# Dashboard: chỉ qua SSH tunnel
ssh -L 8080:localhost:8080 bot@<vps-ip>
```

Windows: dùng **WSL2**. Không bind-mount từ `F:\` cho SQLite (chậm + khoá file).

**Compose:** một `docker-compose.yml`, service `binance-demo-server` luôn chạy; `engine`/`dashboard` đặt sau `profiles: ["app"]`.
`docker compose up -d` = chỉ mock · `docker compose --profile app up -d` = cả hệ.
Trong container, engine gọi mock bằng **hostname `binance-demo-server:8080`** — `127.0.0.1:8081` chỉ là cổng debug map ra host, **không** dùng trong config container.

### 6.1 Script PowerShell — luật bắt buộc

Máy dev **không có `pwsh` 7**, chỉ có **Windows PowerShell 5.1**. Mọi script phải chạy được trên 5.1:

1. **Không gọi `pwsh`.** Dùng `powershell -NoProfile -ExecutionPolicy Bypass -File ...`. Nếu script tự nâng quyền, chọn exe theo mẫu:
   ```powershell
   $exe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell.exe" }
   ```
2. **Lưu file UTF-8 CÓ BOM.** 5.1 đọc UTF-8 không BOM sẽ lỗi dấu tiếng Việt. Sau khi tạo/sửa bằng công cụ khác, chuẩn hoá lại:
   ```powershell
   $c = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
   [System.IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($true)))
   ```
3. **Đặt encoding ở đầu script** để `Write-Host` hiện đúng dấu:
   ```powershell
   try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
   ```
4. **`"$var:"` là lỗi cú pháp** (`:` bị hiểu là scope). Luôn dùng **`"${var}:"`** khi biến đứng trước dấu hai chấm.
5. **Không dùng cú pháp chỉ có ở PS 7**: `??`, `?.`, `-Parallel`, ternary `? :`, `Get-Content -AsByteStream`.
6. **Kiểm tra cú pháp trước khi commit** (rẻ hơn sửa sau):
   ```powershell
   $e=$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $p),[ref]$null,[ref]$e); $e.Count
   ```
7. **Không nhúng tiếng Việt vào chuỗi heredoc qua `-replace` của shell** — dễ hỏng dấu; dùng công cụ `edit`/`write` thay vì sed/replace từ PowerShell.
8. **Mọi thông báo output bằng tiếng Việt có dấu**, đúng chính tả, không viết tắt; giữ tên lệnh/kỹ thuật bằng tiếng Anh.

---

## 7. Quy ước code

- **Python 3.12**, `asyncio`, type hints đầy đủ, `ruff` làm linter + formatter.
- **Node 22**, `server.js` một file, không React/TypeScript/ORM/build step. Chart nếu cần: `<canvas>`.
- Tên biến/hàm/field DB: **tiếng Anh**. Comment giải thích "vì sao": **tiếng Việt** (khớp tài liệu).
- Thời gian: **UTC, mili-giây**, `TZ=UTC` trong mọi container.
- Số tiền/tỷ lệ: dùng `Decimal` hoặc float có quy ước rõ; không so sánh `==` trên float giá.
- Mọi thao tác tiền tệ phải **idempotent** (`newClientOrderId` / `clientAlgoId`).
- Không log: API key, secret, signature, listenKey, token Telegram.
- Log ra **stdout** (Docker xoay vòng), không ghi file log trong container.

### Bảng DB (tối thiểu)

`bars`, `features`, `regime`, `signals`, `orders`, `fills`, `positions`, `equity`, `runtime_state`, `commands`, `shadow_trades`, `events`, `incidents` — xem §7.3 spec.

SQLite **WAL**, `busy_timeout=5000`. Python là **writer duy nhất**; Node mở `readonly: true`.

---

## 8. Yêu cầu test trước khi báo "xong"

Không có code nào được coi là hoàn thành nếu thiếu:

- [ ] Unit test cho logic thuần (features, sizing, risk limits, consensus).
- [ ] Test cho **mọi** error code đã khai trong tài liệu liên quan.
- [ ] Nếu chạm execution: test trên `binance-demo-server` — fill → SL trong 300ms → reconcile → restart.
- [ ] Nếu chạm risk: test injection cố tình vượt limit → phải bị chặn.
- [ ] `ruff check` + `pytest` xanh.
- [ ] Không có secret trong diff, không có `print` debug còn sót.

Cổng chất lượng theo phase: xem bảng trạng thái cuối mỗi file `phaseX_task.md`. **Không đánh dấu ✅ khi chưa có bằng chứng** (log, report, hash, ảnh).

---

## 9. Đặc thù của mock server

Khi làm `mock/binance-demo-server/`:

- **Tier A phải tuyệt đối**: ký HMAC (đúng thứ tự param, `signature` không nằm trong chuỗi ký), `timestamp`/`recvWindow`, tên field JSON, error code, tick/step/minNotional, vòng đời Algo order, `-4120`, `ALGO_UPDATE`, listenKey, header rate-limit.
- **Tier C bỏ hẳn**: depth sâu, ADL, STP, batch orders, WebSocket API, Portfolio Margin.
- Dùng **golden signature vector** trong docs làm test auth — không tự nghĩ ra test case.
- Mặc định `FILL_MODEL=pessimistic`, `AUTH_STRICT=true`, `SLIPPAGE_BPS=5`.
- `AUTH_STRICT` chỉ được tắt khi debug tay, không bao giờ trong CI.
- Determinism: cùng `SEED` + cùng scenario → state hash giống. Test này phải xanh trước khi merge.
- Kết quả chạy `SPEED=60` (nén thời gian) **chỉ để tìm bug**, không dùng để kết luận edge.

---

## 10. Khi sửa tài liệu

- Bump version ở dòng đầu file (`- Phiên bản: X.Y (...)`) + thêm 1 dòng vào "Lịch sử".
- Sửa 1 con số ở spec → **grep toàn repo** xem số đó còn xuất hiện ở đâu (config, bảng, checklist, phase task). Mâu thuẫn chéo là lỗi phổ biến nhất của repo này.
- Không xoá thông tin sai: ghi đè + ghi lý do vào lịch sử.
- Không thêm "chiến lược vàng", "bộ tham số tối ưu", hay con số lợi nhuận dự báo. Mọi con số hiệu năng là ví dụ toán học, không phải cam kết.

---

## 11. Khi nào phải hỏi user thay vì tự quyết

- Thay đổi bất kỳ con số trong §4 (risk limits, chiến lược).
- Thay đổi kiến trúc (thêm service, thêm DB, đổi writer).
- Bật bất kỳ tính năng nào liên quan tiền: live trading, tăng size, bật `allow_short`, bật Trend live.
- Phát hiện mâu thuẫn giữa 2 tài liệu.
- Cần thêm secret mới hoặc thay đổi quyền của API key.
- Muốn bỏ qua một cổng nghiệm thu (dù chỉ "tạm thời").

---

## 12. Bối cảnh môi trường

- OS dev: Windows 11, chạy Docker qua WSL2. Working dir: `F:\3.Laptrinh\1. Project\4. Crypto\4.AutotradeFutures\17102026_AutotradeFutures`
- VPS: Linux, tận dụng máy sẵn có (không bắt buộc Tokyo/Singapore — khung 15m chịu được latency 100–300ms), **NTP sync bắt buộc**.
- Chi phí: VPS 0 USD, Telegram 0 USD, AI gate (phase 2) 2–7 USD/tháng.
- AI gate (phase 2) dùng **GLM 5.3 Flash** (triage) + **DeepSeek V4 Flash 0731** (reasoner) qua OpenRouter. AI chỉ được **giảm size hoặc veto**, không bao giờ là trigger.
- **Môi trường demo = `binance-demo-server` tự dựng.** Binance Demo Trading (`demo.binance.com`) **không dùng** (tạo API key hỏng, testnet đã gộp về đó). Mock không cần API key Binance; secret mặc định `mock-secret`. Live chỉ sau live smoke test ≤ 0.05 USD.
- Chế độ dữ liệu thị trường: **dev/paper = `proxy`** (cần internet, giá thật) · **CI = `replay`** (offline, tất định) · **test crash = `synthetic`**. Không dùng `replay` để đánh giá hành vi dài hạn (thị trường lặp y nguyên), không dùng `synthetic` để đánh giá chiến lược.

---

## 13. Knowledge graph (graphify)

Repo này dùng skill **graphify** để tra cứu cấu trúc mã nguồn thay vì đọc từng file.

### 13.1 Phạm vi

Graphify chạy trên **mã nguồn**, không chạy trên toàn repo:

```
mock/binance-demo-server/      ← chạy graphify ở đây
```

Lý do: thư mục này là **code-only** → chỉ AST, **không cần LLM, không tốn token, không cần API key**. Thư mục `docs/` là văn xuôi tiếng Việt, grep trực tiếp rẻ hơn nhiều.

### 13.2 Lệnh

```text
/graphify mock/binance-demo-server          # build lần đầu (AST, miễn phí)
/graphify mock/binance-demo-server --update # sau khi thêm/xoá file
/graphify query "SL được đặt ở đâu?" --budget 1500
/graphify path "Engine.place" "apply_fill"
/graphify explain "AlgoEngine"
```

Khi `graphify-out/graph.json` đã tồn tại và câu hỏi là về codebase → **query luôn**, không build lại.

### 13.3 Luật

1. `graphify-out/` là **artifact sinh tự động** — đã nằm trong `.gitignore`. **Không commit, không sửa tay.**
2. Chạy `--update` sau khi **thêm/xoá file** hoặc đổi cấu trúc module (không cần cho mỗi lần sửa logic).
3. **Không bao giờ** trỏ graphify vào `.env`, `mock/fixtures/raw/`, `data/`, `backups/`.
4. Graph là **bản đồ, không phải nguồn sự thật**: khi graph và code khác nhau, **code thắng** — báo lại nếu lệch.
5. Nếu `graphify-out/graph.json` bị xoá, cứ build lại; không coi đó là mất dữ liệu.
6. Trả lời câu hỏi về code phải **trích `source_location`** (file:line) lấy từ graph hoặc từ code, không nói chung chung.

### 13.4 Khi nào dùng gì

| Câu hỏi | Công cụ |
|---|---|
| "Hàm X gọi gì", "SL được đặt ở đâu", "luồng dữ liệu đi thế nào" | `graphify query` |
| "Đường đi từ A tới B", "cái này ảnh hưởng module nào" | `graphify path` |
| "Module này làm gì" (tổng quan) | `graphify explain` |
| "Quy tắc risk là gì", "tại sao chọn 0.5%", "phase nào làm gì" | grep/đọc `docs/*.md` |
| "Cấu hình hiện tại" | `config/`, `.env.example`, `docker-compose.yml` |

---

**Nhắc lại điều quan trọng nhất:** nếu một thay đổi làm tăng PnL kỳ vọng nhưng vi phạm một dòng trong §3, thì thay đổi đó sai. Từ chối nó và nói rõ lý do.
