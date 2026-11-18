"""Aggregate 1m -> 15m/1h. Chi nen da dong; gap -> warning, khong doan moc."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

TF_MS = {"15m": 15 * 60_000, "1h": 60 * 60_000}
NEED = {"15m": 15, "1h": 60}
GAP_TOLERANCE = 0  # 1m phai lien tuc tuyet doi trong cua so
WARN_EVERY = 1  # log 1 lan cho moi (symbol, gap) de khong spam


def iter_closed(bars: Iterable[dict]) -> Iterator[dict]:
    """Chi tra nen da dong — moi thu trong P1.2 deu di qua day."""
    for b in bars:
        if b.get("closed"):
            yield b


def _dedup_sorted(bars: Iterable[dict]) -> list[dict]:
    by_ts: dict[int, dict] = {}
    for b in iter_closed(bars):
        by_ts[int(b["open_time"])] = b
    return [by_ts[k] for k in sorted(by_ts)]


def aggregate(bars_1m: list[dict], tf: str) -> tuple[list[dict], list[tuple[int, int]]]:
    """Gom nen 1m da sap xep thanh tf. Tra ve (bars_tf, gaps).

    Bo cua so thieu nen 1m hoac co nen chua dong. gaps: [(prev_close, next_open)].
    """
    if tf not in TF_MS:
        raise ValueError(f"tf khong ho tro: {tf}")
    tf_ms = TF_MS[tf]
    need = NEED[tf]
    buckets: dict[int, list[dict]] = {}
    for b in _dedup_sorted(bars_1m):
        buckets.setdefault(b["open_time"] // tf_ms * tf_ms, []).append(b)
    out: list[dict] = []
    gaps: list[tuple[int, int]] = []
    prev_close: int | None = None
    for w in sorted(buckets):
        grp = buckets[w]
        if len(grp) != need or grp[0]["open_time"] != w:
            continue  # cua so thieu -> bo, se hien trong gap neu lech chuoi
        if any(g["open_time"] != w + i * 60_000 for i, g in enumerate(grp)):
            continue
        ot, ct = w, w + tf_ms - 1
        if prev_close is not None and ot - prev_close > tf_ms:
            gaps.append((prev_close, ot))
        out.append(
            {
                "open_time": ot,
                "close_time": ct,
                "o": grp[0]["o"],
                "h": max(g["h"] for g in grp),
                "l": min(g["l"] for g in grp),
                "c": grp[-1]["c"],
                "v": sum(g["v"] for g in grp),
                "closed": True,
            }
        )
        prev_close = ct
    return out, gaps


def aggregate_all(bars_1m: list[dict]) -> dict[str, tuple[list[dict], list[tuple[int, int]]]]:
    return {tf: aggregate(bars_1m, tf) for tf in TF_MS}
