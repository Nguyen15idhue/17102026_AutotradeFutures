# binance-demo-server

Mock **Binance USDⓈ-M Futures** (REST + WebSocket) để phát triển và test engine **không cần API key, không cần tiền thật**.

Đặc tả đầy đủ: [`docs/phase0-binance-demo-server.md`](../../docs/phase0-binance-demo-server.md)

## Nguyên tắc

| Tier | Phạm vi |
|---|---|
| **A — chính xác tuyệt đối** | Ký HMAC, `timestamp`/`recvWindow`, mã lỗi, tên field, tick/step/minNotional, phí, vòng đời Algo order, `-4120`, listenKey, header rate-limit |
| **B — xấp xỉ** | Matching top-of-book, funding 8h, giá thanh lý bậc 1 |
| **C — không làm** | Depth sâu, ADL, STP, batch orders, WebSocket API, Portfolio Margin |

## Chạy

```powershell
# Toàn bộ hệ thống (chỉ có mock ở Phase 0)
docker compose up -d --build binance-demo-server

# Kiểm tra
curl http://127.0.0.1:8081/fapi/v1/ping
start http://127.0.0.1:8081/_debug      # trang debug read-only
```

Engine trỏ vào mock bằng env — **không** sửa code:

```
BINANCE_BASE_URL=http://binance-demo-server:8080
BINANCE_WS_URL=ws://binance-demo-server:8080/ws
```

## Cấu hình (env)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MARKET_MODE` | `proxy` | `proxy` (giá thật) · `replay` (fixture, offline, tất định) · `synthetic` (random walk có seed) |
| `UPSTREAM` | `https://fapi.binance.com` | Nguồn khi mode `proxy` |
| `FIXTURES_DIR` | `/app/fixtures` | Nơi chứa `exchangeInfo.json`, `klines.json` |
| `SEED` | `42` | Seed cho synthetic + chaos (tất định) |
| `SPEED` | `1` | Nén thời gian (60 = nhanh 60×) |
| `INITIAL_BALANCE` | `5000` | Số dư USDT ban đầu |
| `FEE_MAKER_BPS` / `FEE_TAKER_BPS` | `2` / `5` | Phí (bps) = 0,02% / 0,05% |
| `FILL_MODEL` | `pessimistic` | `pessimistic` = limit chỉ khớp khi giá xuyên qua |
| `SLIPPAGE_BPS` | `5` | Trượt giá cho MARKET / LIMIT khớp ngay |
| `AUTH_STRICT` | `true` | `false` chỉ để debug tay, **không bao giờ trong CI** |
| `MOCK_API_KEY` / `MOCK_API_SECRET` | rỗng / `mock-secret` | Đặt `MOCK_API_KEY` để buộc key đúng |
| `FAIL_RATE` `LATENCY_MS` `CHAOS_*` | `0` | Bơm lỗi xem mục Chaos |

## Endpoint đã có

**Market (NONE)**: `/fapi/v1/ping` `/time` `/exchangeInfo` `/klines` `/ticker/price` `/ticker/bookTicker` `/premiumIndex` `/fundingRate` `/openInterest`

**Account (SIGNED)**: `/fapi/v2/balance` `/fapi/v2/account` `/fapi/v2/positionRisk` `/fapi/v1/commissionRate` `/fapi/v1/leverageBracket` `/fapi/v1/income` `/fapi/v1/userTrades` `POST /leverage` `POST /marginType`

**Trade (SIGNED)**: `POST /fapi/v1/order` `POST /order/test` `GET /order` `DELETE /order` `DELETE /allOpenOrders` `GET /openOrders` `GET /allOrders`

**Algo (SIGNED)**: `POST /fapi/v1/algoOrder` `GET /algoOrder` `DELETE /algoOrder` `DELETE /algoOpenOrders` `GET /openAlgoOrders` `GET /historicalAlgoOrders`

**User stream**: `POST/PUT/DELETE /fapi/v1/listenKey` · WS `/ws/<listenKey>` và `/private/ws/<listenKey>`

**Admin (chỉ dùng cho test)**: `POST /_admin/chaos` · `POST /_admin/reset` · `GET /_admin/state` · `POST /_admin/snapshot` · `POST /_admin/restore`

## Ký request

```python
qs = urllib.parse.urlencode(params_without_signature)
signature = hmac.new(secret, qs.encode(), hashlib.sha256).hexdigest()
url = base + path + "?" + qs + "&signature=" + signature
```

Secret mặc định của mock là `mock-secret` — **không phải** secret Binance thật.
Vector vàng để test: `mock/contracts/contracts.json` → `auth`.

## Chaos

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8081/_admin/chaos `
  -ContentType application/json `
  -Body '{"fail_rate":0.3,"unknown_503":true}'

Invoke-RestMethod -Method Post http://127.0.0.1:8081/_admin/reset
```

Ba kịch bản quan trọng:

1. `unknown_503` — bắt engine query lại order thay vì gửi lại (tránh 2 vị thế).
2. `throttle_1008` — kiểm tra reduce-only/close-position được miễn.
3. `latency_ms` — test timeout.

## Test

```powershell
# Chạy trong mock/binance-demo-server
..\..\.venv\Scripts\python.exe -m pytest -q
..\..\.venv\Scripts\python.exe -m ruff check app tests

# Hoặc qua script từ repo root
powershell -ExecutionPolicy Bypass -File scripts\ps\step-verify.ps1 -Step all
```

CI chạy `MARKET_MODE=replay` nên **không cần internet**.

## Giới hạn — đọc trước khi tin kết quả

- Không partial fill, không queue order book → fill **lạc quan hơn live**.
- Không mô phỏng ADL, STP, sàn bảo trì diện rộng.
- `TRAILING_STOP_MARKET` chưa hỗ trợ; engine tự trailing bằng cancel+place.
- Nén thời gian (`SPEED`) **chỉ để tìm bug**, không dùng để kết luận edge.
- Mock **không thay thế** live smoke test ≤ 0.05 USD trước khi chạy tiền thật.
