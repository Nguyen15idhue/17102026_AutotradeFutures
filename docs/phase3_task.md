# PHASE 3 TASK — MỞ RỘNG CHIẾN LƯỢC (FUNDING CARRY)

**Tài liệu triển khai chi tiết · Phase 3/3**
Phiên bản: 1.1 · Ngày: 18/11/2026 · Tham chiếu gốc: `docs/mvp-binance-futures-bot.md` v2.0 §15.2, §15.3

> **Thay đổi lớn ở v1.1 (18/11/2026):** Trend Pullback đã được **chuyển vào Phase 1** và bật live
> (cả long + short). Do đó **P3.0–P3.5 không còn là việc phải làm** — chúng đã bị hấp thụ hoặc huỷ.
> Phase 3 giờ chỉ còn **P3.6 Funding carry**. Các mục P3.0–P3.5 giữ lại để đọc lịch sử quyết định.

---

## 0. Giải thích cơ bản — Phase 3 là gì

### 0.1 Toàn bộ kế hoạch trong 1 trang

| Phase | Nội dung | Vốn thật | Chi phí/tháng |
|---|---|---|---|
| 1 | MVP: MR + Trend (long + short), mock 2 tuần, live 300 USD 8 tuần | 300 USD | 0 USD |
| 2 | AI gate: 2 LLM phủ quyết/giảm size | giữ 300 USD | 2–7 USD |
| **3 (file này)** | **Funding carry** (delta-neutral). Trend đã ở Phase 1. | tăng dần | 2–7 USD |

### 0.2 Vì sao phải có Phase 3

Phase 1 kiếm tiền trong `RANGE` (MR) và `TREND` (Trend long + short). Phase 3 **không còn mở khoá trend** — việc đó đã làm ở spec v2.0; Phase 3 chỉ thêm **funding carry**, một nguồn thu không đánh hướng.

Phase 3 cũng là phase **nguy hiểm nhất về mặt tâm lý**, vì lúc này bạn đã có lãi (hoặc nghĩ là có) và muốn tăng size. Đây đúng là lúc dễ vi phạm §16 nhất.

### 0.3 Nội dung của Phase 3 (v1.1)

**Funding carry** — không đánh hướng. Long spot + short perp cùng khối lượng = delta-neutral; thu funding 8h/lần, rủi ro hướng gần 0. Đây là "nền an toàn" cho danh mục, nhưng cần hạ tầng spot (thêm API, thêm quản lý basis).

**Đã chuyển sang Phase 1 (không làm ở đây nữa):** Trend Pullback live long + short, `trend_dir`, khung 4h, global position manager. Xem `docs/phase1_task.md` P1.3/P1.4/P1.6 và spec §15.2.

### 0.4 Vì sao Trend **không** còn shadow trước (quyết định 18/11/2026)

Bản 1.0 yêu cầu shadow trước vì "4 tuần mock = 12–32 lệnh là không đủ kết luận". Điều đó vẫn đúng về mặt thống kê, nhưng v2.0 chọn đánh đổi khác: **bật live ngay, chấp nhận rằng 8 tuần live cũng chưa đủ 50 lệnh/nhánh**. Kết luận hợp lệ cho Trend vì thế là "ổn định vận hành, chưa đủ mẫu để nói có edge" — không phải "Trend có lãi".

### 0.5 Vì sao bật cả short (quyết định 18/11/2026)

Người vận hành chấp nhận rủi ro gap của buy-stop để rút ngắn ~3 tháng. Hai lý do phản đối cũ đã hết hiệu lực:

- **Xung đột chiều:** `SQUEEZE`-down vs `TREND`-short — Squeeze đã bị huỷ, nên không còn tranh chấp.
- **Không đủ power thống kê:** vẫn đúng, nhưng nay được ghi nhận là **giới hạn đã biết** thay vì lý do để hoãn.

Rủi ro còn lại (gap buy-stop, funding âm, multiple testing) được ghi rõ ở spec §15.2 và không được dùng để biện minh cho việc nới risk limit.

### 0.6 Định nghĩa "xong" của Phase 3

- Carry chạy được với basis và funding đo thật, delta-neutral trong giới hạn.
- Không ảnh hưởng MR/Trend đang chạy ở Phase 1 (tách `strategy_id`, tách risk budget).
- (Điều kiện) Nếu bật thêm biến thể chiến lược nào, phải có walk-forward + ghi lý do.

### 0.7 Cấu trúc phase con (v1.1)

| Mã | Phase con | Trạng thái | Ghi chú |
|---|---|---|---|
| P3.0 | Kế thừa dữ liệu shadow | ⛔ Huỷ | Không có shadow ở v2.0 (Trend live ngay) |
| P3.1 | Bật Trend trên mock | ⛔ Huỷ | Trend đã chạy trong mock 2 tuần ở P1.7 |
| P3.2 | Global position manager | ⛔ Huỷ | Không cần: Squeeze bỏ → không còn xung đột chiều; slot + correlated cap nằm ở P1.3 |
| P3.3 | Forward 12 tuần | ⛔ Huỷ | Thay bằng 8 tuần live ở P1.8 |
| P3.4 | Trend live | ⛔ Huỷ | Đã gộp vào P1.8 |
| P3.5 | (Điều kiện) bật short | ⛔ Huỷ | Short đã bật ở P1.8, rủi ro được chấp nhận |
| P3.6 | Funding carry | ⬜ Chưa | **Việc duy nhất còn lại của Phase 3**, 4–6 tuần |

---

## P3.0 — Kế thừa dữ liệu shadow (không tốn thời gian) — **ĐÃ HUỶ (v1.1)**

> Không có shadow ở v2.0: Trend chạy live ngay từ P1.8. Phần dưới chỉ để đọc lịch sử.

### Giải thích cơ bản

Bạn không bắt đầu từ số 0. Trong suốt Phase 1 (tuần 7–14) và Phase 2, Trend đã chạy shadow: tính tín hiệu đầy đủ, giả lập fill bảo thủ, ghi R ảo và **lý do bỏ lỡ**.

Bước này chỉ là đọc lại dữ liệu đó và quyết định có đủ điều kiện đi tiếp không.

### Việc cần làm

1. Truy vấn `shadow_trades` và `signals` của `strategy_id = trend_pullback`.
2. Thống kê: số tín hiệu, fill rate, R trung bình, phân phối `missed_reason`.
3. Kiểm tra 0 lỗi logic (ví dụ: signal sinh ra khi regime không phải TREND).
4. So sánh `missed_reason` để biết filter nào đang chặn quá nhiều.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Đủ mẫu | ≥ 20 tín hiệu trong 4 tuần |
| 2 | Fill rate hợp lý | ≥ 40% |
| 3 | Không lỗi logic | 0 signal sai regime |
| 4 | Có phân tích missed reason | Báo cáo 4 nhóm: no_pullback / too_deep / no_trigger / regime_filtered |

### Checklist test

- [ ] Query shadow ra đúng tập dữ liệu
- [ ] 0 signal có regime ≠ TREND
- [ ] Fill rate tính đúng công thức
- [ ] Có báo cáo missed reason
- [ ] R ảo phân phối hợp lý (đuôi phải, không phải toàn thua nhỏ)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Shadow đủ 20 tín hiệu | ⬜ Chưa | | |
| Fill rate ≥ 40% | ⬜ Chưa | | |
| Báo cáo missed reason | ⬜ Chưa | | |

### Ghi chú

- Nếu shadow < 20 tín hiệu: **không phải lỗi**, chỉ là thị trường ít trend. Chờ thêm, đừng nới điều kiện.
- Nếu fill rate < 40%: entry market có thể đang vào quá trễ sau khi giá đã chạy — xem lại `fib_max` và `trail_after_atr`.

---

## P3.1 — Bật Trend trên mock, budget 20% (4 tuần) — **ĐÃ HUỶ (v1.1)**

> Trend đã chạy trong mock 2 tuần ở P1.7 (`docs/phase1_task.md`).

### Giải thích cơ bản

Trend được cấp một "ví" riêng: 20% tổng risk budget. Nghĩa là nếu Trend lỗ sạch phần của nó, MVP (MR + Squeeze) vẫn còn 80% và không bị ảnh hưởng.

Đây là cách ly rủi ro quan trọng: một chiến lược mới chưa được chứng minh không được phép kéo cả hệ thống xuống.

### Việc cần làm

1. `trend_pullback.mode: shadow` → `live` nhưng **chỉ trên mock**.
2. Risk budget tách: `allocation.trend_pullback = 0.2`, và risk engine theo dõi riêng.
3. Sổ ảo riêng cho Trend (để PnL không lẫn).
4. Bật `allow_short: false`; vẫn ghi signal short vào shadow (miễn phí dữ liệu).
5. Spec chi tiết: regime TREND + 1h signal / 4h filter, hồi 30–61,8%, chạm EMA20/50, volume giảm, RSI 40–55; SL `swing_low − 1,5 ATR`; trailing 2 ATR sau 1,5 ATR; time stop 36 nến.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | PnL tách được | Query theo `strategy_id` ra số riêng |
| 2 | Budget không vượt 20% | Test: Trend xin thêm khi đã dùng 20% → chặn |
| 3 | 0 xung đột symbol | Log 0 trường hợp 2 chiến lược cùng symbol |
| 4 | Đủ mẫu | ≥ 50 lệnh mock |
| 5 | Signal short vẫn được ghi | `shadow_trades` có `side = short` |

### Checklist test

- [ ] `mode: live` trên mock, lệnh thật trên mock API
- [ ] PnL theo `strategy_id` đúng
- [ ] Test budget: Trend vượt 20% → chặn
- [ ] Test xung đột: MR đang mở cùng symbol → Trend bị chặn
- [ ] Signal short ghi shadow, không gửi lệnh
- [ ] Trailing dời SL đúng, không mất bảo vệ

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Trend live trên mock | ⬜ Chưa | | |
| Budget 20% tách riêng | ⬜ Chưa | | |
| ≥ 50 lệnh | ⬜ Chưa | | |
| 0 xung đột | ⬜ Chưa | | |

### Ghi chú

- Mock fill lạc quan; Trend dùng market entry nên ít bị ảnh hưởng hơn limit, nhưng SL slippage trong sóng mạnh vẫn cao.
- Không bật Trend live cùng lúc với thay đổi tham số MVP — nếu kết quả xấu, bạn không biết do cái nào.

---

## P3.2 — Global position manager (1 tuần) — **ĐÃ HUỶ (v1.1)**

> Không còn cần: Squeeze bị huỷ nên hết xung đột `SQUEEZE`-down vs `TREND`-short. Slot/chiến lược và correlated cap nằm ở P1.3.

### Giải thích cơ bản

Với 2 chiến lược, có 3 kiểu xung đột phải chặn:

1. **Cùng symbol, cùng lúc** — 2 chiến lược mở 2 lệnh trên BTCUSDT, gấp đôi risk thật.
2. **Cùng symbol, ngược chiều** — hedge vô tình, phí 2 lần, không ai thắng.
3. **Sau khi phase 3 bật short:** `TREND-short` và `SQUEEZE breakout xuống` tranh cùng symbol.

Global position manager là lớp chặn duy nhất, đặt **trước** risk engine, để không chiến lược nào tự quyết.

### Việc cần làm

1. Bảng `symbol_locks` hoặc query trực tiếp: symbol đã có position/order chưa.
2. Luật: 1 symbol = tối đa 1 chiến lược tại 1 thời điểm; ưu tiên theo thứ tự cấu hình (ví dụ MVP ưu tiên hơn Trend nếu tranh).
3. Chặn cả trường hợp ngược chiều (dù khác chiến lược).
4. Ghi `signals.blocked_reason = 'symbol_busy'`.
5. Nếu chưa bật short: vẫn viết luật cho `TREND-short` + `SQUEEZE`, chỉ cần chưa kích hoạt.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | 0 xung đột | Test 20 case tranh chấp → 20 lần chặn |
| 2 | Không deadlock | Không có symbol bị khoá vĩnh viễn sau khi position đóng |
| 3 | Có reason | 100% lần chặn có `blocked_reason` |
| 4 | Ưu tiên đúng | Test: cả 2 cùng muốn mở → chiến lược ưu tiên thắng |

### Checklist test

- [ ] Test: MR mở → Trend bị chặn cùng symbol
- [ ] Test: Trend mở → MR bị chặn cùng symbol
- [ ] Test: position đóng → symbol mở lại ngay
- [ ] Test: restart giữa lúc có lock → lock được đọc lại đúng từ DB
- [ ] Test: 2 chiến lược cùng xin trong 1 tick → chỉ 1 được mở

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Symbol lock | ⬜ Chưa | | |
| Ưu tiên chiến lược | ⬜ Chưa | | |
| 20 test case chặn | ⬜ Chưa | | |

### Ghi chú

- Lock phải **derive từ DB** (position/order thật), không giữ trong RAM — restart sẽ mất.
- Đừng dùng lock kiểu timeout ngắn: position giữ 3 giờ, lock phải theo position.

---

## P3.3 — Forward 12 tuần (8 tuần có lệnh) (8 tuần) — **ĐÃ HUỶ (v1.1)**

> Thay bằng 8 tuần live ở P1.8, với ghi nhận rằng mẫu trend sẽ không đủ 50 lệnh/nhánh.

### Giải thích cơ bản

Đây là cổng khoa học của Phase 3. Spec yêu cầu **12 tuần forward** = 4 tuần shadow (đã có) + 8 tuần có lệnh thật trên mock. Lý do: 3–8 lệnh/tuần × 12 tuần ≈ 36–96 lệnh, đủ để expectancy có ý nghĩa.

Đừng rút ngắn. 4 tuần mock chỉ cho 12–32 lệnh — đó là lý do spec cấm kết luận Trend từ 4 tuần.

### Việc cần làm

1. Chạy 8 tuần mock với Trend có lệnh, giữ nguyên tham số.
2. Báo cáo 2 tuần/lần: số lệnh, expectancy, DD, fill rate, slippage.
3. So sánh với shadow cùng kỳ: fill thật có tệ hơn giả lập không.
4. Theo dõi riêng long vs short-shadow.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Tổng forward | 12 tuần (4 shadow + 8 lệnh) |
| 2 | Số lệnh | ≥ 50 |
| 3 | Expectancy sau phí + funding + slippage | > 0 |
| 4 | Max DD trong budget 20% | không vượt |
| 5 | Không ảnh hưởng MVP | DD của MVP không tăng do Trend |

### Checklist test

- [ ] 8 tuần chạy liên tục, không đổi tham số
- [ ] ≥ 50 lệnh tích luỹ
- [ ] Report 2 tuần/lần đủ 4 bản
- [ ] So sánh shadow vs thật
- [ ] Tách PnL long vs short-shadow
- [ ] DD của MVP và Trend tách riêng

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| 8 tuần có lệnh | ⬜ Chưa | | |
| ≥ 50 lệnh | ⬜ Chưa | | |
| Expectancy > 0 | ⬜ Chưa | | |
| DD trong budget | ⬜ Chưa | | |

### Ghi chú

- Fill rate thật thấp hơn shadow đáng kể là chuyện bình thường; nếu thấp hơn > 30% thì xem lại entry.
- Không dùng kết quả 4 tuần mock để kết luận Trend có edge (§16.18).

---

## P3.4 — Trend live, risk 0,2% (4–8 tuần) — **ĐÃ HUỶ (v1.1)**

> Đã gộp vào P1.8: Trend live cả long + short, risk 0,25% → 0,5% sau checkpoint tuần 4.

### Giải thích cơ bản

Trend lên live với **risk nhỏ hơn MVP** (0,2% so với 0,25–0,5%) vì nó mới được chứng minh trên mock, chưa qua thị trường thật với slippage thật.

Đây là bước cuối của Phase 3. Nếu fail, quay lại shadow, không quay lại "tăng size".

### Việc cần làm

1. `allow_short: false`, risk 0,2%, budget riêng 20%.
2. Chạy cùng MVP trên cùng sub-account nhưng `strategy_id` tách.
3. Đo slippage riêng cho Trend (market entry nên slippage quan trọng hơn MR).
4. Nếu pass sau 8 tuần → xem xét tăng lên 0,25–0,3%, không nhảy cóc.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Slippage thật | ghi lại theo symbol; nếu > 15bps TB → dừng |
| 2 | 0 xung đột symbol | toàn kỳ |
| 3 | DD trong budget 20% | không vượt |
| 4 | Không ảnh hưởng MVP | MVP vẫn chạy đúng limit |
| 5 | Reconcile = 0 | mọi ngày |

### Checklist test

- [ ] Trend live với risk 0,2%
- [ ] PnL tách theo `strategy_id`
- [ ] Đo slippage riêng, so với mock
- [ ] Test xung đột trên live (dùng size tối thiểu)
- [ ] Test kill switch vẫn flat được cả 2 chiến lược
- [ ] Daily report hiển thị tách 2 chiến lược

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Trend live 0,2% | ⬜ Chưa | | |
| Slippage đo được | ⬜ Chưa | | |
| 0 xung đột | ⬜ Chưa | | |
| DD trong budget | ⬜ Chưa | | |

### Ghi chú

- SL của Trend rộng (1,5 ATR) → notional nhỏ → margin ít, nhưng lỗ mỗi lệnh vẫn đúng 0,2% vốn.
- Đừng bật short ở bước này. Short là P3.5 và cần điều kiện riêng.

---

## P3.5 — (Điều kiện) Bật short — **ĐÃ HUỶ (v1.1)**

> Short đã bật ở P1.8 (quyết định 18/11/2026). Rủi ro gap buy-stop được chấp nhận và ghi ở spec §15.2; không dùng việc "đã bật" để nới risk limit.

### Giải thích cơ bản

Đây là bước **có thể không bao giờ xảy ra** — và điều đó hoàn toàn ổn. Chỉ bật short khi cả 3 điều kiện dưới đây đúng, không phải khi bạn "thấy downtrend đẹp".

### Việc cần làm

1. Kiểm tra 3 điều kiện:
   - Long-trend pass: ≥ 50 lệnh, expectancy > 0 sau phí + funding + slippage, DD trong budget 20%.
   - Shadow short ≥ 50 lệnh, tách riêng `side`, **dương sau phí**.
   - Luật chặn `TREND-short` + `SQUEEZE` cùng symbol đã hoạt động (P3.2).
2. Nếu đủ: bật `allow_short: true` với risk 0,1–0,2% (thấp hơn long).
3. Đo slippage **riêng cho short** (buy-stop trong panic rally xấu hơn).
4. Bật `priceProtect`, ghi log riêng.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | 3 điều kiện đều đạt | bằng chứng bằng số |
| 2 | Risk short thấp hơn long | 0,1–0,2% |
| 3 | Slippage short đo riêng | có báo cáo |
| 4 | 0 xung đột với SQUEEZE | toàn kỳ |

### Checklist test

- [ ] Bằng chứng 3 điều kiện trong `docs/decisions.md`
- [ ] Test short SL: buy-stop fill đúng
- [ ] Test xung đột TREND-short vs SQUEEZE-down
- [ ] Đo slippage short ≥ 20 lệnh trước khi kết luận

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Long pass | ⬜ Chưa | | |
| Shadow short ≥ 50, dương | ⬜ Chưa | | |
| Bật short | ⬜ Chưa | | |

### Ghi chú

- Nếu 1 trong 3 điều kiện thiếu: **giữ `allow_short: false`** và tiếp tục ghi shadow. Không có hình phạt nào cho việc chỉ trade long.
- Đây là chỗ dễ vi phạm §16.19 nhất (bật short khi long chưa pass, hoặc chia mẫu quá sớm).

---

## P3.6 — Funding carry (phase 4 nội bộ)

### Giải thích cơ bản

Carry không đánh hướng giá. Bạn **mua spot** coin và **bán perp** cùng khối lượng: giá tăng thì spot lãi/perp lỗ (bù nhau), giá giảm thì ngược lại. Lợi nhuận đến từ **funding**: khi funding dương, bên short perp nhận tiền 8h/lần.

Ưu điểm: rủi ro hướng gần 0, dòng tiền đều. Nhược điểm: cần hạ tầng spot (API thứ 2), cần quản lý basis (chênh spot/perp), và lợi nhuận mỏng (vài %/năm trong điều kiện bình thường).

### Việc cần làm

1. Bật quyền spot cho sub-account hoặc dùng account riêng.
2. Chọn coin có funding dương ổn định + thanh khoản spot tốt.
3. Vào: mua spot X% + short perp cùng notional (delta ≈ 0).
4. Theo dõi: funding nhận, basis, phí 2 chân, rủi ro thanh lý chân perp.
5. Thoát: khi funding âm kéo dài, hoặc basis xấu.
6. Quản lý margin chân short để không bị liquidation khi giá tăng mạnh.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Delta-neutral | |spot notional − perp notional| / tổng < 1% |
| 2 | Funding đo thật | ghi từng snapshot |
| 3 | Không bị liquidation | margin chân short luôn đủ, có cảnh báo |
| 4 | Lợi nhuận ròng dương | sau phí 2 chân + basis |

### Checklist test

- [ ] Test vào/ra đồng thời 2 chân, đo lệch delta
- [ ] Test funding dương → nhận đúng số
- [ ] Test funding chuyển âm → có rule thoát
- [ ] Test cảnh báo margin chân short
- [ ] Test phí 2 chân được tính vào PnL
- [ ] Test basis: đo chênh spot/perp hàng ngày

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Hạ tầng spot | ⬜ Chưa | | |
| Vào/ra 2 chân | ⬜ Chưa | | |
| Delta < 1% | ⬜ Chưa | | |
| Funding đo thật | ⬜ Chưa | | |

### Ghi chú

- Carry là **phase 4** theo spec gốc, ở đây gộp vào Phase 3 như bước tùy chọn cuối. Chỉ làm khi P3.1–P3.4 đã ổn định.
- Rủi ro thật của carry không phải giá mà là **margin chân short**: giá tăng mạnh → perp lỗ → cần thêm margin. Phải có rule nạp margin tự động giới hạn hoặc thoát.
- Với 300 USD, carry gần như không đáng làm (lợi nhuận tuyệt đối quá nhỏ so với công sức). Cân nhắc chỉ làm khi vốn ≥ 2.000 USD.

---

## Bảng trạng thái tổng — Phase 3

| Mã | Phase con | Trạng thái | Ngày xong | Ghi chú |
|---|---|---|---|---|
| P3.0 | Kế thừa shadow | ⛔ Huỷ | 18/11/2026 | Không có shadow ở v2.0 |
| P3.1 | Trend mock, budget 20% | ⛔ Huỷ | 18/11/2026 | Đã chạy trong P1.7 |
| P3.2 | Global position manager | ⛔ Huỷ | 18/11/2026 | Squeeze bỏ → hết xung đột chiều |
| P3.3 | Forward 12 tuần | ⛔ Huỷ | 18/11/2026 | Thay bằng 8 tuần live P1.8 |
| P3.4 | Trend live 0,2% | ⛔ Huỷ | 18/11/2026 | Gộp vào P1.8 |
| P3.5 | (Điều kiện) short | ⛔ Huỷ | 18/11/2026 | Đã bật ở P1.8 |
| P3.6 | Funding carry | ⬜ Chưa | | Việc duy nhất còn lại |

**Kết thúc Phase 3 = hệ thống hoàn chỉnh:** 2 chiến lược định hướng (MR + Trend long/short), AI gate tùy chọn, dashboard, kill switch, và (tùy chọn) carry delta-neutral.

---

## Nhật ký thay đổi tài liệu

| Ngày | Phiên bản | Nội dung |
|---|---|---|
| 17/11/2026 | 1.0 | Tạo mới, tách Trend (shadow → live) + funding carry từ spec v1.6 §15.2/§15.3 |
| 18/11/2026 | 1.1 | **Thu hẹp Phase 3 còn funding carry.** Trend đã chuyển vào Phase 1 và bật live cả long + short (spec v2.0); P3.0–P3.5 huỷ, giữ lại làm lịch sử quyết định |
