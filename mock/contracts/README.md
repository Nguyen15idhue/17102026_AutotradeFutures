# CONTRACTS — Hợp đồng API của mock

Mục đích: freeze hình dạng response để engine và mock không lệch nhau.

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `contracts.json` | Tất cả response mẫu + vector ký + event WS (gộp 1 file để test harness load 1 lần) |
| `../fixtures/exchangeInfo.json` | Snapshot thật 10 symbol (tickSize/stepSize/minNotional) |
| `../fixtures/klines.json` | Nến thật: 15m × 500, 1m × 300 cho 10 symbol |
| `../fixtures/meta.json` | Nguồn + thời điểm tải |

## Phân tầng

**Tier A — không được đổi** (đổi = engine phải sửa, coi là breaking change):

- Tên field, kiểu dữ liệu (Binance trả **chuỗi** cho số thập phân: `"0.001"`, không phải `0.001`)
- Mã lỗi (`code`/`msg`)
- Vòng đời `algoStatus`: `NEW → TRIGGERING → TRIGGERED → FINISHED`, cộng `CANCELED`/`REJECTED`/`EXPIRED`
- Tên event: `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`, `MARGIN_CALL`, `listenKeyExpired`
- Header: `X-MBX-USED-WEIGHT-1M`, `X-MBX-ORDER-COUNT-10S`, `X-MBX-ORDER-COUNT-1M`
- Quy tắc ký: HMAC SHA256 trên `query + body`, `signature` là param cuối và **không** nằm trong chuỗi ký

**Tier B — xấp xỉ** (ghi rõ sai số):

- Khớp lệnh: top-of-book, không mô phỏng queue/partial fill
- Funding: snapshot 00/08/16 UTC, rate lấy từ `premiumIndex`
- Giá thanh lý: công thức isolated bậc 1

**Tier C — không implement**: depth sâu, ADL, STP, batch orders, WebSocket API (request/response), Portfolio Margin, TradFi-Perps.

## Vector ký vàng (golden vector)

Lấy từ tài liệu chính thức Binance, dùng làm test auth duy nhất được phép:

```
secret  = 2b5eb11e18796d12d88f13dc27dbbd02c2cc51ff7059765ed9821957d82bb4d9
payload = symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC&recvWindow=5000&timestamp=1591702613943
sig     = 3c661234138461fcc7a7d8746c6558c9842d4e10870d2ecbedf7777cad694af9
```

Đã kiểm chứng lại bằng `hmac.new(secret, payload, sha256).hexdigest()` → khớp.

## Giới hạn

- Số thập phân luôn là **string** trong response, để không mất precision.
- Timestamp là **mili-giây**, UTC.
- Không chứa secret thật, không chứa dữ liệu tài khoản thật (balance mẫu = 5000).
