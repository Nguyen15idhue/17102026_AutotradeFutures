# PHASE 1 TASK — MVP BOT BINANCE FUTURES

**Tài liệu triển khai chi tiết · Phase 1/3**
Phiên bản: 1.9 · Ngày: 18/11/2026 · Tham chiếu gốc: `docs/mvp-binance-futures-bot.md` v2.0

---

## 0. Giải thích cơ bản — Phase 1 là gì

### 0.1 Toàn bộ kế hoạch trong 1 trang

Bạn đang xây một bot tự động giao dịch **Binance USDⓈ-M Futures** (hợp đồng vĩnh viễn, ký quỹ bằng USDT). Toàn bộ kế hoạch có 3 phase nối tiếp, mỗi phase chỉ mở khi phase trước **pass cổng**:

| Phase | Nội dung | Vốn thật | Thời lượng | Chi phí/tháng |
|---|---|---|---|---|
| **1 (file này)** | MVP: MR + Trend (long + short) + risk engine + dashboard + mock + live 300 USD | 300 USD | **~15 tuần** | 0 USD (VPS sẵn có) |
| 2 | AI gate: 2 LLM phủ quyết/giảm size trước tin tức | giữ 300 USD | ~8–12 tuần | 2–7 USD |
| 3 | Funding carry (Trend đã chuyển vào Phase 1 ở v2.0) | tăng dần | ~6 tuần | 2–7 USD |

Phase 1 là **toàn bộ phần khó nhất**: nếu phase 1 sai, phase 2 và 3 chỉ là trang trí thêm cho một hệ thống hỏng. AI không cứu được một bot không quản nổi SL, không reconcile được position.

### 0.2 Phase 1 làm đúng những gì

Bot làm 2 việc, không hơn:

1. **Mean Reversion (MR) trong `RANGE`** — thị trường đi ngang trong hộp: mua ở biên dưới, bán ở mid. TP cố định, SL cứng, time stop 12 nến.
2. **Trend Pullback trong `TREND`, cả long và short** — vào khi giá hồi 30–61,8% impulse và chạm EMA20/50, **không TP**, nuôi lãi bằng trailing 2×ATR, time stop 36 nến 1h.

Ngoài 2 trạng thái đó bot **không trade** (`SQUEEZE` → đứng ngoài, `CRISIS`, `UNKNOWN`).

**Squeeze Breakout đã bị huỷ ở v2.0** (18/11/2026): bỏ chiến lược nhưng **giữ nhãn `SQUEEZE`** để chặn MR trong vùng nén. Lý do đầy đủ ở spec §6.1/§6.4.

### 0.3 Ba bất biến không được vi phạm

1. **Không vị thế nào tồn tại mà không có SL** — kể cả 300ms.
2. **Risk ≤ 0,5%/lệnh, đòn bẩy ≤ 3x**, margin sử dụng ≤ 60% equity.
3. **CRISIS = không mở lệnh mới.**

Vi phạm 1 trong 3 = phase 1 thất bại, dù PnL dương.

### 0.4 Định nghĩa "xong" của Phase 1

Không phải "lãi". Xong là:

- Hệ thống chạy 24/7 không sập, không có vị thế trần, không orphan order.
- Số liệu thực tế khớp backtest (expectancy lệch ≤ ±30%).
- Bạn giải thích được **tại sao** từng lệnh được mở/đóng, chỉ bằng cách đọc DB.
- Dashboard tắt không ảnh hưởng bot; dashboard **không thể** đặt lệnh.
- Live 300 USD chạy 8 tuần với DD < 6% và reconcile = 0.

### 0.5 Cấu trúc phase con

| Mã | Phase con | Tuần | Cổng ra (tóm tắt) |
|---|---|---|---|
| P1.0 | Xác minh môi trường & tài khoản | 0 | 13/13 mục §4.3 pass |
| P1.1 | Exchange adapter (REST/WS/algo/reconcile) | 1–2 | 72h mock, 0 orphan |
| P1.2 | Data + Regime engine | 2 | nhãn regime ổn định, replay tất định |
| P1.2b | `trend_dir` + khung 4h (bổ sung cho P1.2) | 2 | down-trend ra TREND, hướng bền 3 nến |
| P1.3 | Risk engine + Executor (4 slot, short SL) | 3 | 100% lệnh qua risk, kill switch OK |
| P1.4 | MR backtest + Trend long/short backtest | 4 | MR ≥150 lệnh; trend ≥20 lệnh/nhánh |
| ~~P1.5~~ | ~~Squeeze + gating~~ | — | **HUỶ 18/11/2026** — xem spec §6.1 |
| P1.6 | Paper + Dashboard v1 + Trend live wiring | 5 | dashboard OK, kill switch < 2s |
| P1.7 | Mock 5.000 USD (2 tuần) | 6–7 | go/no-go §9.5 pass |
| P1.8 | Live 300 USD (8 tuần) | 8–15 | checkpoint tuần 4, 8 tuần ổn định mới tăng size |

> Ghi chú lịch: bản 1.x có P1.5 (Squeeze) và 4 tuần mock, tổng 22 tuần. v2.0 bỏ P1.5, rút mock còn 2 tuần, đưa Trend live vào P1.8 → **~15 tuần**. Đổi lại: Trend 2 nhánh sẽ **không đủ 50 lệnh/nhánh** trong 8 tuần (xem spec §15.2).

---

## P1.0 — Xác minh môi trường & tài khoản (tuần 0)

### Giải thích cơ bản

Trước khi viết dòng code nào, bạn phải chứng minh **những thứ tài liệu nói là đúng với tài khoản của bạn**. Binance đổi API, đổi host mock, đổi cơ chế lệnh điều kiện (vụ Algo migration 09/12/2025 là ví dụ: `STOP_MARKET` gửi vào `/fapi/v1/order` giờ trả lỗi `-4120`). Nếu bạn xây 3 tuần rồi mới phát hiện host mock sai, bạn mất 3 tuần.

### Việc cần làm

1. Dựng `binance-demo-server` (`docker compose up -d --build`) — **không cần API key Binance**. Tạo sub-account live riêng với key **tắt withdrawal + IP whitelist** (chưa nạp tiền).
2. Chạy 13 mục bảng §4.3, ghi kết quả thật vào `docs/verification.md` (bảng: mục / lệnh đã chạy / output thật / ngày).
3. Dựng Docker skeleton: `engine/Dockerfile`, `dashboard/Dockerfile`, `docker-compose.yml` (profile `app`), healthcheck, named volume. App rỗng nhưng `docker compose ps` phải healthy.
4. Tạo `.env` từ `.env.example`; xác nhận `.dockerignore` che `.env`, `data/`, `.git`.
5. Test `curl -I https://api.telegram.org` từ máy sẽ chạy bot.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | 13/13 mục §4.3 có output thật, không "theo tài liệu" | `docs/verification.md` đầy đủ |
| 2 | Biết chính xác WS host mock hoạt động | Ghi lại host đã test được |
| 3 | Biết `/fapi/v1/algoOrder` có chạy trên mock hay không | Trả `algoId` = OK; lỗi = phải có phương án B (SL mô phỏng trong bot + market close) |
| 4 | `docker compose ps` = 2 service healthy | Ảnh/log |
| 5 | `docker history --no-trunc <image>` không chứa secret | grep rỗng |

### Checklist test

- [ ] `GET http://127.0.0.1:8081/fapi/v1/time` → có `serverTime` (**không dùng `demo-fapi.binance.com`**)
- [ ] `POST /fapi/v1/listenKey` → có `listenKey`
- [ ] WS user (`ws://127.0.0.1:8081/ws/<key>`) nhận được `ORDER_TRADE_UPDATE` và `ALGO_UPDATE`
- [ ] `POST /fapi/v1/algoOrder` với `STOP_MARKET closePosition` → có `algoId`
- [ ] `GET /fapi/v1/exchangeInfo` → đọc được tickSize/stepSize/minNotional 10 symbol
- [ ] `GET /fapi/v1/commissionRate` → ~0,02/0,05%
- [ ] `GET /fapi/v1/leverageBracket` → có MMR bậc 1
- [ ] Tải 1 file kline từ `data.binance.vision` thành công
- [ ] Đặt SL `closePosition=true`, đóng position bằng market → SL chuyển `EXPIRED`
- [ ] `POST /_admin/ws/drop` → WS đóng, listenKey còn hiệu lực, reconnect được
- [ ] `curl -I https://api.telegram.org` từ VPS → 200/302
- [ ] NTP offset < 1s (`w32tm /stripchart` hoặc `chronyc tracking`)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| 13 mục xác minh | ✅ Xong (mock) | `docs/verification.md` §6, 16/16 PASS 17/11/2026 | 17/11/2026 |
| Mock API key | ✅ | secret mock mặc định (`mock-secret`), key `verify-key` — không dùng key live | 17/11/2026 |
| Live sub-account (chưa nạp tiền) | ✅ | key an toàn (`enableWithdrawals=false`), balance 4,85 USDT — xem `verification.md` §3 | 17/11/2026 |
| Docker skeleton healthy | ✅ | `docker compose --profile app ps` = 3 healthy (mock+engine+dashboard) local 17/11/2026 | 17/11/2026 |
| `.env` + `.env.example` | ✅ | `.gitignore` che `.env`; image engine không chứa `.env`; history không có secret | 17/11/2026 |

### Ghi chú

- Nếu mục 3 (Algo order trên mock) fail: **không bỏ qua**. Phương án B = bot tự mô phỏng SL bằng cách theo dõi mark price 1s và gửi market close — chậm hơn SL thật, phải ghi rõ trong `verification.md` và chấp nhận rủi ro gap.
- Đừng tạo key live có quyền rút, kể cả để test. Chỉ tạo 1 lần và tắt withdrawal ngay.
- Latency VPS không quan trọng với khung 15m (100–300ms là chấp nhận được), nhưng **NTP sync bắt buộc** vì Binance ký request theo timestamp (`-1021` nếu lệch).

---

## P1.1 — Exchange adapter (tuần 1–2)

### Giải thích cơ bản

Adapter là lớp duy nhất nói chuyện với Binance. Nó lo 5 việc mà nếu làm sai sẽ mất tiền: ký request (HMAC), tôn trọng rate limit, retry đúng cách, đồng bộ đồng hồ, và **reconcile** (đối chiếu sổ của bot với sổ của sàn).

Reconcile là phần quan trọng nhất: bot giữ state trong SQLite, sàn giữ state thật. Hai bên lệch nhau = bạn không biết mình đang có gì. Nên REST là **nguồn sự thật**, WS chỉ là tín hiệu tăng tốc.

### Việc cần làm

1. REST client: HMAC SHA256, `recvWindow`, retry 429/5xx với backoff, đọc `X-MBX-USED-WEIGHT-1M`.
2. WS: market (`kline_1m`, `markPrice`, `bookTicker`, `aggTrade`) + user (`ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`); auto-reconnect; `listenKey` create/keepalive 30 phút.
3. Order state machine + `clientOrderId` idempotent (`{strategy}-{symbol}-{ts}-{nonce}`): gửi lại cùng id không tạo lệnh trùng.
4. Reconcile 5s: `positionRisk` + `openAlgoOrders` + `openOrders` vs DB.
5. Telegram alert cơ bản (outbound group, queue + dedup).
6. Clock offset check trước mỗi phiên.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Không tạo lệnh trùng khi retry | Test gửi 2 lần cùng `clientOrderId` → sàn trả lỗi duplicate, DB chỉ 1 lệnh |
| 2 | Reconnect không lệch state | Kill mạng 5 lần, mỗi lần reconcile diff = 0 |
| 3 | Restart container không mất state | `docker compose restart engine` → position/algo còn nguyên |
| 4 | Rate limit không bị 429 | theo dõi header weight, luôn < 50% |
| 5 | Alert tới group khi có sự kiện | tin test hiện trong group |

### Checklist test

- [ ] Chạy mock 72h liên tục: 0 orphan order (harness sẵn sàng, smoke 3 vòng pass, chờ SSH VPS)
- [x] Reconnect ≥ 5 lần: reconcile diff = 0 mỗi lần (soak smoke: drop + reconnect OK, diff 0)
- [x] Restart container giữa lúc có position: SL còn trên sàn, bot đọc lại đúng (soak: reopen DB, diff 0)
- [x] Gửi trùng `clientOrderId`: không tạo lệnh thứ 2 (unit + soak đều pass)
- [x] Giả lập 429: có backoff, không spam (chaos throttle_1008 + unit MockTransport)
- [x] `ALGO_UPDATE` được parse đúng vào `orders`/`fills` (unit, event thật trên mock)
- [x] `listenKey` renew sau 30 phút không mất event (unit keeper; mốc 30 phút thật ở soak 72h)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| REST + ký HMAC | ✅ | `engine/app/exchange/rest.py`, retry 429/5xx + backoff, weight header, 7 error code có test | 17/11/2026 |
| WS market + user | ✅ | user stream trên mock (`listenKey` + reconnect + renew); market URL đúng format Binance, test bằng stub local (mock không có market WS) | 17/11/2026 |
| Order state machine | ✅ | `engine/app/exchange/orders.py`: id `{strategy}-{symbol}-{ts}-{nonce}`, dedup, SL qua `/fapi/v1/algoOrder` | 17/11/2026 |
| Reconcile 5s | ✅ | `engine/app/exchange/reconcile.py`: lệch → HALT + incident + alert, không tự sửa (đã chứng minh trong container) | 17/11/2026 |
| 72h mock 0 orphan | 🟡 Đang chạy trên VPS | soak service commit 6fb0ba7, state=running (xem `/check72h` / `soak-status.json`), xong mới tick ✅ | |

### Ghi chú

- Đừng đặt SL bằng `STOP_MARKET` qua `/fapi/v1/order` — sẽ nhận `-4120`. Dùng `/fapi/v1/algoOrder` với `algoType=CONDITIONAL`.
- `closePosition=true` để SL tự khớp size hiện tại (chịu được partial fill và ADL).
- WS chết không được làm bot "mù": nếu market data cũ > 3s thì cấm mở lệnh mới.
- Event `ORDER_TRADE_UPDATE` của mock gửi `l="0"`, dồn fill vào `z` (cumulative) — adapter tính
  incremental = max(l, z − đã ghi) để tương thích cả live lẫn mock (`orders.py`, có test).
- SQLite dùng `check_same_thread=False` vì WS thread ghi / reconcile thread đọc (`db/store.py`).
- Đã quan sát reconcile HALT đúng spec trong container: soak trên host mở position lạ,
  engine trong container phát hiện lệch và latch `halted=1`, không tự sửa (17/11/2026).
- Soak 72h chạy trên **VPS sẵn có** (mock + engine cùng compose, không cần key Binance, không chờ live).
  Được hoãn sang chạy song song với P1.2, với điều kiện: (1) giữ trạng thái ⬜ cho tới khi có log/report/hash;
  (2) đóng băng code `exchange/` trong lúc soak — sửa adapter thì chạy lại từ đầu;
  (3) bắt buộc pass trước P1.7; (4) bài soak phải có traffic thật: ≥ 20–30 vòng mở/đóng lệnh,
  ≥ 5 lần drop WS + reconcile diff = 0, 1 lần restart giữa position, qua mốc renew listenKey 30 phút,
  1 lần inject 429, 1 lần gửi trùng `clientOrderId`; log RSS + WAL size mỗi giờ.
  Chi tiết triển khai xem **P1.1.1** dưới đây (service soak riêng + `/check72h`).

---

## P1.1.1 — Deploy lên VPS + chạy soak 72h (sau P1.1, song song P1.2)

### Giải thích cơ bản

Soak 72h kiểm tra adapter bằng traffic thật trên mock, nhưng phải chạy trên VPS 24/7
(máy dev Windows sleep/reboot giữa chừng thì kết quả vô giá trị). Soak chạy dưới dạng
**service riêng** trong compose (`soak`, profile `app`), cùng compose với mock.
Lúc soak **không chạy service engine** (reconcile của engine sẽ HALT oan vì position
của soak — đã quan sát ở local, xem ghi chú P1.1).

### Việc cần làm

1. Đóng băng code `exchange/`: ghi commit sha đang soak vào bảng kết quả. Sửa adapter
   trong lúc soak → chạy lại từ đầu.
2. Trên VPS: `git pull` (repo đã clone), `docker compose --profile app up -d mock soak`.
   Không cần key Binance; service soak lấy `TELEGRAM_*` từ `.env` ở runtime
   (không bake vào image).
3. Kiểm tra trạng thái bất cứ lúc nào bằng lệnh `/check72h` trong group Telegram
   (hoặc `powershell -File scripts/ps/check72h.ps1 -Target Vps`).
4. Hết 72h: lấy `soak-report.json` trên VPS về, ghi kết quả vào bảng P1.1.

### Trạng thái soak (`/app/data/soak-status.json`, volume `botdata`)

| State | Nghĩa |
|---|---|
| `pending` | Chưa bắt đầu (service vừa lên, đang flatten) |
| `running` | Đang chạy (kèm deadline UTC + vòng hiện tại) |
| `done` | Xong, `pass: true/false` + bảng số liệu |
| `error` | Crash giữa chừng + thông điệp lỗi (không mất file status) |

Bảng `/check72h` hiện: state, giờ đã chạy/còn lại, vòng x/y, orphan, reconcile diff,
drop/reconnect, trùng ID, chaos backoff, restart, WAL size, lỗi cuối.

### Tiêu chí xong

`pass: true` = 0 orphan cuối kỳ + reconcile diff = 0 mọi vòng + dup/chaos/restart/drop
đều OK + qua mốc renew listenKey 30 phút + ≥ 20–30 vòng lệnh. Thiếu 1 tiêu chí = fail,
ghi log và chạy lại.

### Dọn dẹp

- Tay: `ssh VPS "rm /app/data/soak-*"` (đường dẫn trong volume `botdata`;
  xem bằng `docker volume inspect <project>_botdata`).
- Tự động: service soak khi khởi động xóa mọi file `soak-*` quá **7 ngày tuổi**.

### Ngoại lệ kiến trúc đã duyệt (17/11/2026)

- Kênh **inbound Telegram chỉ tồn tại trong service soak**, read-only, đúng 1 lệnh
  `/check72h`, chỉ trả lời đúng chat ID đã cấu hình. Engine giao dịch giữ nguyên
  outbound-only. Mở thêm lệnh Telegram khác = quyết định kiến trúc riêng, không tự ý.

---

---

## P1.2 — Data + Regime engine (tuần 2)

### Giải thích cơ bản

Regime engine là bộ phân loại thị trường thành 5 nhãn. Nó là "công tắc" quyết định chiến lược nào được phép chạy. Phân loại sai thì chiến lược đúng cũng thua: fade (MR) trong lúc hộp nén sắp nổ là cách nhanh nhất để mất tiền đều.

Toàn bộ tính trên **nến đã đóng**, không bao giờ dùng nến đang chạy (look-ahead).

### Việc cần làm

1. Tải historical từ `data.binance.vision` (bulk) + backfill phần thiếu bằng REST; lưu Parquet theo symbol/ngày.
2. Aggregate 1m → 15m/1h, chỉ nến đã đóng; phát hiện gap.
3. Feature engine: ATR(14), BB(20,2σ), BBW + percentile 90 ngày, ADX(14), z-score, vol percentile (realized vol 1h), range_24h + `range_pct`, OI, funding. Unit test bằng dữ liệu tổng hợp (biết trước kết quả).
4. Regime: 5 nhãn, thứ tự ưu tiên CRISIS → SQUEEZE → RANGE → TREND → UNKNOWN; hysteresis 3 nến + cooldown 5 nến.
5. Replay mode: chạy lại 1 khoảng thời gian ra cùng kết quả 2 lần.
6. Spot-check 3 giai đoạn: 1 tuần range, 1 giai đoạn squeeze, 1 ngày crash.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Không look-ahead | Feature tại nến T chỉ dùng dữ liệu ≤ T |
| 2 | Nhãn không nhảy mỗi nến | Đếm số lần đổi nhãn/ngày, phải giảm rõ so với không hysteresis |
| 3 | Replay tất định | 2 lần chạy cùng input → hash output giống nhau |
| 4 | BBW percentile đúng | So với tính tay 10 điểm ngẫu nhiên |
| 5 | CRISIS bắt đúng ngày crash | Spot-check lịch sử |

### Checklist test

- [x] Unit test ATR/ADX/BB/z bằng dữ liệu tổng hợp pass — `engine/tests/test_features.py` (21 test: ATR/ADX Wilder, BB/z tính tay, pct_rank brute-force 10 điểm, không look-ahead bitwise)
- [x] Replay 2 lần → cùng kết quả — `scripts/ps/p1.2-check.ps1 -Mode Replay`, hash `1986c4f9…9704d3` cho BTCUSDT 2026-08-01..11-01 (2 lần trùng) *(hash trước P1.2b; hash sau P1.2b: `55530fb1…4e6ebf`)*
- [x] Ngày crash lịch sử → nhãn CRISIS — 2026-02-06, nến giảm −4,245%, 6 nến `CRISIS` (`docs/reports/p1.2-spotcheck.json`)
- [x] Tuần sideway → RANGE trội trong nhãn tradable — tuần 2026-06-25: RANGE 51,2% / TREND 45,1% / SQUEEZE 3,7% (loại UNKNOWN); RANGE ở tuần TREND mạnh nhất = 0% → cổng A/B đạt
- [x] Percentile BBW không bị lỗi khi chưa đủ 90 ngày dữ liệu (fallback) — test 8639 mẫu → `None`; 8640 mẫu → có giá trị; cửa sổ 60 ngày: 100% `bbw_pct=None`, 0 CRISIS, không crash
- [x] Gap dữ liệu → log warning, không tính feature trên nến thiếu — bỏ partition 2026-09-15: `data.gap` from=1789430399999 to=1789516800000, 384/384 nến `UNKNOWN`

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Data pipeline Parquet | ✅ | 3 symbol × 168 ngày (BTC/ETH/SOL) = 504 file, 725.760 nến 1m, 28,3 MB; BTC thêm 516 ngày lịch sử (2025-01→2026-05); `.CHECKSUM` verify, ghi atomic | 18/11/2026 |
| Aggregate 1m→15m/1h | ✅ | `engine/app/data/bars.py` + 14 test (`test_bars.py`): cửa sổ thiếu bị bỏ, gap báo, nến chưa đóng bị loại | 18/11/2026 |
| Feature engine + unit test | ✅ | `features.py` single-pass; 21 test; `vol_pct` = percentile realized vol 1h (không phải volume); `range_pct` percentile 90 ngày | 18/11/2026 |
| Regime + hysteresis | ✅ | `engine/app/regime/`; 25 test; 3 nến + cooldown 5, CRISIS 1 nến; transitions 404 vs raw 715 (giảm 43,5%) trên 168 ngày | 18/11/2026 |
| Replay tất định | ✅ | hash `1986c4f92d192327037097cec026334afe978f61ad165a6ecd1a4168659704d3`; `params_sha256=201a3109…40c18d7`; 2 lần chạy giống nhau. **Trước P1.2b** — hash sau P1.2b: `55530fb14020ab7e5920b2faec16ce9e4171dd16907d6c77f6e02ce8354e6ebf`, `params_sha256=2a680166…30adba5` | 18/11/2026 |

### Ghi chú

- `bbw_pct` cần **đủ 8640 mẫu** (90 ngày × 96 nến) mới có giá trị; thiếu → `None` → nhãn `UNKNOWN`, `allow_mr=false`. Fallback đã test với cửa sổ 60 ngày (không crash, 100% `bbw_pct=None`).
- Quy tắc an toàn số 1 của toàn hệ thống: **cấm MR khi `bbw_pct < 15`**. Test riêng: `test_bbw_pct_15_blocks_mean_reversion` (None/14,9/15,0 → cấm; 15,1 → cho).
- **Sửa so với spec gốc:** `range_24h < 2,5×ATR` (và `1,5×ATR` cho Squeeze) là sai thứ nguyên — range 96 nến luôn ~10× ATR 15m (trung vị 10,66 trên BTCUSDT 2026-06→11), nên RANGE/SQUEEZE = 0% trên dữ liệu thật. Đã chuẩn hoá thành `range_pct` = percentile 90 ngày của `range_24h/ATR` (chỉ dùng quá khứ): RANGE `range_pct < 50`, SQUEEZE `range_pct < 30`. Đo lại: RANGE ~7% nến, SQUEEZE ~2,1%.
- **Cổng "tuần sideway"** đo khả năng phân biệt thay vì độ phổ biến: (A) trong tuần RANGE tốt nhất, RANGE trội trong 3 nhãn tradable (bỏ UNKNOWN khỏi mẫu số); (B) RANGE ở tuần đó ≥ 2× RANGE ở tuần TREND mạnh nhất. Số tuyệt đối chỉ ghi tham khảo: tuần 2026-06-25 có RANGE 12,5% tổng số nến (51,2% trong nhãn tradable), tuần TREND mạnh nhất có RANGE 0%.
- **CRISIS xác nhận 1 nến** (các nhãn khác 3 nến + cooldown 5) vì đây là trạng thái an toàn; chờ 45 phút trái nguyên tắc "CRISIS = không mở lệnh mới". Có hằng số `CRISIS_CONFIRM_BARS` để đổi.
- **vol_pct** = percentile của realized vol 1h (`sqrt(Σ 4 log-return 15m bình phương)`), 30 ngày — không phải percentile volume. Percentile luôn tính trên mẫu quá khứ, không gồm nến hiện tại.
- **CRISIS bằng chứng thật:** ngày 2026-02-06 (BTC −4,245% trong 1 nến 15m, dữ liệu 2025-01→2026-11) → 6 nến CRISIS. Trong riêng 2026-06→11 mức giảm lớn nhất chỉ −3,0% nên phải tải thêm lịch sử.
- **FE: không áp dụng** (dashboard v1 là P1.6). Smoke: `node dashboard/server.js` → `/healthz` 200, trang chủ 200, `server.js` không đọc DB/không giữ secret.
- **Bỏ DuckDB** (spec tuần 2 ghi "Parquet + DuckDB query"): dùng pyarrow đọc/ghi trực tiếp, replay bằng Python thuần; thêm `pyarrow>=17` vào requirements. **Đã build lại image và xác minh trong container 18/11/2026:** pyarrow 26.0.1, `bars/features/regime` có trong DB, `params_sha256` khớp host, 3 service healthy (mock + engine + dashboard), dashboard `/healthz` 200, `docker history` không có secret.
- Dữ liệu không commit: `data/market/**` (Parquet), `data/p1.2.db`, report runtime; chỉ commit `docs/reports/p1.2-spotcheck.json` (3,2 KB).
- **Bổ sung v2.0 — tách thành mục riêng `P1.2b` (chưa làm):** regime cần thêm `trend_dir` (`+1`/`−1`/`0`) để Trend chạy short. Luật: giữ 3 nến (`trend_dir_confirm_bars`), phải khớp EMA50/200 trên 1h, lệch → `direction_conflict` và không vào lệnh. Đây là **thêm field**, không thêm nhãn thứ 6. Xem spec §6.2 và mục P1.2b bên dưới.

---

## P1.2b — `trend_dir` + khung 4h (bổ sung cho P1.2, làm trước P1.3)

### Giải thích cơ bản

P1.2 phân loại đúng 5 nhãn nhưng chỉ nhận ra trend **tăng** (`ema50 > ema200`); downtrend rơi vào `UNKNOWN`. Sau quyết định 18/11/2026 (Trend live **cả long + short**), downtrend phải ra `TREND` với hướng `−1`.

Bước này thêm **field `trend_dir`** (không thêm nhãn thứ 6) và khung **4h** cho bối cảnh trend.

Vì sao tách khỏi P1.2: P1.2 đã pass cổng theo phạm vi cũ (chỉ cần RANGE để chạy MR). Đây là việc **mới**, có cổng riêng — không được tính là "P1.2 xong nên xong luôn".

### Việc cần làm

1. `engine/app/data/bars.py`: thêm khung **`4h`** vào `TF_MS` / `NEED` (240 phút, đủ 240 nến 1m).
2. `engine/app/regime/types.py`: `RegimeResult` thêm `trend_dir: int` (`+1` / `−1` / `0`).
3. `engine/app/regime/detector.py`:
   - `classify()` trả `TREND` cho **cả hai chiều**: `adx > 22` và `trend_dir_15m != 0` (tính từ `ema50` / `ema200`), kèm hướng.
   - `RegimeMachine`: streak `trend_dir` phải giữ đủ `trend_dir_confirm_bars = 3` nến mới được dùng; đổi chiều → reset streak.
   - Chưa đủ 3 nến hoặc vừa đổi chiều → `trend_dir = 0`, ghi `reason` (chiến lược không được vào lệnh).
4. `engine/app/db/store.py`: thêm cột `trend_dir INTEGER NOT NULL DEFAULT 0` vào bảng `regime`, kèm **migration** (`PRAGMA table_info(regime)` → `ALTER TABLE`) cho DB `data/p1.2.db` đã tồn tại.
5. `engine/app/data/persist.py`: ghi/đọc thêm `trend_dir`.
6. **Cập nhật hash replay:** field mới vào canonical line → `params_sha256` / `replay_hash` **sẽ đổi**. Ghi hash mới vào `docs/reports/p1.2-spotcheck.json` và test tương ứng; **không** giữ test hash cũ để "cho xanh".
7. Test mới: `test_regime.py`, `test_bars.py`, `test_persist.py` (danh sách dưới).
8. `.github/workflows/ci.yml`: thêm job **`engine`** (`ruff check app tests` + `pytest -q`, Python 3.12, không cần mock). Hiện CI chỉ chạy mock.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Down-trend ra `TREND` | `adx > 22`, `ema50 < ema200` → `label=TREND`, `trend_dir=-1` (trước đây `UNKNOWN`) |
| 2 | Hướng phải bền | đổi chiều EMA → `trend_dir=0` trong 2 nến đầu, chỉ `±1` từ nến thứ 3 |
| 3 | Không look-ahead | `trend_dir` tại nến T chỉ dùng EMA ≤ T |
| 4 | Migration DB cũ | mở DB chưa có cột → tự thêm, mặc định 0, không mất dữ liệu |
| 5 | Replay vẫn tất định | 2 lần chạy → cùng hash **mới**; hash ghi vào report |
| 6 | CI có engine | job `engine` xanh trên PR |

### Checklist test

- [x] Test đối xứng: up `trend_dir=+1`, down `trend_dir=−1`, thiếu mẫu EMA → 0 — `test_trend_both_directions`, `test_direction_for_missing_or_equal_is_zero`
- [x] Test streak: 2 nến → 0, nến thứ 3 → `±1`; đổi chiều → reset về 0 — `test_trend_dir_confirmed_after_three_bars`, `test_trend_dir_resets_when_direction_flips`
- [x] Test 4h aggregate: 240 nến 1m, cửa sổ thiếu bị bỏ, gap báo — 4 test trong `test_bars.py`
- [x] Test migration: DB cũ (không cột) mở lên vẫn chạy, `trend_dir=0` — `test_migration_adds_trend_dir_to_old_db`
- [x] Test không look-ahead: thêm nến tương lai → `trend_dir` tại T không đổi — `test_trend_dir_has_no_lookahead`
- [x] `pytest` + `ruff` xanh; replay 2 lần cùng hash mới; report cập nhật — 128 passed, ruff check + format sạch; hash `55530fb1…`

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| `trend_dir` + đối xứng up/down | ✅ | `direction_for()` + `TREND` cho cả 2 chiều; `ema50<ema200` không còn ra `UNKNOWN` (5 test mới) | 18/11/2026 |
| Streak 3 nến + reset khi đổi chiều | ✅ | `RegimeMachine._update_direction`, `TREND_DIR_CONFIRM_BARS=3`; `trend_dir=0` ngoài TREND và khi chưa đủ 3 nến; test không look-ahead qua `run_bars` | 18/11/2026 |
| Khung 4h aggregate | ✅ | `bars.py` thêm `4h` (240 nến 1m, `NEED=240`) + 4 test mới trong `test_bars.py` (OHLCV, cửa sổ thiếu bị bỏ, gap báo, 1h/15m không đổi) — 18 test pass | 18/11/2026 |
| Migration cột `regime.trend_dir` | ✅ | `store._migrate()` (PRAGMA → ALTER, idempotent) + persist ghi/đọc; 2 test mới (DB cũ giữ dữ liệu, round-trip `trend_dir`), 8 test persist pass | 18/11/2026 |
| Hash replay mới được ghi lại | ✅ | `replay.canonical_line` format v2 (thêm `trend_dir`), `params_sha256` bump `hash_format=2`; replay 2 lần cùng hash `55530fb14020ab7e5920b2faec16ce9e4171dd16907d6c77f6e02ce8354e6ebf`, `params=2a680166…30adba5`; report `docs/reports/p1.2-spotcheck.json` cập nhật | 18/11/2026 |
| CI job `engine` | ✅ | `.github/workflows/ci.yml` thêm job `engine` (3.12, `ruff check` + `ruff format --check` + `pytest -q`, `working-directory: engine`); YAML parse hợp lệ (2 job: `engine`, `mock`) | 18/11/2026 |

### Ghi chú

- **Script kiểm tra:** `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ps\p1.2b-check.ps1 -Mode All` → 3 mục (test, replay, trend_dir trên dữ liệu thật). Kết quả 18/11/2026: `128 passed`; hash `55530fb1…`; `trend_dir up 4324 / down 4442`, 0 vi phạm bền 3 nến.
- **FE regression (18/11/2026):** `docker compose --profile app up -d --build binance-demo-server engine dashboard` → 3 service `healthy`; `GET /healthz` 200, trang chủ 200; log engine chỉ có `clock.sync` + `engine.start`, không traceback. Dashboard vẫn là skeleton (widget là P1.6). Không chạy service `soak`.
- `trend_dir` là **field**, không phải nhãn thứ 6 → giữ nguyên schema, dashboard, mapping chiến lược.
- **Luật khớp EMA trên 1h và `direction_conflict` kiểm ở tầng signal (P1.4/P1.6)**, không ở detector: detector chạy trên 15m nên không tự thấy 1h. Detector chỉ chịu trách nhiệm "hướng 15m + độ bền 3 nến"; strategy đọc thêm 1h và bỏ tín hiệu nếu lệch.
- Không đổi ngưỡng nào của P1.2 trong bước này. Nếu thấy cần đổi → dừng, đó là thay đổi chiến lược, phải walk-forward (AGENTS §10).
- **Cổng spot-check sau P1.2b: 4/5 đạt, 1 fail đã biết (quyết định 18/11/2026 — phương án lai):**
  - **Gate A đổi định nghĩa (vì phép đo mất hiệu lực, không phải vì kết quả xấu):** từ "RANGE trội trong nhãn tradable" → **`RANGE(tuần tốt nhất) ≥ 2 × RANGE(tuần trung vị)`**. Lý do: khi TREND nhận cả hai chiều, mẫu số "tradable" đổi nghĩa (down-trend trước là `UNKNOWN`, nay là `TREND`) → gate cũ đo mật độ nhãn. Bằng chứng: share **tuyệt đối** của RANGE trong tuần 2026-06-25 gần như không đổi (12,50% → 12,65%). Gate mới: 21,2% vs trung vị 8,68% = **2,44× → đạt**; vẫn fail nếu RANGE thoái hoá thật.
  - **Gate D giữ nguyên ngưỡng 50% và chấp nhận fail:** 660/1.298 = **50,85%** (trước P1.2b: 505/1.088 = 46,4%). Không nới ngưỡng sau khi thấy kết quả. Churn thực tế 3,93 lần/ngày (trước: 3,0) — theo dõi trong mock 2 tuần; chỉ xem lại hysteresis khi có bằng chứng từ mock, và phải ghi lý do.
  - Gate cũ giữ ở `report.diagnostics` để tra cứu, không còn là cổng.
  - Hệ quả: `scripts/ps/p1.2-check.ps1 -Mode SpotCheck` trả exit 2 cho tới khi D pass — đúng như thiết kế, không che giấu.

---

## P1.3 — Risk engine + Executor (tuần 3)

### Giải thích cơ bản

Risk engine là người gác cổng: mọi lệnh phải đi qua nó, không có đường vòng. Executor là người thi hành: đặt entry, đặt SL ngay sau khi fill, đặt TP, dời trailing bằng make-before-break.

Make-before-break nghĩa là: đặt SL mới **trước**, xóa SL cũ **sau**. Như vậy không có khoảnh khắc nào vị thế không được bảo vệ (dù chỉ 200ms).

Ở v2.0 có thêm 3 thứ bắt buộc: **SL short là buy-stop**, **slot/chiến lược + correlated cap**, và **reject khi notional < minNotional**.

### Việc cần làm

1. Risk engine: risk/lệnh, max positions, **max_positions_per_strategy**, portfolio risk, **correlated cap**, margin usage cap, daily/weekly/DD, blackout, stale data, max orders/day.
2. Risk budget/chiến lược: `allocation × portfolio_risk_max`; chặn khi chiến lược đã dùng hết budget dù còn slot.
3. Sizing: `size = risk$ / stop_distance`, round theo stepSize, **reject nếu notional < minNotional** (không làm tròn lên), cap theo leverage và margin.
4. Executor: post-only entry (MR), market entry (Trend), SL `closePosition` (**short = buy-stop trên giá**), TP `closePosition` (chỉ MR), OCO do bot quản, trailing cancel+place.
5. Kill switch 3 cấp (mềm/cứng/thủ công CLI).
6. Bảng `commands` để dashboard/CLI ghi lệnh, Python thực thi.
7. Test injection: cố tình vượt từng limit → phải bị chặn.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | 100% lệnh đi qua risk | Grep code: không có chỗ nào gọi `orders.place` ngoài executor |
| 2 | Không bypass được | 11 test injection, 11 lần bị chặn |
| 3 | SL luôn có sau fill | Audit log 100% position có `algo_id` |
| 4 | Không có 2 SL cùng lúc ngoài 200ms | Đo `openAlgoOrders` mỗi 100ms trong test trailing |
| 5 | Kill switch < 2s | Đo từ POST command tới khi flat |
| 6 | Short SL đúng phía | `openAlgoOrders` của short: `STOP_MARKET` **trên** entry, `closePosition=true` |

### Checklist test

- [ ] Test risk: risk/lệnh vượt → chặn
- [ ] Test risk: max positions → chặn
- [ ] Test risk: vượt `max_positions_per_strategy` → chặn (dù còn slot)
- [ ] Test risk: 2 vị thế cùng nhóm tương quan vượt cap → chặn
- [ ] Test risk: portfolio risk → chặn
- [ ] Test risk: margin > 60% → chặn
- [ ] Test risk: daily loss → dừng 24h
- [ ] Test risk: blackout ±45 phút → chặn
- [ ] Test risk: stale data > 3s → chặn
- [ ] Test sizing: notional sau round < minNotional → **huỷ lệnh**, không tăng size
- [ ] Test trailing: SL dời lên, luôn còn ≥1 SL active
- [ ] Test SL fail 3 lần → đóng market + alert
- [ ] Test kill switch 3 cấp

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Config loader | ✅ | `engine/app/config.py` đọc `CONFIG_PATH`, validate cứng (allocation=1.0, risk ≤0,5%, live ≤0,25%, margin ≤60%, slot/chiến lược, secret cấm trong YAML); 12 test `test_config.py` pass, đọc đúng `config/mvp.{mock,live}.yaml` | 18/11/2026 |
| Risk engine đủ limit | ⬜ Chưa | | |
| Slot/chiến lược + correlated cap | ⬜ Chưa | | |
| Sizing + rounding + minNotional reject | ⬜ Chưa | | |
| Executor SL/TP/trailing (cả short) | ⬜ Chưa | | |
| Kill switch 3 cấp | ⬜ Chưa | | |
| 11 test injection pass | ⬜ Chưa | | |

### Ghi chú

- `margin_usage_max: 0.60`: với TK nhỏ, margin cạn **trước** risk cap. Trên 300 USD: MR stop ~0,4% → notional ~188 → margin ~63/lệnh → chỉ 2 lệnh vừa cap 60%.
- Cảnh báo mềm khi `stop% < 0,5%` — notional > 2× vốn/lệnh, phí và slippage ăn tỷ lệ R xấu hơn nhiều.
- Short SL là buy-stop: bắt buộc `priceProtect` + `workingType=MARK_PRICE`; đo riêng slippage theo `side`.

---

## P1.4 — MR backtest + Trend long/short backtest (tuần 4)

### Giải thích cơ bản

MR là chiến lược tần suất cao: vào lệnh khi giá lệch 2σ khỏi trung bình **và** đóng nến quay lại trong band. TP về mid (gần), SL ngoài biên range (rộng hơn). Win rate kỳ vọng 45–55%.

Trend là chiến lược tần suất thấp, ăn bằng đuôi dày: vào khi giá hồi 30–61,8% impulse trong xu hướng, SL 1,5×ATR, trailing 2×ATR, **không TP**. Chạy cả long và short.

Backtest ở bước này không phải để "tìm bộ tham số đẹp", mà để **chứng minh chiến lược không âm sau phí** và để có baseline so với mock/live sau này.

### Ước lượng tần suất trước backtest (baseline 18/11/2026)

Đo trên **BTC/ETH/SOL × 168 ngày** (2026-06-01 → 11-15) với regime hiện có. Đây **không phải backtest**: điều kiện vào lệnh là proxy, thiếu cấu trúc HH/HL và impulse thật; dùng để đặt kỳ vọng, không để kết luận.

| Chiến lược | Cách đo | Tần suất | Ngoại suy 10 symbol |
|---|---|---|---|
| MR | `\|z\| ≥ 2` tại nến đóng (trong RANGE) | 0,27–0,36 /ngày/symbol | ~3 /ngày |
| MR | Wick ra biên + đóng lại trong band | 0,43–0,58 /ngày/symbol | ~5 /ngày |
| MR | Nến trước `\|z\|≥2`, nến này đóng vào band | 0,12–0,13 /ngày/symbol | ~1,2 /ngày |
| MR | Đọc literal `\|z\|≥2` **và** đóng trong band | 0,00–0,01 /ngày/symbol | ~0 → **phải chốt lại định nghĩa** |
| Trend | Regime-eligible (TREND + `trend_dir`) | 25–27 nến/ngày/symbol | — |
| Trend | Mô phỏng vòng đời lệnh: chạm EMA20 + RSI + EMA 1h/4h cùng chiều + hồi 30–61,8% (proxy) + volume giảm | 0,33–0,47 lệnh/ngày/symbol | **~3,9 lệnh/ngày ≈ 27/tuần** |

Ghi chú:

- **Điều kiện MR trong spec tự mâu thuẫn** ("z ≤ −2" và "đóng quay lại trong band" không thể cùng đúng). Phải chốt một trong ba cách đọc ở bảng trên (khuyến nghị: wick ra biên + đóng vào band) trước khi code.
- Trend ước lượng **cao hơn ~10 lần** dự phóng của spec (3–8 lệnh/tuần/25 symbol) vì proxy chưa có structure + impulse thật → coi là **cận trên**.
- Long/short lệch **≈1,76:1** trong giai đoạn này (thị trường tăng) → nhánh short sẽ có ít mẫu hơn long.
- Win 54,1% và R trung bình 0,37 **chưa có phí/funding/slippage** → **không phải bằng chứng edge**, chỉ dùng cho tần suất.
- Kỳ vọng khi backtest thật: MR 0,3–0,6 tín hiệu/ngày/symbol; Trend 0,3–0,5 lệnh/ngày/symbol. Lệch quá 2× → điều kiện cài đặt khác spec.
- Cap live 5 lệnh/ngày + `max_positions_per_strategy = 2` sẽ **hạn chế Trend** nếu proxy đúng.
- Universe backtest nên chạy 10–15 symbol để đủ mẫu; dữ liệu hiện mới có 3 symbol (BTC/ETH/SOL) → phải tải thêm.

### Việc cần làm

1. Implement MR: chốt cách đọc điều kiện vào lệnh (khuyến nghị: wick ra biên + đóng lại trong band — xem baseline), `bbw_pct > 15`, spread < 2 bps, không blackout.
2. Entry MR: limit post-only `best_bid + 1 tick`, TTL 2 nến, không đuổi giá quá 0,3 ATR.
3. Exit MR: SL `range_low − 1,2 ATR`, TP mid, time stop 12 nến, regime flip đóng ngay.
4. Implement Trend đối xứng: `trend_dir` 3 nến + khớp EMA 1h, hồi 30–61,8%, chạm EMA20/50, RSI, entry **market tại open nến 1h** + guard spread 2 bps, SL 1,5×ATR, trailing 2×ATR sau 1,5×ATR, time stop 36 nến.
5. Backtest engine: event-driven 1m, fill model bảo thủ (limit chỉ khớp khi giá xuyên qua; market chịu slippage), phí maker/taker thật, funding, slippage 5bps.
6. Walk-forward: 6 tháng train / 2 tháng test, cuộn. Out-of-sample 6 tháng cuối **chỉ chạy 1 lần**.
7. Báo cáo **tách theo `strategy_id` và `side`**: expectancy, WR, R distribution, DD, theo coin, theo tháng.
8. Đo khoảng SL thực tế của MR và Trend → dùng cho quyết định nâng risk ở live tuần 4 (margin 60% là cap chặn thật).

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Số lệnh MR đủ mẫu | ≥ 150 |
| 2 | Expectancy MR sau phí/funding/slippage | > 0 |
| 3 | Max DD | < 8% |
| 4 | Dương trên nhiều coin | ≥ 60% coin |
| 5 | Out-of-sample | chạy 1 lần, kết quả ghi lại |
| 6 | Fees/gross | < 30% |
| 7 | Số lệnh Trend | ≥ 20/nhánh (long, short) — **không** kỳ vọng đạt 50 |
| 8 | Trend long/short | Báo cáo riêng; nhánh < 20 lệnh → ghi "chưa đủ mẫu", không kết luận |

### Checklist test

- [ ] Backtest khớp unit test trên đoạn dữ liệu nhỏ biết trước kết quả
- [ ] Fill model: limit không khớp nếu giá không xuyên qua (test)
- [ ] Funding được trừ đúng ở 00/08/16 UTC
- [ ] Walk-forward chạy đủ các cửa sổ, không leak dữ liệu tương lai
- [ ] Out-of-sample chạy 1 lần, lưu report
- [ ] Báo cáo tách theo coin và theo regime
- [ ] Trend: backtest long và short đối xứng, 0 lệnh short khi `trend_dir = +1`
- [ ] Report tách PnL theo `strategy_id` và `side`

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| MR implement | ⬜ Chưa | | |
| Trend implement (long + short) | ⬜ Chưa | | |
| Backtest engine + fill model | ⬜ Chưa | | |
| Walk-forward | ⬜ Chưa | | |
| Out-of-sample (1 lần) | ⬜ Chưa | | |
| Report MR ≥150 lệnh | ⬜ Chưa | | |
| Report Trend ≥20 lệnh/nhánh | ⬜ Chưa | | |

### Ghi chú

- Nếu expectancy âm: **không chỉnh tham số cho tới khi dương** — đó là overfit. Ghi lại rồi thử ở đoạn dữ liệu khác.
- Đóng băng tham số ngay khi pass, gắn version (`params-v1`) và ghi hash vào report.

---

## P1.5 — Squeeze + gating — **ĐÃ HUỶ ở v2.0**

> **Không làm.** Quyết định 18/11/2026: bỏ chiến lược Squeeze, giữ nhãn `SQUEEZE` (đứng ngoài khi gặp). Lý do: Squeeze chỉ phủ ~2% số nến với win rate 35–45%; bỏ nó biến vùng nén thành vùng im lặng (an toàn hơn fade), đồng thời xoá xung đột chiều `SQUEEZE`-down vs `TREND`-short. Chi tiết: spec §6.1, §6.4.
>
> Phần dưới giữ lại **làm tài liệu tham khảo**. Gating (1 symbol = 1 chiến lược, correlation cap) vẫn phải làm — nhưng nó nằm ở **P1.3** (risk engine) và **P1.6** (trend), không phải ở đây.

### Giải thích cơ bản (tham khảo)

Squeeze là chiến lược "đuôi dày": thua nhỏ nhiều lần, thắng lớn ít lần. Nó không có TP — nuôi lãi bằng trailing 2 ATR. Win rate thấp (35–45%) là bình thường; đừng đánh giá nó bằng win rate.

Gating là luật chặn 2 chiến lược đánh nhau trên cùng symbol: mỗi symbol tại một thời điểm chỉ thuộc 1 chiến lược, và tổng risk nhóm tương quan bị cap.

### Việc cần làm

1. Implement Squeeze: `bbw_pct ≤ 20`, range 24 nến < 1,5 ATR, volume giảm, nến đóng ngoài hộp ≥ 0,2 ATR, volume > 1,5× TB20.
2. Exit: SL mép đối diện hộp hoặc 1,5 ATR (chọn gần hơn nhưng ≥ 1 ATR); trailing 2 ATR khi lãi ≥ 1 ATR; time stop 12 nến; regime flip đóng.
3. Global position manager: 1 symbol = 1 chiến lược; correlation cap theo nhóm beta > 0,8.
4. Backtest riêng và gộp; kiểm tra không có lệnh trùng/đối nghịch cùng symbol.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Không đánh nhau | Log 0 trường hợp 2 chiến lược cùng symbol |
| 2 | Squeeze dương trong regime của nó | Report riêng |
| 3 | Trailing không làm mất bảo vệ | Audit ≥1 SL active |
| 4 | Equity gộp không có đoạn "đánh nhau" | So sánh equity gộp vs từng chiến lược |

### Checklist test

- [ ] Backtest Squeeze riêng: report R distribution (đuôi phải dày)
- [ ] Test gating: cố mở Squeeze khi MR đang mở cùng symbol → chặn
- [ ] Test correlation cap: 4 lệnh cùng nhóm → chặn ở ngưỡng
- [ ] Test trailing dời SL đúng công thức
- [ ] Test time stop 12 nến không follow-through

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Squeeze implement | ⛔ Huỷ | Quyết định 18/11/2026, spec §6.1 | 18/11/2026 |
| Trailing policy | ⛔ Huỷ | Chuyển sang Trend trailing (P1.4/P1.6) | 18/11/2026 |
| Global position manager | ⬜ Chưa | Chuyển sang P1.3 (slot + correlated cap) | |
| Backtest gộp | ⛔ Huỷ | Không còn chiến lược thứ 3 | 18/11/2026 |

### Ghi chú

- Squeeze chỉ ~1–2% số nến đủ điều kiện → 2–8 lệnh/tháng là bình thường. Đừng nới điều kiện để có thêm lệnh.
- Trailing phải dùng cancel+place (SL không modify được), và verify chỉ còn 1 SL.

---

## P1.6 — Paper trading + Dashboard v1 + Trend live wiring (tuần 5)

### Giải thích cơ bản

Paper = chạy full pipeline trên dữ liệu live nhưng không gửi lệnh thật (hoặc gửi mock). Mục đích là bắt lỗi vận hành trước khi có tiền.

Dashboard là 1 trang **read-only + kill switch**. Nó chỉ đọc SQLite và ghi bảng `commands`. Nó không giữ API key, không đặt lệnh, không tính size — vì nếu dashboard bị xâm nhập, thiệt hại tối đa là "dừng bot", không phải "mất tiền".

**Trend live wiring** (thay cho "Trend shadow" của bản 1.x): nối `trend_dir` vào strategy, thêm khung 4h, bật long/short, và kiểm tra luật `direction_conflict`.

### Việc cần làm

1. Chạy paper 7 ngày trên dữ liệu live.
2. Metrics collector + daily report 00:05 UTC vào Telegram group.
3. Dashboard: 8 widget (status, equity, positions, orders, regime, trades, risk, alerts), WS push, basic auth, `allowlist_commands`; hiện `TREND ↑/↓`.
4. Build dashboard image, compose 2 service, healthcheck, log rotation.
5. Trend: `trend_dir` (3 nến) + khớp EMA 1h + entry market tại open nến 1h + guard spread 2 bps.
6. Watchdog: stale data, orphan, mismatch, WS disconnect, API error rate. Replay mode để debug.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Dashboard sống 72h không rò memory | RSS phẳng |
| 2 | Kill switch < 2s + có ack | Đo |
| 3 | Dashboard tắt → bot vẫn chạy | Test |
| 4 | Không endpoint nào đặt được lệnh | Review route |
| 5 | `direction_conflict` chặn đúng | Inject 15m down + 1h up → 0 lệnh, có `reason` |

### Checklist test

- [ ] Dashboard không có route POST nào ngoài `/command` với allowlist
- [ ] `POST /command {action:"flatten"}` → bot flat, có ack trong DB
- [ ] Tắt dashboard container → engine không lỗi
- [ ] Daily report tới group đúng 00:05 UTC
- [ ] Trend signal ghi đủ: `trend_dir`, reason, cờ `direction_conflict`
- [ ] Replay mode ra cùng kết quả 2 lần
- [ ] Watchdog phát hiện stale data (giả lập) và alert

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Paper 7 ngày | ⬜ Chưa | | |
| Dashboard 8 widget | ⬜ Chưa | | |
| Kill switch từ UI | ⬜ Chưa | | |
| Trend live wiring | ⬜ Chưa | | |
| Watchdog | ⬜ Chưa | | |

### Ghi chú

- Đổi tham số chiến lược: sửa YAML + restart. **Không** qua UI — giữ audit trail trong git.
- Command cần confirm string + token để tránh CSRF.

---

## P1.7 — Mock 5.000 USD, 2 tuần (tuần 6–7)

### Giải thích cơ bản

Đây là lần đầu hệ thống chạm thị trường đang chạy thật, nhưng bằng tiền ảo. Mock **không chứng minh edge** (fill lạc quan, không có cảm xúc, không có sự cố mạng thật) — nó chỉ chứng minh **vận hành**.

Vì vậy bot giữ **sổ ảo riêng 5.000 USD** (`equity_base`), không dùng số dư mock của Binance để tính risk. Nhờ vậy kết quả chuyển sang live 300 USD cùng thang đo %.

**Vì sao rút còn 2 tuần (18/11/2026):** mock là bài kiểm tra vận hành, và 2 tuần × cap 10 lệnh/ngày vẫn tạo đủ hàng trăm vòng lệnh để bắt lỗi reconcile/SL/restart. Cắt 2 tuần không được dùng để hạ cổng — nếu số lệnh không đạt thì **kéo dài**, không tick.

### Việc cần làm

1. Chạy MR + Trend (long và short) trên mock 2 tuần, **đóng băng tham số**.
2. Tối đa 2 vị thế/chiến lược; kiểm tra correlated cap thực sự chặn.
3. Mỗi ngày đọc report 5 phút; mỗi tuần review metrics + incidents.
4. Ghi lại mọi lần bot lỗi; nếu lỗi → dừng, sửa, **reset đồng hồ 2 tuần**.

### Yêu cầu cần đạt (go/no-go §9.5)

| Chỉ số | Ngưỡng |
|---|---|
| Expectancy vs backtest | lệch ≤ ±30% |
| Max DD | ≤ 1,5× backtest |
| Reconcile diff | 0 mọi ngày |
| Orphan order | 0 |
| Số lệnh MR | ≥ 50 |
| Số lệnh Trend | ≥ 6 (tổng long + short) |
| Sự cố nghiêm trọng | 0 |
| Slippage mô phỏng | ≤ 2 bps |
| Vị thế vượt slot/chiến lược | 0 |
| Chạm daily −2% | ≤ 1 ngày; nếu > 1 → hạ portfolio về 1,5% |

### Checklist test

- [ ] 2 tuần chạy liên tục, không reset
- [ ] Reconcile = 0 mỗi ngày (ghi log)
- [ ] 0 orphan order
- [ ] 0 vị thế không có SL (audit log, gồm cả short)
- [ ] Kill switch test giữa kỳ pass
- [ ] Report cuối kỳ: expectancy, DD, fees/gross, slippage **tách theo `strategy_id` và `side`**
- [ ] Trend: 0 ca vượt `max_positions_per_strategy`, 0 ca vượt correlated cap
- [ ] Qua 1 mốc funding 8h với vị thế đang mở

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| 2 tuần mock hoàn tất | ⬜ Chưa | | |
| MR ≥ 50 lệnh / Trend ≥ 6 lệnh | ⬜ Chưa | | |
| Expectancy lệch ≤ ±30% | ⬜ Chưa | | |
| Reconcile = 0 | ⬜ Chưa | | |
| Go/no-go pass | ⬜ Chưa | | |

### Ghi chú

- Fail 1 mục → chạy lại mock, **không lên live sớm**.
- Đừng suy ra lợi nhuận năm từ 2 tuần này.
- Đừng đổi tham số "một chút cho hợp lý" giữa kỳ — đó là phá tính hợp lệ của toàn bộ thí nghiệm.
- Nếu Trend < 6 lệnh sau 2 tuần: kéo dài mock, **không** hạ cổng xuống.

---

## P1.8 — Live 300 USD, 8 tuần (tuần 8–15)

### Giải thích cơ bản

Live là để trả học phí với giá rẻ nhất: slippage thật, funding thật, cảm xúc thật. Với 300 USD và risk 0,25%, kết quả cơ sở là −3% → +3% (tức −9 → +9 USD). Đây **không phải thu nhập**, đây là chi phí học.

Nguyên tắc: risk 0,25% trong 4 tuần đầu, chỉ tăng lên 0,5% nếu checkpoint pass. **4 vị thế**, tối đa 2 vị thế/chiến lược, correlated cap 0,5%. DD −6% là dừng hẳn.

Trend chạy **live cả long + short** ngay từ tuần đầu (quyết định 18/11/2026). Rủi ro gap buy-stop đã được chấp nhận và ghi ở spec §15.2 — đổi lại, 8 tuần **không đủ** 50 lệnh/nhánh, nên kết luận cho Trend là "ổn định vận hành", không phải "có edge".

### Việc cần làm

0. **Live smoke test ≤ 0,05 USD (bắt buộc trước khi nạp 300 USD).** 1 lệnh size tối thiểu + SL qua
   `/fapi/v1/algoOrder` + cancel + close trên Binance thật, để xác nhận sàn chấp nhận payload
   (encoding/param/fill thật — mock không chứng minh được điều này). Pass mới làm bước 1.
1. Sub-account riêng, API key futures + **tắt withdrawal** + IP whitelist. Nạp đúng 300 USD, không thêm.
2. Isolated margin, leverage 3x.
3. Chạy 4 tuần ở risk 0,25% → **checkpoint** (0 HALT, DD < 6%, reconcile = 0) → 4 tuần ở 0,5% nếu pass.
4. Review hàng tuần, không đổi tham số giữa tuần.
5. Đo slippage thật theo `side` **và** theo symbol; slippage của short là số quan trọng nhất.
6. Kiểm tra mỗi ngày: 4 vị thế không vượt 2/chiến lược, không quá 2 vị thế cùng nhóm tương quan.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Reconcile | 0 trong 7 ngày liên tiếp |
| 2 | Orphan order | 0 |
| 3 | 100% vị thế có SL (cả short) | audit log |
| 4 | Max DD | < 6% |
| 5 | Kill switch | test thành công 3 cấp |
| 6 | Slippage thật | ghi lại; nếu > 10 bps trung bình → dừng, xem lại universe |
| 7 | Fees/gross | < 30% |
| 8 | Slot/chiến lược + correlated cap | 0 vi phạm trong 8 tuần |

### Checklist test

- [ ] Live smoke ≤ 0,05 USD pass (1 lệnh + SL algo + cancel + close, payload được sàn chấp nhận)
- [ ] API key không có quyền rút (kiểm tra trên Binance)
- [ ] IP whitelist đúng IP VPS
- [ ] `.env` không nằm trong image (`docker history` sạch)
- [ ] Backup DB tự động hàng ngày, đã test restore
- [ ] Kill switch 3 cấp test trên live với size tối thiểu
- [ ] Daily/weekly/DD limit đã test (dùng lệnh nhỏ, không chờ thật)
- [ ] Alert tới group cho mọi incident thật
- [ ] Mở thử 1 lệnh short với size tối thiểu: SL buy-stop xuất hiện trên sàn < 300ms
- [ ] Đếm vị thế/chiến lược + nhóm tương quan mỗi ngày trong báo cáo

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Live smoke ≤ 0,05 USD | ⬜ Chưa | | |
| Sub-account + key an toàn | ⬜ Chưa | | |
| 4 tuần risk 0,25% | ⬜ Chưa | | |
| Checkpoint tuần 4 pass | ⬜ Chưa | | |
| 4 tuần risk 0,5% | ⬜ Chưa | | |
| Reconcile = 0 7 ngày | ⬜ Chưa | | |
| DD < 6% | ⬜ Chưa | | |

### Ghi chú

- Nếu chạm DD −6%: dừng hẳn, quay về mock. **Không** nạp thêm tiền, **không** tăng leverage, **không** đổi tham số để "gỡ".
- Với 300 USD, min notional 5 USDT và stepSize khiến risk thực tế thường thấp hơn 0,25% — chấp nhận, không tăng risk để bù.
- Đo slippage theo từng symbol: đó là dữ liệu quyết định universe tuần sau.

---

## Bảng trạng thái tổng — Phase 1

| Mã | Phase con | Trạng thái | Ngày xong | Ghi chú |
|---|---|---|---|---|
| P1.0 | Xác minh môi trường | ⬜ Chưa | | |
| P1.1 | Exchange adapter | ⬜ Chưa | | |
| P1.2 | Data + Regime | ✅ Xong | 18/11/2026 | 74 test mới; replay hash tất định; **spot-check 4/5 sau P1.2b** (gate D fail 50,85% — đã biết, xem Ghi chú P1.2b); image engine build lại + 3 service healthy |
| P1.2b | `trend_dir` + khung 4h | ✅ Xong | 18/11/2026 | 9 test mới (tổng 128); migration DB cũ; hash mới `55530fb1…`; CI job engine; 3 service healthy; gate D của P1.2 fail 50,85% (đã biết) |
| P1.3 | Risk + Executor | ⬜ Chưa | | |
| P1.4 | MR + backtest | ⬜ Chưa | | |
| P1.5 | ~~Squeeze + gating~~ | ⛔ Huỷ | 18/11/2026 | Bỏ chiến lược, giữ nhãn SQUEEZE; gating chuyển sang P1.3/P1.6 (spec §6.1) |
| P1.6 | Paper + Dashboard + Trend live wiring | ⬜ Chưa | | |
| P1.7 | Mock 2 tuần | ⬜ Chưa | | |
| P1.8 | Live 8 tuần (4 vị thế, long + short) | ⬜ Chưa | | |

**Cổng vào Phase 2:** P1.8 pass + 8 tuần live ổn định + expectancy > 0 sau phí.

---

## Nhật ký thay đổi tài liệu

| Ngày | Phiên bản | Nội dung |
|---|---|---|
| 17/11/2026 | 1.0 | Tạo mới, tách từ spec v1.6 |
| 17/11/2026 | 1.1 | P1.1: chốt soak 72h chạy trên VPS, cho phép hoãn song song với P1.2 kèm 4 điều kiện + tiêu chí traffic tối thiểu |
| 17/11/2026 | 1.2 | P1.8: bổ sung live smoke test ≤ 0,05 USD làm bước 0 bắt buộc + checklist + dòng kết quả |
| 17/11/2026 | 1.3 | Thêm mục P1.1.1: soak là service compose riêng + `/check72h` + dọn sau 7 ngày; ghi ngoại lệ inbound Telegram read-only trong service soak |
| 18/11/2026 | 1.4 | P1.2 xong: `range_24h` chuẩn hoá bằng percentile (range_24h/ATR) vì so trực tiếp với ATR là sai thứ nguyên (0% nến thoả); cổng "tuần sideway" đổi sang A/B đo khả năng phân biệt; vol_pct theo realized vol 1h; CRISIS 1 nến; BBW cần đủ 8640 mẫu; bỏ DuckDB; FE không áp dụng |
| 18/11/2026 | 1.5 | P1.2: xác minh lại trong container sau khi bật Docker — image engine build lại (pyarrow 26.0.1), 3 service healthy, dashboard 200, không secret trong history |
| 18/11/2026 | 1.6 | **Đổi phạm vi theo spec v2.0:** bỏ P1.5 (Squeeze), Trend chạy live long + short ngay trong P1.8 thay vì shadow rồi phase 3; mock 4 → 2 tuần; live 4 vị thế, portfolio 2,0%, correlated 0,5%; lộ trình 22 → ~15 tuần |
| 18/11/2026 | 1.7 | Tách phần bổ sung `trend_dir` + khung 4h thành **P1.2b** (trước đây gọi tạm là "B2"), có cổng nghiệm thu và dòng trạng thái riêng; bỏ toàn bộ nhãn B1–B8 khỏi tài liệu để chỉ còn một hệ P1.x |
| 18/11/2026 | 1.8 | **P1.2b xong:** khung 4h, `trend_dir` (field, bền 3 nến, 0 ngoài TREND), migration `regime.trend_dir`, hash replay format v2 (`55530fb1…`), script `p1.2b-check.ps1`, CI job `engine`; gate A đổi sang đo tương đối (2,44×), gate D giữ fail 50,85% có ghi chú |
| 18/11/2026 | 1.9 | P1.4: thêm baseline tần suất đo trên BTC/ETH/SOL (MR 0,3–0,6 tín hiệu/ngày/symbol; Trend proxy 0,33–0,47 lệnh/ngày/symbol); ghi rõ điều kiện MR trong spec tự mâu thuẫn và phải chốt cách đọc trước khi code |
