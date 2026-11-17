# MVP AUTO-TRADING BINANCE FUTURES

**Kế hoạch triển khai cho người mới (dân CNTT, chưa biết trading/bot)**

- Phiên bản: 1.7 (thêm service `binance-demo-server` giả lập USDⓈ-M Futures cho dev/test offline — xem `docs/phase0-binance-demo-server.md`)
- Lịch sử: 1.6 (chi phí thật: VPS tận dụng sẵn = 0; AI gate dùng GLM 5.3 Flash + DeepSeek V4 Flash ≈ 2–7 USD/tháng; tách tài liệu triển khai theo phase)
- Lịch sử: 1.5 (thêm margin_usage_max 60% + cảnh báo stop hẹp < 0,5%)
- Lịch sử: 1.4 (rà soát chéo: fix max positions demo 3→4; allocation shadow không tiêu budget; risk live 0,25% 4 tuần đầu; fee/slippage/recvWindow vào config; DASH_* vào .env; Telegram group outbound-only + .env.example)
- Lịch sử: 1.3 (portfolio risk demo 2,0% + 4 vị thế; bổ sung Docker Compose)
- Ngày: 17/11/2026
- Phạm vi: Binance USDⓈ-M Futures (USDT-M), perpetual
- Vốn demo: 5.000 USD (theo dõi ảo), vốn live: 300 USD
- Mục tiêu: **học + xác thực hệ thống**, không phải kiếm tiền nhanh

> **Miễn trừ trách nhiệm:** Tài liệu này là kế hoạch kỹ thuật và giáo dục, không phải lời khuyên đầu tư. Futures có đòn bẩy có thể mất toàn bộ vốn. Không có tham số nào trong tài liệu này đảm bảo lợi nhuận. Mọi con số hiệu năng là ví dụ toán học, không phải dự báo.

---

## Mục lục

1. [TL;DR — đọc 2 phút](#1-tldr--đọc-2-phút)
2. [Thực tế bạn đang bước vào](#2-thực-tế-bạn-đang-bước-vào)
3. [Kiến thức tối thiểu (từ số 0)](#3-kiến-thức-tối-thiểu-từ-số-0)
4. [Điều kiện tiên quyết và xác minh](#4-điều-kiện-tiên-quyết-và-xác-minh)
5. [Phạm vi MVP](#5-phạm-vi-mvp)
6. [Hai chiến lược của MVP](#6-hai-chiến-lược-của-mvp)
7. [Kiến trúc hệ thống](#7-kiến-trúc-hệ-thống)
8. [Lộ trình 12 tuần](#8-lộ-trình-12-tuần)
9. [Chạy demo 5.000 USD](#9-chạy-demo-5000-usd)
10. [Chạy live 300 USD](#10-chạy-live-300-usd)
11. [Quản trị rủi ro và vận hành](#11-quản-trị-rủi-ro-và-vận-hành)
12. [Chi phí](#12-chi-phí)
13. [KPI và cách đánh giá](#13-kpi-và-cách-đánh-giá)
14. [Kết quả kỳ vọng (thực tế)](#14-kết-quả-kỳ-vọng-thực-tế)
15. [Mở rộng sau MVP](#15-mở-rộng-sau-mvp)
16. [Sai lầm chết người](#16-sai-lầm-chết-người)
17. [Tài liệu tham khảo đã kiểm chứng](#17-tài-liệu-tham-khảo-đã-kiểm-chứng)
18. [Phụ lục](#18-phụ-lục)

---

# 1. TL;DR — đọc 2 phút

**Bạn sẽ xây gì:** một bot Python chạy trên VPS, giao dịch 10–15 coin thanh khoản cao trên Binance Futures, dùng 2 chiến lược đơn giản được "cổng chế độ thị trường" (regime gate) chọn lựa, với **SL cứng luôn tồn tại**, rủi ro **0,5%/lệnh**, đòn bẩy tối đa **3x**.

**Bạn sẽ không xây gì:** AI dự đoán giá, grid, martingale, 30 chiến lược, UI phức tạp, trading trong lúc thị trường hỗn loạn. Dashboard chỉ là **1 trang Node.js read-only + kill switch**.

**Thời gian thực tế:** MVP ~12 tuần (6 code + 4 demo + 2 live nhỏ); thêm Trend Pullback +10 tuần (4 shadow + 4 demo + 2 chuẩn bị). Part-time 15 giờ/tuần.

**Đóng gói:** Docker Compose ngay từ ngày đầu — 2 service (`engine` Python, `dashboard` Node), SQLite trên named volume, secrets qua `.env` (không bake vào image).

**Kỳ vọng thực tế:** 3 tháng đầu **hòa đến lỗ nhỏ**. Mục tiêu đúng là: (1) hệ thống không sập, (2) số liệu khớp backtest, (3) bạn hiểu từng lệnh bot làm, (4) không bao giờ để vị thế không có SL.

**Ba quy tắc bất biến:**

1. **Không có vị thế nào tồn tại mà không có SL** (kể cả 300ms).
2. **Rủi ro mỗi lệnh ≤ 0,5% vốn; đòn bẩy ≤ 3x.**
3. **CRISIS = không mở lệnh mới.** Không cố gắng "bắt đáy".

**Con số quan trọng nhất cần nhớ:** phí round-trip của bạn là **0,07%–0,10% notional**. Nếu stop của bạn rộng 0,6% notional, phí đã ăn **12–17% của mỗi R**. Đây là lý do phải trade ít, chọn lọc, và dùng maker entry.

---

# 2. Thực tế bạn đang bước vào

## 2.1 Futures không phải "hold có đòn bẩy"

Hold spot: bạn sở hữu coin, lỗ tối đa là 100% vốn, không có hạn chót.

Futures perpetual:

- Bạn mở **hợp đồng**, không sở hữu coin.
- Có **funding** trả/nhận mỗi 8 giờ nếu giữ vị thế.
- Có **thanh lý (liquidation)**: giá đi ngược đủ xa thì vị thế bị đóng, mất margin.
- Phí giao dịch tính trên **notional** (giá trị hợp đồng), không phải margin.
- Đòn bẩy làm cả lãi và lỗ phóng đại, và làm phí/ funding phóng đại theo.

## 2.2 Vì sao đa số bot retail thua

Không phải vì "chiến lược dở", mà vì 5 thứ mang tính cấu trúc:

1. **Phí + slippage**: mỗi vòng lệnh mất 0,07–0,15% notional. Trade 20 lần/tuần là mất 0,9–2,5%/tuần nếu không có edge đủ lớn.
2. **Đòn bẩy quá cao**: liquidation xảy ra trước khi chiến lược kịp đúng.
3. **Không có SL cứng**: một cú gap xóa nhiều tháng lãi.
4. **Overfit**: tối ưu tham số trên quá khứ, chết ở tương lai.
5. **Lỗi vận hành**: mất WebSocket, lệnh mồ côi, lệch vị thế, restart giữa lệnh.

Bot của bạn phải được thiết kế để **sống sót qua cả 5 thứ trên**, trước khi nói đến lợi nhuận.

## 2.3 Demo khác live ở đâu

Binance Demo Trading cho bạn tiền ảo và API riêng, nhưng:

- Chart, order book và **cách khớp lệnh có thể khác live** (Binance nói rõ trong FAQ).
- Demo **không có export** lịch sử → bot phải tự ghi log/DB.
- Fill trong demo thường **lạc quan hơn** live, đặc biệt với limit order.
- Không có cảm xúc, không có slippage thật, không có sự cố mạng thật.

→ Demo dùng để **kiểm tra plumbing và kỷ luật**, không dùng để kết luận "sẽ lãi".

## 2.4 Định nghĩa thành công của MVP

MVP **thành công** nếu sau 4 tuần demo + 8 tuần live nhỏ:

- Không có sự cố mất kiểm soát (không orphan order, không vị thế trần).
- Drawdown nằm trong giới hạn đã định.
- Expectancy không âm rõ rệt sau phí.
- Bạn giải thích được **tại sao** từng lệnh được mở/đóng.
- Bạn sẵn sàng chạy tiếp mà không phải "sửa chiến lược mỗi ngày".
- Dashboard tắt không ảnh hưởng bot; dashboard **không thể** đặt lệnh.

MVP **thất bại** nếu: phải tăng vốn để cứu, phải đổi tham số liên tục, hoặc không dám để bot chạy qua đêm.

---

# 3. Kiến thức tối thiểu (từ số 0)

## 3.1 Sản phẩm và thuật ngữ nền

| Thuật ngữ | Nghĩa dễ hiểu |
|---|---|
| **Spot** | Mua/bán coin thật, sở hữu coin |
| **Futures** | Hợp đồng chênh lệch giá, có đòn bẩy, không sở hữu coin |
| **USDⓈ-M** | Futures ký quỹ bằng stablecoin (USDT/USDC), đây là thứ ta dùng |
| **Perpetual** | Hợp đồng không có ngày đáo hạn, thay bằng funding |
| **Notional** | Giá trị hợp đồng = giá × số lượng. Phí tính trên con số này |
| **Margin** | Tiền ký quỹ thực tế bị giữ |
| **Leverage** | Notional / margin. 3x nghĩa là margin 100 USD mở được 300 USD notional |
| **Long / Short** | Cược giá tăng / giảm |
| **Position** | Vị thế đang mở (khác với "order") |
| **Order** | Lệnh gửi lên sàn. Khớp xong thì order biến mất, chỉ còn position |
| **Reduce-only** | Lệnh chỉ được giảm vị thế, không được mở ngược |
| **Close-position** | Lệnh đóng toàn bộ vị thế tại thời điểm kích hoạt, tự khớp size hiện tại |

## 3.2 Các loại lệnh bạn sẽ dùng

| Loại | Công dụng | Ghi chú |
|---|---|---|
| `MARKET` | Khớp ngay | Luôn là taker, phí cao hơn, có slippage |
| `LIMIT` | Đặt giá mong muốn | Có thể là maker (phí thấp) nếu không khớp ngay |
| `LIMIT + GTX` (post-only) | Limit nhưng **hủy nếu sẽ khớp ngay** | Đảm bảo maker, nhưng có thể không khớp. Futures dùng `timeInForce=GTX` |
| `STOP_MARKET` | Kích hoạt market khi chạm giá | SL cứng. Đặt qua **Algo API** |
| `TAKE_PROFIT_MARKET` | Kích hoạt market khi chạm giá | TP. Đặt qua **Algo API** |
| `TRAILING_STOP_MARKET` | SL tự dời theo giá | Có `callbackRate` + `activationPrice`. MVP **không cần** |

**Quan trọng:** từ **09/12/2025**, Binance chuyển các lệnh điều kiện (`STOP`, `STOP_MARKET`, `TAKE_PROFIT`, `TAKE_PROFIT_MARKET`, `TRAILING_STOP_MARKET`) sang **Algo Service**. Gửi vào `POST /fapi/v1/order` sẽ nhận lỗi **`-4120 STOP_ORDER_SWITCH_ALGO`**. Phải dùng:

```
POST   /fapi/v1/algoOrder
GET    /fapi/v1/openAlgoOrders
GET    /fapi/v1/algoOrder
DELETE /fapi/v1/algoOrder
DELETE /fapi/v1/algoOpenOrders
```

User data stream báo bằng event `ALGO_UPDATE` (không phải `ORDER_TRADE_UPDATE`).

Ba hệ quả thực tế:

- **Không kiểm tra margin trước khi lệnh điều kiện kích hoạt** → SL có thể fail nếu balance cạn.
- **Không modify được lệnh điều kiện chưa kích hoạt** → muốn dời SL phải cancel + place.
- `GTE_GTC` giờ chỉ phụ thuộc **position**, không phụ thuộc open orders đối diện.

## 3.3 Margin, đòn bẩy, thanh lý

**Isolated** (khuyến nghị cho MVP): mỗi vị thế có margin riêng. Cháy vị thế chỉ mất margin của vị thế đó.

**Cross**: toàn bộ balance làm margin chung. Một vị thế xấu có thể quét sạch tài khoản.

Công thức liquidation (isolated, one-way, bậc 1, bỏ qua phí/funding):

```
Long:   LP = Entry × (1 − 1/L) / (1 − MMR)
Short:  LP = Entry × (1 + 1/L) / (1 + MMR)
```

Trong đó `L` = leverage, `MMR` = maintenance margin rate (BTC bậc 1 hiện ~0,4%; ETH ~0,5%; alt 1–2,5%; lấy chính xác từ `GET /fapi/v1/leverageBracket`).

Ví dụ long BTC entry 65.000, 3x, MMR 0,4%:

```
LP = 65.000 × (1 − 1/3) / (1 − 0,004)
   = 65.000 × 0,6667 / 0,996
   ≈ 43.500
```

Tức giá phải giảm ~33% mới bị thanh lý. Với 20x:

```
LP = 65.000 × 0,95 / 0,996 ≈ 62.000  (−4,6%)
```

Đây là lý do **3x, không phải 20x**.

Vài điểm cần biết:

- Thanh lý dùng **mark price**, không dùng last price.
- MMR tăng theo bậc notional; notional càng lớn, MMR càng cao.
- Công thức trên bỏ qua phí và funding; liquidation thực tế gần hơn một chút.
- **Không bao giờ để giá đến gần LP.** SL của bạn phải cách LP rất xa.

## 3.4 PnL, phí, funding

**PnL long** = (giá đóng − giá mở) × size.
**PnL short** = (giá mở − giá đóng) × size.
**ROE** = PnL / margin.

**Phí USDⓈ-M (Regular User, đã kiểm chứng 11/2026):**

- Maker: **0,02%**
- Taker: **0,05%**
- Giảm 10% nếu trả bằng BNB nằm trong ví Futures (maker 0,018%, taker 0,045%)
- Tính trên notional, không trên margin

**Funding:**

- Mặc định mỗi 8 giờ: 00:00, 08:00, 16:00 UTC.
- Base rate 0,01%/8h; nhiều hợp đồng cap ±2%; có hợp đồng chu kỳ khác.
- Chỉ trả/nhận nếu đang giữ vị thế tại thời điểm snapshot.
- Funding dương: long trả short. Âm: short trả long.
- Binance không thu phí funding.

**Slippage:** chênh lệch giữa giá bạn thấy và giá khớp. Market order trong biến động có thể trượt 0,05–0,3%. Stop-market cũng bị.

**Spread:** chênh bid/ask. Coin thanh khoản tốt: 0,5–2 bps. Coin kém: 5–20 bps → phải loại khỏi universe.

## 3.5 Chỉ báo bạn sẽ dùng (và nguồn gốc)

| Chỉ báo | Công thức / cách dùng | Nguồn chuẩn |
|---|---|---|
| **ATR(14)** | Trung bình biên độ thật 14 nến | Wilder, *New Concepts in Technical Trading Systems* (1978) |
| **ADX(14)** | Độ mạnh xu hướng, 0–100 | Wilder (1978): ADX > 25 = trend mạnh, < 20 = yếu/không trend |
| **EMA(20/50/200)** | Trung bình động hàm mũ | Dùng phổ biến; EMA50/200 là chuẩn trend filter |
| **Bollinger Bands (20, 2σ)** | Mid ± 2 độ lệch chuẩn | John Bollinger, *Bollinger on Bollinger Bands* (2001) |
| **BB Width** | (Upper − Lower) / Mid | Bollinger; **squeeze** = bandwidth ở đáy nhiều tháng |
| **z-score** | (giá − trung bình) / độ lệch chuẩn | Thống kê chuẩn; ±2σ ≈ 95% |
| **RSI(2)** | RSI chu kỳ 2 | Connors & Alvarez, *Short Term Trading Strategies That Work* (2008) — dùng cho cổ phiếu daily, **phải adapt** khi dùng crypto 15m |
| **Volume z-score** | Volume hiện tại lệch bao nhiêu σ so với trung bình | Chuẩn thống kê |
| **OI (Open Interest)** | Tổng hợp đồng đang mở | Binance `GET /fapi/v1/openInterest` |
| **Funding rate** | Lãi suất funding hiện tại/dự kiến | Binance `GET /fapi/v1/premiumIndex` |

**Lưu ý trung thực:** các nguồn trên là nguồn gốc của *khái niệm và ngưỡng*, không phải bằng chứng chiến lược có lãi trên crypto 15m. Bạn **bắt buộc** phải walk-forward để xác thực.

## 3.6 Regime thị trường

MVP dùng 5 nhãn:

| Nhãn | Điều kiện (15m) | Hành động |
|---|---|---|
| `RANGE` | ADX < 20; range 24h < 2,5×ATR; vol percentile 20–60; BBW percentile > 15 | Bật Mean Reversion |
| `SQUEEZE` | BBW percentile ≤ 20 (90 ngày); range 24h < 1,5×ATR; volume giảm | Bật Squeeze Breakout |
| `TREND` | ADX > 22; EMA50 > EMA200; cấu trúc HH/HL | MVP: **không trade** (dành cho phase 3) |
| `CRISIS` | Cascade thanh lý; spread giãn > 3×; funding cực trị; correlation chéo → 1 | **Đóng lệnh yếu, không mở mới** |
| `UNKNOWN` | Thiếu dữ liệu / mâu thuẫn | Không làm gì |

Thêm **hysteresis**: cần 3 nến xác nhận nhãn mới + cooldown 5 nến, để tránh nhảy nhãn liên tục.

## 3.7 Backtest và các bẫy

| Khái niệm | Nghĩa | Bẫy nếu làm sai |
|---|---|---|
| **Look-ahead** | Dùng dữ liệu tương lai để ra quyết định | Kết quả đẹp giả tạo |
| **Fill model** | Giả định cách lệnh được khớp | Limit luôn khớp = backtest ảo |
| **Walk-forward** | Train 6 tháng → test 2 tháng → cuộn tiếp | Tối ưu trên toàn bộ dữ liệu = overfit |
| **Out-of-sample** | Dữ liệu chưa từng chạm | Bắt buộc có |
| **Survivorship bias** | Chỉ test coin còn sống | Bỏ qua coin đã delist |
| **Multiple testing** | Thử 100 bộ tham số, chọn cái tốt nhất | Gần như chắc chắn may mắn |

Quy tắc MVP: **đóng băng tham số trước khi chạy demo**, không sửa trong 4 tuần.

## 3.8 Mười hiểu lầm phổ biến (đã gặp trong quá trình thiết kế)

1. **"Trailing stop là SL"** → Không. Trước khi arm, nó không bảo vệ gì.
2. **"Đặt trailing là có bảo vệ"** → Không. Chưa chạm activation thì vị thế trần.
3. **"TP cũng dời theo giá"** → Không. TP cố định hoặc bỏ; dời TP lên mãi thì không bao giờ khớp.
4. **"Lệnh không khớp thì không mất tiền"** → Đúng, nhưng vị thế vẫn mở và vẫn lỗ được.
5. **"Đòn bẩy cao = lãi nhanh"** → Cũng là chết nhanh; liquidation đến trước chiến lược.
6. **"Demo lãi thì live cũng lãi"** → Không. Fill và slippage khác.
7. **"Nhiều chiến lược = đa dạng"** → Không. Cùng regime = cùng một cược.
8. **"Cứ có SL là an toàn"** → SL có thể trượt giá, có thể fail nếu margin cạn, có thể bị gap xuyên qua.
9. **"Bot chạy 24/7 là không cần giám sát"** → Sai. Cần watchdog, alert, reconcile.
10. **"AI đọc tin là đủ để trade"** → Không. AI chỉ nên là lớp phủ quyết, không phải trigger.

---

# 4. Điều kiện tiên quyết và xác minh

## 4.1 Checklist tài khoản

- [ ] Tài khoản Binance (KYC cho live; demo có thể không cần tùy khu vực).
- [ ] Bật Futures account cho live.
- [ ] Tạo **sub-account** riêng cho bot (live).
- [ ] Tạo API key **chỉ cho sub-account**, quyền: `Enable Futures`. **Tắt withdrawal.**
- [ ] Giới hạn IP (whitelist) = IP VPS.
- [ ] 2FA bật; không dùng email/password cho bot.
- [ ] Demo: vào `demo.binance.com` → API Management → tạo key demo riêng.

**Quy tắc bảo mật tuyệt đối:**

- API secret chỉ nằm trong biến môi trường hoặc secret manager. Không commit, không log.
- Key **không có quyền rút tiền**. Nếu sàn bị xâm nhập, thiệt hại tối đa là vốn trên futures account.
- Không dùng key live cho testnet/demo và ngược lại (key không tương thích).

## 4.2 Checklist môi trường

- [ ] Python 3.12 (khớp image `python:3.12-slim`; local 3.11+ cũng chạy được).
- [ ] Docker Engine 24+ và Docker Compose v2 (dev: WSL2 hoặc Docker Desktop; prod: Linux VPS).
- [ ] Named volume cho SQLite; bind mount chỉ cho `config/`.
- [ ] `.env` nằm ngoài git và ngoài image; `.dockerignore` có `.env`, `.git`, `data/`, `node_modules/`, `.venv/`.
- [ ] VPS gần Binance: Tokyo (`ap-northeast-1`) hoặc Singapore. 2 vCPU / 2–4 GB RAM là đủ.
- [ ] NTP sync (VPS thường có sẵn; kiểm tra offset < 1s).
- [ ] Thư viện: `httpx` hoặc `aiohttp`, `websockets`, `polars`/`pandas`, `duckdb` hoặc `sqlite`, `pydantic`, `pyyaml` (Telegram outbound-only chỉ dùng `httpx.post`, không cần `python-telegram-bot`).
- [ ] Git repo riêng, `.env` trong `.gitignore`; có `.env.example` chỉ chứa placeholder.
- [ ] `.env` trên VPS đủ: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DASH_USER`, `DASH_PASS` (không có giá trị thật trong repo/image/log).
- [ ] VPS mở được `https://api.telegram.org` (test `curl -I` trước, nếu chặn phải có proxy mới đi tiếp).
- [ ] Backup DB hàng ngày (SQLite `.backup`, không copy file WAL đang chạy).

## 4.3 Bảng xác minh kỹ thuật bắt buộc (Phase 0)

Làm **trước khi viết chiến lược**. Mỗi mục phải có kết quả thực tế, không tin tài liệu mù.

| # | Việc cần xác minh | Cách làm | Kỳ vọng / nguồn |
|---|---|---|---|
| 1 | Demo REST hoạt động | `GET https://demo-fapi.binance.com/fapi/v1/time` | Trả `serverTime` |
| 2 | Demo WS host | Kết nối thử `wss://demo-fstream.binance.com` và `wss://fstream.binancefuture.com` | Một trong hai nhận dữ liệu; ghi lại host đúng |
| 3 | Demo hỗ trợ Algo Order | `POST /fapi/v1/algoOrder` với `STOP_MARKET` size nhỏ | Trả `algoId`; nếu không, dùng testnet khác hoặc mô phỏng SL trong bot |
| 4 | Phí thực tế | `GET /fapi/v1/commissionRate` | ~0,02% maker / 0,05% taker |
| 5 | Min notional | `GET /fapi/v1/exchangeInfo` → filter `NOTIONAL`/`MIN_NOTIONAL` | Thường 5 USDT/symbol; có thể thay đổi |
| 6 | Tick/step | `exchangeInfo` → `PRICE_FILTER.tickSize`, `LOT_SIZE.stepSize` | Phải round đúng, nếu không lỗi `-4014`/`-4023` |
| 7 | Rate limit | Response header `X-MBX-USED-WEIGHT-1M` | 2.400 weight/phút/IP; 1.200 lệnh/phút; 300 lệnh/10s |
| 8 | Algo migration | Gửi `STOP_MARKET` vào `/fapi/v1/order` | Phải nhận `-4120` → dùng `/fapi/v1/algoOrder` |
| 9 | `closePosition` | Đặt SL `closePosition=true`, đóng position bằng market | Kỳ vọng SL còn lại tự hủy/expired; tài liệu công khai không mô tả rõ nên **phải kiểm tra** `openAlgoOrders` |
| 10 | `ALGO_UPDATE` | Đặt SL rồi theo dõi user stream | Nhận event `ALGO_UPDATE` |
| 11 | Data lịch sử | Tải 1 file từ `data.binance.vision` | URL dạng `/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-YYYY-MM-DD.zip` |
| 12 | Funding lịch sử | `GET /fapi/v1/fundingRate` | Có dữ liệu 8h |
| 13 | Liquidation bracket | `GET /fapi/v1/leverageBracket` | Có MMR theo bậc |

Nếu bất kỳ mục nào fail, **dừng lại xử lý**, không đi tiếp.

---

# 5. Phạm vi MVP

## 5.1 Trong phạm vi

| Hạng mục | Quyết định |
|---|---|
| Sàn | Binance USDⓈ-M Futures, one-way mode |
| Coin | 10–15 symbol thanh khoản cao nhất, review hàng tuần |
| Khung tín hiệu | 15m; dữ liệu 1m; context 1h |
| Chiến lược | Mean Reversion (RANGE) + Squeeze Breakout (SQUEEZE); Trend Pullback chỉ **shadow mode** trong demo |
| Exit | MR: TP cố định + SL cứng. Squeeze: SL cứng + trailing do bot dời |
| Risk/lệnh | 0,5% demo; 0,25–0,5% live |
| Đòn bẩy | 3x isolated |
| Số vị thế | Demo 4; live 2 |
| Portfolio risk (tổng risk mở) | Demo **2,0%**; live 1,0% |
| Kill switch | Daily −2%, weekly −4%, DD −6% |
| Logging | SQLite (WAL) + stdout (Docker log rotation) + Telegram alert (outbound-only vào 1 group) |
| AI | **Chưa có** (phase 2) |
| UI | Dashboard Node.js **read-only** + kill switch, 1 trang; **không đặt lệnh từ UI** |

## 5.2 Ngoài phạm vi (không làm)

- Grid, market making, scalping tick.
- Martingale, averaging down, "gồng lệnh".
- Trend Pullback **live**, funding carry, cross-sectional. (Trend Pullback **shadow** được phép từ demo — xem 15.2.)
- AI/LLM trong hot path.
- Tối ưu tham số theo từng coin.
- Chạy nhiều chiến lược trên cùng symbol.
- Withdraw tự động (không bao giờ).

## 5.3 Universe coin

Tiêu chí lọc (chạy hàng tuần):

- 24h quote volume > 100 triệu USD.
- Spread trung bình < 2 bps.
- Listed > 6 tháng.
- Không đang có sự kiện listing/delisting/pump.
- Tick size và step size đủ nhỏ so với size dự kiến.

Gợi ý 10 symbol khởi điểm: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT`, `DOGEUSDT`, `ADAUSDT`, `AVAXUSDT`, `LINKUSDT`, `SUIUSDT`.

**Cảnh báo tương quan:** các alt này tương quan rất cao với BTC. 4 vị thế long cùng lúc thực chất là 1 cược (portfolio risk demo cap 2,0%; live 1,0%). Risk engine phải có correlation cap.

---

# 6. Hai chiến lược của MVP

## 6.1 Vì sao chọn hai cái này

Chúng là hai mặt của cùng một cấu trúc:

- `RANGE`: giá đi trong hộp → **trade bên trong** (mean reversion).
- `SQUEEZE`: hộp bị nén và sắp nổ → **trade lúc phá hộp** (breakout).

Chúng không bao giờ chạy cùng lúc trên cùng symbol, nên không đánh nhau. Chúng phủ hai trạng thái phổ biến nhất của crypto, và mỗi cái có một cơ chế thoát phù hợp.

## 6.2 Regime detector — nền tảng chung

Tính trên nến 15m đã đóng:

```
atr       = ATR(14)
bb_mid    = SMA(close, 20)
bb_sd     = STDEV(close, 20)
bb_up     = bb_mid + 2*bb_sd
bb_dn     = bb_mid - 2*bb_sd
bbw       = (bb_up - bb_dn) / bb_mid
bbw_pct   = percentile_rank(bbw, 90 ngày)
adx       = ADX(14)
vol_pct   = percentile_rank(realized_vol_1h, 30 ngày)
range_24h = (highest(high, 96) - lowest(low, 96))
z         = (close - bb_mid) / bb_sd
range_pos = (close - lowest(low,96)) / (highest(high,96) - lowest(low,96))
```

Phân loại có thứ tự ưu tiên:

```
if crisis_conditions:            -> CRISIS
elif bbw_pct <= 20 and range_24h < 1.5*atr and volume_declining:
                                 -> SQUEEZE
elif adx < 20 and range_24h < 2.5*atr and 20 <= vol_pct <= 60 and bbw_pct > 15:
                                 -> RANGE
elif adx > 22 and ema50 > ema200:
                                 -> TREND
else:                            -> UNKNOWN
```

`crisis_conditions` gồm bất kỳ: spread > 3× trung bình 1h, có > 5 lệnh thanh lý lớn trong 1 phút, funding |rate| > 0,1%, hoặc BTC giảm > 4% trong 15 phút.

Hysteresis: nhãn mới phải giữ 3 nến liên tiếp; sau khi đổi nhãn, cooldown 5 nến không đổi lại.

**Quy tắc an toàn quan trọng nhất toàn hệ thống:**

> **Cấm mean-reversion khi `bbw_pct < 15`.**

Không có dòng này, MR sẽ fade đúng lúc hộp nén và bị breakout giết.

## 6.3 Mean Reversion trong RANGE

### Logic

Giá trong range có xu hướng quay về giữa. Mua ở biên dưới, bán ở giữa. Bán khống ở biên trên, mua lại ở giữa.

### Điều kiện vào

Tất cả phải đúng:

- Regime = `RANGE`.
- `z <= -2.0` (long) hoặc `z >= +2.0` (short).
- Nến 15m đóng **quay lại trong band** (không đóng ngoài band).
- `bbw_pct > 15`.
- Không trong blackout tin macro (±45 phút).
- Spread hiện tại < 2 bps.

### Vào lệnh

- **Limit post-only** tại `best_bid + 1 tick` (long) hoặc `best_ask − 1 tick` (short).
- TTL 2 nến; không khớp thì hủy. Không đuổi giá.
- Không vào nếu giá đã chạy quá 0,3×ATR kể từ lúc phát tín hiệu.

### Thoát

- **SL:** `range_low − 1.2×ATR` (long) / `range_high + 1.2×ATR` (short), `STOP_MARKET closePosition`, `workingType=MARK_PRICE`.
- **TP:** mid range (hoặc 0,7 quãng đường tới mid), `TAKE_PROFIT_MARKET closePosition`.
- **Time stop:** 12 nến không đạt 0,5R → đóng market.
- **Regime flip:** rời RANGE → đóng ngay.

### Vì sao hợp lý

- RANGE là regime phổ biến nhất (40–60% thời gian trên 15m).
- TP gần, SL chặt → nhiều lệnh, dễ đo.
- Khớp trực tiếp triết lý "chỉ trade khi yên tĩnh".
- Chỉ báo gốc: z-score (thống kê), RSI(2) (Connors), Bollinger (2001). Ngưỡng 2σ và RSI(2)<10 là quy ước phổ biến, **không phải bảo chứng lợi nhuận**.

### Điểm chết

- Range bị phá → lỗ liên tiếp. Bảo vệ: BBW > 15 và SL ngoài biên.
- Range quá hẹp → TP < phí. Bảo vệ: yêu cầu range_24h ≥ 1,5×ATR.
- Maker không khớp → bỏ lỡ. Chấp nhận, không đuổi.
- Funding xấu khi giữ lâu → time stop 12 nến.

### Ví dụ số

BTC 15m, range 64.000–66.000, ATR 250.

```
z = -2 tại giá 64.100
entry limit 64.150
SL  = 64.000 - 1.2*250 = 63.700   (rủi ro 450 = 0,70%)
TP  = 65.000                      (lợi 850 = 1,33% → R ≈ 1,9)
risk 0,5% của 300 USD = 1,5 USD
size = 1,5 / 450 ≈ 0,00333 BTC → làm tròn stepSize 0,001 → 0,003 BTC
notional ≈ 0,003 × 64.150 ≈ 192 USD
phí round-trip ~0,07% × 192 ≈ 0,13 USD (≈9% của R)
```

## 6.4 Squeeze Breakout

### Logic

Khi biến động nén hết mức, giá thường bùng nổ. Không đoán hướng; chờ nến xác nhận phá hộp, vào theo hướng phá, giữ bằng trailing.

### Điều kiện vào

Tất cả phải đúng:

- Regime = `SQUEEZE`.
- `bbw_pct <= 20` trong 90 ngày.
- Range 24 nến < 1,5×ATR.
- Volume 24 nến giảm dần (volume z < 0).
- Nến 15m đóng **ngoài hộp ≥ 0,2×ATR**.
- Volume nến phá > 1,5× trung bình 20 nến.
- Không blackout; spread < 2 bps.

### Vào lệnh

- Market tại open nến kế tiếp sau nến xác nhận (hoặc limit retest mép hộp).
- Chấp nhận taker phí vì payoff lớn.

### Thoát

- **SL ban đầu:** mép đối diện hộp, hoặc `1,5×ATR` từ entry (chọn cái gần hơn nhưng không dưới 1×ATR).
- **Trailing:** khi lãi ≥ 1×ATR, dời SL lên `đỉnh − 2×ATR` (long) / `đáy + 2×ATR` (short). Dời bằng **cancel + place**, make-before-break. **Không TP.**
- **Time stop:** 12 nến không follow-through → đóng (breakout thất bại).
- **Regime flip:** về RANGE/CRISIS → đóng.

### Vì sao hợp lý

- Bắt được chân sóng lớn — nguồn lợi nhuận đuôi dày.
- Không cần đoán hướng trước.
- Trailing 2N là khái niệm có nguồn: Turtle Trading dùng stop/exit 2N với N = ATR(20) (Faith, 2007). MVP dùng ATR(14) và 2×ATR; đây là **adaptation**, không phải nguyên bản.

### Điểm chết

- Fakeout (crypto rất hay) → lỗ nhỏ nhiều lần.
- Vào trễ sau khi giá đã chạy → R:R tệ.
- SL bị slippage trong cú nổ ngược.
- Win rate thấp (35–45%) → cần kỷ luật chịu chuỗi thua.

### Ví dụ số

BTC 15m, hộp 64.800–65.200, ATR 120, BBW percentile 6.

```
Nến phá đóng 65.260 (> 65.200 + 0,2*120 = 65.224)
volume 2,1× trung bình
entry market 65.270
SL = 64.800 (mép dưới) = 470 (0,72%)
risk 0,5% của 300 = 1,5 USD
size = 1,5 / 470 ≈ 0,00319 BTC → làm tròn 0,003 BTC
notional ≈ 196 USD
khi giá lên 66.470 (+1.200 = 1%): SL dời lên 66.470 - 2*120 = 66.230
```

## 6.5 Bảng tham số và nguồn

| Tham số | Giá trị MVP | Cơ sở | Ghi chú |
|---|---|---|---|
| ATR period | 14 | Wilder (1978) | Chuẩn phổ biến |
| ADX period / ngưỡng | 14 / 25 mạnh, 20 yếu | Wilder (1978) | MVP dùng 20/22 để phân loại |
| Bollinger | 20, 2σ | Bollinger (2001) | Chuẩn |
| BBW squeeze | percentile ≤ 20, 90 ngày | Khái niệm "Bollinger Squeeze" | Bollinger dùng đáy 6 tháng; MVP dùng 90 ngày |
| z-score entry | ±2,0 | Thống kê chuẩn (≈95%) | Có thể thử 1,8–2,2 |
| RSI(2) | <10 / >90 (tham khảo) | Connors & Alvarez (2008) | Adapt từ daily equity sang crypto 15m |
| Risk/lệnh | 0,5% | Van Tharp; Turtle 1–2% | MVP thận trọng hơn |
| Stop MR | 1,2×ATR ngoài biên | ATR-based, phổ biến | Đủ rộng để không bị wick |
| Trailing Squeeze | 2×ATR | Turtle 2N (Faith, 2007) | N của Turtle là ATR(20) |
| Time stop | 12 nến 15m (3 giờ) | Kinh nghiệm vận hành | Tránh lệnh treo vô hạn |
| Leverage | 3x | Tự đặt, thận trọng | Liquidation rất xa |
| Max positions | 2 live / 4 demo | Tự đặt | Demo 4×0,5% = portfolio 2,0%; live 2×0,5% = 1,0%; correlation cap |

> Các tham số này là **điểm khởi đầu có cơ sở**, không phải "cấu hình vàng". Mọi thay đổi phải qua walk-forward và ghi lại lý do.

---

# 7. Kiến trúc hệ thống

## 7.1 Sơ đồ

```
                    ┌─────────────────────────────┐
                    │        Binance Demo/Live     │
                    │  REST + WS (market + user)   │
                    └───────────┬─────────────────┘
                                │
                 ┌──────────────▼──────────────┐
                 │      Exchange Adapter        │
                 │  rate limit, sign, retry,    │
                 │  clock sync, idempotency     │
                 └──────────────┬──────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
┌───────▼────────┐     ┌────────▼────────┐      ┌────────▼────────┐
│  Data Plane    │     │  Order Router   │      │  Account State  │
│ 1m→15m/1h bars │     │ entry/exit      │      │ positions,      │
│ features       │     │ algo orders     │      │ orders, fills   │
│ funding, OI    │     │ OCO by bot      │      │ reconcile       │
└───────┬────────┘     └────────┬────────┘      └────────┬────────┘
        │                       │                        │
┌───────▼────────┐     ┌────────▼────────┐      ┌────────▼────────┐
│ Regime Engine  │     │  Risk Engine    │      │   Watchdog      │
│ RANGE/SQUEEZE  │     │ hard limits     │      │ stale data,     │
│ TREND/CRISIS   │     │ sizing, buckets │      │ orphan, mismatch│
└───────┬────────┘     └────────┬────────┘      └────────┬────────┘
        │                       │                        │
        └───────────┬───────────┴────────────┬───────────┘
                    │                        │
          ┌─────────▼─────────┐    ┌─────────▼─────────┐
          │ Strategy Engine   │    │  Ops / Reporting  │
          │ MR + Squeeze      │    │ logs, metrics,    │
          │ (+ Trend shadow)  │    │ Telegram group    │
          └─────────┬─────────┘    └─────────┬─────────┘
                    │                        │
                    └───────────┬────────────┘
                                │ write (Python = writer duy nhất)
                     ┌──────────▼──────────┐
                     │  SQLite WAL (truth) │
                     │  runtime_state,     │
                     │  positions, orders, │
                     │  signals, commands  │
                     └──────────┬──────────┘
                                │ read-only + poll 1s
                     ┌──────────▼──────────┐
                     │  Node.js Dashboard  │
                     │  HTTP + WS browser  │
                     │  read + kill switch │
                     └──────────┬──────────┘
                                │ WS push
                     ┌──────────▼──────────┐
                     │  Browser (1 trang)  │
                     └─────────────────────┘
```

**Ranh giới bất biến:** Python là bộ não duy nhất. Node.js **không** giữ API key, **không** đặt/hủy lệnh Binance, **không** tính size. Node chỉ đọc state và ghi `commands` (kill switch) để Python thực thi.

**Đóng gói:** toàn bộ sơ đồ trên chạy trong Docker Compose (2 service + 1 named volume). Xem 7.9.

## 7.2 Module và trách nhiệm

| Module | Trách nhiệm | Không được làm |
|---|---|---|
| `exchange/rest` | Gọi API có ký, rate limit, retry | Không chứa logic chiến lược |
| `exchange/ws` | Market stream + user stream, auto-reconnect, listenKey | Không quyết định lệnh |
| `exchange/orders` | Đặt/hủy lệnh, state machine, idempotency | Không tự tính size |
| `data/bars` | 1m → 15m/1h, gap fill, backfill | Không dùng nến chưa đóng |
| `data/features` | ATR, BB, ADX, z, vol, OI, funding | Không look-ahead |
| `regime` | Nhãn + hysteresis | Không phụ thuộc strategy |
| `risk` | Cap mọi thứ, sizing, blackout, global position manager (1 symbol = 1 chiến lược) | Không bị strategy bypass |
| `strategies` | Signal + exit policy | Không gọi API trực tiếp |
| `exec` | Entry, SL/TP, trailing, OCO-by-bot | Không bỏ qua risk |
| `watchdog` | Phát hiện bất thường, kill switch | Không phụ thuộc strategy |
| `ops` | Log, metric, alert Telegram group (outbound-only), report | Token/chat_id đọc từ env, không log secret |
| `db` | Python là writer duy nhất; WAL; snapshot `runtime_state` mỗi 1s | Không cho process khác ghi state giao dịch |
| `dashboard/` (Node) | Đọc DB, WS tới browser, ghi `commands` kill switch | **Không** đặt lệnh, không giữ API key, không tính size |

## 7.3 Bảng dữ liệu tối thiểu

| Bảng | Cột chính |
|---|---|
| `bars` | symbol, tf, open_time, o,h,l,c,v, closed |
| `features` | symbol, tf, ts, atr, adx, bbw, bbw_pct, z, vol_pct, range_24h |
| `regime` | symbol, ts, label, confidence |
| `signals` | id, strategy, symbol, side, ts, reason_json |
| `orders` | client_id, exchange_id, algo_id, strategy_id, type, side, qty, price, status |
| `fills` | order_id, strategy_id, ts, price, qty, fee, fee_asset |
| `positions` | symbol, strategy_id, side, qty, entry, sl, tp, opened_at, closed_at, pnl |
| `equity` | ts, strategy_id (nullable), balance, equity, unrealized |
| `runtime_state` | ts, mode, heartbeat, ws_ok, data_age_ms, equity, dd, kill_level |
| `commands` | id, ts, action, payload, status, acked_at |
| `shadow_trades` | strategy_id, symbol, ts, side, entry, exit, r_multiple, missed_reason |
| `events` | ts, level, module, message, context_json |
| `incidents` | ts, type, resolution, duration |

SQLite chạy **WAL mode**, `busy_timeout` 5s. Python là writer duy nhất. Node mở connection `readonly: true`. `runtime_state` được Python ghi mỗi 1s — đây là nguồn cho dashboard, không phải balance thật.

## 7.4 State machine của một vị thế

```
IDLE
 └─ signal → PENDING_ENTRY
      ├─ fill → OPEN (đặt SL ngay)
      └─ timeout/cancel → IDLE

OPEN
 ├─ TP fill → CLOSED
 ├─ SL fill → CLOSED
 ├─ time stop → CLOSING → CLOSED
 ├─ regime flip → CLOSING → CLOSED
 └─ profit >= threshold → TRAILING

TRAILING
 ├─ SL trail fill → CLOSED
 ├─ regime flip → CLOSING → CLOSED
 └─ position = 0 → CLOSED

CLOSED
 └─ cancel mọi conditional order còn lại, verify positionAmt = 0
```

**Bất biến:**

- Trong `OPEN` và `TRAILING`, **luôn có đúng 1 lệnh thoát active**.
- Không bao giờ có 2 lệnh `closePosition` cùng lúc trừ lúc make-before-break (~200ms).
- `CLOSED` chỉ đạt được khi `positionAmt == 0` **và** không còn algo order.

## 7.5 Quy tắc execution

### Entry

- MR: post-only limit, TTL 2 nến.
- Squeeze: market.
- `newClientOrderId` dạng `{strategy}-{symbol}-{ts}-{nonce}`.

### SL cứng

```
POST /fapi/v1/algoOrder
algoType=CONDITIONAL
symbol=BTCUSDT
side=SELL
type=STOP_MARKET
triggerPrice=63700
closePosition=true
workingType=MARK_PRICE
priceProtect=true
clientAlgoId=sl-...
```

- Đặt **ngay sau khi fill**, không chờ.
- `closePosition=true` để tự khớp size hiện tại (partial fill/ADL).
- Nếu API lỗi: retry 3 lần với backoff; nếu vẫn lỗi → **đóng vị thế bằng market** và alert. Không giữ vị thế trần.

### TP (MR)

Tương tự với `TAKE_PROFIT_MARKET closePosition`.

### Dời SL (trailing)

`STOP_MARKET` **không modify được**. Quy trình:

1. `POST` SL mới cao hơn (closePosition).
2. `DELETE` SL cũ.
3. Verify `openAlgoOrders` chỉ còn 1.

Đây là make-before-break: không có khoảnh khắc mất bảo vệ.

### Đóng khẩn cấp

- Market `reduceOnly` (one-way) hoặc `closePosition` qua `STOP_MARKET` trigger ngay.
- Sau đó `DELETE /fapi/v1/algoOpenOrders?symbol=...` để dọn.

### Reconcile

Mỗi 5–10 giây:

```
REST positionRisk + openAlgoOrders + openOrders
  so với state trong DB
  nếu lệch:
    - position lệch → HALT, alert
    - thiếu SL khi có position → đặt lại ngay
    - có order khi position = 0 → hủy, ghi incident
```

WS chỉ là tín hiệu tăng tốc; **REST là nguồn sự thật**.

## 7.6 Config mẫu

```yaml
# config/mvp.yaml
env: demo                      # demo | live (file config tách riêng mỗi env: mvp.demo.yaml / mvp.live.yaml)
base_url: https://demo-fapi.binance.com
equity_base: 5000              # demo: sổ ảo riêng, bất kể balance demo; live: 300 (file live ghi đè)

universe:
  symbols: [BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT,
            DOGEUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, SUIUSDT]
  min_quote_volume_24h: 100_000_000
  max_spread_bps: 2

timeframes:
  signal: 15m                  # MR + Squeeze
  data: 1m
  context: 1h
  trend_signal: 1h              # chỉ Trend Pullback (shadow trong MVP)
  trend_context: 4h

risk:
  risk_per_trade: 0.005         # demo; live 4 tuần đầu ghi đè 0.0025, sau đó 0.005 nếu pass review
  max_leverage: 3
  max_positions: 4              # demo; live ghi đè = 2
  daily_loss_limit: 0.02
  weekly_loss_limit: 0.04
  max_drawdown: 0.06
  portfolio_risk_max: 0.02      # demo 2,0%; live ghi đè 0.01 — risk engine chặn mở mới khi vượt, không trừ risk/lệnh
  max_correlated_risk: 0.02     # demo 2,0%; live ghi đè 0.01. Nhóm tương quan = return 1h 30 ngày corr > 0.8 với BTC
  blackout_minutes: 45
  stale_data_seconds: 3
  funding_close_bps: 10         # không giữ lệnh qua snapshot nếu |funding| > 0,1%, trừ khi trailing lãi > 1×ATR
  margin_usage_max: 0.60        # chặn mở mới khi Σ initial_margin + margin lệnh mới > 60% equity (TK nhỏ: margin cạn trước risk cap)
  narrow_stop_warn_pct: 0.005   # cảnh báo mềm khi stop% < 0,5% (notional > 2× vốn/lệnh): margin phình nhanh, slippage/R xấu đi

regime:
  atr_period: 14
  adx_period: 14
  bb_period: 20
  bb_std: 2
  bbw_lookback_days: 90
  hysteresis_bars: 3
  cooldown_bars: 5

strategies:
  allocation:                   # tổng risk budget = 1.0; chỉ áp cho mode live (shadow không tiêu budget)
    mean_reversion: 0.5
    squeeze_breakout: 0.3
    trend_pullback: 0.2         # chỉ có hiệu lực khi trend_pullback.mode: live; ở shadow thì budget = 0
  mean_reversion:
    enabled: true
    z_entry: 2.0
    stop_atr: 1.2
    tp: mid
    time_stop_bars: 12
    entry: post_only
    ttl_bars: 2
  squeeze_breakout:
    enabled: true
    bbw_pct_max: 20
    box_bars: 24
    buffer_atr: 0.2
    vol_mult: 1.5
    stop_atr: 1.5
    trail_atr: 2.0
    trail_after_atr: 1.0
    time_stop_bars: 12
    entry: market
  trend_pullback:
    enabled: true
    mode: shadow                # shadow | live
    allow_short: false          # chỉ bật sau khi long pass + shadow short dương
    timeframe: 1h
    ema_fast: 50
    ema_slow: 200
    adx_min: 22
    fib_min: 0.30
    fib_max: 0.618
    rsi_min: 40
    rsi_max: 55
    stop_atr: 1.5
    trail_atr: 2.0
    trail_after_atr: 1.5
    time_stop_bars: 36
    entry: market

execution:
  entry_ttl_bars: 2
  sl_working_type: MARK_PRICE
  price_protect: true
  reconcile_seconds: 5
  max_retries: 3
  recv_window_ms: 5000
  fee_bps_maker: 2             # 0,02%; backtest dùng đúng số này trừ khi commissionRate trả khác
  fee_bps_taker: 5             # 0,05%; BNB discount -10% chỉ áp khi bật trả phí bằng BNB
  slippage_bps: 5              # giả định bảo thủ cho backtest; đo lại bằng fills thực tế
  max_orders_per_day: 10        # demo; live ghi đè = 5 (risk engine là nguồn duy nhất enforce)

dashboard:
  enabled: true
  host: 127.0.0.1             # chỉ localhost; truy cập qua SSH tunnel
  port: 8080
  poll_ms: 1000
  auth: basic                 # user/pass đọc từ DASH_USER / DASH_PASS trong .env, không hardcode
  allowlist_commands: [pause, resume, flatten, stop]   # server.js từ chối mọi action ngoài list này

ops:
  telegram_enabled: true       # outbound-only: chỉ gửi vào 1 group, không nhận lệnh
  telegram_topic_id: null      # chỉ đặt nếu group bật Topics; còn lại để null
  log_level: INFO
  db_path: data/bot.db
  # TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID nằm trong .env, không nằm ở đây
```

## 7.7 Pseudocode vòng lặp chính

```python
async def main_loop():
    while running:
        await ws.ensure_connected()
        await bars.ingest_until_now()
        await account.reconcile_if_due()

        if not risk.trading_allowed():
            continue

        for symbol in universe:
            bars15 = bars.closed(symbol, "15m")
            if not bars15.new_bar_since(last_seen[symbol]):
                continue

            feats = features.compute(symbol, bars15)
            label = regime.update(symbol, feats)
            pos = account.position(symbol)

            # 1) quản lý vị thế đang mở trước
            if pos:
                actions = exits.evaluate(pos, feats, label)
                for a in actions:
                    await exec.apply(a, pos)

            # 2) chỉ mở lệnh mới nếu không có vị thế
            elif risk.can_open(symbol, label):
                strat = strategies.for_regime(label)
                if strat:
                    sig = strat.on_bar(feats, label)
                    if sig and risk.validate(sig):
                        await exec.open(sig)

        await watchdog.tick()
        await ops.flush_metrics()
        await asyncio.sleep(1)
```

## 7.8 Dashboard Node.js (MVP, tối giản)

### Mục đích

Một trang để **nhìn** hệ thống đang làm gì và **bấm dừng** khi cần. Không phải nơi giao dịch, không phải nơi cấu hình chiến lược.

### Ranh giới (bắt buộc)

| Được làm | Không được làm |
|---|---|
| Đọc SQLite (read-only), hiển thị state | Đặt/hủy lệnh Binance |
| Ghi `commands` (kill switch, pause, resume, flatten) | Giữ API key/secret |
| WS push tới browser | Tính size, tính PnL giao dịch, sửa position |
| Hiển thị log, incident, metric | Chạy chiến lược hoặc đổi tham số runtime |

Nếu dashboard chết, Python **vẫn trade bình thường**. Nếu Python chết, dashboard chỉ hiện "stale" — không được tự làm gì khác.

### Stack tối giản

```
Node 22 LTS
  fastify (hoặc express)     HTTP + static
  ws                         push tới browser
  better-sqlite3 (readonly)  đọc DB
  basic-auth                 một user, một mật khẩu
  html + vanilla JS          một trang, không build step
```

Không React, không TypeScript, không ORM, không chart library. Nếu cần sparkline, vẽ bằng `<canvas>` 30 dòng.

### Cấu trúc

```
dashboard/
  server.js       # 1 file: HTTP, WS, DB read, command write
  public/
    index.html    # 1 trang
    app.js        # 1 file: fetch + WS, render
    style.css
```

### 8 widget của trang

1. **Status**: mode (demo/live), uptime, heartbeat, WS ok, data age, clock offset.
2. **Equity**: balance, equity, today PnL, week PnL, DD from peak, khoảng cách tới kill switch.
3. **Positions**: symbol, strategy, side, size, entry, mark, uPnL, SL, TP, R, age.
4. **Orders**: SL/TP đang active, số orphan, lệnh gần nhất.
5. **Regime**: mỗi symbol nhãn hiện tại + lý do; tín hiệu bị chặn.
6. **Trades**: 20 fill gần nhất, phí, slippage, R.
7. **Risk**: exposure theo nhóm tương quan, risk budget từng chiến lược, nút **Pause** / **Flatten** / **Stop** (có xác nhận).
8. **Alerts**: incident và warning chưa xử lý.

### Luồng dữ liệu

```
Python ghi runtime_state mỗi 1s
Node poll SQLite mỗi 1s (hoặc 500ms)
Node push delta qua WS tới browser
Browser render, không tự tính toán gì quan trọng
```

### Kill switch qua dashboard

```
Browser POST /command {action:"pause"|"resume"|"flatten"|"stop", confirm:"..."}
Node INSERT INTO commands (status='pending')
Python poll commands mỗi 1s → thực thi → UPDATE status='acked'
Dashboard hiển thị ack + thời gian
```

Đổi tham số chiến lược: **sửa YAML + restart**, không qua UI. Lý do: tránh drift giữa config và state, tránh tai nạn bấm nhầm, và giữ audit trail trong git.

Lý do dùng bảng `commands` thay vì gọi thẳng Python: command **sống sót qua restart**, có audit trail, và dashboard không cần mở port vào engine.

### Bảo mật (MVP)

- Bind `127.0.0.1`, truy cập qua **SSH tunnel** (`ssh -L 8080:localhost:8080 bot@vps`).
- Nếu buộc phải public: Caddy/Nginx + TLS + basic auth + IP allowlist; vẫn read-only.
- Không đặt dashboard sau một domain dễ đoán mà không auth.
- CSRF: mọi command cần token + confirm string.
- Không log secret; DB không chứa API key.

### Không làm ở MVP

- Không đăng nhập nhiều user, không phân quyền.
- Không đặt lệnh, không sửa SL/TP từ UI.
- Không backtest trên UI, không chart nến.
- Không mobile app, không real-time < 500ms (1s là đủ).
- Không lưu lịch sử dài hơn 7 ngày trên dashboard (DB vẫn giữ).

### Cổng nghiệm thu

- Dashboard sống 72h, không rò rỉ memory.
- Kill switch từ UI có hiệu lực < 2s và có ack.
- Dashboard tắt → bot vẫn chạy, không lỗi.
- Không có endpoint nào có thể đặt lệnh.

## 7.9 Docker hóa (ngay từ ngày đầu)

### Vì sao

- Dev và VPS chạy **cùng một môi trường**; Python/Node version cố định.
- `restart: unless-stopped`, healthcheck, log rotation, resource limit có sẵn.
- Deploy = `git pull` + `docker compose up -d --build`.
- Dashboard bị cô lập khỏi engine; engine không cần mở port.

### Mô hình

```
Docker Compose
├── engine (Python)      -> Binance REST/WS, SQLite writer
├── dashboard (Node)     -> SQLite reader + WS browser, port 127.0.0.1:8080
└── botdata (volume)     -> /app/data/bot.db (WAL)
```

Không có service DB riêng. SQLite đủ cho MVP; nếu sau này cần đa writer thì thay bằng Postgres.

### Service thứ 3 (tùy chọn): `binance-demo-server`

Vì Demo Trading của Binance có thể hỏng ở khâu tạo API key (và `testnet.binancefuture.com` đã bị gộp về `demo.binance.com`), hệ thống có thêm **1 container giả lập** trong cùng compose network:

```
engine              → base_url http://binance-demo-server:8080
binance-demo-server → mock USDⓈ-M Futures (REST + WS), state SQLite, read-only, 256 MB
```

Mục tiêu: chính xác ở tầng hợp đồng API (ký HMAC, error code, Algo order, `ALGO_UPDATE`, listenKey, rate-limit header), xấp xỉ ở tầng matching. Đổi môi trường chỉ bằng env `BINANCE_BASE_URL` — engine **không** có nhánh `if mock`.

Chi tiết đầy đủ: `docs/phase0-binance-demo-server.md`.

### docker-compose.yml

```yaml
services:
  engine:
    build: ./engine
    env_file: .env
    environment:
      TZ: UTC
    volumes:
      - botdata:/app/data
      - ./config:/app/config:ro
    restart: unless-stopped
    init: true
    stop_grace_period: 30s
    mem_limit: 1g
    cpus: "1.0"
    logging:
      driver: json-file
      options: { max-size: "20m", max-file: "5" }
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - |
          import sqlite3, time, sys
          con = sqlite3.connect("/app/data/bot.db", timeout=5)
          ts = con.execute("select max(ts) from runtime_state").fetchone()[0] or 0
          sys.exit(0 if time.time() * 1000 - ts < 15000 else 1)
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  dashboard:
    build: ./dashboard
    env_file: .env
    environment:
      TZ: UTC
      DB_PATH: /app/data/bot.db
    volumes:
      - botdata:/app/data
    ports:
      - "127.0.0.1:8080:8080"   # chỉ loopback; vào bằng SSH tunnel
    depends_on:
      engine:
        condition: service_started
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
      test:
        - CMD
        - node
        - -e
        - "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

volumes:
  botdata:
```

### Dockerfile engine

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd -m -u 1000 bot
COPY --chown=bot:bot app ./app
RUN mkdir -p /app/data && chown bot:bot /app/data
USER bot
CMD ["python", "-m", "app.main"]
```

### Dockerfile dashboard

```dockerfile
FROM node:22-bookworm-slim
ENV NODE_ENV=production TZ=UTC
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY --chown=node:node . .
USER node
EXPOSE 8080
CMD ["node", "server.js"]
```

Dùng `node:22-bookworm-slim` (glibc) thay vì Alpine để `better-sqlite3` dùng prebuilt binary, tránh phải build từ source.

### .dockerignore (bắt buộc)

```
.git
.env
.env.*
!.env.example
data/
logs/
node_modules/
.venv/
__pycache__/
*.pyc
*.db
*.db-wal
*.db-shm
```

### Secrets

- `.env` chỉ nằm trên server, không commit, không `COPY` vào image.
- Compose dùng `env_file: .env`; image không chứa secret.
- Kiểm tra: `docker history --no-trunc <image> | findstr -i secret` phải rỗng.
- `.env.example` chỉ có placeholder.
- Telegram (outbound-only vào 1 group): `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` **chỉ nằm trong `.env`**, không nằm trong YAML/git/image/log. `config/mvp.yaml` chỉ giữ `ops.telegram_enabled` và `ops.telegram_topic_id` (null nếu group không bật Topics).

```bash
# .env (trên VPS, không commit) — danh sách đầy đủ, xem .env.example ở repo root
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
TELEGRAM_BOT_TOKEN=8123456789:AAH-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_TOPIC_ID=
DASH_USER=bot
DASH_PASS=doi-mat-khau-manh-o-day
```

### Quy trình deploy

```bash
git pull
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f --tail=100 engine
```

Rollback: `git checkout <tag> && docker compose up -d --build`.

### Vận hành

- `docker compose restart engine`: SL vẫn trên server Binance, không mất bảo vệ.
- `docker compose down` (không `-v`) giữ volume. **Không bao giờ `down -v` trên prod.**
- Backup an toàn (không copy file WAL khi đang chạy):

```bash
docker compose exec -T engine python -c "import sqlite3,datetime; s=sqlite3.connect('/app/data/bot.db'); d=sqlite3.connect('/app/data/backup-'+datetime.date.today().isoformat()+'.db'); s.backup(d)"
docker cp "$(docker compose ps -q engine):/app/data/backup-$(date +%F).db" ./backups/
```

- Log đi ra stdout; Docker xoay vòng theo `logging.options`. Không ghi file log trong container.
- `TZ=UTC` cố định; host chạy NTP.
- `stop_grace_period: 30s`: engine nhận SIGTERM → ngừng mở lệnh mới, flush state, thoát. SL vẫn nằm trên Binance.

### Lưu ý thực tế

1. **SQLite trên volume chia sẻ**: Python là writer chính; dashboard chỉ ghi `commands`. Bật WAL + `busy_timeout=5000`. Ở tần suất 1s, tranh chấp không đáng kể.
2. **UID**: engine dùng uid 1000 (`bot`), dashboard dùng uid 1000 (`node`) → cùng đọc/ghi volume. Nếu đổi user, phải `chown` lại volume.
3. **Named volume vs bind mount**: named volume tránh lỗi permission; bind mount dễ backup nhưng phải `chown 1000:1000`.
4. **Windows dev**: chạy trong WSL2, không dùng bind mount từ `F:\` cho SQLite (chậm và khóa file).
5. **Không** mount Docker socket, không `privileged`, không `network_mode: host`.
6. **Healthcheck fail** → container restart; nếu lặp lại, alert và dừng để review, không để loop vô hạn.
7. Pin version trong `requirements.txt`, `package-lock.json`; image tag cố định (`python:3.12-slim`, `node:22-bookworm-slim`).

### Cổng nghiệm thu Docker

- Clone sạch + `docker compose up -d --build` chạy được, cả 2 service healthy.
- Restart engine → position/SL còn nguyên, reconcile = 0.
- `down` rồi `up -d` → state khôi phục từ volume.
- `docker history` không có secret; dashboard chỉ nghe `127.0.0.1`.
- Chạy 72h, memory phẳng, log không có ERROR lặp.

### 7.10 Telegram group alert (outbound-only)

Mục tiêu: bot Telegram chỉ **gửi thông báo vào 1 group cụ thể**, không nhận lệnh, không polling.

Phạm vi gửi: alert sự cố (§11.3), daily report (§9.4), kết quả kill switch. Kill switch thực hiện bằng lệnh CLI / nút dashboard; Telegram chỉ báo "đã thực thi lúc HH:MM".

Mọi khóa/token nằm trong `.env` (xem 7.9 Secrets), không nằm trong YAML/git/image/log:

```bash
TELEGRAM_BOT_TOKEN=8123456789:AAH-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_TOPIC_ID=
```

Thêm bot vào group (làm 1 lần):

1. Chat @BotFather → `/newbot` → nhận `TELEGRAM_BOT_TOKEN`.
2. Thêm `@<bot_username>` vào group (Add Members, hoặc link `https://t.me/<bot_username>?startgroup=true`); chỉ cần quyền gửi tin. Không cần admin, trừ khi muốn pin tin trạng thái.
3. Gửi 1 tin vào group, rồi gọi `GET https://api.telegram.org/bot<TOKEN>/getUpdates` để lấy `TELEGRAM_CHAT_ID` (group/supergroup là số âm dạng `-100...`).
4. Nếu group bật Topics thì điền `TELEGRAM_TOPIC_ID` (= `message_thread_id`); còn lại để trống.
5. Test: `POST /bot<TOKEN>/sendMessage` với `chat_id` → phải trả `{"ok":true}`. Xoay token bằng `/revoke` trong BotFather nếu lộ.

Quy tắc code (engine, module `ops`):

- Gửi bằng `httpx.post` async qua worker queue có `maxsize`, retry 429 theo `retry_after`, không gọi đồng bộ trong hot path.
- Dedup theo `dedup_key` (ví dụ WS flap chỉ báo 1 lần); queue đầy thì bỏ alert thay vì block engine.
- Tin ngắn, prefix `[severity] module:`, cắt 4000 ký tự, `disable_web_page_preview: true`.
- Không log token; `docker history` không được lộ chuỗi `TELEGRAM_`.

Cổng nghiệm thu: tin test tới đúng group; kill switch từ CLI/dashboard có alert xác nhận trong group; không có endpoint inbound nào đọc Telegram update.

---

# 8. Lộ trình 12 tuần

*MVP 12 tuần; mở rộng Trend Pullback thêm ~10 tuần (tổng 22).*

## Tổng quan

| Giai đoạn | Tuần | Mục tiêu | Cổng |
|---|---|---|---|
| P0 | 0 | Chuẩn bị tài khoản, môi trường, xác minh | 13 mục bảng 4.3 pass |
| P1 | 1–2 | Exchange adapter + data + regime | 72h không orphan, regime label đúng |
| P2 | 3 | Risk engine + executor | Không bypass được limit |
| P3 | 4 | MR + backtest | ≥150 lệnh, expectancy > 0 sau phí |
| P4 | 5 | Squeeze + gating | 2 chiến lược không đánh nhau |
| P5 | 6 | Paper infra + metrics + **dashboard Node.js v1** | Báo cáo + dashboard chạy |
| Demo | 7–10 | Demo 5.000 USD + **Trend shadow** | Go/no-go MVP |
| Demo+ | 11–14 | Bật Trend thật trên demo (budget 20%) | 12 tuần forward |
| Live | 15–22 | Live 300 USD (MVP trước, Trend sau) | Review hàng tuần |

## Tuần 0 — Chuẩn bị

- Làm toàn bộ checklist 4.1, 4.2.
- Chạy bảng xác minh 4.3, ghi kết quả vào `docs/verification.md`.
- Tạo repo, CI đơn giản (ruff + pytest), `.env.example`, `.dockerignore`.
- **Docker skeleton**: `engine/Dockerfile`, `dashboard/Dockerfile`, `docker-compose.yml`, healthcheck, named volume.
- `docker compose up -d --build` với app rỗng phải chạy; sau đó mới viết logic.
- Viết `README` quickstart bằng Docker.

**Cổng:** 13/13 mục pass; `docker compose ps` healthy; không có secret trong image.

## Tuần 1 — Adapter

- REST client: ký HMAC, `recvWindow`, retry 429/5xx, backoff, clock offset.
- WS: market (`kline_1m`, `markPrice`, `bookTicker`, `aggTrade`) + user (`ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`).
- `listenKey` lifecycle (create/keepalive 30 phút/renew).
- Order state machine + `clientOrderId` idempotent.
- Reconcile 5s.
- Telegram alert cơ bản (outbound-only vào group: queue + dedup, không polling).
- Chạy trong container, log ra stdout; kiểm tra `restart: unless-stopped`.

**Cổng:** chạy demo 72h; 0 orphan order; reconnect ≥ 5 lần không lệch state; restart container không mất state.

## Tuần 2 — Data & Regime

- Tải historical từ `data.binance.vision` (bulk) + backfill phần thiếu bằng REST.
- Parquet theo symbol/ngày; DuckDB query.
- Aggregate 1m → 15m/1h (chỉ nến đã đóng).
- Feature engine + unit test với dữ liệu tổng hợp.
- Regime + hysteresis + replay.
- Spot-check 3 giai đoạn: một tuần range, một squeeze, một ngày crash.

**Cổng:** nhãn regime ổn định, không nhảy mỗi nến; replay ra cùng kết quả 2 lần.

## Tuần 3 — Risk & Execution

- Risk engine với mọi limit ở 4.3/5.1.
- Sizing: `size = risk$ / stop_distance`, round theo stepSize, cap theo leverage.
- Executor: post-only entry, SL closePosition, TP closePosition, OCO-by-bot, make-before-break.
- Kill switch 3 cấp.
- Test injection: cố tình vượt limit → phải bị chặn.

**Cổng:** 100% lệnh đi qua risk; test kill switch hoạt động.

## Tuần 4 — MR + backtest

- Implement MR đúng spec.
- Backtest engine: event-driven 1m, fill model bảo thủ, phí, funding, slippage.
- Walk-forward: 6 tháng train / 2 tháng test, cuộn.
- Out-of-sample 6 tháng cuối, chỉ chạy 1 lần.
- Báo cáo: expectancy, win rate, R distribution, DD, theo coin, theo regime.

**Cổng:** ≥150 lệnh; expectancy > 0 sau phí; DD < 8%; dương trên ≥60% coin.

## Tuần 5 — Squeeze + gating

- Implement Squeeze + trailing policy.
- Mutual exclusion theo regime.
- Correlation cap.
- Backtest riêng và gộp.
- Kiểm tra không có lệnh trùng/đối nghịch trên cùng symbol.

**Cổng:** mỗi chiến lược dương trong regime của nó; equity gộp không có đoạn "đánh nhau".

## Tuần 6 — Paper infra + Dashboard v1

- Chạy full pipeline trên dữ liệu live, không gửi lệnh thật (hoặc demo).
- Metrics collector + daily report.
- **Dashboard Node.js v1**: 1 trang, 8 widget, read-only, kill switch qua bảng `commands`.
- Build dashboard image; compose chạy 2 service; healthcheck + log rotation hoạt động.
- Skeleton `trend_pullback.py` + `mode: shadow` (signal + fill giả lập, không gửi lệnh).
- Watchdog: stale data, orphan, mismatch, WS disconnect, API error rate.
- Replay mode để debug.

**Cổng:** report + dashboard chạy; kill switch < 2s; trend shadow ghi đủ signal + lý do bỏ lỡ.

## Tuần 7–10 — Demo 5.000 USD + Trend shadow

- MVP MR + Squeeze chạy demo theo mục 9.
- Trend Pullback chạy **shadow**: không đặt lệnh, ghi signal/fill giả/PnL ảo.
- Đo: số tín hiệu, tỷ lệ có pullback hợp lệ, R ảo, lý do bỏ lỡ.

**Cổng:** MVP pass go/no-go; shadow có ≥ 20 tín hiệu, không lỗi logic.

## Tuần 11–14 — Bật Trend thật trên demo

- Chỉ khi MVP ổn định và shadow sạch.
- Sổ ảo riêng cho Trend, risk budget 20%.
- Global position manager chặn 2 chiến lược cùng symbol.
- 4 tuần demo có lệnh thật + 4 tuần shadow = **12 tuần forward**.

**Cổng:** không xung đột lệnh; PnL tách được theo `strategy_id`.

## Tuần 15–22 — Live 300 USD

- Live MVP (MR + Squeeze) trước, risk 0,25%.
- Trend live chỉ sau 12 tuần forward + backtest, risk 0,2% và budget riêng.
- Xem mục 10.

**Cổng:** 8 tuần live ổn định mới tăng size.

---

# 9. Chạy demo 5.000 USD

## 9.1 Bật demo

1. Đăng nhập Binance → `More` → `Demo Trading` (hoặc `demo.binance.com`).
2. Tạo API key **trong Demo** (key demo tách biệt key live).
3. Bot dùng REST `https://demo-fapi.binance.com`.
4. Ghi lại WS host thực tế hoạt động (xem bảng 4.3 mục 2).
5. Điền key vào `.env` trên VPS, rồi `docker compose up -d --build`.
6. Kiểm tra `docker compose ps` cả 2 service **healthy**.

## 9.2 Vấn đề số dư demo

Binance cấp tiền ảo theo khu vực/thời điểm (nhiều nguồn ghi 15.000 USDT; không có cam kết cố định). **Đừng phụ thuộc số dư demo.**

Cách đúng: bot giữ **sổ ảo riêng 5.000 USD**:

```yaml
equity_base: 5000
```

- Sizing luôn tính trên `equity_base` (hoặc equity ảo cập nhật theo PnL của bot).
- Báo cáo PnL theo % của 5.000.
- Số dư demo thực tế chỉ là "trần" để lệnh không bị từ chối; không dùng nó để tính risk.

Nhờ vậy, kết quả demo chuyển sang live 300 USD **cùng thang đo %**.

## 9.3 Demo khác live — nhớ kỹ

| Điểm | Demo | Live |
|---|---|---|
| Fill limit | Lạc quan, dễ khớp | Có queue, có thể không khớp |
| Slippage | Gần như 0 | 0,05–0,3% khi biến động |
| Order book | Mô phỏng | Thật |
| Export | **Không có** | Có |
| Cảm xúc | Không | Có |
| Sự cố mạng | Không | Có |

→ Demo đánh giá **vận hành**, không đánh giá **edge**.

## 9.4 Quy tắc 4 tuần demo

- Risk 0,5%/lệnh; leverage 3x; max 4 vị thế; tổng risk mở ≤ 2,0%.
- **Không sửa tham số** trong 4 tuần.
- Trend Pullback chạy **shadow**, không gửi lệnh; không tính vào PnL của MVP.
- Dashboard là nơi theo dõi chính; chỉ thao tác kill switch, không đặt lệnh.
- Mỗi ngày 00:05 UTC: bot tự gửi daily report vào Telegram group (PnL ngày/tuần, DD, số lệnh, incidents); bạn đọc 5 phút.
- Mỗi tuần: review metrics + incidents.
- Nếu bot lỗi → dừng, sửa, **reset đồng hồ 4 tuần** (không cộng dồn).

## 9.5 Go/no-go sau demo

| Chỉ số | Ngưỡng |
|---|---|
| Expectancy vs backtest | lệch ≤ ±30% |
| Max DD | ≤ 1,5× backtest |
| Reconcile diff | 0 mọi ngày |
| Orphan order | 0 |
| Số lệnh | ≥ 40 |
| Sự cố nghiêm trọng | 0 (mất kiểm soát vị thế) |
| Slippage mô phỏng | ≤ 2 bps |
| Trend shadow | ≥ 20 tín hiệu, 0 lỗi logic, fill rate ≥ 40% |
| Chạm daily loss −2% (portfolio 2,0%) | ≤ 1 ngày trong 4 tuần; nếu >1 → hạ portfolio về 1,5% |

Fail bất kỳ mục nào → sửa, chạy lại demo. **Không lên live sớm.**

---

# 10. Chạy live 300 USD

## 10.1 Setup an toàn

- Sub-account riêng.
- API key: Futures bật, **withdrawal tắt**, IP whitelist, không universal transfer.
- Isolated margin; leverage 3x.
- Vốn trên futures account: **đúng 300 USD**, không thêm.
- Tiền ngoài sàn: giữ ở nơi khác, không nạp thêm để "cứu lệnh".
- `.env` trên VPS (không commit); deploy bằng `docker compose up -d --build`.

## 10.2 Sizing thực tế với 300 USD

Công thức:

```
risk$        = 0,5% × 300 = 1,50 USD
stop_distance = stop% × price
size (base)  = risk$ / stop_distance
notional     = size × price = risk$ / stop%
```

| Stop (% giá) | Notional | % vốn | Leverage thực |
|---|---|---|---|
| 0,4% | 375 | 125% | 1,25x |
| 0,6% | 250 | 83% | 0,83x |
| 0,8% | 188 | 63% | 0,63x |
| 1,2% | 125 | 42% | 0,42x |

→ Với stop 0,4–1,2%, leverage thực chỉ 0,4–1,25x. **Đòn bẩy 3x không bao giờ bị chạm** trừ khi stop cực hẹp. Đây là điều tốt.

Lưu ý min notional 5 USDT và stepSize: size sau khi round có thể nhỏ hơn kỳ vọng → risk thực tế thấp hơn 0,5%. Chấp nhận; **không tăng risk để bù**.

## 10.3 Bài toán phí — con số quan trọng nhất

Với notional/equity = risk% / stop%:

| Stop | Notional/vốn | Phí round-trip maker→taker (0,07%) | % vốn/lệnh | 20 lệnh/tuần |
|---|---|---|---|---|
| 0,5% | 1,0x | 0,070% | 0,070% | 1,40%/tuần |
| 0,6% | 0,83x | 0,058% | 0,058% | 1,16%/tuần |
| 0,8% | 0,63x | 0,044% | 0,044% | 0,88%/tuần |
| 1,2% | 0,42x | 0,029% | 0,029% | 0,58%/tuần |

Taker→taker (0,10%) thì cao hơn ~43%.

**Hệ quả:** nếu bạn trade 20 lệnh/tuần với stop 0,6%, bạn cần **> 1,2%/tuần lợi nhuận gộp** chỉ để hòa phí. Với target MR ~1% và win rate 50%, điều này rất khó. Vì vậy:

- Giảm tần suất: **5–10 lệnh/tuần** là mục tiêu live.
- Ưu tiên maker entry.
- Không trade coin spread rộng.
- Tránh stop quá hẹp.

## 10.4 Quy tắc live

- Risk 0,25% trong 4 tuần đầu, sau đó 0,5% nếu ổn.
- Max 2 vị thế.
- Không trade khi `CRISIS`, khi data stale, khi blackout.
- Không can thiệp thủ công trừ kill switch.
- Mỗi lệnh phải có SL **trước** khi bot làm việc khác.
- Review hàng tuần; **không đổi tham số giữa tuần**.

## 10.5 Khi nào dừng

- Daily −2% → dừng 24h.
- Weekly −4% → dừng, review cuối tuần.
- DD −6% từ đỉnh → dừng hẳn, quay lại demo.
- 3 sự cố vận hành nghiêm trọng trong 2 tuần → dừng.
- Bạn cảm thấy muốn "gỡ" → dừng.

---

# 11. Quản trị rủi ro và vận hành

## 11.1 Bảng giới hạn cứng

| Giới hạn | Demo | Live |
|---|---|---|
| Risk/lệnh | 0,5% | 0,25–0,5% |
| Leverage | 3x | 3x |
| Max vị thế | 4 | 2 |
| Portfolio risk (tổng risk mở) | 2,0% | 1,0% |
| Max risk nhóm tương quan | 2,0% | 1,0% |
| Margin sử dụng tối đa | 60% equity | 60% equity |
| Daily loss | 2% | 2% |
| Weekly loss | 4% | 4% |
| Max drawdown | 6% | 6% |
| Max lệnh/ngày | 10 | 5 |
| Blackout tin | ±45 phút | ±45 phút |
| Stale data | 3s | 3s |

**Ghi chú về Portfolio risk 2,0% (demo):**

- 4 vị thế × 0,5% = **2,0%** tổng risk mở; risk/lệnh **không đổi** (0,5%).
- Hệ quả phải chấp nhận: nếu cả 4 vị thế dừng lỗ cùng lúc (alt tương quan BTC cao, xem 5.3), mức lỗ −2,0% **chạm đúng** `daily loss −2%` → bot dừng 24h. Đây là hành vi mong muốn: daily limit đóng vai trò chốt chặn cuối, không phải trần lãi.
- Vì vậy **không nới** `daily/weekly/DD`: nếu nới cả ba thì mất luôn lưới an toàn.
- Live giữ 1,0% (2 vị thế) cho tới khi demo 4 tuần pass go/no-go 9.5 mà không có ngày nào chạm daily limit.
- Correlation cap: 4 lệnh cùng hướng trên nhóm `beta>0.8` vẫn bị chặn ở 2,0%; muốn mở lệnh thứ 5 phải chờ đóng bớt.
- **Margin là ràng buộc thật trên TK nhỏ:** stop 0,69% với 3x isolated cần margin ~21% vốn/lệnh; 4 vị thế ≈ 85% vốn dù portfolio risk mới 1,8%. Vì vậy risk engine chặn mở mới khi margin vượt 60% equity, và log cảnh báo mềm khi stop% < 0,5% (notional > 2× vốn/lệnh).

## 11.2 Kill switch 3 cấp

1. **Mềm:** ngừng mở lệnh mới, giữ SL, alert.
2. **Cứng:** đóng toàn bộ market, hủy algo orders, dừng bot.
3. **Thủ công:** lệnh CLI + nút dashboard (`commands`), hoạt động cả khi loop chính treo; Telegram group chỉ nhận thông báo kết quả, không nhận lệnh.

## 11.3 Incident playbook

| Sự cố | Phát hiện | Hành động |
|---|---|---|
| Mất WS market | Không có tick > 3s | Không mở lệnh mới; reconnect; nếu > 60s → alert |
| Mất WS user | Không có event > 60s | Reconcile REST; renew listenKey |
| Position lệch DB | Reconcile diff | **HALT ngay**, alert, không tự sửa mù |
| Thiếu SL | Reconcile thấy position không có algo SL | Đặt lại SL ngay; nếu fail 3 lần → đóng market |
| Orphan order | Position = 0 còn order | Hủy, ghi incident |
| API 429 | Header weight cao | Backoff, giảm tần suất |
| API 418 | IP ban | Dừng, đổi IP/giờ, không spam |
| Clock lệch | `-1021` | Sync NTP, dừng đặt lệnh |
| Flash crash | Regime CRISIS | Đóng lệnh yếu, không mở mới |
| Funding xấu | funding tuyệt đối > 0,1% | Không giữ lâu; đóng nếu sắp snapshot |
| Bot chết | Heartbeat mất | VPS auto-restart; SL vẫn trên server |
| Sàn bảo trì | API 503 | Không làm gì; SL đã đặt trước |

## 11.4 Bảo mật

- Không commit `.env`; dùng secret manager nếu có.
- Không log API key/signature; không log `TELEGRAM_BOT_TOKEN`.
- `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` chỉ nằm trong `.env` trên VPS; YAML chỉ giữ cờ `ops.telegram_enabled` / `ops.telegram_topic_id`.
- SSH key-only, tắt password login, firewall chỉ IP của bạn.
- 2FA; email riêng cho bot.
- Không cài package lạ trên VPS bot.
- Backup DB + config hàng ngày ra ngoài VPS.
- **Dashboard**: bind `127.0.0.1`, truy cập qua SSH tunnel; nếu public phải TLS + basic auth + IP allowlist.
- Dashboard **không** giữ API key và **không** có endpoint đặt lệnh.
- Command kill switch cần confirm token + ghi audit vào bảng `commands`.
- Docker image **không chứa** `.env`; kiểm tra `docker history` trước khi push/deploy.
- Không dùng `docker compose down -v` trên prod; backup bằng SQLite `.backup`.

## 11.5 Checklist vận hành

**Hàng ngày (5 phút):**

- [ ] Bot alive, heartbeat OK.
- [ ] `docker compose ps` healthy, không restart loop.
- [ ] Position khớp sàn.
- [ ] Mỗi position có đúng 1 SL.
- [ ] Không orphan order.
- [ ] PnL trong giới hạn.
- [ ] Data tươi, không gap.
- [ ] Không có alert chưa xử lý.

**Hàng tuần (30 phút):**

- [ ] Expectancy, win rate, R distribution.
- [ ] Phí, funding, slippage thực tế.
- [ ] Tỷ lệ thời gian theo regime.
- [ ] Số lệnh, số ngày 0 lệnh.
- [ ] Incidents + fix.
- [ ] Universe review (volume/spread).
- [ ] **Không đổi tham số** trừ khi có lý do ghi lại.

---

# 12. Chi phí

| Khoản | Chi phí/tháng |
|---|---|
| VPS (tận dụng máy sẵn có) | **0** — chỉ cần ≥2 vCPU / 2–4 GB, NTP sync. Chiến lược 15m chịu được latency 100–300ms nên không bắt buộc Tokyo/Singapore |
| Data lịch sử Binance | 0 |
| DB (SQLite/Parquet) | 0 |
| Dashboard Node.js | 0 (chạy cùng VPS) |
| Docker/Compose | 0 |
| Telegram bot (outbound group alert) | 0 |
| OpenRouter (phase 2, 2 model rẻ) | **≈ 2–7 USD** (tính ở 15.1) |
| **Tổng MVP (phase 1)** | **≈ 0 USD** |
| **Tổng khi bật AI (phase 2)** | **≈ 2–7 USD** |
| Vốn live | 300 USD |
| Phí giao dịch live | ~2–5 USD/tháng (tùy tần suất) |

Thời gian: ~120–180 giờ trong 12 tuần cho MVP; +40–60 giờ cho Trend shadow/demo.

---

# 13. KPI và cách đánh giá

## 13.1 Định nghĩa

| Chỉ số | Công thức | Ý nghĩa |
|---|---|---|
| Expectancy | `(WR × avg_win) − (LR × avg_loss)` | Lãi kỳ vọng mỗi lệnh |
| R-multiple | `PnL / risk$` | Chuẩn hóa theo rủi ro |
| Profit factor | `gross_profit / gross_loss` | > 1,2 mới đáng |
| Win rate | `wins / trades` | Một mình nó vô nghĩa |
| Max DD | đỉnh → đáy equity | Rủi ro thật |
| Sharpe | `mean(daily_ret)/std(daily_ret) × √365` | Biến động điều chỉnh |
| Time in market | % thời gian có vị thế | Càng cao càng chịu funding |
| Fees/gross | `fees / gross_profit` | > 30% là báo động |
| Funding PnL | tổng funding trả/nhận | Phải tính vào |
| Slippage | `fill − expected` | So với model |
| MAE/MFE | max adverse/favorable excursion | Đánh giá SL/TP |
| Per-strategy PnL | lọc `strategy_id` | Biết chiến lược nào gánh |
| Shadow fill rate | `fillable_signals / total_signals` | Trend có khớp được không |
| Missed reason | `no_pullback / too_deep / no_trigger / filtered` | Trend bỏ lỡ vì đâu |

## 13.2 Ngưỡng MVP

| Chỉ số | Ngưỡng chấp nhận |
|---|---|
| Expectancy | > 0 sau phí, funding, slippage |
| Profit factor | > 1,15 |
| Max DD | < 8% demo, < 6% live |
| Fees/gross | < 30% |
| Số lệnh/4 tuần | ≥ 40 |
| Slippage | ≤ 2 bps so với model |
| Shadow tín hiệu/4 tuần | ≥ 20 (Trend) |
| Shadow fill rate | ≥ 40% (Trend) |
| Expectancy theo `side` | Báo cáo tách long/short; short chỉ được tính khi ≥50 lệnh |

## 13.3 Cách tránh tự lừa mình

- Ghi lại **mọi** lần đổi tham số + lý do.
- Không chọn tham số tốt nhất trong 100 lần thử; chọn bộ **ổn định** qua nhiều coin.
- Giữ out-of-sample 6 tháng, chỉ chạm 1 lần.
- So sánh với benchmark: "không trade" (0%) và "hold BTC".
- Nếu equity đẹp nhưng chỉ nhờ 1 lệnh → coi như chưa chứng minh.

---

# 14. Kết quả kỳ vọng (thực tế)

## 14.1 Demo 4 tuần (5.000 USD)

| Kịch bản | Kết quả | Diễn giải |
|---|---|---|
| Xấu | −6% đến −3% | Nhiều fakeout, phí, học phí |
| Cơ sở | −2% đến +2% | Chấp nhận được nếu DD trong limit |
| Tốt | +2% đến +5% | Có thể do may mắn, chưa kết luận |

Mục tiêu **không phải** PnL mà là: 0 sự cố, số liệu khớp backtest, hiểu hệ thống.

## 14.2 Live 8–12 tuần (300 USD)

| Kịch bản | Kết quả | Tiền |
|---|---|---|
| Xấu | −15% đến −8% | −45 đến −24 USD |
| Cơ sở | −3% đến +3% | −9 đến +9 USD |
| Tốt | +5% đến +10% | +15 đến +30 USD |

**Thực tế cần chấp nhận:** với 300 USD, lợi nhuận tuyệt đối rất nhỏ. 20%/năm = 60 USD. Đây không phải thu nhập; đây là **học phí mua kỹ năng và hệ thống**.

## 14.3 Toán học của edge (không phải dự báo)

Với MR, R = 1,5 USD, TP = 1,5R, phí ≈ 0,11R:

| Win rate | EV gộp (R) | Sau phí 0,11R | 10 lệnh/tuần (% vốn) |
|---|---|---|---|
| 40% | 0,00 | −0,11 | −0,55%/tuần |
| 45% | +0,125 | +0,015 | +0,08%/tuần |
| 50% | +0,25 | +0,14 | +0,70%/tuần |
| 55% | +0,375 | +0,265 | +1,33%/tuần |
| 60% | +0,50 | +0,39 | +1,95%/tuần |

Bảng này cho thấy: **break-even sau phí ở khoảng 44,4% win rate**; ở 45–50%, chỉ cần slippage xấu thêm 0,1–0,2R là về 0. Đây là lý do:
- Phải chọn lọc.
- Phải đo slippage thật.
- Không được tăng tần suất để "gỡ".

## 14.4 Điều không được làm

- Không nạp thêm tiền khi đang lỗ.
- Không tăng leverage để "nhanh về bờ".
- Không suy ra lợi nhuận năm từ 2 tuần.
- Không so sánh với ảnh chụp lợi nhuận trên mạng.

---

# 15. Mở rộng sau MVP

## 15.1 AI gate (phase 2)

Vai trò: **phủ quyết hoặc giảm size**, không phải trigger.

```
News/calendar → 2 model OpenRouter (triage nhanh + reasoner mạnh)
              → JSON {severity, symbols, direction, confidence}
              → đồng thuận? → risk_multiplier 0..1
              → nhân vào size, không bao giờ vượt cap
```

Nguyên tắc:

- Async, 1–15 phút, không nằm trên hot path.
- Output phải qua schema + validator tất định.
- Bất đồng giữa 2 model → multiplier 0 (chặn lệnh mới).
- Budget cap/ngày, cache, timeout, fallback rule.
- Không backtest được tin tức → chỉ forward test.

**Model và chi phí (chốt cho MVP AI gate):**

| Vai trò | Model | Giá in / out (USD/1M token) | Context |
|---|---|---|---|
| Triage nhanh | Z.ai GLM 5.3 Flash | 0,0399 / 0,0784 | 1,048,576 |
| Reasoner | DeepSeek V4 Flash 0731 | 0,0434 / 0,30 | 1,0M |

Giả định 1 lần đánh giá = 4.000 token in + 700 token out cho mỗi model:

```
GLM 5.3 Flash/call       = 4.000×0,0399/1M + 700×0,0784/1M ≈ 0,000215 USD
DeepSeek V4 Flash/call   = 4.000×0,0434/1M + 700×0,30/1M   ≈ 0,000384 USD
1 cặp (đồng thuận)                                       ≈ 0,00060 USD
```

| Tần suất | Call/ngày (cặp) | USD/tháng | Ghi chú |
|---|---|---|---|
| 15 phút | 96 | **≈ 1,7** | mức khuyến nghị; ×1,3 retry ≈ 2,2 |
| 5 phút | 288 | ≈ 5,2 | ×1,3 retry ≈ 6,8 |
| Chỉ khi có headline mới (cache) | 20–60 | **≈ 0,4–1,4** | tốt nhất: phần lớn thời gian multiplier = 1,0 từ cache |

→ **Ngân sách thực tế 2–7 USD/tháng**, không phải 20–50. Cap cứng trong code: `ai_budget_usd_per_day: 0.25` (~7,5 USD/tháng) và dừng gọi khi chạm cap (fallback multiplier = 1,0, ghi `events`).

## 15.2 Trend Pullback (phase 3, có shadow mode)

### Vì sao shadow trước

Trend 1h chỉ có 3–8 lệnh/tuần trên 25 symbol. Bốn tuần demo = 12–32 lệnh, không đủ kết luận. Shadow mode cho phép bắt đầu đo **ngay từ tuần 7** mà không thêm rủi ro và không làm nhiễu kết quả MVP.

### Shadow mode là gì

- Strategy tính signal đầy đủ.
- Không gọi API order; ghi vào `signals` + `shadow_trades`.
- Giả lập fill bảo thủ: market tại open nến sau; limit chỉ khớp nếu giá xuyên qua.
- Tính R ảo, MAE/MFE, và **lý do bỏ lỡ**: `no_pullback`, `too_deep`, `no_trigger`, `regime_filtered`.
- Dashboard hiển thị tab "Trend (shadow)".

### Điều kiện chuyển từ shadow sang demo có lệnh

- MVP MR + Squeeze pass go/no-go 4 tuần.
- Shadow ≥ 20 tín hiệu, 0 lỗi logic.
- PnL tách được theo `strategy_id`.
- Global position manager chặn 2 chiến lược mở cùng symbol.
- Có sổ ảo + risk budget riêng (20%).

### Spec

- Regime `TREND` + 1h signal / 4h filter.
- Entry: hồi 30–61,8% impulse, chạm EMA20/50, volume giảm, RSI 40–55.
- Exit: trailing 2×ATR + time stop 36 nến.
- Chung risk bucket với Squeeze nếu cùng hướng.
- Thêm 1 file strategy, không sửa core.

### Long và short: định nghĩa đối xứng nhưng **chỉ bật long**

Định nghĩa đối xứng (dùng cho code, để không phải viết lại về sau):

| Thành phần | Long | Short |
|---|---|---|
| Regime | `EMA50 > EMA200`, cấu trúc HH/HL | `EMA50 < EMA200`, cấu trúc LH/LL |
| Pullback | hồi 30–61,8% impulse tăng | hồi 30–61,8% impulse giảm |
| Vùng chạm | EMA20/50 từ dưới | EMA20/50 từ trên |
| RSI | 40–55 | 45–60 |
| SL | `swing_low − 1,5×ATR` | `swing_high + 1,5×ATR` |
| Trailing | lãi ≥1,5×ATR → `đỉnh − 2×ATR` | lãi ≥1,5×ATR → `đáy + 2×ATR` |

**Quyết định MVP: `allow_short: false`.** Lý do, theo thứ tự quan trọng:

1. **Không đủ power thống kê.** Trend 1h chỉ 3–8 lệnh/tuần/25 symbol; chia đôi long/short thì mỗi nhánh cần 12 tuần riêng để đạt ≥50 lệnh. MVP cần kết luận trong 22 tuần, không phải 34.
2. **Skew xấu hơn.** SL của short là buy-stop trong panic rally → gap + slippage tệ hơn SL long; win rate thấp hơn, tail risk dày hơn. Ở mẫu nhỏ, không phân biệt được edge với may mắn.
3. **Multiple testing.** Thêm một biến thể để thử là đúng bẫy 3.7/13.3. Chưa có dữ liệu long thì không có cơ sở bật short.
4. **Xung đột chiều.** Trong downtrend, `SQUEEZE` breakout xuống và `TREND-short` sẽ tranh cùng symbol; luật "1 chiến lược/symbol" hiện tại chưa phủ trường hợp này.
5. **Lợi ích của short không miễn phí.** Funding dương (long trả short) là carry thật, nhưng phải chống lại drift tăng của giá; lợi ích này chưa đo được trên chính hệ thống này.

**Điều kiện để bật short (cả 3, không thoả thì không bật):**

- Long-trend đã pass: ≥50 lệnh, expectancy > 0 sau phí + funding + slippage, DD trong budget 20%.
- Shadow short ≥50 lệnh, tách riêng trong `shadow_trades` với `side`, và **dương sau phí**.
- Có luật chặn rõ: `TREND-short` và `SQUEEZE` không được cùng symbol (mở rộng global position manager), cộng correlation cap hiện có.

Trong shadow hiện tại, vẫn **ghi signal short** (side, reason, R ảo) nhưng không tính vào PnL; làm vậy để có dữ liệu short miễn phí mà không tăng rủi ro hay thời gian chạy.

### Điều kiện lên live

- 12 tuần forward (4 shadow + 8 có lệnh demo).
- ≥ 50 lệnh shadow/demo.
- Expectancy > 0 sau phí + funding + slippage.
- Max DD trong budget 20%, không ảnh hưởng MVP.
- Nếu fail → giữ shadow, không lên live.
- `allow_short` chỉ bật khi thoả cả 3 điều kiện short ở trên; nếu không, live chỉ long.

### Cảnh báo

- Demo fill lạc quan; trend dùng market entry nên ít bị ảnh hưởng hơn limit, nhưng SL slippage trong sóng mạnh vẫn cao.
- Không dùng 4 tuần demo để kết luận; cần 12 tuần.
- Không bật trend live cùng lúc với thay đổi tham số MVP.
- Nếu bật short: SL short là buy-stop trong panic rally, slippage và gap có thể xấu hơn long đáng kể — phải dùng `priceProtect` và đo riêng slippage theo `side`.

## 15.3 Funding carry (phase 4)

- Long spot + short perp, delta-neutral.
- Thu funding, rủi ro hướng thấp.
- Cần hạ tầng spot + quản lý basis.
- Là "nền an toàn" cho danh mục.

---

# 16. Sai lầm chết người

1. Không đặt SL ngay sau khi fill.
2. Dời SL xuống (long) để "cho nó thở".
3. Trung bình giá xuống / martingale.
4. Tăng leverage sau chuỗi thua.
5. Trade trong CRISIS vì "cơ hội".
6. Đổi tham số mỗi ngày.
7. Tin demo fill là thật.
8. Không reconcile, để lệnh mồ côi.
9. API key có quyền rút tiền.
10. Chạy bot trên máy không giám sát, không UPS.
11. Bật nhiều chiến lược cùng symbol.
12. Vừa chạy bot vừa tự trade tay.
13. Nạp thêm tiền để cứu tài khoản.
14. Bỏ qua funding khi giữ lệnh nhiều ngày.
15. Dùng stop quá hẹp vì "risk nhỏ" → phí ăn hết R.
16. Public dashboard không auth, hoặc cho dashboard đặt lệnh trực tiếp.
17. Chạy Trend live trước khi đủ 12 tuần forward.
18. Dùng kết quả demo 4 tuần để kết luận Trend có edge.
19. Bật Trend-short khi long-trend chưa pass, hoặc chia mẫu long/short quá sớm khiến cả hai nhánh đều thiếu power.
20. `docker compose down -v` trên prod (xóa volume = xóa DB).
21. COPY `.env` vào image hoặc commit `.env` lên git.

---

# 17. Tài liệu tham khảo đã kiểm chứng

## 17.1 Binance (chính thức)

- Demo Trading FAQ: https://www.binance.com/en/support/faq/detail/9be58f73e5e14338809e3b705b9687dd
- Futures Fee Structure: https://www.binance.com/en/support/faq/detail/360033544231
- Futures rate limits: https://www.binance.com/en/support/faq/detail/281596e222414cdd9051664ea621cdc3
- Derivatives changelog (Algo migration 2025-11-06, hiệu lực 2025-12-09): https://developers.binance.com/docs/derivatives/change-log
- New Algo Order: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- Liquidation price: https://www.binance.com/en/support/faq/how-to-calculate-liquidation-price-of-usd%E2%93%A2-m-futures-contracts-b3c689c1f50a44cabb3a84e663b81d93
- Leverage & margin: https://www.binance.com/en/support/faq/leverage-and-margin-of-usd%E2%93%A2-m-futures-360033162192
- Min notional / trading rules: https://www.binance.com/en/support/announcement/updates-to-usd%E2%93%A2-m-futures-trading-rules-1d762daf60dd417f9d8a05d44b06a25c
- Strategy order TP/SL (OTOCO, loại trừ trailing): https://www.binance.com/en/support/faq/what-are-limit-tp-sl-orders-strategy-order-and-frequently-asked-questions-e1ee1738141c49718550fa9061be4bf3
- Binance Public Data: https://github.com/binance/binance-public-data, https://data.binance.vision

## 17.2 Sách / nguồn chỉ báo

- J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* (1978) — ATR, ADX, RSI.
- John Bollinger, *Bollinger on Bollinger Bands* (2001) — Bollinger Bands, squeeze.
- Curtis Faith, *Way of the Turtle* (2007) — 2N stop/exit, position sizing, risk 1–2%.
- Larry Connors & Cesar Alvarez, *Short Term Trading Strategies That Work* (2008) — RSI(2).
- Van Tharp, *Trade Your Way to Financial Freedom* (2006) — position sizing.

## 17.3 Ghi chú xác minh

- Thông tin phí, rate limit, Algo migration, công thức liquidation, min notional: kiểm tra tháng 11/2026.
- Demo REST host `https://demo-fapi.binance.com`: xác nhận bởi nhiều nguồn và SDK.
- Demo WS host: **chưa thống nhất giữa các nguồn** → bắt buộc tự test (bảng 4.3 mục 2).
- Số dư demo mặc định: không có cam kết chính thức → dùng sổ ảo riêng.
- Các tham số chiến lược là **adaptation** từ nguồn gốc, chưa được chứng minh trên crypto 15m; phải walk-forward.

---

# 18. Phụ lục

## A. Thuật ngữ nhanh

| Thuật ngữ | Nghĩa |
|---|---|
| R | 1 đơn vị rủi ro = số tiền bạn chấp nhận mất nếu SL khớp |
| Expectancy | Lãi kỳ vọng mỗi lệnh |
| Drawdown | Mức giảm từ đỉnh equity |
| Slippage | Trượt giá so với kỳ vọng |
| Maker/Taker | Người treo lệnh / người khớp lệnh ngay |
| Post-only | Chỉ được làm maker |
| Funding | Phí định kỳ giữa long và short |
| MMR | Maintenance margin rate |
| Algo order | Lệnh điều kiện trên Algo Service |
| Regime | Trạng thái thị trường |
| Walk-forward | Test cuốn theo thời gian |
| OCO | One-Cancels-Other (futures không có native) |
| Shadow mode | Chiến lược chạy và ghi tín hiệu/PnL ảo, không gửi lệnh thật |

## B. Mẫu nhật ký giao dịch

```csv
ts,symbol,strategy,side,entry,exit,qty,notional,sl,tp,risk_usd,pnl_usd,pnl_r,fees_usd,funding_usd,slippage_bps,regime,exit_reason,notes
```

## C. Checklist trước khi bật live

- [ ] Demo 4 tuần pass go/no-go.
- [ ] Reconcile = 0 trong 7 ngày liên tiếp.
- [ ] Kill switch test thành công 3 cấp.
- [ ] SL luôn tồn tại (audit log 100% vị thế).
- [ ] API key không quyền rút, IP whitelist.
- [ ] VPS auto-restart, alert Telegram group hoạt động (nhận được tin test).
- [ ] Backup DB tự động.
- [ ] Tham số đóng băng, có version.
- [ ] Dashboard chỉ bind `127.0.0.1`, truy cập qua SSH tunnel.
- [ ] Dashboard không có API key và không có endpoint đặt lệnh; kill switch test từ UI thành công.
- [ ] `docker compose up -d --build` từ clone sạch chạy được, 2 service healthy.
- [ ] `.dockerignore` có `.env`, `data/`, `.git`; `docker history` không lộ secret.
- [ ] Backup/restore named volume đã test; không dùng `down -v` trên prod.
- [ ] Sổ ảo + risk budget tách theo `strategy_id`.
- [ ] Nếu bật Trend live: đã có ≥ 12 tuần forward và ≥ 50 lệnh shadow/demo.
- [ ] Bạn đã đọc và hiểu incident playbook.
- [ ] Bạn chấp nhận mất 300 USD như học phí.

## D. Câu hỏi tự kiểm tra

1. Nếu giá sập 10% trong 1 phút, bot làm gì? SL có khớp không? Có slippage không?
2. Nếu WS chết 5 phút, vị thế có được bảo vệ không?
3. Nếu bot restart giữa lúc có vị thế, nó có biết SL đang ở đâu không?
4. Nếu API trả 503 khi đặt SL, bot làm gì?
5. Nếu position lệch DB, bot có tự sửa mù không?
6. Nếu funding tăng vọt, bot có đóng lệnh không?
7. Nếu 5 lệnh thua liên tiếp, bạn có đổi tham số không?
8. Nếu demo lãi 20%, bạn có tăng vốn live ngay không?

Nếu chưa trả lời được 1–6, **chưa được live**.

## E. Lệnh khởi tạo nhanh

```powershell
# Dev local (chỉ để test/backtest, không phải deploy)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install httpx websockets polars duckdb pydantic pyyaml pytest ruff

# Kiểm tra kết nối demo (không cần key)
curl https://demo-fapi.binance.com/fapi/v1/time

# Tải 1 ngày dữ liệu mẫu
curl -O https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-11-15.zip

# Deploy bằng Docker (cách chính)
cp .env.example .env          # điền API key, dashboard user/pass
docker compose build
docker compose up -d
docker compose ps             # cả 2 service phải healthy
docker compose logs -f --tail=100 engine

# Dashboard: mở SSH tunnel từ máy bạn
# ssh -L 8080:localhost:8080 bot@<vps-ip>
# rồi mở http://127.0.0.1:8080
```

---

**Kết luận:** MVP này không được thiết kế để "kiếm tiền". Nó được thiết kế để **không chết** trong lúc bạn học. Ranh giới cốt lõi: Python là bộ não duy nhất, dashboard Node.js chỉ để nhìn và bấm dừng, Trend Pullback chạy shadow trước khi có tiền thật. Nếu sau 12 tuần hệ thống vẫn chạy, sổ sách minh bạch, drawdown trong giới hạn, và bạn hiểu từng quyết định của nó — đó là thành công thật, và là nền tảng duy nhất đáng để mở rộng tiếp.
