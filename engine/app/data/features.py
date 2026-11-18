"""Feature engine P1.2 theo spec §6.2. Chi dung du lieu <= T (khong look-ahead).

- ATR(14)/ADX(14): Wilder RMA.
- BB(20, 2σ): SMA + STDEV population (/n).
- bbw_pct: hang percentile cua bbw trong 90 ngay (8640 nen 15m), CHI mau qua khu;
  thieu mau -> None (fallback: khong trade) theo quyet dinh P1.2.
- vol_pct: percentile cua realized vol 1h (sqrt tong binh phuong 4 log-return 15m)
  trong 30 ngay (2880 nen) — spec §6.2, KHONG phai percentile volume.
- range_24h: 96 nen 15m; range_pct: percentile 90 ngay cua range_24h/ATR
  (chuan hoa de so sanh cung don vi — spec goc ghi range_24h < k*ATR la sai thu nguyen).
  oi/funding: optional, thieu -> None.

Tat ca tinh 1 luot (O(n log n) cho percentile) de replay ~100 ngay khong cho.
"""

from __future__ import annotations

import bisect
import math
from collections import deque

BBW_LOOKBACK = 90 * 96  # 8640 nen 15m
VOL_LOOKBACK = 30 * 96  # 2880 nen
RANGE_LOOKBACK = 90 * 96  # percentile cua range_24h/ATR, cung 90 ngay
RANGE_N = 96
RV_N = 4  # realized vol 1h = 4 nen 15m
BBW_MIN_SAMPLES = BBW_LOOKBACK  # du 90 ngay moi co percentile (fallback = None)
VOL_MIN_SAMPLES = VOL_LOOKBACK
RANGE_MIN_SAMPLES = RANGE_LOOKBACK
MIN_BBW_SAMPLE = 20  # so mau toi thieu de bbw ton tai (chi dung trong test cu)


def sma(xs: list[float], n: int, end: int) -> float | None:
    if end + 1 < n:
        return None
    return sum(xs[end - n + 1 : end + 1]) / n


def stdev(xs: list[float], n: int, end: int) -> float | None:
    m = sma(xs, n, end)
    if m is None:
        return None
    seg = xs[end - n + 1 : end + 1]
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


def atr_series(h: list[float], low: list[float], c: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    trs = [0.0] * len(c)
    for i in range(1, len(c)):
        trs[i] = max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1]))
    atr = sum(trs[1 : n + 1]) / n
    out[n] = atr
    for i in range(n + 1, len(c)):
        atr = _rma(atr, trs[i], n)
        out[i] = atr
    return out


def adx_series(h: list[float], low: list[float], c: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) < 2 * n + 1:
        return out
    trs, pdm, mdm = [0.0] * len(c), [0.0] * len(c), [0.0] * len(c)
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], low[i - 1] - low[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        trs[i] = max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1]))
    str_ = sum(trs[1 : n + 1])
    sp, sm = sum(pdm[1 : n + 1]), sum(mdm[1 : n + 1])
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
    """Hang percentile 0-100 cua x trong window (empirical CDF, x <= v)."""
    if not window:
        return 50.0
    le = sum(1 for v in window if v <= x)
    return 100.0 * le / len(window)


def _pct_rank_sorted(sorted_vals: list[float], x: float) -> float:
    return 100.0 * bisect.bisect_right(sorted_vals, x) / len(sorted_vals)


def allow_mean_reversion(bbw_pct: float | None) -> bool:
    """Quy tac an toan so 1: cam MR khi bbw_pct < 15 (None = chua du mau -> cam)."""
    return bbw_pct is not None and bbw_pct > 15


def realized_vol_1h(closes: list[float], i: int, n: int = RV_N) -> float | None:
    """sqrt(tong binh phuong n log-return 15m ket thuc tai i). i < n -> None."""
    if i < n:
        return None
    s = 0.0
    for j in range(i - n + 1, i + 1):
        if closes[j - 1] <= 0 or closes[j] <= 0:
            return None
        r = math.log(closes[j] / closes[j - 1])
        s += r * r
    return math.sqrt(s)


def funding_from_premium(payload: dict) -> float | None:
    """lastFundingRate tu /fapi/v1/premiumIndex (string)."""
    v = payload.get("lastFundingRate")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def oi_from_payload(payload: dict) -> float | None:
    """openInterest tu /fapi/v1/openInterest (string)."""
    v = payload.get("openInterest")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def gap_boundaries(bars: list[dict]) -> list[int]:
    """Chi so i ma bars[i] khong noi tiep bars[i-1] (15m)."""
    out = []
    for i in range(1, len(bars)):
        if bars[i]["open_time"] - bars[i - 1]["open_time"] != 15 * 60_000:
            out.append(i)
    return out


def _rolling_mean_std(closes: list[float], n: int) -> tuple[list[float | None], list[float | None]]:
    """SMA + STDEV population bang cua so truot (O(n))."""
    m: list[float | None] = [None] * len(closes)
    s: list[float | None] = [None] * len(closes)
    sum_x = sum_x2 = 0.0
    for i, c in enumerate(closes):
        sum_x += c
        sum_x2 += c * c
        if i >= n:
            old = closes[i - n]
            sum_x -= old
            sum_x2 -= old * old
        if i + 1 >= n:
            mean = sum_x / n
            var = max(0.0, sum_x2 / n - mean * mean)  # population, /n
            m[i] = mean
            s[i] = math.sqrt(var)
    return m, s


class _PctWindow:
    """Cua so gia tri qua khu + do phan vi bang bisect (O(log n) tra cuu)."""

    def __init__(self, lookback: int) -> None:
        self.lookback = lookback
        self._q: deque[tuple[int, float]] = deque()
        self._sorted: list[float] = []

    def add(self, idx: int, value: float | None) -> None:
        if value is not None:
            self._q.append((idx, value))
            bisect.insort(self._sorted, value)

    def drop_before(self, idx: int) -> None:
        # idx: chi so nho nhat con duoc giu
        while self._q and self._q[0][0] < idx:
            _, v = self._q.popleft()
            pos = bisect.bisect_left(self._sorted, v)
            if pos < len(self._sorted) and self._sorted[pos] == v:
                self._sorted.pop(pos)

    def pct(self, value: float, min_samples: int) -> float | None:
        if len(self._sorted) < min_samples:
            return None
        return _pct_rank_sorted(self._sorted, value)


def compute_series(
    bars: list[dict],
    *,
    bbw_min_samples: int = BBW_MIN_SAMPLES,
    vol_min_samples: int = VOL_MIN_SAMPLES,
    range_min_samples: int = RANGE_MIN_SAMPLES,
    oi: dict[int, float] | None = None,
    funding: dict[int, float] | None = None,
) -> list[dict | None]:
    """Feature cho tung nen 15m da dong; None neu thieu du lieu/cua so bi gap."""
    n = len(bars)
    if n == 0:
        return []
    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    atr_s = atr_series(highs, lows, closes)
    adx_s = adx_series(highs, lows, closes)
    ema50_s = ema_series(closes, 50)
    ema200_s = ema_series(closes, 200)
    mid_s, sd_s = _rolling_mean_std(closes, 20)
    volumes = [float(b.get("v") or 0.0) for b in bars]
    pv = [0.0]
    for v in volumes:
        pv.append(pv[-1] + v)
    vol5_s = [(pv[i + 1] - pv[i + 1 - 5]) / 5 if i >= 4 else None for i in range(n)]
    vol20_s = [(pv[i + 1] - pv[i + 1 - 20]) / 20 if i >= 19 else None for i in range(n)]

    bbw: list[float | None] = [None] * n
    rv: list[float | None] = [None] * n
    for i in range(n):
        mid, sd = mid_s[i], sd_s[i]
        if mid and sd:
            bbw[i] = 4 * sd / mid  # (up-dn)/mid voi up-dn = 4σ
        rv[i] = realized_vol_1h(closes, i)

    bbw_win, vol_win = _PctWindow(BBW_LOOKBACK), _PctWindow(VOL_LOOKBACK)
    range_win = _PctWindow(RANGE_LOOKBACK)
    out: list[dict | None] = [None] * n
    last_range_ratio: float | None = None
    for i in range(n):
        # cua so phan vi: chi mau QUA KHU (j < i)
        if i > 0:
            bbw_win.add(i - 1, bbw[i - 1])
            vol_win.add(i - 1, rv[i - 1])
            range_win.add(i - 1, last_range_ratio)
        bbw_win.drop_before(i - BBW_LOOKBACK)
        vol_win.drop_before(i - VOL_LOOKBACK)
        range_win.drop_before(i - RANGE_LOOKBACK)

        # range_24h/ATR: tinh ca cho nen khong hop le de cua so percentile lien tuc
        seg = bars[max(0, i - RANGE_N + 1) : i + 1]
        hi, lo = max(b["h"] for b in seg), min(b["l"] for b in seg)
        atr_i = atr_s[i]
        last_range_ratio = (hi - lo) / atr_i if atr_i else None

        if not bars[i].get("closed"):
            continue
        # cua so BB20 phai lien tuc: 20 nen 15m gan nhat khong duoc co gap
        if i < 19 or (i > 0 and bars[i]["open_time"] - bars[i - 1]["open_time"] != 15 * 60_000):
            continue
        contiguous = all(
            bars[j]["open_time"] - bars[j - 1]["open_time"] == 15 * 60_000
            for j in range(i - 18, i + 1)
        )
        if not contiguous:
            continue
        mid, sd, atr, adx = mid_s[i], sd_s[i], atr_s[i], adx_s[i]
        if mid is None or sd is None or sd == 0 or atr is None or adx is None or atr == 0:
            continue
        up, dn = mid + 2 * sd, mid - 2 * sd
        cur_bbw = 4 * sd / mid
        cur_rv = rv[i]
        bbw_pct = bbw_win.pct(cur_bbw, bbw_min_samples)
        vol_pct = vol_win.pct(cur_rv, vol_min_samples) if cur_rv is not None else None
        range_pct = range_win.pct(last_range_ratio, range_min_samples) if last_range_ratio else None
        span = (hi - lo) or 1.0
        warmup = []
        if bbw_pct is None:
            warmup.append("bbw_pct")
        if vol_pct is None:
            warmup.append("vol_pct")
        if range_pct is None:
            warmup.append("range_pct")
        if ema50_s[i] is None:
            warmup.append("ema50")
        if ema200_s[i] is None:
            warmup.append("ema200")
        ts = bars[i]["open_time"]
        out[i] = {
            "ts": ts,
            "close": closes[i],
            "atr": atr,
            "adx": adx,
            "bb_mid": mid,
            "bb_up": up,
            "bb_dn": dn,
            "bb_sd": sd,
            "bbw": cur_bbw,
            "bbw_pct": bbw_pct,
            "z": (closes[i] - mid) / sd,
            "vol_pct": vol_pct,
            "rv_1h": cur_rv,
            "range_24h": hi - lo,
            "range_pct": range_pct,
            "range_ratio": last_range_ratio,
            "range_pos": (closes[i] - lo) / span,
            "vol_sma5": vol5_s[i],
            "vol_sma20": vol20_s[i],
            "ema50": ema50_s[i],
            "ema200": ema200_s[i],
            "oi": (oi or {}).get(ts),
            "funding": (funding or {}).get(ts),
            "allow_mr": allow_mean_reversion(bbw_pct),
            "warmup": warmup,
        }
    return out


def compute_at(bars: list[dict], i: int) -> dict | None:
    """Wrapper cho test: feature tai nen i, chi dung bars[<=i]."""
    if i < 0 or i >= len(bars):
        return None
    return compute_series(bars[: i + 1])[i]
