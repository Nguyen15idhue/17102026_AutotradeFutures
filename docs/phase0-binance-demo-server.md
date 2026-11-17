# PHASE 0 — BINANCE DEMO SERVER (MOCK)

**Kế hoạch triển khai container `binance-demo-server`**
Phiên bản: 1.0 · Ngày: 17/11/2026
Nguồn tham chiếu: `https://developers.binance.com/en/docs/products/derivatives-trading-usds-future` (mirror đọc được: `developers.binance.info/legacy-docs/...`)
Liên quan: `docs/mvp-binance-futures-bot.md` §7.9, `docs/phase1_task.md` P1.1/P1.3

---

## 0. Giải thích cơ bản

### 0.1 Vì sao cần container này

Demo Trading của Binance **hỏng ở khâu tạo API key** và `testnet.binancefuture.com` đã bị gộp về `demo.binance.com` (redirect) ⇒ không còn môi trường ảo chính thức nào dùng được.

Nhưng bot **không cần** Binance thật để phát triển. 95% code là: ký request, đặt lệnh, quản lý state, đặt SL, reconcile, restart, alert. Tất cả những thứ đó test được với một **server giả lập chạy cùng Docker network**.

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
| REST testnet/demo | `https://demo-fapi.binance.com` |
| WS live (market) | `wss://fstream.binance.com` |
| WS testnet/demo | `wss://demo-fstream.binance.com` |
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

- [ ] `docker compose up -d binance-demo-server` → healthy
- [ ] `curl 127.0.0.1:8081/fapi/v1/ping` → `{}`
- [ ] `curl .../fapi/v1/time` → `serverTime` cùng giây với host
- [ ] Engine trỏ vào mock, log không có lỗi kết nối
- [ ] `docker stats` RAM < 200 MB sau 1 giờ

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Container healthy | ⬜ Chưa | | |
| Env override ở engine | ⬜ Chưa | | |
| RAM < 200 MB | ⬜ Chưa | | |

### Ghi chú

- Port: mock dùng 8080 **bên trong**, map ra 8081 **bên ngoài** để không đụng dashboard.
- Đừng mount Docker socket, không `privileged`, không `network_mode: host`.

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

- [ ] Golden signature → 200
- [ ] Sai secret → `-1022`
- [ ] Sai thứ tự param → `-1022`
- [ ] `timestamp` lệch 10s → `-1021`
- [ ] recvWindow = 1 → `-1021` (giả lập delay)
- [ ] Key sai → `-2015`
- [ ] Gọi 2401 weight → 429 + `Retry-After`
- [ ] Tiếp tục gọi sau 429 → 418

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| HMAC verify | ⬜ Chưa | | |
| Timing check | ⬜ Chưa | | |
| Weight/order header | ⬜ Chưa | | |
| 429/418 | ⬜ Chưa | | |

### Ghi chú

- `signature` **không** được nằm trong chuỗi ký. Đây là lỗi phổ biến nhất khi tự implement.
- Param rỗng phải bị loại khỏi chuỗi ký (giống Binance) — test riêng case `price=`.

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

- [ ] `/klines` 3 mode → cùng key set
- [ ] `replay` chạy 2 lần → hash giống
- [ ] `synthetic` seed 42 → chuỗi giá giống ở 2 lần
- [ ] `jump_prob=0.05` → tạo được cú nhảy > 2% (test crash)
- [ ] Cache: đo số request upstream
- [ ] `/premiumIndex` có `markPrice` + `nextFundingTime`

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Proxy | ⬜ Chưa | | |
| Replay | ⬜ Chưa | | |
| Synthetic | ⬜ Chưa | | |
| Cache TTL | ⬜ Chưa | | |

### Ghi chú

- `proxy` mode là **rủi ro phụ thuộc**: nếu Binance đổi field, mock đổi theo. Vì vậy `replay` mới là chế độ dùng cho CI.
- Mark price phải khác last price một chút (0,02–0,05%) để test `workingType=MARK_PRICE` thật sự có ý nghĩa.

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

- [ ] Balance ban đầu = 5000
- [ ] Mở 0,01 BTC long → isolatedWallet = notional/leverage
- [ ] Mark tăng 1% → uPnL = +notional×1%
- [ ] Short: mark tăng 1% → uPnL âm
- [ ] `availableBalance` giảm đúng bằng margin
- [ ] Restart → balance/position giữ nguyên

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Balance/account | ⬜ Chưa | | |
| PositionRisk | ⬜ Chưa | | |
| Persist | ⬜ Chưa | | |

### Ghi chú

- Ghi rõ công thức trong `mock/README.md`: nếu không, sau này không ai biết "số này từ đâu ra".

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

- [ ] Market BUY 0,01 BTC → position 0,01, balance giảm phí
- [ ] LIMIT không khớp → nằm trong `openOrders`
- [ ] DELETE lệnh đó → status CANCELED
- [ ] DELETE lần 2 → `-2011`
- [ ] Qty 0.0001 BTC (dưới step 0,001) → `-4023` (hoặc `-1111`)
- [ ] Notional 3 USDT → `-4164`
- [ ] STOP_MARKET qua `/order` → `-4120`
- [ ] Trùng `newClientOrderId` → lỗi, 1 lệnh duy nhất
- [ ] Đóng position → realized PnL đúng, `availableBalance` về đúng

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Order CRUD | ⬜ Chưa | | |
| Filter validation | ⬜ Chưa | | |
| Fill + position + fee | ⬜ Chưa | | |
| Idempotency | ⬜ Chưa | | |

### Ghi chú

- `fill_model: pessimistic` là mặc định — nếu optimistic, test của bạn sẽ lạc quan hơn live và đó chính là bẫy §3.7.
- Slippage 5 bps mặc định; cho phép override bằng env để test slippage xấu (30 bps).

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

- [ ] Đặt STOP_MARKET closePosition → `algoId`, status NEW
- [ ] Giá chạm trigger → position đóng, status FINISHED
- [ ] TP_SELL khi giá ≥ trigger → khớp
- [ ] STOP_BUY (short) khi giá ≥ trigger → khớp
- [ ] Đóng position bằng tay → SL còn lại EXPIRED
- [ ] `closePosition` + `quantity` → lỗi param
- [ ] `priceProtect` + mark lệch xa → không trigger
- [ ] `GET /openAlgoOrders` phản ánh đúng ngay sau mỗi thao tác
- [ ] Restart → algo order còn nguyên

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Algo CRUD | ⬜ Chưa | | |
| Trigger 4 chiều | ⬜ Chưa | | |
| closePosition | ⬜ Chưa | | |
| EXPIRED khi flat | ⬜ Chưa | | |

### Ghi chú

- Đây là chỗ engine dễ mất tiền nhất ở live. Mock phải bắt được lỗi "SL đặt nhưng không bao giờ trigger vì sai chiều".
- `-4120` chỉ trả ở `/order`; nếu mock trả `-4120` ở `/algoOrder` thì engine sẽ không bao giờ test được happy path.

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

- [ ] Fill → `ORDER_TRADE_UPDATE` với `X=FILLED`, `ap`, `z`
- [ ] SL trigger → `ALGO_UPDATE` `X=FINISHED` + `ORDER_TRADE_UPDATE` fill
- [ ] `PUT listenKey` sai → `-1125`
- [ ] `listenKeyExpired` → engine tạo key mới, reconnect
- [ ] Kill mock giữa lúc có position → engine reconnect, reconcile đúng

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| listenKey lifecycle | ⬜ Chưa | | |
| 4 event types | ⬜ Chưa | | |
| Reconnect | ⬜ Chưa | | |

### Ghi chú

- WS user stream dùng path `/private/ws/<listenKey>` theo docs; nhưng engine nên cấu hình được path để mock có thể dùng `/ws/<listenKey>` đơn giản.

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

- [ ] `FAIL_RATE=0.2` → engine có retry, không mất lệnh
- [ ] 503 unknown → engine query order, không đặt trùng
- [ ] `-1008` với lệnh thường → fail; với `closePosition=true` → pass
- [ ] `WS_DROP_EVERY=10` → engine reconnect, reconcile
- [ ] `-1021` bơm → engine sync clock rồi retry

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Chaos endpoint | ⬜ Chưa | | |
| 429/418 | ⬜ Chưa | | |
| 503 unknown | ⬜ Chưa | | |
| -1008 exemption | ⬜ Chưa | | |

### Ghi chú

- Test quan trọng nhất ở đây: **503 "Unknown error" khi đặt lệnh** → engine phải query lại thay vì gửi lại. Nếu gửi lại, bạn sẽ có 2 vị thế ở live.

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

- [ ] Mở position + SL → restart mock → engine reconcile diff = 0
- [ ] Restart engine (không restart mock) → reconcile diff = 0
- [ ] Snapshot rồi restore → state hash giống
- [ ] `algoId` không trùng sau restart

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| SQLite state | ⬜ Chưa | | |
| Restart an toàn | ⬜ Chưa | | |
| Snapshot/restore | ⬜ Chưa | | |

### Ghi chú

- Không dùng `docker compose down -v` khi test restart; đó là lỗi của chính bạn, không phải của bot.

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

- [ ] `pytest mock/tests` xanh
- [ ] E2E: 1 ngày nén hoàn tất < 60s thực
- [ ] Hash state 2 lần chạy giống
- [ ] CI chạy trên clean clone
- [ ] Không cần internet khi `MARKET_MODE=replay`

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Contract tests | ⬜ Chưa | | |
| E2E nén thời gian | ⬜ Chưa | | |
| Determinism | ⬜ Chưa | | |
| CI | ⬜ Chưa | | |

### Ghi chú

- Time scale là tính năng bắt buộc: test 12 tuần demo trong vài phút thay vì chờ 3 tháng. Nhưng phải ghi rõ: **kết quả nén thời gian không dùng để kết luận edge**, chỉ để tìm bug.

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
