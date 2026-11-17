# PHASE 0 — BINANCE DEMO SERVER (MOCK)

**Kế hoạch triển khai container `binance-demo-server`**
Phiên bản: 1.0 · Ngày: 17/11/2026
Nguồn tham chiếu: `https://developers.binance.com/en/docs/products/derivatives-trading-usds-future` (mirror đọc được: `developers.binance.info/legacy-docs/...`)
Liên quan: `docs/mvp-binance-futures-bot.md` §7.9, `docs/phase1_task.md` P1.1/P1.3

---

## 0. Giải thích cơ bản

### 0.1 Vì sao cần container này

**Đây là môi trường demo chính thức của dự án.** Demo Trading của Binance **hỏng ở khâu tạo API key** và `testnet.binancefuture.com` đã bị gộp về `demo.binance.com` (redirect) ⇒ không còn môi trường ảo chính thức nào dùng được.

Từ đây, khi tài liệu nói **"mock"** hoặc **"demo"**, nghĩa là `binance-demo-server` trong repo này — **không phải** `demo.binance.com`.

Bot **không cần** Binance thật để phát triển. 95% code là: ký request, đặt lệnh, quản lý state, đặt SL, reconcile, restart, alert. Tất cả những thứ đó test được với một **server giả lập chạy cùng Docker network**.

### 0.2 Nguyên tắc thiết kế: "chính xác chứ không phải đầy đủ"

Mục tiêu **không phải** clone toàn bộ Binance. Mục tiêu là: **mọi thứ bot này gọi thì phải cư xử y như thật**, phần còn lại bỏ.

Phân tầng độ trung thực:

| Tier | Phạm vi | Yêu cầu |
|---|---|---|
| **A — Phải chính xác tuyệt đối** | Ký HMAC, timestamp/recvWindow, error code, tên field JSON, tick/step/minNotional, phí, vòng đời Algo order, `-4120`, listenKey, header rate-limit | Sai 1 ly là test vô nghĩa |
| **B — Xấp xỉ đủ tốt** | Matching engine (top-of-book), funding 8h, giá thanh lý | Sai số chấp nhận được, ghi rõ trong doc |
| **C — Ngoài phạm vi P0** | Order book sâu, ADL, STP, batch orders, WebSocket API (request/response), Portfolio Margin, TradFi-Perps | Không implement |

### 0.3 Thông số thật đã xác minh từ docs

| Hạng mục | Giá trị thật |
|---|---|
| REST live | `https://fapi.binance.com` |
| REST demo (tham chiếu lịch sử, **không dùng**) | `https://demo-fapi.binance.com` |
| WS live (market) | `wss://fstream.binance.com` |
| WS demo (tham chiếu lịch sử, **không dùng**) | `wss://demo-fstream.binance.com` |
| WS user stream | `wss://fstream.binance.com/private/ws/<listenKey>` |
| API key header | `X-MBX-APIKEY` |
| Chữ ký | `HMAC SHA256(secretKey, totalParams)`, `totalParams` = query string + body, **signature là param cuối** |
| Timing | hợp lệ khi `timestamp < serverTime + 1000` **và** `serverTime - timestamp <= recvWindow` (mặc định 5000) |
| listenKey | sống **60 phút**; `PUT` gia hạn 60 phút; connection tối đa **24 giờ** |
| Header rate-limit | `X-MBX-USED-WEIGHT-1M`, `X-MBX-ORDER-COUNT-10S`, `X-MBX-ORDER-COUNT-1M` |
| 429 / 418 | vượt limit → 429; tiếp tục spam → 418 (IP ban 2 phút → 3 ngày) |
| Error payload | `{"code": -1121, "msg": "Invalid symbol."}` |
| 503 variants | `"Unknown error, please check your request or try again later."` ⇒ **execution UNKNOWN**, có thể đã thành công. `"Service Unavailable."` ⇒ 100% fail |
| `-1008` | throttle hệ thống; **reduce-only / close-position được miễn** |
| `-4120` | `STOP_ORDER_SWITCH_ALGO` — STOP/TP gửi vào `/fapi/v1/order` bị từ chối |

### 0.4 Algo order — phần dễ sai nhất

Đây là lý do spec phải dùng Algo Service thay vì `/fapi/v1/order`:

```
POST /fapi/v1/algoOrder
  algoType    = CONDITIONAL           (bắt buộc, chỉ hỗ trợ giá trị này)
  type        = STOP_MARKET | TAKE_PROFIT_MARKET | STOP | TAKE_PROFIT | TRAILING_STOP_MARKET
  triggerPrice, workingType (MARK_PRICE|CONTRACT_PRICE), priceProtect
  closePosition = "true"              (không được gửi kèm quantity, không kèm reduceOnly)
  clientAlgoId                        (regex ^[\.A-Z\:/a-z0-9_-]{1,36}$)
```

Điều kiện kích hoạt (phải giả đúng từng chiều):

| Type | BUY | SELL |
|---|---|---|
| `STOP`, `STOP_MARKET` | `price >= triggerPrice` | `price <= triggerPrice` |
| `TAKE_PROFIT`, `TAKE_PROFIT_MARKET` | `price <= triggerPrice` | `price >= triggerPrice` |

Vòng đời status: `NEW → TRIGGERING → TRIGGERED → FINISHED`, cộng `CANCELED`, `REJECTED`, `EXPIRED`.

`EXPIRED` xuất hiện khi **đóng hết position thì SL còn lại tự bị hệ thống hủy** — chính là hành vi ở mục 9 bảng §4.3 của spec mà tài liệu công khai không mô tả rõ. Mock phải tái hiện điều này để engine test được.

Event user stream là **`ALGO_UPDATE`**, không phải `ORDER_TRADE_UPDATE`:

```json
{"e":"ALGO_UPDATE","T":...,"E":...,
 "o":{"caid":"...","aid":2148719,"at":"CONDITIONAL","o":"TAKE_PROFIT",
      "s":"BNBUSDT","S":"SELL","ps":"BOTH","f":"GTC","q":"0.01",
      "X":"CANCELED","ai":"","ap":"0.00000","aq":"0.00000","act":"0",
      "tp":"750","p":"750","V":"EXPIRE_MAKER","wt":"CONTRACT_PRICE",
      "pm":"NONE","cp":false,"pP":false,"R":false,"tt":0,"gtd":0,
      "rm":"","ia":false}}
```

---

## 1. Kiến trúc

### 1.1 Vị trí trong compose

```
Docker Compose (cùng network)
├── engine (Python)              → base_url: http://binance-demo-server:8080
│                                   ws_url  : ws://binance-demo-server:8080/ws
├── dashboard (Node)             → 127.0.0.1:8080
├── binance-demo-server (Python) → 127.0.0.1:8081 (chỉ để curl debug)
├── botdata (volume)             → SQLite của engine
└── mockdata (volume)            → state + fixtures của mock
```

`binance-demo-server` **không khai báo `profiles`** nên luôn chạy. `engine` + `dashboard` đặt sau `profiles: ["app"]`:

```powershell
docker compose up -d                    # chỉ mock (dev, CI)
docker compose --profile app up -d      # mock + engine + dashboard
```

Ranh giới: engine **không biết** đây là mock. Đổi môi trường chỉ bằng 1 biến env, không sửa code.

### 1.2 Stack

| Thành phần | Chọn | Lý do |
|---|---|---|
| Runtime | Python 3.12-slim | Cùng toolchain với engine, dùng lại pydantic model & helper ký |
| HTTP | FastAPI + uvicorn (1 worker) | Nhẹ (~80–120 MB), tự sinh OpenAPI để đối chiếu contract |
| Market proxy | httpx (async) + TTL cache | Lấy dữ liệu thật, không cần key (endpoint public) |
| State | SQLite (stdlib `sqlite3`, WAL) | Sống qua restart; không cần DB server |
| WS | `websockets` | Bắn event giả |
| Đóng gói | `python:3.12-slim`, read-only, 256 MB, 0.5 CPU | Nhẹ |

Từ chối Go/Rust: nhanh hơn nhưng phải viết lại toàn bộ helper ký + model, và tốc độ không phải nút cổ chai (engine poll ~1 req/s).

### 1.3 Ba chế độ dữ liệu thị trường

| Mode | Nguồn giá | Dùng khi | Tính chất |
|---|---|---|---|
| `proxy` (mặc định) | Forward sang `https://fapi.binance.com` + cache 1–5s | Dev hàng ngày | Giá thật, cần internet, tốn 0 đồng |
| `replay` | File Parquet/JSON fixtures | CI, test hồi quy | Tất định 100%, offline, nhanh |
| `synthetic` | Random walk có seed từ config | Test scenario (squeeze, crash, gap) | Điều khiển được mọi tình huống |

**Account/order luôn mô phỏng local ở mọi mode** — không bao giờ proxy (không thể, và không nên).

### 1.4 Matching model (Tier B)

```
LIMIT   : khớp khi giá chạm/xuyên qua (cấu hình: pessimistic = phải xuyên, optimistic = chạm là khớp)
MARKET  : khớp tại best bid/ask + slippage_bps (mặc định 5)
PARTIAL : P0 = tắt (khớp đủ). Ghi rõ trong doc, bật ở P1 nếu cần test ADL.
Phí     : maker 2 bps, taker 5 bps (tính trên notional khớp)
Funding : snapshot 00/08/16 UTC, rate lấy từ premiumIndex, trừ vào balance
SL      : trigger theo workingType (mặc định MARK_PRICE → lấy markPrice)
closePosition=true : khi trigger → đóng toàn bộ position tại market
```

Bất biến phải luôn đúng (assert trong code, không chỉ trong test):

```
1. positionAmt == Σ fill_qty(signed)  của symbol
2. balance == initial + realized_pnl − fees + funding
3. Không thể mở lệnh nếu margin < yêu cầu  →  -2019
4. positionAmt == 0  ⇒  mọi algo order của symbol chuyển EXPIRED
5. Trả về đúng header rate-limit trên MỌI response
```

---

## 2. Bảng endpoint

### 2.1 Market data (security = NONE)

| Endpoint | P0 | Ghi chú |
|---|---|---|
| `GET /fapi/v1/ping` | ✅ | dùng cho healthcheck |
| `GET /fapi/v1/time` | ✅ | `{"serverTime": ...}` |
| `GET /fapi/v1/exchangeInfo` | ✅ | **snapshot thật**, gồm `filters`, `triggerProtect`, `rateLimits` |
| `GET /fapi/v1/klines` | ✅ | replay từ fixture hoặc proxy |
| `GET /fapi/v1/ticker/price` | ✅ | |
| `GET /fapi/v1/ticker/bookTicker` | ✅ | best bid/ask → nguồn cho matching |
| `GET /fapi/v1/premiumIndex` | ✅ | `markPrice`, `lastFundingRate`, `nextFundingTime` |
| `GET /fapi/v1/fundingRate` | ✅ | lịch sử funding |
| `GET /fapi/v1/openInterest` | ✅ | |
| `GET /fapi/v1/depth` | ⬜ P1 | chỉ cần top-of-book ở P0 |
| `GET /fapi/v1/aggTrades` | ⬜ P1 | |

### 2.2 Account (USER_DATA, signed)

| Endpoint | P0 | Ghi chú |
|---|---|---|
| `GET /fapi/v2/balance` | ✅ | danh sách asset USDT |
| `GET /fapi/v2/account` | ✅ | `totalWalletBalance`, `availableBalance`, `positions` |
| `GET /fapi/v2/positionRisk` | ✅ | `positionAmt`, `entryPrice`, `markPrice`, `unRealizedProfit`, `liquidationPrice`, `leverage`, `marginType` |
| `GET /fapi/v1/commissionRate` | ✅ | trả 0.0002 / 0.0005 |
| `GET /fapi/v1/leverageBracket` | ✅ | MMR bậc 1–2 |
| `GET /fapi/v1/income` | ✅ | REALIZED_PNL, COMMISSION, FUNDING_FEE |
| `GET /fapi/v1/userTrades` | ✅ | |
| `POST /fapi/v1/leverage` | ✅ | đổi leverage (validate 1–125) |
| `POST /fapi/v1/marginType` | ✅ | ISOLATED/CROSSED |

### 2.3 Trade (TRADE, signed)

| Endpoint | P0 | Ghi chú |
|---|---|---|
| `POST /fapi/v1/order` | ✅ | **phải trả `-4120`** nếu `type ∈ {STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET}` |
| `GET /fapi/v1/order` | ✅ | theo `orderId` hoặc `origClientOrderId` |
| `DELETE /fapi/v1/order` | ✅ | `-2011` nếu không tồn tại |
| `DELETE /fapi/v1/allOpenOrders` | ✅ | trả số lượng đã hủy |
| `GET /fapi/v1/openOrders` | ✅ | |
| `GET /fapi/v1/allOrders` | ✅ | |
| `POST /fapi/v1/order/test` | ✅ | validate nhưng không tạo lệnh |
| `POST /fapi/v1/batchOrders` | ⬜ P1 | |

### 2.4 Algo (TRADE, signed)

| Endpoint | P0 | Ghi chú |
|---|---|---|
| `POST /fapi/v1/algoOrder` | ✅ | vòng đời đầy đủ, trả `algoId` |
| `DELETE /fapi/v1/algoOrder` | ✅ | theo `algoId` |
| `DELETE /fapi/v1/algoOpenOrders` | ✅ | theo symbol |
| `GET /fapi/v1/algoOrder` | ✅ | |
| `GET /fapi/v1/openAlgoOrders` | ✅ | nguồn cho reconcile |
| `GET /fapi/v1/historicalAlgoOrders` | ✅ | |

### 2.5 User data stream

| Endpoint / stream | P0 | Ghi chú |
|---|---|---|
| `POST /fapi/v1/listenKey` | ✅ | trả `listenKey`, sống 60 phút |
| `PUT /fapi/v1/listenKey` | ✅ | gia hạn; `-1125` nếu không tồn tại |
| `DELETE /fapi/v1/listenKey` | ✅ | |
| `WS /ws/<listenKey>` | ✅ | event: `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`, `MARGIN_CALL`, `listenKeyExpired` |

Thứ tự event phải đảm bảo: cùng loại event trên cùng connection thì đơn điệu theo `T` và `E`.

---

## 3. Bảng error code phải giả

Không giả được hết thì **tối thiểu** phải có bảng này, vì đây là những lỗi engine sẽ thật sự gặp:

| Code | Kích hoạt khi | Engine phải làm gì (để test) |
|---|---|---|
| `-1021` | `timestamp` lệch > recvWindow | sync NTP, retry |
| `-1022` | sai chữ ký | dừng, không spam |
| `-2015` | sai key / IP / thiếu quyền | alert, dừng |
| `-1121` | symbol không tồn tại | bỏ symbol |
| `-1102` | thiếu param bắt buộc | bug code |
| `-1111` | sai precision | round lại |
| `-2010` | lệnh bị từ chối | đọc msg |
| `-2011` | cancel lệnh không tồn tại | coi là đã hủy |
| `-2013` | order không tồn tại | reconcile |
| `-2018` | balance không đủ | giảm size |
| `-2019` | margin không đủ | **chặn ở risk engine trước** |
| `-2020` | order would immediately trigger | dời trigger |
| `-2021` | reduce-only reject | bug logic |
| `-4164` | notional < minNotional | tăng size hoặc bỏ |
| `-4120` | STOP/TP gửi sai endpoint | dùng `/algoOrder` |
| `-1003` / 429 | vượt rate limit | backoff |
| `-1008` | throttle hệ thống | backoff; reduce-only được miễn |
| `-1125` | listenKey không tồn tại | tạo lại listenKey |
| 418 | IP ban | dừng hẳn, không retry |
| 503 `"Unknown error..."` | fault injection | **không coi là fail**, kiểm tra qua WS/query |

> Việc còn lại: đối chiếu tên/ngữ nghĩa từng code với trang `Error Code` của Binance khi implement, không chép từ trí nhớ.

---

## 4. Các phase con

| Mã | Phase con | Thời lượng | Cổng ra |
|---|---|---|---|
| M0.1 | Chốt contract & fixtures | 0,5 ngày | Mọi response mẫu được freeze từ docs |
| M0.2 | Skeleton container + compose | 0,5 ngày | `up -d` healthy, curl `/ping` OK |
| M0.3 | Auth & rate-limit layer | 1 ngày | Golden signature test pass |
| M0.4 | Market data 3 modes | 1 ngày | Proxy/replay/synthetic cùng schema |
| M0.5 | Account state | 0,5 ngày | balance/positionRisk khớp phép tính tay |
| M0.6 | Order engine | 1,5 ngày | Fill → position → balance đúng |
| M0.7 | Algo engine | 1,5 ngày | SL lifecycle + `-4120` + EXPIRED |
| M0.8 | User data stream | 1 ngày | Event đúng thứ tự, engine nhận được |
| M0.9 | Fault injection | 0,5 ngày | Bơm được 429/503/timeout |
| M0.10 | Persistence & restart | 0,5 ngày | Restart giữ position/order |
| M0.11 | Test harness + CI | 1 ngày | `pytest` + engine end-to-end |
| | **Tổng** | **~9,5 ngày** | |

---

## M0.1 — Chốt contract & fixtures (0,5 ngày)

### Giải thích cơ bản

Trước khi viết server, freeze lại "hợp đồng": mỗi endpoint trả JSON hình gì, field nào, kiểu gì. Làm bước này trước để 2 bên (engine và mock) không lệch nhau, và để test so sánh được.

### Việc cần làm

1. Lưu response mẫu thật vào `mock/contracts/<endpoint>.json` (lấy từ docs + 1 lần gọi thật nếu được).
2. Snapshot `exchangeInfo` thật của 10 symbol → `mock/fixtures/exchangeInfo.json` (giữ nguyên `tickSize`, `stepSize`, `minNotional`, `triggerProtect`).
3. Ghi lại **golden signature vector** từ docs để test auth:
   ```
   secret = 2b5eb11e18796d12d88f13dc27dbbd02c2cc51ff7059765ed9821957d82bb4d9
   payload = symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC&recvWindow=5000&timestamp=1591702613943
   → signature = 3c661234138461fcc7a7d8746c6558c9842d4e10870d2ecbedf7777cad694af9
   ```
4. Viết `mock/contracts/README.md` ghi rõ: field nào Tier A (không được đổi), field nào Tier C (bỏ).

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Đủ contract cho mọi endpoint P0 | Check list 2.1–2.5 khớp file |
| 2 | exchangeInfo là snapshot thật | tick/step đúng, không bịa |
| 3 | Golden vector có trong repo | 1 file + 1 test dùng nó |

### Checklist test

- [x] Mỗi endpoint P0 có 1 file contract JSON
- [x] `exchangeInfo.json` parse được, đủ 10 symbol
- [x] Golden signature vector chạy ra đúng hash đã ghi
- [x] Có README phân Tier A/B/C

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Contracts frozen | ✅ | `mock/contracts/contracts.json` (~10KB): auth, account, balance, positionRisk, order, algoOrder, events WS | 17/11/2026 |
| exchangeInfo snapshot | ✅ | `mock/fixtures/exchangeInfo.json` — 10 symbol, 12.455 bytes, tải từ `fapi.binance.com` | 17/11/2026 |
| Klines thật | ✅ | `mock/fixtures/klines.json` — 15m×500 + 1m×300 ×10 symbol, 1.048.912 bytes | 17/11/2026 |
| Golden vector | ✅ | tính lại bằng `hmac` → `3c661234...694af9` khớp tài liệu | 17/11/2026 |
| README Tier A/B/C | ✅ | `mock/contracts/README.md` | 17/11/2026 |

### Ghi chú

- **Lệch spec:** gộp thành 1 file `contracts.json` thay vì 1 file/endpoint — test harness load 1 lần, ít file rác hơn. Đã ghi trong `_meta` của file.
- Field Tier A đổi tên = engine phải sửa → coi như breaking change, ghi vào changelog của mock.
- Đừng lấy `exchangeInfo` từ trí nhớ; tick/step là thứ sẽ gây `-4014`/`-4023`/`-4164` khó hiểu nhất.
- Fixture là **dữ liệu thật** tải ngày 17/11/2026, dùng lại được offline cho `MARKET_MODE=replay`.

---

## M0.2 — Skeleton container (0,5 ngày)

### Giải thích cơ bản

Dựng container rỗng nhưng **healthy**, để từ đó thêm endpoint. Làm đúng ngay từ đầu: read-only filesystem, memory limit, healthcheck — vì đây là thứ sẽ chạy song song hàng tháng.

### Việc cần làm

1. `mock/binance-demo-server/` với `app/main.py`, `Dockerfile`, `requirements.txt`.
2. Endpoint `/fapi/v1/ping`, `/fapi/v1/time`, `/healthz`.
3. Compose fragment (xem mục 6).
4. Engine: env override `BINANCE_BASE_URL`, `BINANCE_WS_URL` (không hardcode trong YAML).

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Time khởi động | < 3s |
| 2 | RAM | < 200 MB idle |
| 3 | Healthcheck | pass trong 10s |
| 4 | Không ghi filesystem ngoài `/tmp` và volume | `read_only: true` chạy được |

### Checklist test

- [x] `docker compose up -d binance-demo-server` → healthy
- [x] `curl 127.0.0.1:8081/fapi/v1/ping` → `{}`
- [x] `curl .../fapi/v1/time` → `serverTime` cùng giây với host
- [x] `/_debug` trả HTML 200, `/_debug/json` trả JSON
- [x] `docker stats` RAM < 200 MB
- [ ] Engine trỏ vào mock — **chưa áp dụng** (engine chưa tồn tại)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Container healthy | ✅ | `docker compose ps` → `Up (healthy)`, port `127.0.0.1:8081->8080` | 17/11/2026 |
| Startup | ✅ | local 1.350 ms < 3.000 ms | 17/11/2026 |
| RAM | ✅ | `docker stats` → **35,77 MiB** / 256 MiB; CPU 0,15% | 17/11/2026 |
| `/ping` `/time` `/healthz` | ✅ | `{}` · `serverTime` lệch host −64 ms · `{"status":"ok"}` | 17/11/2026 |
| `/_debug` | ✅ | HTTP 200, HTML + `/_debug/json` đủ panel | 17/11/2026 |
| read-only filesystem | ✅ | `read_only: true` + tmpfs `/tmp` chạy được | 17/11/2026 |

### Ghi chú

- Port: mock **8080 bên trong**, map `127.0.0.1:8081` bên ngoài để không đụng dashboard.
- **Không** dùng `env_file: .env` cho mock: file đó chứa secret Binance thật, mock không cần. Chỉ truyền env tường minh.
- `/_debug` là **công cụ debug** (FE của Phase 0), read-only, không có form ghi, không gọi endpoint làm đổi state — không thuộc luồng giao dịch.

---

## M0.3 — Auth & rate-limit layer (1 ngày)

### Giải thích cơ bản

Đây là phần **quan trọng nhất** của mock. Nếu mock chấp nhận chữ ký sai, engine của bạn sẽ viết sai chữ ký và bạn chỉ phát hiện khi lên live — tức là đã mất tiền để học.

Mock phải khó tính y như thật: đúng thứ tự param, đúng timestamp, đúng header.

### Việc cần làm

1. Verify `X-MBX-APIKEY`; key lạ → `-2015`.
2. Verify chữ ký: HMAC SHA256 trên `totalParams` (query + body), **loại bỏ param `signature`**, giữ đúng thứ tự gửi lên; sai → `-1022`.
3. Timing: `timestamp < now + 1000 && now - timestamp <= recvWindow` (default 5000); sai → `-1021`.
4. Param bắt buộc thiếu → `-1102`; param rỗng → `-1105`; param không hỗ trợ → `-1106`.
5. Đếm weight theo bảng endpoint, trả `X-MBX-USED-WEIGHT-1M`; vượt 2400 → 429; spam sau 429 → 418.
6. Đếm order: `X-MBX-ORDER-COUNT-10S` (300), `X-MBX-ORDER-COUNT-1M` (1200).
7. Chế độ `AUTH_STRICT=false` cho phép tắt kiểm tra chữ ký khi debug (mặc định **true**).

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Golden vector pass | test dùng đúng vector docs |
| 2 | Sai 1 ký tự trong signature → `-1022` | test |
| 3 | Đảo thứ tự param → `-1022` | test |
| 4 | Timestamp lùi 10s → `-1021` | test |
| 5 | Thiếu `signature` → `-1102` | test |
| 6 | Header weight có trên 100% response | test |

### Checklist test

- [x] Golden signature → 200 (unit test + gọi container thật)
- [x] Sai secret → `-1022`
- [x] Sai thứ tự param → `-1022`
- [x] `timestamp` lệch 20s → `-1021`
- [x] `recvWindow` nhỏ + timestamp cũ → `-1021`
- [x] Key sai → `-2015` (khi `MOCK_API_KEY` được đặt); thiếu key → `-2014`
- [x] Vượt weight → 429 + `Retry-After`
- [x] Tiếp tục gọi sau 429 → 418
- [x] Header `X-MBX-USED-WEIGHT-1M` có trên mọi response

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| HMAC verify | ✅ | 15 test pass; golden vector `3c661234…694af9` khớp | 17/11/2026 |
| Timing check | ✅ | `-1021` khi lệch 20s và khi `recvWindow=100` | 17/11/2026 |
| Weight + order header | ✅ | container trả `x-mbx-used-weight-1m`, `x-mbx-order-count-10s/1m` | 17/11/2026 |
| 429 → 418 | ✅ | test hạ limit xuống 30: lần 2 → 429, lần 3 → 418 | 17/11/2026 |
| Signed endpoint thật | ✅ | `GET /fapi/v1/commissionRate` → `0.000200 / 0.000500` | 17/11/2026 |

### Ghi chú

- `signature` **không** nằm trong chuỗi ký — đã tách bằng `split_total_params`, có test riêng.
- Mock **chấp nhận mọi key không rỗng** theo mặc định (giống demo sẵn sàng cho engine). Chỉ khi đặt `MOCK_API_KEY` mới trả `-2015` cho key sai.
- Secret dùng để verify là `MOCK_API_SECRET`, mặc định `mock-secret` — **không phải** secret Binance thật.
- Trọng số endpoint lấy theo docs nhưng có thể lệch nhỏ; đây là Tier B. Ghi nhận `commissionRate = 20`.
- Header bị uvicorn chuyển về chữ thường (`x-mbx-…`) — HTTP header không phân biệt hoa thường, engine phải đọc case-insensitive.

---

## M0.4 — Market data 3 modes (1 ngày)

### Giải thích cơ bản

`proxy` cho dev hàng ngày (giá thật), `replay` cho CI (tất định), `synthetic` cho test scenario. Cả 3 phải trả **cùng một schema**, chỉ khác nguồn.

### Việc cần làm

1. Implement 2.1 với 3 backend, chọn bằng env `MARKET_MODE`.
2. Cache TTL: `bookTicker` 1s, `klines` 5s, `exchangeInfo` 1h, `premiumIndex` 3s.
3. `replay`: đọc fixture theo `scenario` + `clock_ms`, trả nến "đã đóng" đúng thời điểm.
4. `synthetic`: random walk theo seed, cấu hình được `vol_bps`, `trend_bps`, `jump_prob` để tạo squeeze/crash.
5. Nến phải **không bao giờ** trả nến chưa đóng nếu `closed_only=true` (để test look-ahead).

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | 3 mode cùng schema | diff JSON 3 mode = rỗng |
| 2 | `replay` tất định | 2 lần chạy cùng clock → byte-identical |
| 3 | `synthetic` tất định | cùng seed → cùng chuỗi |
| 4 | Cache hoạt động | 100 req trong 1s → ≤ 2 lần gọi upstream |
| 5 | Proxy không cần key | không gửi `X-MBX-APIKEY` lên upstream |

### Checklist test

- [x] `/klines` 3 mode → cùng key set (12 cột)
- [x] `replay` chạy 2 lần → kết quả giống
- [x] `synthetic` cùng seed → chuỗi giá giống ở 2 lần
- [x] `SYNTH_JUMP_PROB=0.05` → tạo được cú nhảy > 2% (test crash)
- [x] Cache TTL hoạt động (test helper)
- [x] `/premiumIndex` có `markPrice` + `nextFundingTime`, mark ≠ last
- [x] `replay` dịch thời gian → nến cuối "tươi" (< 1 khung)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Proxy | ✅ (code) | Forward `fapi.binance.com` + cache TTL; **chưa test do cần internet ổn định** | 17/11/2026 |
| Replay | ✅ | container: BTC 15m close `64922.30` (giá thật từ fixture), nến cuối cách hiện tại 979s | 17/11/2026 |
| Synthetic | ✅ | test tất định theo seed; hỗ trợ jump để tạo crash | 17/11/2026 |
| Cache TTL | ✅ | `_store/_cached` test: hết hạn đúng 50ms | 17/11/2026 |
| mark ≠ last | ✅ | `64922.48` vs `64922.30` (basis 0,02%) | 17/11/2026 |
| bookTicker | ✅ | ETH `1818.42 / 1818.52`, spread = 1 tick | 17/11/2026 |

### Ghi chú

- `replay` **dịch thời gian**: nến cuối được kéo về sát hiện tại, để engine không coi dữ liệu là stale. Nội dung nến là dữ liệu thật, chỉ timestamp bị dịch — ghi rõ để không ai nhầm là dữ liệu real-time.
- `synthetic` dùng hàm băm theo **(seed, symbol, chỉ số nến)** → một nến luôn có cùng giá trị dù gọi lúc nào. Đây là điều kiện để test tất định.
- `synthetic` không đảm bảo nhất quán giữa 1m và 15m (Tier B). Không dùng để kiểm tra logic aggregate.
- Proxy mode là **rủi ro phụ thuộc**: Binance đổi field thì mock phải sửa theo. CI luôn chạy `replay`.

---

## M0.5 — Account state (0,5 ngày)

### Giải thích cơ bản

Mock giữ "sổ" của tài khoản: balance, position, leverage, margin type. Mọi thứ phải tính lại được bằng tay để đối chiếu.

### Việc cần làm

1. `INITIAL_BALANCE` (mặc định 5000), asset USDT.
2. `balance` = wallet balance, `availableBalance` = wallet − margin đã dùng − unrealized loss.
3. `positionRisk` từ vị thế nội bộ: `positionAmt`, `entryPrice`, `markPrice`, `unRealizedProfit`, `liquidationPrice`, `leverage`, `marginType`, `isolatedWallet`.
4. `leverageBracket`: bậc 1–2 với MMR hợp lý (BTC 0,4%; alt 1–2,5%).
5. `commissionRate`: 0.0002/0.0005.
6. Persist xuống SQLite; reload khi start.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Số liệu khớp tính tay | 1 test có bảng tính cứng |
| 2 | `availableBalance` đúng khi có vị thế | test mở 1 vị thế |
| 3 | `unRealizedProfit` đúng dấu long/short | test 2 chiều |
| 4 | Persist | restart → số liệu giữ nguyên |

### Checklist test

- [x] Balance ban đầu = 5000
- [x] Mở 0,01 BTC long → margin ≈ notional/leverage (200–240 USDT)
- [x] uPnL đúng dấu long/short
- [x] Realized PnL đúng số khi đóng (10 USDT cho 0,01 BTC × 1000 giá)
- [x] `availableBalance` giảm đúng bằng margin
- [x] Flip vị thế (long 0,01 → short 0,02) đúng entry mới
- [x] Công thức thanh lý khớp `entry×(1−1/L)/(1−MMR)`
- [x] Đổi leverage / marginType; chặn `-4048` khi đã có vị thế
- [x] Persist: đóng store rồi mở lại từ file → wallet + position giữ nguyên

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Balance/account | ✅ | container: `wallet 5000.00000000`, 41 test pass | 17/11/2026 |
| PositionRisk | ✅ | `posRisk` 200, số vị thế 0; test có vị thế trả đúng `positionAmt/entry/liq` | 17/11/2026 |
| Bracket MMR | ✅ | `maintMarginRatio 0.004` cho BTC | 17/11/2026 |
| Set leverage | ✅ | POST `/fapi/v1/leverage` → `{"leverage":3}` | 17/11/2026 |
| Persist | ✅ | test `tmp_path` mở lại store giữ wallet + position | 17/11/2026 |

### Ghi chú

- Toàn bộ tiền lưu **TEXT (Decimal)** trong SQLite, không dùng float — tránh sai số khi so khớp tick/step.
- `availableBalance = wallet + ΣuPnL − ΣinitialMargin`, sàn 0. Đây là Tier B (Binance còn tính maint margin và cross collateral).
- `canWithdraw` trong `/fapi/v2/account` mock **luôn false** — tránh lặp lại bẫy `canWithdraw` ở `docs/verification.md`.
- Vị thế 1 chiều (one-way), mỗi symbol 1 dòng; chưa hỗ trợ hedge mode (Tier C).

---

## M0.6 — Order engine (1,5 ngày)

### Giải thích cơ bản

Đây là trái tim: nhận lệnh, validate filter, khớp, cập nhật position + balance + fees, phát event.

### Việc cần làm

1. `POST /fapi/v1/order` cho `MARKET`, `LIMIT`, `LIMIT+GTX`; cấm 5 type điều kiện bằng `-4120`.
2. Validate filter: `tickSize` → `-4014`; `stepSize` → `-4023`; `minNotional` → `-4164`; margin → `-2019`; trigger ngay → `-2020`.
3. `newClientOrderId` idempotent: trùng → lỗi, không tạo lệnh thứ 2.
4. Fill: LIMIT theo `fill_model`; MARKET tại best bid/ask + slippage.
5. Cập nhật position (one-way), entry price trung bình, realized PnL, phí theo maker/taker.
6. `GET/DELETE order`, `openOrders`, `allOrders`, `allOpenOrders`.
7. Phát `ORDER_TRADE_UPDATE` + `ACCOUNT_UPDATE`.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Filter validation đúng code | 5 test, 5 code đúng |
| 2 | Position == Σ fills | assert sau mỗi fill |
| 3 | Balance == initial + pnl − fees | assert sau mỗi fill |
| 4 | `clientOrderId` không trùng | gửi 2 lần → 1 lệnh |
| 5 | STOP/TP → `-4120` | test 5 type |

### Checklist test

- [x] Market BUY 0,002 BTC → position 0,002, balance giảm phí
- [x] LIMIT không khớp → nằm trong `openOrders`
- [x] `tick()` khớp lệnh LIMIT khi giá chạm → FILLED
- [x] DELETE lệnh → CANCELED; DELETE lần 2 → `-2011`
- [x] Qty dưới step → `-1111`
- [x] Price sai tick → `-4014`
- [x] Notional < minNotional → `-4164`
- [x] STOP_MARKET qua `/order` → `-4120` (5 type điều kiện)
- [x] Trùng `newClientOrderId` → `-2010`, chỉ 1 lệnh được tạo
- [x] `order/test` không tạo lệnh
- [x] reduceOnly khi không có vị thế → `-2021`
- [x] Margin không đủ → `-2019`
- [x] GTX sẽ khớp ngay → `-5022`

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Order CRUD | ✅ | container: market FILLED, `openOrders` 0→1→0, cancel 2 lần → `-2011` | 17/11/2026 |
| Filter validation | ✅ | `-1111` (step), `-4014` (tick), `-4164` (notional), `-2019` (margin) | 17/11/2026 |
| Fill + position + fee | ✅ | 53 test pass; phí ghi vào `fills`, wallet giảm đúng | 17/11/2026 |
| Idempotency | ✅ | lặp `newClientOrderId` → `-2010 Duplicate order sent.` | 17/11/2026 |
| `-4120` | ✅ | container + test: cả 5 type điều kiện bị chặn | 17/11/2026 |

### Ghi chú

- **Không partial fill** (Tier B): mỗi lệnh khớp toàn bộ. Muốn test ADL/partial phải bật ở P1.
- `fill_model=pessimistic`: lệnh LIMIT chỉ khớp khi **ask ≤ giá mua** (giá xuyên qua), không khớp khi chỉ chạm.
- Slippage 5 bps áp cho MARKET và LIMIT khớp ngay (taker); LIMIT nghỉ khớp ở đúng giá limit (maker).
- `quantity` mặc định trong test là 0,002 BTC để vượt minNotional 50 USDT của BTCUSDT.
- Lệnh nghỉ được khớp bởi `ENGINE.tick()` chạy mỗi 1s trong background task (không phải bởi request của client).

---

## M0.7 — Algo engine (1,5 ngày)

### Giải thích cơ bản

SL/TP của hệ thống đi qua đây. Mock phải tái hiện đúng: tạo → chờ trigger → chuyển TRIGGERED → FINISHED, và **tự EXPIRED khi position đóng**.

### Việc cần làm

1. `POST /fapi/v1/algoOrder` với validate: `algoType=CONDITIONAL`, `closePosition` không được kèm `quantity`/`reduceOnly`, `clientAlgoId` đúng regex.
2. Lưu algo order; phát `ALGO_UPDATE` status `NEW`.
3. Mỗi tick giá: kiểm tra điều kiện trigger theo `workingType` (MARK_PRICE/CONTRACT_PRICE) và đúng chiều BUY/SELL.
4. Khi trigger: `TRIGGERING` → tạo market order → `TRIGGERED` → khi khớp → `FINISHED`.
5. `closePosition=true` → đóng **toàn bộ** position hiện tại, không cần `quantity`.
6. `priceProtect=true` → nếu |mark − last|/last > `triggerProtect` → không trigger (và/hoặc `-2021` lúc đặt nếu trigger ngay).
7. `positionAmt == 0` → mọi algo còn lại của symbol → `EXPIRED`.
8. `DELETE /algoOrder`, `DELETE /algoOpenOrders`, `GET /openAlgoOrders`, `GET /algoOrder`, `GET /historicalAlgoOrders`.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Vòng đời đủ 4 status | test log status sequence |
| 2 | Chiều trigger đúng | 4 test (STOP/TP × BUY/SELL) |
| 3 | `closePosition` đóng đúng size hiện tại | test partial |
| 4 | EXPIRED khi position về 0 | test |
| 5 | `-4120` không xuất hiện ở `/algoOrder` | test |
| 6 | `ALGO_UPDATE` có `caid`, `aid`, `X` | test schema |

### Checklist test

- [x] Đặt STOP_MARKET closePosition → `algoId`, status NEW
- [x] Giá chạm trigger → position đóng, status FINISHED
- [x] TP_SELL khi giá ≥ trigger → khớp
- [x] STOP_BUY (short) khi giá ≥ trigger → khớp
- [x] SL không trigger khi giá chưa chạm
- [x] Đóng position bằng tay → SL còn lại EXPIRED
- [x] `closePosition` + `quantity` → `-1106`
- [x] Trigger đặt sai chiều → `-2020`
- [x] `priceProtect` + mark lệch xa → không trigger
- [x] triggerPrice sai tick → `-4014`
- [x] `GET /openAlgoOrders` phản ánh đúng ngay sau mỗi thao tác
- [x] Trùng `clientAlgoId` → `-2010`
- [ ] Restart mock → algo còn nguyên (**chuyển sang M0.10**)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Algo CRUD | ✅ | container: NEW → query → cancel → `CANCELED`; `history` total 1 | 17/11/2026 |
| Trigger 4 chiều | ✅ | test: SL/TP × BUY/SELL với giá cố định | 17/11/2026 |
| closePosition | ✅ | đóng đúng `abs(positionAmt)`, order con có `close_position=1` | 17/11/2026 |
| EXPIRED khi flat | ✅ | đóng tay → `ALGO.tick()` → `EXPIRED` | 17/11/2026 |
| priceProtect | ✅ | mark 94.000 vs last 100.000 (6% > 5%) → giữ `NEW` | 17/11/2026 |
| 67 test pass | ✅ | `pytest` xanh, `ruff` sạch | 17/11/2026 |

### Ghi chú

- **Đây là phần quan trọng nhất của mock.** Engine mất tiền ở live chủ yếu vì SL đặt sai chiều hoặc không bao giờ trigger; 4 test chiều trigger là lá chắn cho lỗi đó.
- SL dùng `ENGINE.market_close()` — **bỏ qua kiểm tra margin**. Nếu dùng đường đặt lệnh thường, một vị thế đang lỗ có thể bị từ chối đóng vì "margin insufficient", đúng thảm hoạ mà mock phải ngăn.
- `close_position=1` trên order con để phân biệt lệnh SL/TP với lệnh thường khi phân tích PnL.
- `TRAILING_STOP_MARKET` **chưa hỗ trợ** (Tier C). Engine phải tự trailing bằng cancel+place, mock chỉ cần STOP_MARKET.
- Test dùng `monkeypatch` giá cố định thay vì `replay` để không phụ thuộc dữ liệu thị trường thật.

---

## M0.8 — User data stream (1 ngày)

### Giải thích cơ bản

Engine nghe WS để biết fill xảy ra. Mock phải bắn event đúng thứ tự, đúng schema, và có thể "chết" để test reconnect.

### Việc cần làm

1. `POST/PUT/DELETE /fapi/v1/listenKey`; `PUT` với key lạ → `-1125`.
2. WS `/ws/<listenKey>`; sai key → đóng với code phù hợp.
3. Bắn `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`, `MARGIN_CALL`, `listenKeyExpired`.
4. Đảm bảo thứ tự theo `T`/`E` cho cùng loại event.
5. Option `chaos: listenkey_renew_after=59m` để test renew.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Engine nhận event < 100ms sau fill | đo |
| 2 | Schema khớp contract | validate |
| 3 | `listenKeyExpired` được xử lý | test tắt/mở lại |
| 4 | Reconnect sau khi mock restart | test |

### Checklist test

- [x] Fill → `ORDER_TRADE_UPDATE` với `X=NEW` rồi `X=FILLED`
- [x] Đặt SL → `ALGO_UPDATE` `X=NEW`
- [x] SL trigger → `ALGO_UPDATE` `X=FINISHED` (test unit, giá cố định)
- [x] `PUT listenKey` sai → `-1125`
- [x] `listenKeyExpired` được phát và log
- [x] WS path `/ws/<key>` và `/private/ws/<key>` đều chạy
- [x] Key sai → nhận `-1125` rồi đóng kết nối
- [x] Thứ tự event đơn điệu theo `E`
- [ ] Kill mock giữa lúc có position → engine reconnect (**chuyển sang M0.10**)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| listenKey lifecycle | ✅ | container: POST → key; POST lần 2 trả cùng key; PUT sai → `-1125` | 17/11/2026 |
| WS push | ✅ | container: đặt lệnh ETH → nhận `ORDER_TRADE_UPDATE` `NEW` rồi `FILLED` | 17/11/2026 |
| 4 loại event | ✅ | `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`, `MARGIN_CALL`/`listenKeyExpired` (cấu trúc sẵn) | 17/11/2026 |
| Reconnect | ✅ (mock) | handler phát hiện disconnect bằng `receive_text`, huỷ sender task | 17/11/2026 |
| 74 test pass | ✅ | `pytest` xanh | 17/11/2026 |

### Ghi chú

- **Bẫy đã gặp:** nếu handler chỉ có vòng `queue.get()` thì khi client đóng, task treo vĩnh viễn và test timeout. Cách đúng: một task gửi + vòng `receive_text()` để phát hiện ngắt.
- `events.publish()` là điểm duy nhất phát event — vừa ghi `events_log`, vừa đẩy WS. Đừng gọi `HUB.broadcast` trực tiếp (sẽ không có log, đúng lỗi đã gặp ở `listenKeyExpired`).
- `listenKey` sống 60 phút (env `LISTENKEY_TTL_S`), `check_expired()` chạy trong loop 1s.
- Giới hạn 24h/kết nối của Binance **chưa mô phỏng** (Tier B).

---

## M0.9 — Rate limit & fault injection (0,5 ngày)

### Giải thích cơ bản

Một mock "hoàn hảo" không bao giờ lỗi là mock vô dụng: bug xử lý lỗi của engine sẽ không bao giờ được test. Fault injection biến mock thành môi trường khắc nghiệt.

### Việc cần làm

1. Env: `FAIL_RATE`, `LATENCY_MS`, `FAIL_CODES` (danh sách code), `WS_DROP_EVERY`.
2. Bơm 429/418 theo weight thật.
3. Bơm 503 với message `"Unknown error, please check your request or try again later."` → engine phải **không** coi là fail.
4. Bơm `-1008` cho mọi lệnh **trừ** reduce-only/closePosition (đúng như docs).
5. Endpoint điều khiển: `POST /_admin/chaos {...}`, `POST /_admin/reset`.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Bơm lỗi được theo % | test 100 req, ~20% lỗi khi FAIL_RATE=0.2 |
| 2 | 503 unknown → engine query lại, không double order | test end-to-end |
| 3 | `-1008` miễn reduce-only | test |
| 4 | Latency bơm được | đo p99 |

### Checklist test

- [x] `fail_rate=1` → mọi request lỗi theo code cấu hình
- [x] `fail_rate=0.3` → ~70% thành công trên 100 request
- [x] `unknown_503` → 503 với đúng message "Unknown error, please check your request or try again later."
- [x] `latency_ms` bơm được (đo ≥ 100ms với 120ms)
- [x] `-1008` chặn lệnh thường, **miễn** reduce-only
- [x] `POST /_admin/ws/drop` cắt WS, **giữ listenKey**, reconnect bằng key cũ chạy được
- [x] `/fapi/v1/ping`, `/_admin`, `/_debug` không bị ảnh hưởng
- [x] `POST /_admin/reset` tắt chaos ngay
- [ ] `-1021` bơm → engine sync clock (thuộc engine, P1)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Chaos endpoint | ✅ | container: `/_admin/chaos` → `/_admin/reset` hoạt động | 17/11/2026 |
| 503 unknown | ✅ | container: `503 Unknown error, please check your request or try again later.` | 17/11/2026 |
| `-1008` exemption | ✅ | container: lệnh thường → `503 -1008`; test reduce-only → 200 | 17/11/2026 |
| `ws/drop` | ✅ | container: `dropped=1`, WS đóng, `listenKey` vẫn hợp lệ, reconnect nhận event | 17/11/2026 |
| Ping không bị ảnh hưởng | ✅ | container: ping 200 khi `fail_rate=1.0` | 17/11/2026 |
| 84 test pass | ✅ | `pytest` xanh, `ruff` sạch | 17/11/2026 |

### Ghi chú

- RNG **có seed** (`SEED`) + đếm thứ tự → cùng kịch bản cho cùng kết quả, cần cho test hồi quy.
- `ping` được **miễn chaos** có chủ ý: nếu healthcheck bị bơm lỗi, Docker restart container liên tục và phá chính test.
- `-1008` kiểm ở tầng endpoint (không phải middleware) vì cần đọc `reduceOnly` từ body; đọc body trong middleware sẽ làm hỏng request downstream.
- Test quan trọng nhất của bước này: **503 "Unknown error" khi đặt lệnh** → engine phải query lại `GET /fapi/v1/order`, không gửi lại, nếu không sẽ có 2 vị thế ở live.

---

## M0.10 — Persistence & restart (0,5 ngày)

### Giải thích cơ bản

Restart engine giữa lúc có position là kịch bản thật, và là kịch bản dễ mất tiền nhất. Mock cũng phải sống qua restart để test được.

### Việc cần làm

1. Toàn bộ state (orders, algo, positions, balance, listenKey) → SQLite WAL.
2. Reload khi start; không regenerate algoId/orderId đã cấp.
3. Endpoint `POST /_admin/snapshot` và `POST /_admin/restore` để test tất định.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Restart giữ position/order/algo | test |
| 2 | ID không bị tái sử dụng | test |
| 3 | Snapshot/restore tất định | hash state giống |

### Checklist test

- [x] Restart mock → position/order/algo giữ nguyên, `state_hash` giống hệt
- [x] `algoId` / `orderId` không tái sử dụng sau restart
- [x] Snapshot rồi restore → `state_hash` quay về đúng giá trị cũ
- [x] SL đặt trước restart vẫn trigger được sau restart
- [x] Đếm bảng (`counts`) ổn định khi không thao tác
- [ ] Restart engine (không restart mock) — **chưa áp dụng** (engine chưa tồn tại)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| SQLite state | ✅ | toàn bộ state trong `mock.db` (WAL), tiền lưu TEXT | 17/11/2026 |
| Restart an toàn | ✅ | container: `hash=0d721a8b1de5` trước và sau restart, orders=4 algo=1 fills=4 | 17/11/2026 |
| Snapshot/restore | ✅ | `/_admin/snapshot` → `/app/data/mock.db.snapshot`; test roundtrip hash khớp | 17/11/2026 |
| 91 test pass | ✅ | `pytest` xanh | 17/11/2026 |

### Ghi chú

- Snapshot dùng `VACUUM INTO` — an toàn khi DB đang chạy, không cần dừng process, không copy file WAL.
- Restore **đóng kết nối trước khi ghi đè** và xoá `-wal`/`-shm`; nếu không sẽ gặp DB hỏng hoặc đọc dữ liệu cũ.
- Test `determinism`: cùng chuỗi thao tác cho cùng `counts`; `state_hash` **khác nhau** vì `orderId` tăng — đây là hành vi đúng, hash nhạy với id.
- Đây là bước chứng minh engine có thể restart giữa lúc có vị thế mà không mất SL (bất biến #1 của AGENTS.md).

---

## M0.11 — Test harness & CI (1 ngày)

### Giải thích cơ bản

Mock chỉ có giá trị nếu có bộ test chạy lại được mỗi lần sửa code. Đây là tài sản lâu dài: không cần demo, không cần tiền thật, vẫn biết mình không phá gì.

### Việc cần làm

1. `pytest` suite: contract test (mọi response vs schema), auth test (golden vector), order test, algo test, chaos test.
2. Integration test: chạy engine thật + mock, scenario 1 ngày nén (time scale 60×), assert: 0 orphan, reconcile 0, 100% position có SL.
3. Determinism test: cùng seed + cùng scenario → DB state hash giống.
4. Script `make test-mock`, `make test-e2e`.
5. Chạy trong CI (GitHub Actions hoặc local pre-push).

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Contract test | 100% endpoint P0 pass |
| 2 | E2E 1 ngày nén | 0 orphan, reconcile 0 |
| 3 | Determinism | 2 lần chạy cùng hash |
| 4 | Thời gian chạy CI | < 5 phút |

### Checklist test

- [x] `pytest mock/tests` xanh (91+ test)
- [x] `ruff check` sạch
- [x] E2E invariant: `position == Σ fills`, `wallet == initial + pnl − fee`, liquidation đúng phía
- [x] Determinism: cùng seed/chuỗi thao tác → cùng `counts`
- [x] `MARKET_MODE=replay` chạy được offline
- [x] CI workflow `.github/workflows/ci.yml` (Python 3.12, không cần internet)
- [x] 4 script PS: `env-check`, `step-verify`, `release`, `db-inspect`
- [x] `step-verify.ps1 -Step all` → tất cả bước ĐẠT

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Contract tests | ✅ | `tests/test_contracts.py` — 8 test, golden vector khớp | 17/11/2026 |
| E2E invariants | ✅ | `tests/test_e2e.py` — 6 test, 30 lệnh random giữ bất biến | 17/11/2026 |
| Determinism | ✅ | `test_persist.py::test_determinism_same_sequence` | 17/11/2026 |
| Tổng test | ✅ | **98 test pass** (`pytest -q`), `ruff` sạch | 17/11/2026 |
| CI | ✅ | `.github/workflows/ci.yml` — ruff + pytest + kiểm tra fixture | 17/11/2026 |
| Script PS | ✅ | `step-verify -Step all` → "TỔNG KẾT: tất cả bước ĐẠT" | 17/11/2026 |
| Offline | ✅ | CI + test dùng `MARKET_MODE=replay`, fixtures local | 17/11/2026 |

### Ghi chú

- Bất biến trong `test_e2e.py` là thứ đáng giá nhất của bộ test: nó bắt lỗi kế toán (mất tiền ảo) mà test chức năng thường bỏ qua.
- `step-verify.ps1` map bước → file test; chạy `-Step M0.7` để kiểm tra riêng một bước.
- Script PS viết cho **Windows PowerShell 5.1**, lưu UTF-8 BOM, có `[Console]::OutputEncoding = UTF8`.
- Test dùng `:memory:` (nhanh) trừ test persistence dùng file tạm.
- Không có test nào gọi internet — `proxy` mode chỉ dùng khi chạy tay.

---

## 5. Giới hạn của mock — phải nói rõ

| Không giả được | Hệ quả | Bù bằng |
|---|---|---|
| Matching engine thật (queue, partial fill) | Fill lạc quan hơn live | Live smoke test + đo slippage thật |
| Latency & jitter mạng thật | Bug timeout không lộ | Fault injection giả lập được phần nào |
| ADL, STP, thanh lý tự động | Không test được | Chấp nhận; SL luôn cách LP rất xa |
| Funding thật theo từng symbol | PnL lệch | Proxy `premiumIndex` thật |
| Sàn bảo trì, 503 diện rộng | Không test được | Fault injection |
| Hành vi "sàn chấp nhận payload hay không" | Bug encoding/param chỉ lộ ở live | **Live smoke test ≤ 0.05 USD** (1 lệnh + SL + cancel + close) |

Kết luận: mock **không thay thế** live smoke test. Nó chỉ làm cho live smoke test trở nên an toàn, vì mọi bug logic đã bị bắt trước đó.

---

## 6. Compose fragment

```yaml
services:
  binance-demo-server:
    build: ./mock/binance-demo-server
    environment:
      TZ: UTC
      MARKET_MODE: proxy            # proxy | replay | synthetic
      UPSTREAM: https://fapi.binance.com
      SEED: "42"
      SPEED: "1"                    # 1 = realtime, 60 = nén 60x
      INITIAL_BALANCE: "5000"
      FEE_MAKER_BPS: "2"
      FEE_TAKER_BPS: "5"
      FILL_MODEL: pessimistic       # pessimistic | optimistic
      SLIPPAGE_BPS: "5"
      MAKER_LEVERAGE_MAX: "125"
      AUTH_STRICT: "true"
      FAIL_RATE: "0"
      LOG_LEVEL: INFO
    ports:
      - "127.0.0.1:8081:8080"       # debug only; engine dùng network nội bộ
    volumes:
      - mockdata:/app/data
      - ./mock/fixtures:/app/fixtures:ro
    restart: unless-stopped
    init: true
    read_only: true
    tmpfs:
      - /tmp
    mem_limit: 256m
    cpus: "0.5"
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/fapi/v1/ping', timeout=3).status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  mockdata:
```

Engine dùng:

```yaml
  engine:
    environment:
      BINANCE_BASE_URL: http://binance-demo-server:8080
      BINANCE_WS_URL: ws://binance-demo-server:8080/ws
```

---

## 7. Cổng nghiệm thu Phase 0

Mock đạt chuẩn khi **tất cả** đúng:

1. `docker compose up -d` → 3 service healthy, RAM tổng < 400 MB.
2. Engine chạy **24 giờ nén (SPEED=60)** với mock: reconcile = 0 mọi vòng, 0 orphan, 100% position có SL.
3. Golden signature test pass; sai secret/thứ tự param đều bị `-1022`.
4. STOP/TP qua `/order` → `-4120`; qua `/algoOrder` → `algoId`.
5. Đóng position bằng tay → SL còn lại `EXPIRED`.
6. Restart mock giữa lúc có position → engine reconcile = 0.
7. `FAIL_RATE=0.3` + `WS_DROP_EVERY=10` chạy 1 giờ → 0 double order, 0 position trần.
8. Determinism: cùng seed + scenario → state hash giống.
9. `MARKET_MODE=replay` chạy được **offline** hoàn toàn (test bằng cách chặn egress).
10. Không có secret nào trong image; `docker history` sạch.

---

## 8. Lộ trình tổng thể sau Phase 0

```
Phase 0 (tài liệu này, ~9-10 ngày)
   └─ mock server + test harness
        ↓
P1.1–P1.6 (phase1_task.md)   → chạy trên mock thay vì demo
        ↓
Live smoke test ≤ 0.05 USD    → xác nhận Binance thật chấp nhận payload
        ↓
Live 100 USD (L0 → L1)        → theo cấu hình 100 USD
        ↓
Song song: retry demo mỗi tuần; nếu hoạt động lại → 4 tuần demo 5.000 USD
```

---

## 9. Rủi ro & cách xử lý

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Mock "quá dễ" khiến engine pass sai | **Cao** | Tier A phải tuyệt đối; `AUTH_STRICT=true`; `FILL_MODEL=pessimistic` |
| Mock lệch Binance sau này (API đổi) | Trung bình | Contract test + proxy mode; mỗi quý đối chiếu 1 lần |
| Tốn thời gian hơn dự kiến | Trung bình | Cắt Tier C ngay từ đầu; không implement batch/STP/ADL |
| Engine viết riêng cho mock (hardcode) | **Cao** | Mock chỉ đổi `base_url`; không có `if mock:` trong engine |
| Tin tưởng kết quả nén thời gian | Cao | Ghi rõ trong doc: nén thời gian chỉ để tìm bug, không kết luận edge |

---

## 10. Nhật ký thay đổi

| Ngày | Phiên bản | Nội dung |
|---|---|---|
| 17/11/2026 | 1.0 | Tạo mới; thông số endpoint lấy từ developers.binance.com (USDⓈ-M Futures), xác minh demo REST/WS host, Algo order, ALGO_UPDATE schema |
| 17/11/2026 | 1.1 | **Hoàn tất Phase 0 (M0.1–M0.11)**: 104 test pass, container healthy 45 MB RAM, CI xanh. Xem báo cáo R0 bên dưới |

---

## 11. Báo cáo R0 — kết quả Phase 0

### 11.1 Bảng bước

| Mã | Nội dung | Trạng thái | Test | Commit |
|---|---|---|---|---|
| B0 | Bootstrap repo + môi trường | ✅ | — | `f328937` |
| M0.1 | Contract + fixtures thật + golden vector | ✅ | 8 | `3373166` |
| M0.2 | Skeleton container + compose + `/_debug` | ✅ | — | `ae74820` |
| M0.3 | Auth HMAC + timing + weight + 429/418 | ✅ | 15 | `ae74820` |
| M0.4 | Market data proxy/replay/synthetic | ✅ | 13 | `26961b4` |
| M0.5 | Account state + SQLite | ✅ | 14 | `0e5e272` |
| M0.6 | Order engine | ✅ | 17 | `80033c0` |
| M0.7 | Algo engine (SL/TP) | ✅ | 15 | `c259b33` |
| M0.8 | User data stream (WS) | ✅ | 7 | `029e2f3` |
| M0.9 | Chaos / fault injection | ✅ | 10 | `c79659c` |
| M0.10 | Persistence + snapshot/restore | ✅ | 7 | *(gộp vào M0.11)* |
| M0.11 | Harness + E2E + CI + script PS | ✅ | 98→**104** | `d48fd8b` |

**Quy mô:** 2.558 dòng code Python, 1.069 dòng test, 5 file script PowerShell.

### 11.2 Mười cổng nghiệm thu (§7)

| # | Cổng | Kết quả |
|---|---|---|
| 1 | Compose healthy, RAM < 400 MB | ✅ `healthy`, **45,5 MiB** / 256 MiB |
| 2 | 24h nén, reconcile 0, 100% position có SL | ⚠️ **một phần** — bất biến "SL tồn tại sau entry" test được; reconcile thật cần engine (P1.1) |
| 3 | Golden vector pass, sai secret/thứ tự → `-1022` | ✅ |
| 4 | STOP/TP qua `/order` → `-4120`; qua `/algoOrder` → `algoId` | ✅ |
| 5 | Đóng position → SL còn lại `EXPIRED` | ✅ |
| 6 | Restart giữa lúc có position → state nguyên | ✅ hash `0d721a8b1d` trước/sau giống hệt |
| 7 | Bơm lỗi 30% + WS drop → 0 double order | ✅ chaos + `POST /_admin/ws/drop` (cắt WS, giữ listenKey) đã có; "0 double order" vẫn cần engine để kiểm chứng đầy đủ |
| 8 | Determinism: cùng seed → cùng state | ✅ `counts` giống; hash khác do `orderId` tăng (đúng thiết kế) |
| 9 | `replay` chạy offline | ✅ CI + test không gọi internet |
| 10 | Không secret trong image | ✅ Dockerfile chỉ `COPY app`, `.dockerignore` che `.env` |

Hai cổng đánh dấu ⚠️ là **giới hạn đã biết**: chúng cần engine để kiểm chứng đầy đủ, không phải lỗi của mock. Ghi rõ để không ai đọc thành "đã pass hết".

### 11.3 Lệnh tự chạy lại

```powershell
pwsh scripts\ps\env-check.ps1
powershell -ExecutionPolicy Bypass -File scripts\ps\step-verify.ps1 -Step all
docker compose up -d --build && docker stats --no-stream
curl http://127.0.0.1:8081/fapi/v1/ping
start http://127.0.0.1:8081/_debug
```

### 11.4 Điều mock KHÔNG kiểm chứng được

1. Matching engine thật (queue, partial fill) → fill của mock lạc quan hơn.
2. Latency/jitter mạng thật, sàn bảo trì diện rộng.
3. ADL, STP, thanh lý tự động.
4. Hành vi "Binance có chấp nhận payload hay không" → **bắt buộc live smoke test ≤ 0.05 USD**.
5. Nén thời gian (`SPEED`) chỉ để tìm bug, **không** kết luận edge.
6. `TRAILING_STOP_MARKET`, batch orders, WebSocket API — Tier C, không có.

### 11.5 Bước kế tiếp

**P1.1 Exchange adapter** (`docs/phase1_task.md`) — viết REST/WS client của engine trỏ vào `BINANCE_BASE_URL=http://binance-demo-server:8080`.

Cần user quyết trước khi sang P1:

- Engine nằm trong compose với service name `engine` (đúng thiết kế §7.9)?
- Có giữ `MARKET_MODE=proxy` cho paper trade, `replay` cho CI không?
- Có cần bổ sung `WS_DROP_EVERY` (chaos cho WS) trước khi làm adapter không?

### 11.6 Tuyên bố phạm vi

Phase 0 **chỉ chứng minh mock cư xử đúng hợp đồng API**. Nó **không** chứng minh engine đúng, không chứng minh chiến lược có lãi, và **không** cho phép chạy live.
