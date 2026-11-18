"""Test P1.2: aggregate 1m, parse bulk, checksum, parquet, idempotent download."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import date, datetime, timezone

import pytest

from app.data import bars as bars_mod
from app.data import downloader as dl
from app.data import parquet_io


def m1(n: int = 15, start: int = 1_700_000_000_000, price: float = 100.0) -> list[dict]:
    start = start // 900_000 * 900_000  # can moc 15m de test ro rang
    out = []
    for i in range(n):
        p = price + i
        out.append(
            {
                "open_time": start + i * 60_000,
                "close_time": start + i * 60_000 + 59_999,
                "o": p,
                "h": p + 5,
                "l": p - 5,
                "c": p + 1,
                "v": 10.0 + i,
                "closed": True,
            }
        )
    return out


def test_aggregate_15m_ohlcv():
    src = m1(15)
    out, gaps = bars_mod.aggregate(src, "15m")
    assert len(out) == 1 and gaps == []
    b = out[0]
    assert b["o"] == src[0]["o"] and b["c"] == src[-1]["c"]
    assert b["h"] == max(x["h"] for x in src)
    assert b["l"] == min(x["l"] for x in src)
    assert b["v"] == pytest.approx(sum(x["v"] for x in src))
    assert b["close_time"] == b["open_time"] + 15 * 60_000 - 1


def m1_4h(n: int = 240, price: float = 100.0) -> list[dict]:
    """Nến 1m bắt đầu đúng mốc 4h để test cửa sổ 4h."""
    start = 1_700_000_000_000 // 14_400_000 * 14_400_000
    return m1(n, start=start, price=price)


def test_aggregate_4h_ohlcv():
    src = m1_4h(240)
    out, gaps = bars_mod.aggregate(src, "4h")
    assert len(out) == 1 and gaps == []
    b = out[0]
    assert b["o"] == src[0]["o"] and b["c"] == src[-1]["c"]
    assert b["h"] == max(x["h"] for x in src)
    assert b["l"] == min(x["l"] for x in src)
    assert b["v"] == pytest.approx(sum(x["v"] for x in src))
    assert b["close_time"] == b["open_time"] + 240 * 60_000 - 1


def test_aggregate_4h_incomplete_window_dropped():
    src = m1_4h(480)
    del src[300]  # thieu 1 nen 1m -> ca cua so 4h thu 2 bi bo
    out, gaps = bars_mod.aggregate(src, "4h")
    assert len(out) == 1 and gaps == []


def test_aggregate_4h_missing_window_reported_as_gap():
    src = m1_4h(720)
    del src[240:480]  # mat tron cua so 4h thu 2
    out, gaps = bars_mod.aggregate(src, "4h")
    assert len(out) == 2
    assert gaps == [(out[0]["close_time"], out[1]["open_time"])]


def test_timeframes_declared():
    assert set(bars_mod.TF_MS) == {"15m", "1h", "4h"}
    assert bars_mod.NEED["4h"] == 240 and bars_mod.TF_MS["4h"] == 14_400_000
    out, _ = bars_mod.aggregate(m1(60), "1h")
    assert len(out) == 1  # 1h khong doi hanh vi


def test_incomplete_window_dropped_and_gap_reported():
    src = m1(45)
    del src[15:30]  # mat ca cua so 15m thu 2
    out, gaps = bars_mod.aggregate(src, "15m")
    assert len(out) == 2
    assert gaps == [(out[0]["close_time"], out[1]["open_time"])]


def test_open_bar_never_used():
    src = m1(15)
    src[-1]["closed"] = False
    out, _ = bars_mod.aggregate(src, "15m")
    assert out == []


def test_hour_from_60_bars():
    out, gaps = bars_mod.aggregate(m1(60), "1h")
    assert len(out) == 1 and gaps == [] and out[0]["v"] > 0


def test_unsorted_duplicate_input_normalized():
    src = m1(15)
    shuffled = list(reversed(src)) + [src[3], src[3]]
    out, _ = bars_mod.aggregate(shuffled, "15m")
    assert len(out) == 1
    assert out[0]["c"] == src[-1]["c"]


def test_unknown_tf_rejected():
    with pytest.raises(ValueError):
        bars_mod.aggregate(m1(15), "5m")


def _csv(rows: list[list], header: bool = False) -> str:
    lines = []
    if header:
        lines.append(
            "open_time,open,high,low,close,volume,close_time,"
            "quote_volume,count,taker_buy_volume,taker_buy_quote,ignore"
        )
    for r in rows:
        lines.append(",".join(str(x) for x in r))
    return "\n".join(lines) + "\n"


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


def test_parse_bulk_csv_header_and_microseconds():
    rows = [[1_700_000_000_000_000, 1, 2, 0.5, 1.5, 10, 1_700_000_059_999_000, 0, 0, 0, 0, 0]]
    out = dl.parse_bulk_csv(_csv(rows, header=True))
    assert len(out) == 1
    assert out[0]["open_time"] == 1_700_000_000_000
    assert out[0]["close_time"] == 1_700_000_059_999
    assert out[0]["closed"] is True


def test_parse_bulk_csv_dedup_sorted():
    rows = [
        [1_700_000_060_000, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0],
        [1_700_000_000_000, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0],
    ]
    out = dl.parse_bulk_csv(_csv(rows))
    assert [b["open_time"] for b in out] == [1_700_000_000_000, 1_700_000_060_000]


def test_split_by_day_uses_utc():
    t = int(datetime(2026, 6, 1, 23, 59, tzinfo=timezone.utc).timestamp() * 1000)
    src = [
        {"open_time": t, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1, "closed": True},
        {"open_time": t + 60_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1, "closed": True},
    ]
    parts = dl.split_by_day(src)
    assert sorted(parts) == ["2026-06-01", "2026-06-02"]


def test_parquet_roundtrip_atomic(tmp_path):
    src = m1(5)
    path = parquet_io.save_day(tmp_path, "BTCUSDT", "1m", "2026-06-01", src)
    assert path.exists() and not path.with_name(path.name + ".tmp").exists()
    back = parquet_io.load_day(tmp_path, "BTCUSDT", "1m", "2026-06-01")
    assert [b["open_time"] for b in back] == [b["open_time"] for b in src]
    assert back[0]["closed"] is True
    assert parquet_io.sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def _fetcher_with_zip(tmp_path, raw: bytes, checksum: str | None = None) -> dl.BulkFetcher:
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            if checksum is None:
                raise FileNotFoundError(url)
            return f"{checksum}  file.zip\n".encode()
        return raw

    return dl.BulkFetcher(str(tmp_path), get_bytes=get, log=lambda _m: None, verify=True)


def test_bulk_download_idempotent(tmp_path):
    day0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
    csv = _csv(
        [
            [day0 + i * 60_000, 1, 2, 0.5, 1.5, 10, day0 + i * 60_000 + 59_999, 0, 0, 0, 0, 0]
            for i in range(1440)
        ]
    )
    raw = _zip(csv)
    f = _fetcher_with_zip(tmp_path, raw, hashlib.sha256(raw).hexdigest())
    stat = f.download("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1))
    assert stat["files"] == 1 and parquet_io.list_days(tmp_path, "BTCUSDT", "1m") == ["2026-06-01"]
    stat2 = f.download("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1))
    assert stat2["files"] == 0 and stat2["skipped"] >= 1


def test_bulk_checksum_mismatch_raises(tmp_path):
    raw = _zip(_csv([[1_700_000_000_000, 1, 2, 0.5, 1.5, 10, 1_700_000_059_999, 0, 0, 0, 0, 0]]))
    f = _fetcher_with_zip(tmp_path, raw, "0" * 64)
    with pytest.raises(ValueError, match="CHECKSUM"):
        f.download("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1))


def test_bulk_missing_file_recorded(tmp_path):
    def get(url: str) -> bytes:
        raise FileNotFoundError(url)

    f = dl.BulkFetcher(str(tmp_path), get_bytes=get, log=lambda _m: None, verify=False)
    stat = f.download("BTCUSDT", date(2026, 6, 1), date(2026, 6, 2))
    assert stat["files"] == 0 and stat["missing"] >= 1


def test_backfill_dedup_overlapping_batches():
    def rest_get(_path, params, signed=False):  # type: ignore[no-untyped-def]
        s, e = params["startTime"], params["endTime"]
        n = min(1000, (e - s) // 60_000)
        rows = []
        for i in range(n):
            ot = s + i * 60_000
            rows.append([ot, 1, 2, 0.5, 1.5, 10, ot + 59_999])
        return rows

    start = 1_700_000_000_000
    out = dl.backfill(rest_get, "BTCUSDT", start, start + 1500 * 60_000)
    ts = [b["open_time"] for b in out]
    assert len(ts) == len(set(ts)) == 1500
