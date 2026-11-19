"""Trend Pullback long + short (spec §6.2, §15.2; hinh hoc chot 19/11/2026).

Proxy cau truc: pivot fractal k=3 + fib 30-61,8% cua impulse + cham EMA20/50
trong 5 nen 1h. KHONG phai nhan dien HH/HL day du — da ghi ro trong spec.

Ham thuan, khong goi API. Backtest va live dung chung.
"""

from __future__ import annotations

from typing import Any

from ..data import features as feat_mod
from . import indicators as ind_mod

STRATEGY_ID = "trend_pullback"
PIVOT_K = 3
EMA_TOUCH_BARS = 5


def _sma(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    run = 0.0
    for i, x in enumerate(xs):
        run += x
        if i >= n:
            run -= xs[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def prepare(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Tinh truoc chi bao 1 lan cho ca chuoi 1h (tranh tinh lai trong vong lap)."""
    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    vols = [float(b.get("v") or 0.0) for b in bars]
    return {
        "bars": bars,
        "ema20": feat_mod.ema_series(closes, 20),
        "ema50": feat_mod.ema_series(closes, 50),
        "ema200": feat_mod.ema_series(closes, 200),
        "atr": feat_mod.atr_series(highs, lows, closes, 14),
        "adx": feat_mod.adx_series(highs, lows, closes, 14),
        "rsi": ind_mod.rsi_series(closes, 14),
        "vol_sma20": _sma(vols, 20),
        "pivots": ind_mod.pivots(highs, lows, PIVOT_K),
    }


def entry_signal(
    prep: dict[str, Any],
    i: int,
    trend_dir: int,
    context_dir: int,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """Tai nen 1h i (da dong). Tra dict lenh hoac None."""

    if trend_dir == 0 or context_dir != trend_dir:
        return None
    bars = prep["bars"]
    if i < 1 or i >= len(bars):
        return None
    ema20, ema50, ema200 = prep["ema20"][i], prep["ema50"][i], prep["ema200"][i]
    atr, adx, rsi = prep["atr"][i], prep["adx"][i], prep["rsi"][i]
    if None in (ema20, ema50, ema200, atr, adx, rsi) or not atr:
        return None
    adx_min = float(cfg.get("adx_min", 22))
    if adx < adx_min:
        return None
    if trend_dir > 0 and not ema50 > ema200:
        return None
    if trend_dir < 0 and not ema50 < ema200:
        return None
    slope = ind_mod.ema_slope(prep["ema50"], i, 3)
    if slope is None or (trend_dir > 0 and slope <= 0) or (trend_dir < 0 and slope >= 0):
        return None

    confirmed = ind_mod.confirmed(prep["pivots"], PIVOT_K, i)
    impulse = ind_mod.last_impulse(confirmed, trend_dir)
    if impulse is None:
        return None
    (_, swing_low), (_, swing_high) = impulse
    span = swing_high - swing_low
    if span <= 0:
        return None
    fib_min = float(cfg.get("fib_min", 0.30))
    fib_max = float(cfg.get("fib_max", 0.618))
    close = float(bars[i]["c"])
    if trend_dir > 0:
        zone_low, zone_high = swing_high - fib_max * span, swing_high - fib_min * span
    else:
        zone_low, zone_high = swing_low + fib_min * span, swing_low + fib_max * span
    if not (zone_low <= close <= zone_high):
        return None

    touched = False
    for j in range(max(0, i - EMA_TOUCH_BARS + 1), i + 1):
        e20, e50 = prep["ema20"][j], prep["ema50"][j]
        if e20 is None or e50 is None:
            continue
        if trend_dir > 0 and float(bars[j]["l"]) <= max(e20, e50):
            touched = True
            break
        if trend_dir < 0 and float(bars[j]["h"]) >= min(e20, e50):
            touched = True
            break
    if not touched:
        return None

    if trend_dir > 0:
        lo, hi = float(cfg.get("rsi_min", 40)), float(cfg.get("rsi_max", 55))
    else:
        lo, hi = float(cfg.get("short_rsi_min", 45)), float(cfg.get("short_rsi_max", 60))
    if not (lo <= rsi <= hi):
        return None

    vsma = prep["vol_sma20"][i]
    if vsma is None or float(bars[i].get("v") or 0.0) >= vsma:
        return None

    stop_atr = float(cfg.get("stop_atr", 1.5))
    if trend_dir > 0:
        side = "BUY"
        stop = swing_low - stop_atr * atr
        if stop >= close:
            return None
    else:
        side = "SELL"
        stop = swing_high + stop_atr * atr
        if stop <= close:
            return None

    return {
        "strategy_id": STRATEGY_ID,
        "symbol": None,
        "side": side,
        "entry": close,
        "stop": stop,
        "tp": None,
        "order_type": "market",
        "time_stop_bars": int(cfg.get("time_stop_bars", 36)),
        "trail_atr": float(cfg.get("trail_atr", 2.0)),
        "trail_after_atr": float(cfg.get("trail_after_atr", 1.5)),
        "atr": atr,
        "meta": {"fib_span": span, "adx": adx, "rsi": rsi},
    }
