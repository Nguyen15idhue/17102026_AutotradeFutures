"""Feature engine P1.2 theo spec §6.2. Nhan qua, chi dung du lieu <= T.

ATR/ADX: Wilder RMA(14). BB: SMA20 +- 2*STDEV. bbw_pct: hang percentile cua bbw
trong 90 ngay (8640 nen 15m); thieu mau -> None (fallback: khong trade).
vol_pct: percentile volume trong 30 ngay (2880 nen). range_24h: 96 nen 15m.
"""

from __future__ import annotations

import math

BBW_LOOKBACK = 90 * 96  # 8640 nen 15m
VOL_LOOKBACK = 30 * 96  # 2880 nen
RANGE_N = 96
MIN_BBW_SAMPLE = 100  # duoi nguong nay tra None thay vi so ao


def sma(xs: list[float], n: int, end: int) -> float | None:
    if end + 1 < n:
        return None
    return sum(xs[end - n + 1: end + 1]) / n


def stdev(xs: list[float], n: int, end: int) -> float | None:
    m = sma(xs, n, end)
    if m is None:
        return None
    seg = xs[end - n + 1: end + 1]
    return math.sqrt(sum((x - m) ** 2 for x in seg) / n)


def ema_series(xs: list[float], n: int) -> list[float | None]:
    """EMA nhan qua (seed = SMA dau), chi de loc trend, khong phai signal."""
    k = 2 / (n + 1)
    out: list[float | None] = [None] * len(xs)
    if len(xs) < n:
        return out
    seed = sum(xs[:n]) / n
    out[n - 1] = seed
    for i in range(n, len(xs)):
        assert out[i - 1] is not None
        out[i] = xs[i] * k + out[i - 1] * (1 - k)  # type: ignore[operator]
    return out


def _rma(prev: float, x: float, n: int) -> float:
    return (prev * (n - 1) + x) / n


def atr_series(h: list[float], low: list[float], c: list[float], n: int = 14
               ) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    trs = [0.0] * len(c)
    for i in range(1, len(c)):
        trs[i] = max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1]))
    atr = sum(trs[1: n + 1]) / n
    out[n] = atr
    for i in range(n + 1, len(c)):
        atr = _rma(atr, trs[i], n)
        out[i] = atr
    return out


def adx_series(h: list[float], low: list[float], c: list[float], n: int = 14
               ) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) < 2 * n + 1:
        return out
    trs, pdm, mdm = [0.0] * len(c), [0.0] * len(c), [0.0] * len(c)
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], low[i - 1] - low[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        trs[i] = max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1]))
    str_ = sum(trs[1: n + 1])
    sp, sm = sum(pdm[1: n + 1]), sum(mdm[1: n + 1])
    dxs: list[float] = []
    for i in range(n + 1, len(c)):
        if i > n + 1:
            str_ = _rma(str_, trs[i], n)
            sp = _rma(sp, pdm[i], n)
            sm = _rma(sm, mdm[i], n)
        pdi = 100 * sp / str_ if str_ else 0.0
        mdi = 100 * sm / str_ if str_ else 0.0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0
        dxs.append(dx)
        if len(dxs) == n:
            out[i] = sum(dxs) / n
        elif len(dxs) > n:
            assert out[i - 1] is not None
            out[i] = ((out[i - 1] or 0.0) * (n - 1) + dx) / n  # type: ignore[operator]
    return out


def pct_rank(window: list[float], x: float) -> float:
    """Hang percentile 0-100 cua x trong window (chi tinh tren qua khu)."""
    if not window:
        return 50.0
    le = sum(1 for v in window if v <= x)
    return 100.0 * le / len(window)


def allow_mean_reversion(bbw_pct: float | None) -> bool:
    """Quy tac an toan so 1: cam MR khi bbw_pct < 15 (None = chua du mau -> cam)."""
    return bbw_pct is not None and bbw_pct > 15


def compute_at(bars: list[dict], i: int) -> dict | None:
    """Feature tai nen i, chi dung bars[<=i]. None neu thieu gap/lich su."""
    if i < 0 or not bars[i].get("closed"):
        return None
    # Gap: moc mo phai lien tuc 15m, neu khong -> bo (warning o tren goi)
    if i > 0 and bars[i]["open_time"] - bars[i - 1]["open_time"] != 15 * 60_000:
        return None
    if i < 19:  # chua du BB20
        return None
    closes = [b["c"] for b in bars[: i + 1]]
    highs = [b["h"] for b in bars[: i + 1]]
    lows = [b["l"] for b in bars[: i + 1]]
    vols = [b["v"] for b in bars[: i + 1]]
    mid = sma(closes, 20, i)
    sd = stdev(closes, 20, i)
    assert mid is not None and sd is not None
    if sd == 0:
        return None
    atr_s = atr_series(highs, lows, closes)
    adx_s = adx_series(highs, lows, closes)
    atr, adx = atr_s[i], adx_s[i]
    if atr is None or adx is None or atr == 0:
        return None
    up, dn = mid + 2 * sd, mid - 2 * sd
    bbw = (up - dn) / mid if mid else 0.0
    z = (closes[i] - mid) / sd
    # Percentile chi tren qua khu (khong gom i)
    past_bbw: list[float] = []
    for j in range(max(0, i - BBW_LOOKBACK), i):
        m2 = sma(closes, 20, j)
        s2 = stdev(closes, 20, j)
        if m2 and s2:
            past_bbw.append(4 * s2 / m2)
    bbw_pct = pct_rank(past_bbw, bbw) if len(past_bbw) >= MIN_BBW_SAMPLE else None
    past_v = vols[max(0, i - VOL_LOOKBACK): i]
    vol_pct = pct_rank(past_v, vols[i]) if past_v else 50.0
    seg = bars[max(0, i - RANGE_N + 1): i + 1]
    hi, lo = max(b["h"] for b in seg), min(b["l"] for b in seg)
    rng = hi - lo
    span = (hi - lo) or 1.0
    ema50 = ema_series(closes, 50)
    ema200 = ema_series(closes, 200)
    return {
        "ts": bars[i]["open_time"],
        "close": closes[i],
        "atr": atr,
        "adx": adx,
        "bb_mid": mid,
        "bb_up": up,
        "bb_dn": dn,
        "bbw": bbw,
        "bbw_pct": bbw_pct,
        "z": z,
        "vol_pct": vol_pct,
        "range_24h": rng,
        "range_pos": (closes[i] - lo) / span,
        "ema50": ema50[i],
        "ema200": ema200[i],
        "allow_mr": allow_mean_reversion(bbw_pct),
    }
