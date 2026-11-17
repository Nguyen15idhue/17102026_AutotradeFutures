# VERIFICATION — Kết quả xác minh thực tế

File này ghi **kết quả thật** của bảng xác minh §4.3 (`docs/mvp-binance-futures-bot.md`) và các lần kiểm tra API.
Nguyên tắc: chỉ ghi thứ đã chạy và có output. Không chép lại tài liệu.

- Môi trường: live `https://fapi.binance.com` (không dùng demo — demo key không tạo được)
- Ngày chạy: 17/11/2026
- Công cụ: script Python stdlib (urllib + hmac), key đọc từ `.env`, **chỉ đọc** + 1 lệnh `order/test` không gửi lên sàn

---

## 1. Kết quả tổng hợp

| # | Mục (§4.3) | Kết quả | Ghi chú |
|---|---|---|---|
| 1 | REST host hoạt động | ✅ | `GET /fapi/v1/time` → 200 |
| 2 | WS host | ⬜ Chưa test | demo WS không dùng được; test lại khi có mock |
| 3 | Algo order | ✅ **gián tiếp** | `POST /fapi/v1/order/test` với `STOP_MARKET` → **`-4120`** ⇒ phải dùng `/fapi/v1/algoOrder` |
| 4 | Phí thực tế | ✅ | `maker 0,0200%` · `taker 0,0500%` — khớp spec |
| 5 | Min notional | ✅ | **Không đồng nhất** — xem bảng dưới |
| 6 | Tick/step | ✅ | Xem bảng dưới |
| 7 | Rate limit | ⬜ Chưa test | sẽ test ở P1.1 |
| 8 | Algo migration | ✅ | `-4120` xác nhận migration đang bật |
| 9 | `closePosition` tự hủy khi đóng position | ⬜ Chưa test | cần đặt lệnh thật → để mock test trước |
| 10 | `ALGO_UPDATE` | ⬜ Chưa test | cần đặt lệnh thật |
| 11 | Data lịch sử | ⬜ Chưa test | |
| 12 | Funding lịch sử | ⬜ Chưa test | |
| 13 | Liquidation bracket | ✅ | BTCUSDT bậc 1: `MMR = 0,4000%`, max leverage 150x |

---

## 2. Bảng filter thực tế (đo 17/11/2026)

| Symbol | minNotional (USDT) | tickSize | stepSize |
|---|---|---|---|
| BTCUSDT | **50** | 0,10 | 0,001 |
| ETHUSDT | **20** | 0,01 | 0,001 |
| LINKUSDT | **20** | 0,001 | 0,01 |
| BNBUSDT | 5 | 0,010 | 0,01 |
| XRPUSDT | 5 | 0,0001 | 0,1 |
| ADAUSDT | 5 | 0,00010 | 1 |
| DOGEUSDT | 5 | 0,000010 | 1 |
| SOLUSDT | 5 | 0,0100 | 0,01 |
| AVAXUSDT | 5 | 0,0010 | 1 |
| SUIUSDT | 5 | 0,000100 | 0,1 |

**Hệ quả quan trọng:** minNotional **không phải 5 USDT cho mọi symbol**. Với vốn nhỏ (~5–20 USD), BTCUSDT và ETHUSDT không mở được lệnh. Universe thực tế bị chặn theo vốn.

---

## 3. Trạng thái tài khoản tại thời điểm kiểm tra

| Mục | Giá trị |
|---|---|
| `canTrade` | `true` |
| `canDeposit` | `true` |
| `canWithdraw` | `true` — **cờ của TÀI KHOẢN, không phải quyền của API key** |
| `walletBalance` | 4,84855248 USDT |
| `availableBalance` | 4,84855248 USDT |
| Vị thế mở | 0 |
| Lệnh mở | 0 |
| Algo order mở | 0 |
| Clock offset | **ĐÃ SỬA** — từ **+1.836 ms** → **−1 ms** (5 mẫu). `w32time` giờ `Running`/`Automatic` |

### Quyền thật của API key — nguồn chuẩn `GET /sapi/v1/account/apiRestrictions`

Đây là endpoint **chuyên dụng để đọc quyền của key**. Kết quả 17/11/2026:

| Quyền | Giá trị | Đánh giá |
|---|---|---|
| `enableReading` | `true` | ✅ cần thiết |
| `enableFutures` | `true` | ✅ cần thiết |
| `enableWithdrawals` | **`false`** | ✅ an toàn |
| `enableInternalTransfer` | `false` | ✅ |
| `enableSpotAndMarginTrading` | `false` | ✅ |
| `enableMargin` | `false` | ✅ |
| `permitsUniversalTransfer` | `false` | ✅ |
| `enablePortfolioMarginTrading` | `false` | ✅ |
| `ipRestrict` | `true` | ✅ đã giới hạn IP |

⇒ **Key đúng cấu hình an toàn.** Không có quyền rút tiền.

> **Cảnh báo cho người đọc sau:** đừng dùng `canWithdraw` trong `/fapi/v2/account` để kiểm tra quyền key. Đó là cờ cấp tài khoản (tài khoản có được phép rút hay không), luôn `true` với tài khoản đã KYC, bất kể key có quyền gì. Muốn biết quyền key, chỉ có `GET /sapi/v1/account/apiRestrictions`.

### ⚠️ Việc phải làm ngay

1. **Nạp thêm vốn.** 4,85 USDT < 5 USDT (minNotional thấp nhất) ⇒ **không mở được bất kỳ lệnh nào**. Cần tối thiểu ~6 USDT, thực tế nên ≥ 20 USDT để test được ETH, và ≥ 50 USDT nếu muốn có BTC trong universe.
2. **NTP — đã xong.** Lệch ban đầu **+1.836 giây** do service `w32time` ở trạng thái `Stopped`/`Manual`. Đã chạy `pwsh scripts/ps/sync-clock.ps1` (nâng quyền) → `w32time` = `Running`/`Automatic`, offset còn **−1 ms**. Vẫn phải bù offset ở tầng code (ghi chú #7 mục 4).
3. Việc đã xong: ~~tắt quyền rút tiền~~ — kiểm tra lại cho thấy quyền này **vốn đã tắt**; cảnh báo ban đầu là sai.

---

## 4. Ghi chú kỹ thuật rút ra

1. `GET /fapi/v1/balance` trả **404**. Endpoint đúng là `/fapi/v2/balance` (hoặc `/fapi/v3/balance`). Mock phải dùng v2/v3.
2. `GET /fapi/v2/account` trả `assets[]` với `walletBalance`/`availableBalance`, và cờ `canTrade`/`canWithdraw`/`canDeposit` — nhưng **đây là cờ cấp tài khoản, không phải quyền key**. Muốn kiểm tra quyền key phải dùng `GET /sapi/v1/account/apiRestrictions` (thuộc spot API host `api.binance.com`, không phải `fapi`).
3. `GET /sapi/v1/capital/withdraw/history` trả **200** kể cả khi key **không** có quyền rút. Endpoint này chỉ cần quyền đọc ⇒ **không dùng làm phép thử quyền rút**. Chỉ `apiRestrictions` mới đáng tin.
4. `POST /fapi/v1/order/test` là cách an toàn để kiểm tra `-4120` mà **không đặt lệnh thật**. Dùng lại trong mock và trong CI.
5. `leverageBracket` trả `initialLeverage = 150` cho BTCUSDT bậc 1 ⇒ max leverage thị trường là 150x, nhưng hệ thống cố định 3x (§3.3).
6. Key live hoạt động bình thường ⇒ **không cần demo** để phát triển; mock server (Phase 0) vẫn là môi trường chính.
7. Độ lệch đồng hồ **phải bù ở tầng code**, không chỉ dựa vào NTP: đọc `serverTime` khi khởi động, tính `offset`, cộng vào `timestamp` mỗi request. NTP trên VPS/Windows có thể trôi hoặc bị chặn UDP 123.

---

## 5. Nhật ký

| Ngày | Nội dung |
|---|---|
| 17/11/2026 | Chạy probe lần 1 trên live: key hợp lệ, phí và `-4120` khớp spec; phát hiện minNotional không đồng nhất, balance 4,85 USDT dưới ngưỡng giao dịch. **Cảnh báo `canWithdraw` ban đầu là SAI** — đó là cờ cấp tài khoản; kiểm tra lại bằng `/sapi/v1/account/apiRestrictions` xác nhận `enableWithdrawals = false`. |
| 17/11/2026 | Đo lại đồng hồ 5 mẫu: lệch **+1.836 ms**, nguyên nhân `w32time` đang `Stopped`. Thêm `scripts/ps/sync-clock.ps1`. Sau khi chạy (nâng quyền): `Running`/`Automatic`, offset **−1 ms**. |
