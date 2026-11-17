# PHASE 2 TASK — AI GATE (LỚP PHỦ QUYẾT)

**Tài liệu triển khai chi tiết · Phase 2/3**
Phiên bản: 1.0 · Ngày: 17/11/2026 · Tham chiếu gốc: `docs/mvp-binance-futures-bot.md` v1.6 §15.1

---

## 0. Giải thích cơ bản — Phase 2 là gì

### 0.1 Toàn bộ kế hoạch trong 1 trang

| Phase | Nội dung | Vốn thật | Chi phí/tháng |
|---|---|---|---|
| 1 | MVP: 2 chiến lược + risk engine + dashboard + mock + live 300 USD | 300 USD | 0 USD |
| **2 (file này)** | AI gate: 2 LLM đọc tin, phủ quyết hoặc giảm size | giữ 300 USD | **2–7 USD** |
| 3 | Trend Pullback live + (sau đó) Funding carry | tăng dần | 2–7 USD |

### 0.2 AI gate KHÔNG phải cái gì

Đây là chỗ hiểu sai nhiều nhất, nên nói ngay:

- **Không phải bot AI dự đoán giá.** Nó không nhìn chart, không nói "BTC sẽ tăng".
- **Không phải trigger.** Nó không bao giờ tạo ra lệnh. Tín hiệu vẫn do MR/Squeeze của phase 1 sinh ra.
- **Không nằm trên hot path.** Nó chạy async 1–15 phút, kết quả được cache. Loop chính không bao giờ chờ nó.

### 0.3 AI gate là gì

Nó là **một hệ số nhân 0..1** áp lên size:

```
risk_multiplier = 1.0  → mở lệnh bình thường
risk_multiplier = 0.5  → mở nửa size
risk_multiplier = 0.0  → không mở lệnh mới (nhưng KHÔNG đóng lệnh đang mở)
```

Cơ chế: đọc tin tức + lịch macro → hỏi 2 model độc lập → nếu 2 model đồng ý có sự kiện rủi ro ảnh hưởng symbol đó → giảm/chặn. Nếu 2 model bất đồng → **multiplier = 0** (thà bỏ lệnh còn hơn mở trong lúc không chắc).

### 0.4 Vì sao dùng 2 model

Một model có thể bịa (hallucinate) hoặc hiểu sai tin. Hai model khác nhà cung cấp, khác kiến trúc, cùng đọc một input:
- Đồng ý → tăng độ tin cậy.
- Bất đồng → tín hiệu "không đáng tin" → chặn.

Đây là biện pháp rẻ nhất để giảm false negative (bỏ sót rủi ro) mà không cần tự train model.

### 0.5 Model và chi phí thật

| Vai trò | Model | Giá in / out (USD / 1M token) | Context |
|---|---|---|---|
| Triage nhanh | **Z.ai GLM 5.3 Flash** | 0,0399 / 0,0784 | 1.048.576 |
| Reasoner | **DeepSeek V4 Flash 0731** | 0,0434 / 0,30 | 1,0M |

Giả định 1 lần đánh giá = 4.000 token in + 700 token out mỗi model:

```
GLM 5.3 Flash/call       = 4.000×0,0399/1M + 700×0,0784/1M ≈ 0,000215 USD
DeepSeek V4 Flash/call   = 4.000×0,0434/1M + 700×0,30/1M   ≈ 0,000384 USD
1 cặp đồng thuận                                         ≈ 0,00060 USD
```

| Tần suất | Cặp call/ngày | USD/tháng | Ghi chú |
|---|---|---|---|
| 15 phút | 96 | ≈ 1,7 | khuyến nghị |
| 5 phút | 288 | ≈ 5,2 | chỉ khi cần phản ứng nhanh |
| Chỉ khi có headline mới | 20–60 | **≈ 0,4–1,4** | tốt nhất về chi phí |

Cộng 30% cho retry/timeout → **2–7 USD/tháng**. Cap cứng trong code: `ai_budget_usd_per_day: 0.25`.

### 0.6 Định nghĩa "xong" của Phase 2

- AI gate chạy 8 tuần liên tục, không lần nào làm chậm/block loop chính.
- Chứng minh được (bằng số) AI gate **có ích hay không**: so sánh expectancy của lệnh có multiplier < 1.0 vs = 1.0.
- Không có false negative nghiêm trọng: không bỏ sót sự kiện lớn nào khiến lỗ > 1R.
- Chi phí ≤ ngưỡng đã đặt.

Nếu sau 8 tuần không chứng minh được lợi ích → **tắt AI gate**, đây là kết quả hợp lệ và tiết kiệm.

### 0.7 Cấu trúc phase con

| Mã | Phase con | Thời lượng | Cổng ra |
|---|---|---|---|
| P2.0 | Chuẩn bị: nguồn tin, schema, budget | 1 tuần | schema + validator + budget cap chạy được |
| P2.1 | Ingest tin tức & lịch macro | 1 tuần | ≥ 1 nguồn ổn định, dedupe, lưu DB |
| P2.2 | Gọi 2 model + consensus | 1–2 tuần | JSON schema 100% valid, consensus logic đúng |
| P2.3 | Shadow multiplier (chỉ log) | 2 tuần | multiplier được ghi, **không** ảnh hưởng size |
| P2.4 | Áp multiplier vào risk engine | 1 tuần | size thực giảm đúng, không vượt cap |
| P2.5 | Forward test 8 tuần + đánh giá | 8 tuần | báo cáo có/không có lợi ích |

---

## P2.0 — Chuẩn bị: nguồn tin, schema, budget (1 tuần)

### Giải thích cơ bản

Trước khi gọi model, phải chốt 3 thứ: **đầu vào là gì** (nguồn tin), **đầu ra phải có dạng gì** (schema), và **trần chi phí** (budget). Không chốt 3 thứ này thì model trả gì bạn cũng không dùng được máy móc, và hóa đơn không kiểm soát.

### Việc cần làm

1. Chọn nguồn tin: RSS/API tin crypto + lịch macro (CPI, FOMC, NFP). Tối thiểu 1 nguồn ổn định, miễn phí.
2. Định nghĩa JSON schema đầu ra (pydantic):
   ```json
   {
     "severity": "none|low|medium|high",
     "symbols": ["BTCUSDT", "..."],
     "direction": "up|down|both|unclear",
     "confidence": 0.0,
     "multiplier": 0.0,
     "reason": "≤ 240 ký tự"
   }
   ```
3. Viết validator tất định: từ chối field lạ, `multiplier` ngoài [0,1], `symbols` không thuộc universe, `confidence < 0.5` mà `severity = high` → coi là mâu thuẫn.
4. Budget cap: đếm token thực tế, lưu `ai_calls` table (ts, model, tokens_in, tokens_out, cost_usd).
5. Timeout (ví dụ 20s) + fallback rule: timeout/lỗi/mất mạng → `multiplier = 1.0` (không chặn giao dịch vì lỗi hạ tầng AI) **và** ghi `events` cảnh báo.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Schema chặt | 20 output mẫu qua validator, 20/20 quyết định rõ (pass/fail) |
| 2 | Validator từ chối rác | Test 10 JSON hỏng → 10 lần reject |
| 3 | Budget cap hoạt động | Giả lập 100 call → dừng đúng ngưỡng |
| 4 | Fallback không chặn trade | Giả lập timeout → multiplier = 1.0, có event |

### Checklist test

- [ ] Schema pydantic định nghĩa xong, có test
- [ ] Validator reject: field lạ, multiplier 1.5, symbol lạ, confidence âm
- [ ] Budget counter đếm đúng token (so với response API)
- [ ] Timeout 20s → fallback 1.0 + event
- [ ] Mọi call lưu vào `ai_calls` (kể cả lỗi)

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Nguồn tin chọn xong | ⬜ Chưa | | |
| JSON schema + validator | ⬜ Chưa | | |
| Budget cap + ai_calls | ⬜ Chưa | | |
| Timeout + fallback | ⬜ Chưa | | |

### Ghi chú

- Nguyên tắc: **AI lỗi thì không được làm tê liệt giao dịch**. Fallback phải là "bỏ qua AI", không phải "chặn hết".
- Ngược lại: AI trả `multiplier = 0` do **bất đồng** là quyết định thật, không phải lỗi — phải phân biệt 2 trường hợp này trong log.

---

## P2.1 — Ingest tin tức & lịch macro (1 tuần)

### Giải thích cơ bản

Model không tự biết tin. Bạn phải đưa tin vào. Nguồn tin cần 3 tính chất: ổn định (không chết giữa kỳ), dedupe được (cùng tin không tính 2 lần), và có timestamp đáng tin (để biết tin mới hay cũ).

### Việc cần làm

1. Poll RSS/API mỗi 1–5 phút; lưu `news_items (id, ts, source, title, body, url, hash)`.
2. Dedupe bằng hash nội dung + title normalize.
3. Lịch macro: bảng `calendar (ts, event, importance, currency)` cho CPI/FOMC/NFP.
4. Nối với blackout hiện có: ±45 phút quanh sự kiện importance cao → chặn lệnh (đã có sẵn rule này ở phase 1, giờ có nguồn dữ liệu thật).
5. Retention: tin > 30 ngày thì archive.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Nguồn ổn định | 7 ngày không lỗi liên tục > 30 phút |
| 2 | Dedupe đúng | Cùng tin từ 2 nguồn → 1 row |
| 3 | Timestamp đúng | So với giờ công bố thật |
| 4 | Blackout dùng lịch thật | Test: 44 phút trước FOMC → chặn; 46 phút → cho |

### Checklist test

- [ ] Poll 7 ngày, ghi uptime
- [ ] Test dedupe: cùng title khác URL → 1 row
- [ ] Test lịch: FOMC → chặn mở lệnh trong ±45 phút
- [ ] Tin cũ (7 ngày trước) không ảnh hưởng multiplier
- [ ] Nguồn chết → warning, không crash

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| RSS/API poll | ⬜ Chưa | | |
| Dedupe | ⬜ Chưa | | |
| Calendar macro | ⬜ Chưa | | |
| Nối blackout | ⬜ Chưa | | |

### Ghi chú

- Đừng dùng nguồn tin duy nhất. Nếu chỉ có 1 nguồn chết, AI gate mù hoàn toàn.
- Tin cũ là bẫy lớn nhất: model dễ coi tin 3 ngày trước là "mới". Phải filter theo `ts`.

---

## P2.2 — Gọi 2 model + consensus (1–2 tuần)

### Giải thích cơ bản

Đây là phần "brain". Gọi 2 model song song với cùng prompt, parse JSON, so sánh, ra multiplier cuối cùng.

Luật consensus (phải viết rõ ràng, không để model tự quyết):

```
nếu cả 2 trả severity = none              → multiplier = 1.0
nếu cả 2 trả severity ≥ medium, cùng hướng → multiplier = min(m1, m2)
nếu severity lệch ≥ 1 bậc                → multiplier = 0
nếu direction mâu thuẫn (up vs down)      → multiplier = 0
nếu 1 model timeout/JSON hỏng             → multiplier = 1.0 + event (không đủ 2 phiếu)
```

### Việc cần làm

1. Gọi song song (asyncio.gather) 2 model qua OpenRouter, cùng prompt, `temperature = 0`.
2. Prompt: system (vai trò, luật, schema) + user (tin mới, danh sách symbol, thời điểm hiện tại).
3. Parse + validate từng output; loại output hỏng.
4. Áp luật consensus ở trên, thành 1 hàm thuần (pure function) để dễ test.
5. Cache: nếu không có tin mới và chưa quá 15 phút → dùng kết quả cũ.
6. Lưu `ai_decisions (ts, model_a, model_b, consensus, multiplier, tokens, cost)`.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | JSON valid ≥ 99% | Đếm trên 200 call |
| 2 | Consensus tất định | Cùng input → cùng output (test 50 case) |
| 3 | Không block loop | p99 latency của main loop không đổi |
| 4 | Chi phí đúng dự toán | So `ai_calls` với ước tính 2–7 USD/tháng |
| 5 | Bất đồng → 0 | Test 10 case mâu thuẫn → 10 lần ra 0 |

### Checklist test

- [ ] 200 call liên tục: đo % JSON valid
- [ ] Test 50 case consensus (bảng input cố định → output mong đợi)
- [ ] Test temperature = 0: chạy 5 lần cùng input, output giống nhau
- [ ] Test 1 model timeout: multiplier = 1.0 + event
- [ ] Test cache: 2 call trong 5 phút → 1 lần gọi API thật
- [ ] Đo latency: main loop p99 không tăng

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Gọi song song 2 model | ⬜ Chưa | | |
| Consensus function | ⬜ Chưa | | |
| Cache | ⬜ Chưa | | |
| 200 call đo JSON valid | ⬜ Chưa | | |

### Ghi chú

- `temperature = 0` là bắt buộc: bạn cần tất định, không cần sáng tạo.
- Prompt phải có **danh sách symbol đóng** — nếu không, model sẽ bịa ra symbol không trade được.
- Giới hạn `reason ≤ 240 ký tự` để tránh output dài đốt tiền token out.

---

## P2.3 — Shadow multiplier: chỉ log, không áp dụng (2 tuần)

### Giải thích cơ bản

Trước khi cho AI can thiệp vào tiền thật, hãy để nó "nói" mà không ai nghe. Bot vẫn dùng multiplier = 1.0 để tính size thật, nhưng **ghi lại** multiplier mà AI *muốn* áp dụng.

Sau 2 tuần bạn sẽ có câu trả lời: nếu AI được quyền, nó đã chặn/giảm bao nhiêu lệnh, và những lệnh đó thực tế lãi hay lỗ.

### Việc cần làm

1. Chạy song song: size thật dùng 1.0, size ảo dùng multiplier từ AI.
2. Ghi bảng `ai_shadow (ts, signal_id, symbol, multiplier_ai, would_be_size, actual_size)`.
3. Đối chiếu sau khi lệnh đóng: R thật vs R nếu đã áp multiplier.
4. Báo cáo tuần: số lần multiplier < 1.0, số lần = 0, và PnL của nhóm đó.

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | Không ảnh hưởng size thật | So `actual_size` với công thức risk độc lập |
| 2 | Ghi đủ cho mọi signal | 100% signal có row `ai_shadow` |
| 3 | Đủ mẫu để kết luận | ≥ 20 signal có multiplier < 1.0 |
| 4 | Không làm chậm | Latency không đổi |

### Checklist test

- [ ] 100% signal có `ai_shadow`
- [ ] `actual_size` = size theo risk thuần (không bị AI ảnh hưởng)
- [ ] Report tuần có: số lần chặn, số lần giảm, PnL nhóm bị chặn
- [ ] So sánh: nếu áp AI thì PnL 2 tuần là bao nhiêu

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Shadow chạy 2 tuần | ⬜ Chưa | | |
| ≥ 20 signal multiplier < 1 | ⬜ Chưa | | |
| Report đối chiếu | ⬜ Chưa | | |

### Ghi chú

- Nếu sau 2 tuần AI **không bao giờ** trả multiplier < 1.0 → prompt/ngưỡng quá nhạy kém, hoặc nguồn tin không đủ; xem lại trước khi áp dụng.
- Nếu AI chặn quá nhiều (> 50% signal) → ngưỡng quá nhạy, sẽ bỏ lỡ phần lớn cơ hội. Đây cũng là lý do phải shadow trước.

---

## P2.4 — Áp multiplier vào risk engine (1 tuần)

### Giải thích cơ bản

Giờ cho AI một chân trong quyết định, nhưng **rất hẹp**: nó chỉ được nhân vào size, không được vượt bất kỳ cap nào của risk engine. AI là "bộ giảm ga", không phải "bộ tăng ga".

### Việc cần làm

1. Thêm `risk_multiplier` vào `risk.validate()`: `size = base_size × multiplier`, sau đó **vẫn** chạy toàn bộ limit check.
2. Đảm bảo `multiplier` không bao giờ > 1.0 (validator chặn).
3. `multiplier = 0` → bỏ signal, ghi `signals.blocked_reason = 'ai_veto'`.
4. Không áp dụng cho việc đóng lệnh: AI không bao giờ làm bot đóng sớm.
5. Alert khi AI veto liên tiếp ≥ 3 lần (có thể nguồn tin sai).

### Yêu cầu cần đạt

| # | Yêu cầu | Cách đo |
|---|---|---|
| 1 | AI không tăng được size | Test multiplier 1.5 → bị validator reject |
| 2 | Cap vẫn thắng | Test multiplier 1.0 + portfolio đầy → vẫn chặn |
| 3 | AI không đóng lệnh | Test: AI=0 khi đang có position → không có lệnh đóng |
| 4 | Veto có log | 100% veto có `blocked_reason` |

### Checklist test

- [ ] Test: multiplier 0.5 → size giảm đúng 50%
- [ ] Test: multiplier 0 → không mở lệnh, có reason
- [ ] Test: multiplier 1.0 + risk cap đầy → vẫn bị chặn bởi risk
- [ ] Test: AI = 0 trong lúc có position → không đóng
- [ ] Test: 3 veto liên tiếp → alert
- [ ] Test: AI lỗi/timeout → multiplier 1.0, trade bình thường

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| Tích hợp risk.validate | ⬜ Chưa | | |
| Veto + reason | ⬜ Chưa | | |
| Test cap không bị vượt | ⬜ Chưa | | |

### Ghi chú

- Đây là điểm dễ phá hệ thống nhất: một dòng code nhân sai chỗ có thể làm AI thành "trigger". Giữ nguyên tắc: AI chỉ chạy **sau** khi strategy đã sinh signal.
- Không bao giờ để AI tác động tới SL/TP đã đặt.

---

## P2.5 — Forward test 8 tuần + đánh giá (8 tuần)

### Giải thích cơ bản

Không backtest được tin tức (dữ liệu tin quá khứ không tái lập được ngữ cảnh). Vì vậy chỉ có 1 cách đánh giá: chạy forward và so sánh 2 nhóm lệnh.

Phép so sánh cốt lõi:

```
Nhóm A: lệnh có multiplier = 1.0      (AI không can thiệp)
Nhóm B: lệnh có multiplier < 1.0      (AI giảm size)
Nhóm C: lệnh bị veto (multiplier = 0)  → tính R "nếu đã vào" để biết AI chặn đúng hay sai

Kết luận AI có ích nếu: expectancy nhóm B ≥ nhóm A (giảm size đúng chỗ xấu)
                    và: nhóm C nếu vào thì lỗ (veto đúng chỗ)
```

### Việc cần làm

1. Chạy 8 tuần với AI áp dụng thật, giữ nguyên mọi tham số khác.
2. Báo cáo hàng tuần: số lần veto, số lần giảm, PnL từng nhóm, chi phí AI.
3. Theo dõi false negative: có sự kiện lớn nào AI bỏ sót khiến lỗ > 1R không.
4. Kết luận cuối kỳ: giữ / sửa ngưỡng / tắt.

### Yêu cầu cần đạt

| # | Yêu cầu | Ngưỡng |
|---|---|---|
| 1 | Đủ mẫu | ≥ 40 lệnh trong 8 tuần |
| 2 | Chi phí trong cap | ≤ 7 USD/tháng |
| 3 | Không false negative nghiêm trọng | 0 sự kiện lớn bị bỏ sót gây lỗ > 1R |
| 4 | Không làm hỏng vận hành | 0 sự cố do AI gây ra |
| 5 | Kết luận rõ ràng | Báo cáo giữ/tắt có số liệu |

### Checklist test

- [ ] 8 tuần chạy liên tục, không đổi ngưỡng giữa kỳ
- [ ] Report tuần đủ 8 bản
- [ ] So sánh A/B/C có số liệu
- [ ] Chi phí thực ≤ dự toán
- [ ] Quyết định cuối kỳ được ghi vào `docs/decisions.md` kèm lý do

### Kết quả đã đạt

| Hạng mục | Trạng thái | Bằng chứng | Ngày |
|---|---|---|---|
| 8 tuần forward | ⬜ Chưa | | |
| ≥ 40 lệnh | ⬜ Chưa | | |
| Report so sánh A/B/C | ⬜ Chưa | | |
| Quyết định giữ/tắt | ⬜ Chưa | | |

### Ghi chú

- Kết quả "AI không có ích, tắt đi" là **thành công** của phase 2: bạn tiết kiệm tiền và biết chắc. Đừng giữ AI chỉ vì đã đầu tư công sức (sunk cost).
- 8 tuần có thể chưa đủ mẫu nếu thị trường yên ắng. Nếu < 40 lệnh, kéo dài thay vì kết luận sớm.

---

## Bảng trạng thái tổng — Phase 2

| Mã | Phase con | Trạng thái | Ngày xong | Ghi chú |
|---|---|---|---|---|
| P2.0 | Chuẩn bị schema/budget | ⬜ Chưa | | |
| P2.1 | Ingest tin + calendar | ⬜ Chưa | | |
| P2.2 | 2 model + consensus | ⬜ Chưa | | |
| P2.3 | Shadow multiplier | ⬜ Chưa | | |
| P2.4 | Áp vào risk engine | ⬜ Chưa | | |
| P2.5 | Forward test 8 tuần | ⬜ Chưa | | |

**Cổng vào Phase 3:** Phase 2 kết luận xong (giữ hoặc tắt AI) + Phase 1 vẫn ổn định.

---

## Nhật ký thay đổi tài liệu

| Ngày | Phiên bản | Nội dung |
|---|---|---|
| 17/11/2026 | 1.0 | Tạo mới; chốt model GLM 5.3 Flash + DeepSeek V4 Flash, chi phí 2–7 USD/tháng |
