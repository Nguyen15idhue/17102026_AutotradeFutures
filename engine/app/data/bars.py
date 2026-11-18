"""Aggregate 1m -> 15m/1h. Chi nen da dong; gap -> warning, khong doan moc."""

from __future__ import annotations

TF_MS = {"15m": 15 * 60_000, "1h": 60 * 60_000}
NEED = {"15m": 15, "1h": 60}


def aggregate(bars_1m: list[dict], tf: str) -> tuple[list[dict], list[tuple[int, int]]]:
    """Gom nen 1m da sap xep thanh tf. Tra ve (bars_tf, gaps).

    Bo cua so thieu nen 1m hoac co nen chua dong. gaps: [(prev_close, next_open)].
    """
    tf_ms = TF_MS[tf]
    need = NEED[tf]
    buckets: dict[int, list[dict]] = {}
    for b in bars_1m:
        if not b.get("closed"):
            continue  # khong bao gio dung nen dang chay (look-ahead)
        buckets.setdefault(b["open_time"] // tf_ms * tf_ms, []).append(b)
    out: list[dict] = []
    gaps: list[tuple[int, int]] = []
    prev_close = None
    for w in sorted(buckets):
        grp = sorted(buckets[w], key=lambda x: x["open_time"])
        # Du lieu chuan: cac moc 1m lien tuc trong cua so
        if len(grp) != need or grp[0]["open_time"] != w:
            continue  # cua so thieu -> bo, se hien trong gap neu lech chuoi
        exp = w
        ok = all(g["open_time"] == exp + i * 60_000 for i, g in enumerate(grp))
        if not ok:
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
