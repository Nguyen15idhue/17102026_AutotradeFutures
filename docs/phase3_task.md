# PHASE 3 TASK — MỞ RỘNG CHIẾN LƯỢC (TREND + CARRY)

**Tài liệu triển khai chi tiết · Phase 3/3**
Phiên bản: 1.0 · Ngày: 17/11/2026 · Tham chiếu gốc: `docs/mvp-binance-futures-bot.md` v1.6 §15.2, §15.3

---

## 0. Giải thích cơ bản — Phase 3 là gì

### 0.1 Toàn bộ kế hoạch trong 1 trang

| Phase | Nội dung | Vốn thật | Chi phí/tháng |
|---|---|---|---|
| 1 | MVP: MR + Squeeze, demo 4 tuần, live 300 USD 8 tuần | 300 USD | 0 USD |
| 2 | AI gate: 2 LLM phủ quyết/giảm size | giữ 300 USD | 2–7 USD |
| **3 (file này)** | **Trend Pullback live** + **Funding carry** (phase con cuối) | tăng dần | 2–7 USD |

### 0.2 Vì sao phải có Phase 3

Phase 1 chỉ kiếm tiền trong `RANGE` và `SQUEEZE`. Nghĩa là **bỏ toàn bộ sóng trend** — mà crypto dành phần lớn thời gian biến động mạnh ở dạng trend. Phase 3 mở khoá phần đó.

Phase 3 cũng là phase **nguy hiểm nhất về mặt tâm lý**, vì lúc này bạn đã có lãi (hoặc nghĩ là có) và muốn tăng size. Đây đúng là lúc dễ vi phạm §16 nhất.

### 0.3 Hai mảng của Phase 3

**a) Trend Pullback** — chiến lược thứ 3, khung 1h, vào lệnh khi giá hồi 30–61,8% của một impulse trong xu hướng mạnh. Nuôi bằng trailing 2 ATR, không TP. Win rate thấp (35–45%), lãi đến từ đuôi dày.

**b) Funding carry** — không đánh hướng. Long spot + short perp cùng khối lượng = delta-neutral; thu funding 8h/lần, rủi ro hướng gần 0. Đây là "nền an toàn" cho danh mục, nhưng cần hạ tầng spot (thêm API, thêm quản lý basis).

### 0.4 Vì sao Trend phải shadow trước

Trend 1h chỉ có **3–8 lệnh/tuần trên 25 symbol**. Bốn tuần demo = 12–32 lệnh → **không đủ để kết luận**. Nếu vừa chạy vừa đánh giá, bạn sẽ kết luận bằng cảm giác.

Shadow mode cho phép bắt đầu đo **từ tuần 7 của Phase 1** mà không thêm rủi ro và không làm nhiễu kết quả MVP. Đến Phase 3, bạn đã có sẵn 8–10 tuần dữ liệu shadow.

### 0.5 Vì sao chỉ bật long trước

Định nghĩa long/short đối xứng nhưng Phase 3 **chỉ bật long** (`allow_short: false`). Ba lý do:

1. **Không đủ power thống kê.** Chia đôi long/short thì mỗi nhánh cần 12 tuần riêng để đạt ≥50 lệnh. MVP cần kết luận trong 22 tuần, không phải 34.
2. **Skew xấu hơn.** SL của short là buy-stop trong panic rally → gap + slippage tệ hơn long; ở mẫu nhỏ không phân biệt được edge với may mắn.
3. **Xung đột chiều.** Trong downtrend, `SQUEEZE` breakout xuống và `TREND-short` tranh cùng symbol — luật "1 chiến lược/symbol" hiện tại chưa phủ trường hợp này.

Điều kiện bật short (cả 3, không thoả thì không bật):

- Long-trend pass: ≥ 50 lệnh, expectancy > 0 sau phí + funding + slippage, DD trong budget 20%.
- Shadow short ≥ 50 lệnh (tách riêng, có `side`), **dương sau phí**.
- Có luật chặn: `TREND-short` và `SQUEEZE` không được cùng symbol.

### 0.6 Định nghĩa "xong" của Phase 3

- Trend live chạy ổn định, PnL tách được theo `strategy_id`.
- Không xung đột lệnh giữa 2 chiến lược trên cùng symbol (0 vi phạm trong toàn kỳ).
- Max DD của Trend trong budget 20%, không kéo MVP xuống.
- (Nếu làm carry) carry chạy được với basis và funding đo thật.

### 0.7 Cấu trúc phase con

| Mã | Phase con | Thời lượng | Cổng ra |
|---|---|---|---|
| P3.0 | Kế thừa dữ liệu shadow từ Phase 1 | 0 (đã chạy) | ≥ 20 tín hiệu, 0 lỗi logic, fill rate ≥ 40% |
| P3.1 | Bật Trend trên demo, budget 20% | 4 tuần | ≥ 50 lệnh demo, PnL tách được |
| P3.2 | Global position manager (chống xung đột) | 1 tuần | 0 xung đột trong test |
| P3.3 | Forward 12 tuần tổng (4 shadow + 8 có lệnh) | 8 tuần | expectancy > 0 sau phí |
| P3.4 | Trend live, risk 0,2% | 4–8 tuần | ổn định, DD trong budget |
| P3.5 | (Điều kiện) bật short | sau P3.4 | thoả cả 3 điều kiện §0.5 |
| P3.6 | Funding carry (phase 4 nội bộ) | 4–6 tuần | delta-neutral, funding đo thật |

---

## P3.0 — Kế thừa dữ liệu shadow (không tốn thời gian)

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

## P3.1 — Bật Trend trên demo, budget 20% (4 tuần)

### Giải thích cơ bản

Trend được cấp một "ví" riêng: 20% tổng risk budget. Nghĩa là nếu Trend lỗ sạch phần của nó, MVP (MR + Squeeze) vẫn còn 80% và không bị ảnh hưởng.

Đây là cách ly rủi ro quan trọng: một chiến lược mới chưa được chứng minh không được phép kéo cả hệ thống xuống.

### Việc cần làm

1. `trend_pullback.mode: shadow` → `live` nhưng **chỉ trên demo**.
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
| 4 | Đủ mẫu | ≥ 50 lệnh demo |
| 5 | Signal short vẫn được ghi | `shadow_trades` có `side = short` |

### Checklist test

- [ ] `mode: live` trên demo, lệnh thật trên demo API
- [ ] PnL theo `strategy_id` đúng
- [ ] Test budget: Trend vượt 20% → chặn
- [ ] Test xung đột: MR đang mở cùng symbol → Trend bị chặn
- [ ] Signal short ghi shadow, không gửi lệnh
- [ ] Trailing dời SL đúng, không mất bảo vệ

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Trend live trên demo | ⬜ Chưa | | |
| Budget 20% tách riêng | ⬜ Chưa | | |
| ≥ 50 lệnh | ⬜ Chưa | | |
| 0 xung đột | ⬜ Chưa | | |

### Ghi chú

- Demo fill lạc quan; Trend dùng market entry nên ít bị ảnh hưởng hơn limit, nhưng SL slippage trong sóng mạnh vẫn cao.
- Không bật Trend live cùng lúc với thay đổi tham số MVP — nếu kết quả xấu, bạn không biết do cái nào.

---

## P3.2 — Global position manager (1 tuần)

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

## P3.3 — Forward 12 tuần (8 tuần có lệnh) (8 tuần)

### Giải thích cơ bản

Đây là cổng khoa học của Phase 3. Spec yêu cầu **12 tuần forward** = 4 tuần shadow (đã có) + 8 tuần có lệnh thật trên demo. Lý do: 3–8 lệnh/tuần × 12 tuần ≈ 36–96 lệnh, đủ để expectancy có ý nghĩa.

Đừng rút ngắn. 4 tuần demo chỉ cho 12–32 lệnh — đó là lý do spec cấm kết luận Trend từ 4 tuần.

### Việc cần làm

1. Chạy 8 tuần demo với Trend có lệnh, giữ nguyên tham số.
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
- Không dùng kết quả 4 tuần demo để kết luận Trend có edge (§16.18).

---

## P3.4 — Trend live, risk 0,2% (4–8 tuần)

### Giải thích cơ bản

Trend lên live với **risk nhỏ hơn MVP** (0,2% so với 0,25–0,5%) vì nó mới được chứng minh trên demo, chưa qua thị trường thật với slippage thật.

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
- [ ] Đo slippage riêng, so với demo
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

## P3.5 — (Điều kiện) Bật short

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
| P3.0 | Kế thừa shadow | ⬜ Chưa | | |
| P3.1 | Trend demo, budget 20% | ⬜ Chưa | | |
| P3.2 | Global position manager | ⬜ Chưa | | |
| P3.3 | Forward 12 tuần | ⬜ Chưa | | |
| P3.4 | Trend live 0,2% | ⬜ Chưa | | |
| P3.5 | (Điều kiện) short | ⬜ Chưa | | |
| P3.6 | Funding carry | ⬜ Chưa | | |

**Kết thúc Phase 3 = hệ thống hoàn chỉnh:** 3 chiến lược (MR, Squeeze, Trend), AI gate tùy chọn, dashboard, kill switch, và (tùy chọn) carry delta-neutral.

---

## Nhật ký thay đổi tài liệu

| Ngày | Phiên bản | Nội dung |
|---|---|---|
| 17/11/2026 | 1.0 | Tạo mới, tách Trend (shadow → live) + funding carry từ spec v1.6 §15.2/§15.3 |
