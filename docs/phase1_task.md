# PHASE 1 TASK — MVP BOT BINANCE FUTURES

**Tài liệu triển khai chi tiết · Phase 1/3**
Phiên bản: 1.1 · Ngày: 17/11/2026 · Tham chiếu gốc: `docs/mvp-binance-futures-bot.md` v1.6

---

## 0. Giải thích cơ bản — Phase 1 là gì

### 0.1 Toàn bộ kế hoạch trong 1 trang

Bạn đang xây một bot tự động giao dịch **Binance USDⓈ-M Futures** (hợp đồng vĩnh viễn, ký quỹ bằng USDT). Toàn bộ kế hoạch có 3 phase nối tiếp, mỗi phase chỉ mở khi phase trước **pass cổng**:

| Phase | Nội dung | Vốn thật | Thời lượng | Chi phí/tháng |
|---|---|---|---|---|
| **1 (file này)** | MVP: 2 chiến lược + risk engine + dashboard + mock + live 300 USD | 300 USD | ~22 tuần | 0 USD (VPS sẵn có) |
| 2 | AI gate: 2 LLM phủ quyết/giảm size trước tin tức | giữ 300 USD | ~8–12 tuần | 2–7 USD |
| 3 | Trend Pullback live + (sau đó) Funding carry | tăng dần | ~14 tuần | 2–7 USD |

Phase 1 là **toàn bộ phần khó nhất**: nếu phase 1 sai, phase 2 và 3 chỉ là trang trí thêm cho một hệ thống hỏng. AI không cứu được một bot không quản nổi SL, không reconcile được position.

### 0.2 Phase 1 làm đúng những gì

Bot chỉ làm 2 việc, không hơn:

1. **Mean Reversion (MR) trong `RANGE`** — thị trường đi ngang trong hộp: mua ở biên dưới, bán ở mid. TP cố định, SL cứng, time stop 12 nến.
2. **Squeeze Breakout trong `SQUEEZE`** — hộp bị nén hết mức: chờ nến phá hộp rồi đi theo hướng phá, **không TP**, nuôi lãi bằng trailing 2 ATR.

Ngoài 2 trạng thái đó bot **không trade** (TREND, CRISIS, UNKNOWN). Trend Pullback chỉ chạy **shadow** (tính tín hiệu, ghi sổ ảo, không gửi lệnh) để lấy dữ liệu cho phase 3.

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
| P1.3 | Risk engine + Executor | 3 | 100% lệnh qua risk, kill switch OK |
| P1.4 | Mean Reversion + backtest | 4 | ≥150 lệnh, expectancy > 0 |
| P1.5 | Squeeze + gating | 5 | 2 chiến lược không đánh nhau |
| P1.6 | Paper + Dashboard v1 + Trend shadow | 6 | dashboard OK, kill switch < 2s |
| P1.7 | Mock 5.000 USD (4 tuần) | 7–10 | go/no-go §9.5 pass |
| P1.8 | Live 300 USD (8 tuần) | 15–22 | 8 tuần ổn định mới tăng size |

> Ghi chú lịch: tuần 11–14 trong spec gốc dành cho Trend mock. Ở cấu trúc mới, phần đó chuyển sang **Phase 3**, nên Phase 1 nhảy từ P1.7 (tuần 10) sang P1.8 (tuần 15) với 4 tuần đệm để sửa lỗi phát hiện trong mock.

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

- [ ] Chạy mock 72h liên tục: 0 orphan order
- [ ] Reconnect ≥ 5 lần: reconcile diff = 0 mỗi lần
- [ ] Restart container giữa lúc có position: SL còn trên sàn, bot đọc lại đúng
- [ ] Gửi trùng `clientOrderId`: không tạo lệnh thứ 2
- [ ] Giả lập 429: có backoff, không spam
- [ ] `ALGO_UPDATE` được parse đúng vào `orders`/`fills`
- [ ] `listenKey` renew sau 30 phút không mất event

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| REST + ký HMAC | ⬜ Chưa | | |
| WS market + user | ⬜ Chưa | | |
| Order state machine | ⬜ Chưa | | |
| Reconcile 5s | ⬜ Chưa | | |
| 72h mock 0 orphan | ⬜ Chưa | | |

### Ghi chú

- Đừng đặt SL bằng `STOP_MARKET` qua `/fapi/v1/order` — sẽ nhận `-4120`. Dùng `/fapi/v1/algoOrder` với `algoType=CONDITIONAL`.
- `closePosition=true` để SL tự khớp size hiện tại (chịu được partial fill và ADL).
- WS chết không được làm bot "mù": nếu market data cũ > 3s thì cấm mở lệnh mới.
- Soak 72h chạy trên **VPS sẵn có** (mock + engine cùng compose, không cần key Binance, không chờ live).
  Được hoãn sang chạy song song với P1.2, với điều kiện: (1) giữ trạng thái ⬜ cho tới khi có log/report/hash;
  (2) đóng băng code `exchange/` trong lúc soak — sửa adapter thì chạy lại từ đầu;
  (3) bắt buộc pass trước P1.7; (4) bài soak phải có traffic thật: ≥ 20–30 vòng mở/đóng lệnh,
  ≥ 5 lần drop WS + reconcile diff = 0, 1 lần restart giữa position, qua mốc renew listenKey 30 phút,
  1 lần inject 429, 1 lần gửi trùng `clientOrderId`; log RSS + WAL size mỗi giờ.

---

## P1.2 — Data + Regime engine (tuần 2)

### Giải thích cơ bản

Regime engine là bộ phân loại thị trường thành 5 nhãn. Nó là "công tắc" quyết định chiến lược nào được phép chạy. Phân loại sai thì chiến lược đúng cũng thua: fade (MR) trong lúc hộp nén sắp nổ là cách nhanh nhất để mất tiền đều.

Toàn bộ tính trên **nến đã đóng**, không bao giờ dùng nến đang chạy (look-ahead).

### Việc cần làm

1. Tải historical từ `data.binance.vision` (bulk) + backfill phần thiếu bằng REST; lưu Parquet theo symbol/ngày.
2. Aggregate 1m → 15m/1h, chỉ nến đã đóng; phát hiện gap.
3. Feature engine: ATR(14), BB(20,2σ), BBW + percentile 90 ngày, ADX(14), z-score, vol percentile, range_24h, OI, funding. Unit test bằng dữ liệu tổng hợp (biết trước kết quả).
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

- [ ] Unit test ATR/ADX/BB/z bằng dữ liệu tổng hợp pass
- [ ] Replay 2 lần → cùng kết quả
- [ ] Ngày crash lịch sử → nhãn CRISIS
- [ ] Tuần sideway → phần lớn RANGE
- [ ] Percentile BBW không bị lỗi khi chưa đủ 90 ngày dữ liệu (fallback)
- [ ] Gap dữ liệu → log warning, không tính feature trên nến thiếu

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Data pipeline Parquet | ⬜ Chưa | | |
| Aggregate 1m→15m/1h | ⬜ Chưa | | |
| Feature engine + unit test | ⬜ Chưa | | |
| Regime + hysteresis | ⬜ Chưa | | |
| Replay tất định | ⬜ Chưa | | |

### Ghi chú

- `bbw_pct` cần 90 ngày dữ liệu; những ngày đầu phải có fallback rõ ràng (ví dụ: không trade cho tới khi đủ mẫu).
- Quy tắc an toàn số 1 của toàn hệ thống: **cấm MR khi `bbw_pct < 15`**. Viết test riêng cho nó.

---

## P1.3 — Risk engine + Executor (tuần 3)

### Giải thích cơ bản

Risk engine là người gác cổng: mọi lệnh phải đi qua nó, không có đường vòng. Executor là người thi hành: đặt entry, đặt SL ngay sau khi fill, đặt TP, dời trailing bằng make-before-break.

Make-before-break nghĩa là: đặt SL mới **trước**, xóa SL cũ **sau**. Như vậy không có khoảnh khắc nào vị thế không được bảo vệ (dù chỉ 200ms).

### Việc cần làm

1. Risk engine: risk/lệnh, max positions, portfolio risk, correlation cap, margin usage cap, daily/weekly/DD, blackout, stale data, max orders/day.
2. Sizing: `size = risk$ / stop_distance`, round theo stepSize, kiểm minNotional, cap theo leverage và margin.
3. Executor: post-only entry (MR), market entry (Squeeze), SL `closePosition`, TP `closePosition`, OCO do bot quản, trailing cancel+place.
4. Kill switch 3 cấp (mềm/cứng/thủ công CLI).
5. Bảng `commands` để dashboard/CLI ghi lệnh, Python thực thi.
6. Test injection: cố tình vượt từng limit → phải bị chặn.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | 100% lệnh đi qua risk | Grep code: không có chỗ nào gọi `orders.place` ngoài executor |
| 2 | Không bypass được | 10 test injection, 10 lần bị chặn |
| 3 | SL luôn có sau fill | Audit log 100% position có `algo_id` |
| 4 | Không có 2 SL cùng lúc ngoài 200ms | Đo `openAlgoOrders` mỗi 100ms trong test trailing |
| 5 | Kill switch < 2s | Đo từ POST command tới khi flat |

### Checklist test

- [ ] Test risk: risk/lệnh vượt → chặn
- [ ] Test risk: max positions → chặn
- [ ] Test risk: portfolio risk → chặn
- [ ] Test risk: margin > 60% → chặn
- [ ] Test risk: daily loss → dừng 24h
- [ ] Test risk: blackout ±45 phút → chặn
- [ ] Test risk: stale data > 3s → chặn
- [ ] Test trailing: SL dời lên, luôn còn ≥1 SL active
- [ ] Test SL fail 3 lần → đóng market + alert
- [ ] Test kill switch 3 cấp

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Risk engine đủ limit | ⬜ Chưa | | |
| Sizing + rounding | ⬜ Chưa | | |
| Executor SL/TP/trailing | ⬜ Chưa | | |
| Kill switch 3 cấp | ⬜ Chưa | | |
| 10 test injection pass | ⬜ Chưa | | |

### Ghi chú

- `margin_usage_max: 0.60`: với TK nhỏ, margin cạn **trước** risk cap (stop 0,69% + 3x → ~21% vốn/lệnh).
- Cảnh báo mềm khi `stop% < 0,5%` — notional > 2× vốn/lệnh, phí và slippage ăn tỷ lệ R xấu hơn nhiều.

---

## P1.4 — Mean Reversion + backtest (tuần 4)

### Giải thích cơ bản

MR là chiến lược chính. Vào lệnh khi giá lệch 2σ khỏi trung bình **và** đóng nến quay lại trong band. TP về mid (gần), SL ngoài biên range (rộng hơn). Win rate kỳ vọng 45–55%.

Backtest ở bước này không phải để "tìm bộ tham số đẹp", mà để **chứng minh chiến lược không âm sau phí** và để có baseline so với mock/live sau này.

### Việc cần làm

1. Implement MR đúng spec: z ≤ −2 / ≥ +2, đóng nến trong band, `bbw_pct > 15`, spread < 2bps, không blackout.
2. Entry: limit post-only `best_bid + 1 tick`, TTL 2 nến, không đuổi giá quá 0,3 ATR.
3. Exit: SL `range_low − 1,2 ATR`, TP mid, time stop 12 nến, regime flip đóng ngay.
4. Backtest engine: event-driven 1m, fill model bảo thủ (limit chỉ khớp khi giá xuyên qua), phí maker/taker thật, funding, slippage 5bps.
5. Walk-forward: 6 tháng train / 2 tháng test, cuộn. Out-of-sample 6 tháng cuối **chỉ chạy 1 lần**.
6. Báo cáo: expectancy, WR, R distribution, DD, theo coin, theo tháng.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Số lệnh đủ mẫu | ≥ 150 |
| 2 | Expectancy sau phí/funding/slippage | > 0 |
| 3 | Max DD | < 8% |
| 4 | Dương trên nhiều coin | ≥ 60% coin |
| 5 | Out-of-sample | chạy 1 lần, kết quả ghi lại |
| 6 | Fees/gross | < 30% |

### Checklist test

- [ ] Backtest khớp unit test trên đoạn dữ liệu nhỏ biết trước kết quả
- [ ] Fill model: limit không khớp nếu giá không xuyên qua (test)
- [ ] Funding được trừ đúng ở 00/08/16 UTC
- [ ] Walk-forward chạy đủ các cửa sổ, không leak dữ liệu tương lai
- [ ] Out-of-sample chạy 1 lần, lưu report
- [ ] Báo cáo tách theo coin và theo regime

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| MR implement | ⬜ Chưa | | |
| Backtest engine + fill model | ⬜ Chưa | | |
| Walk-forward | ⬜ Chưa | | |
| Out-of-sample (1 lần) | ⬜ Chưa | | |
| Report ≥150 lệnh | ⬜ Chưa | | |

### Ghi chú

- Nếu expectancy âm: **không chỉnh tham số cho tới khi dương** — đó là overfit. Ghi lại rồi thử ở đoạn dữ liệu khác.
- Đóng băng tham số ngay khi pass, gắn version (`params-v1`) và ghi hash vào report.

---

## P1.5 — Squeeze + gating (tuần 5)

### Giải thích cơ bản

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
| Squeeze implement | ⬜ Chưa | | |
| Trailing policy | ⬜ Chưa | | |
| Global position manager | ⬜ Chưa | | |
| Backtest gộp | ⬜ Chưa | | |

### Ghi chú

- Squeeze chỉ ~1–2% số nến đủ điều kiện → 2–8 lệnh/tháng là bình thường. Đừng nới điều kiện để có thêm lệnh.
- Trailing phải dùng cancel+place (SL không modify được), và verify chỉ còn 1 SL.

---

## P1.6 — Paper trading + Dashboard v1 + Trend shadow (tuần 6)

### Giải thích cơ bản

Paper = chạy full pipeline trên dữ liệu live nhưng không gửi lệnh thật (hoặc gửi mock). Mục đích là bắt lỗi vận hành trước khi có tiền.

Dashboard là 1 trang **read-only + kill switch**. Nó chỉ đọc SQLite và ghi bảng `commands`. Nó không giữ API key, không đặt lệnh, không tính size — vì nếu dashboard bị xâm nhập, thiệt hại tối đa là "dừng bot", không phải "mất tiền".

Trend shadow = chạy chiến lược Trend, tính tín hiệu đầy đủ, nhưng **không gửi lệnh**; ghi R ảo và lý do bỏ lỡ vào `shadow_trades` để phase 3 có dữ liệu.

### Việc cần làm

1. Chạy paper 7 ngày trên dữ liệu live.
2. Metrics collector + daily report 00:05 UTC vào Telegram group.
3. Dashboard: 8 widget (status, equity, positions, orders, regime, trades, risk, alerts), WS push, basic auth, `allowlist_commands`.
4. Build dashboard image, compose 2 service, healthcheck, log rotation.
5. Trend shadow: signal + fill giả lập bảo thủ + `missed_reason`.
6. Watchdog: stale data, orphan, mismatch, WS disconnect, API error rate. Replay mode để debug.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Dashboard sống 72h không rò memory | RSS phẳng |
| 2 | Kill switch < 2s + có ack | Đo |
| 3 | Dashboard tắt → bot vẫn chạy | Test |
| 4 | Không endpoint nào đặt được lệnh | Review route |
| 5 | Shadow ghi đủ signal + lý do | ≥ 5 tín hiệu trong 7 ngày |

### Checklist test

- [ ] Dashboard không có route POST nào ngoài `/command` với allowlist
- [ ] `POST /command {action:"flatten"}` → bot flat, có ack trong DB
- [ ] Tắt dashboard container → engine không lỗi
- [ ] Daily report tới group đúng 00:05 UTC
- [ ] Shadow trade ghi đủ: entry/exit/R/missed_reason
- [ ] Replay mode ra cùng kết quả 2 lần
- [ ] Watchdog phát hiện stale data (giả lập) và alert

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Paper 7 ngày | ⬜ Chưa | | |
| Dashboard 8 widget | ⬜ Chưa | | |
| Kill switch từ UI | ⬜ Chưa | | |
| Trend shadow | ⬜ Chưa | | |
| Watchdog | ⬜ Chưa | | |

### Ghi chú

- Đổi tham số chiến lược: sửa YAML + restart. **Không** qua UI — giữ audit trail trong git.
- Command cần confirm string + token để tránh CSRF.

---

## P1.7 — Mock 5.000 USD, 4 tuần (tuần 7–10)

### Giải thích cơ bản

Đây là lần đầu hệ thống chạm thị trường đang chạy thật, nhưng bằng tiền ảo. Mock **không chứng minh edge** (fill lạc quan, không có cảm xúc, không có sự cố mạng thật) — nó chỉ chứng minh **vận hành**.

Vì vậy bot giữ **sổ ảo riêng 5.000 USD** (`equity_base`), không dùng số dư mock của Binance để tính risk. Nhờ vậy kết quả chuyển sang live 300 USD cùng thang đo %.

### Việc cần làm

1. Chạy MR + Squeeze trên mock 4 tuần, **đóng băng tham số**.
2. Trend shadow chạy song song, không tính vào PnL.
3. Mỗi ngày đọc report 5 phút; mỗi tuần review metrics + incidents.
4. Ghi lại mọi lần bot lỗi; nếu lỗi → dừng, sửa, **reset đồng hồ 4 tuần**.

### Yêu cầu cần đạt (go/no-go §9.5)

| Chỉ số | Ngưỡng |
|---|---|
| Expectancy vs backtest | lệch ≤ ±30% |
| Max DD | ≤ 1,5× backtest |
| Reconcile diff | 0 mọi ngày |
| Orphan order | 0 |
| Số lệnh | ≥ 40 |
| Sự cố nghiêm trọng | 0 |
| Slippage mô phỏng | ≤ 2 bps |
| Trend shadow | ≥ 20 tín hiệu, 0 lỗi logic, fill rate ≥ 40% |
| Chạm daily −2% | ≤ 1 ngày; nếu > 1 → hạ portfolio về 1,5% |

### Checklist test

- [ ] 4 tuần chạy liên tục, không reset
- [ ] Reconcile = 0 mỗi ngày (ghi log)
- [ ] 0 orphan order
- [ ] 0 vị thế không có SL (audit log)
- [ ] Kill switch test giữa kỳ pass
- [ ] Report cuối kỳ: expectancy, DD, fees/gross, slippage
- [ ] Shadow report: số tín hiệu, fill rate, missed reason

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| 4 tuần mock hoàn tất | ⬜ Chưa | | |
| ≥ 40 lệnh | ⬜ Chưa | | |
| Expectancy lệch ≤ ±30% | ⬜ Chưa | | |
| Reconcile = 0 | ⬜ Chưa | | |
| Go/no-go pass | ⬜ Chưa | | |

### Ghi chú

- Fail 1 mục → chạy lại mock, **không lên live sớm**.
- Đừng suy ra lợi nhuận năm từ 4 tuần này.
- Đừng đổi tham số "một chút cho hợp lý" giữa kỳ — đó là phá tính hợp lệ của toàn bộ thí nghiệm.

---

## P1.8 — Live 300 USD, 8 tuần (tuần 15–22)

### Giải thích cơ bản

Live là để trả học phí với giá rẻ nhất: slippage thật, funding thật, cảm xúc thật. Với 300 USD và risk 0,25%, kết quả cơ sở là −3% → +3% (tức −9 → +9 USD). Đây **không phải thu nhập**, đây là chi phí học.

Nguyên tắc: risk 0,25% trong 4 tuần đầu, chỉ tăng lên 0,5% nếu ổn. Max 2 vị thế. DD −6% là dừng hẳn.

### Việc cần làm

1. Sub-account riêng, API key futures + **tắt withdrawal** + IP whitelist. Nạp đúng 300 USD, không thêm.
2. Isolated margin, leverage 3x.
3. Chạy 4 tuần ở risk 0,25% → review → 4 tuần ở 0,5% nếu pass.
4. Review hàng tuần, không đổi tham số giữa tuần.
5. Đo slippage thật theo `side` và theo symbol.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Reconcile | 0 trong 7 ngày liên tiếp |
| 2 | Orphan order | 0 |
| 3 | 100% vị thế có SL | audit log |
| 4 | Max DD | < 6% |
| 5 | Kill switch | test thành công 3 cấp |
| 6 | Slippage thật | ghi lại; nếu > 10bps trung bình → dừng, xem lại universe |
| 7 | Fees/gross | < 30% |

### Checklist test

- [ ] API key không có quyền rút (kiểm tra trên Binance)
- [ ] IP whitelist đúng IP VPS
- [ ] `.env` không nằm trong image (`docker history` sạch)
- [ ] Backup DB tự động hàng ngày, đã test restore
- [ ] Kill switch 3 cấp test trên live với size tối thiểu
- [ ] Daily/weekly/DD limit đã test (dùng lệnh nhỏ, không chờ thật)
- [ ] Alert tới group cho mọi incident thật

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Sub-account + key an toàn | ⬜ Chưa | | |
| 4 tuần risk 0,25% | ⬜ Chưa | | |
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
| P1.2 | Data + Regime | ⬜ Chưa | | |
| P1.3 | Risk + Executor | ⬜ Chưa | | |
| P1.4 | MR + backtest | ⬜ Chưa | | |
| P1.5 | Squeeze + gating | ⬜ Chưa | | |
| P1.6 | Paper + Dashboard | ⬜ Chưa | | |
| P1.7 | Mock 4 tuần | ⬜ Chưa | | |
| P1.8 | Live 8 tuần | ⬜ Chưa | | |

**Cổng vào Phase 2:** P1.8 pass + 8 tuần live ổn định + expectancy > 0 sau phí.

---

## Nhật ký thay đổi tài liệu

| Ngày | Phiên bản | Nội dung |
|---|---|---|
| 17/11/2026 | 1.0 | Tạo mới, tách từ spec v1.6 |
| 17/11/2026 | 1.1 | P1.1: chốt soak 72h chạy trên VPS, cho phép hoãn song song với P1.2 kèm 4 điều kiện + tiêu chí traffic tối thiểu |
