"""Test strategy thuan: indicator, MR entry, Trend entry (P1.4)."""

from __future__ import annotations

from app.strategies import indicators as ind
from app.strategies import mean_reversion as mr
from app.strategies import trend_pullback as tr

MR_CFG = {
    "z_entry": 2.0,
    "stop_atr": 1.2,
    "time_stop_bars": 12,
    "ttl_bars": 2,
    "bbw_pct_min": 15,
}
TR_CFG = {
    "ema_fast": 50,
    "ema_slow": 200,
    "adx_min": 22,
    "fib_min": 0.30,
    "fib_max": 0.618,
    "rsi_min": 40,
    "rsi_max": 55,
    "short_rsi_min": 45,
    "short_rsi_max": 60,
    "stop_atr": 1.5,
    "trail_atr": 2.0,
    "trail_after_atr": 1.5,
    "time_stop_bars": 36,
}


def _feat(**over) -> dict:
    base = {
        "allow_mr": True,
        "bbw_pct": 30.0,
        "bb_mid": 100.0,
        "bb_dn": 98.0,
        "bb_up": 102.0,
        "atr": 1.0,
        "range_24h": 6.0,
        "range_pos": 0.2,
        "z": -2.4,
    }
    base.update(over)
    return base


# ---------- indicators ----------


def test_rsi_monotonic_is_100():
    closes = [float(i) for i in range(1, 30)]
    serie = ind.rsi_series(closes, 14)
    assert serie[13] is None
    assert serie[-1] == 100.0


def test_pivots_and_confirmation():
    highs = [1, 2, 5, 2, 1, 2, 1]
    lows = [0.5, 1.0, 4.0, 1.0, 0.4, 1.0, 0.6]
    piv = ind.pivots(highs, lows, k=1)
    assert (2, "H", 5) in piv
    assert (4, "L", 0.4) in piv
    assert ind.confirmed(piv, 1, 2) == []
    assert (2, "H", 5) in ind.confirmed(piv, 1, 3)


def test_last_impulse_long_and_short():
    piv = [(0, "L", 8.0), (2, "H", 11.0), (4, "L", 9.5)]
    assert ind.last_impulse(piv, 1) == ((0, 8.0), (2, 11.0))
    assert ind.last_impulse(piv, -1) == ((4, 9.5), (2, 11.0))
    assert ind.last_impulse([], 1) is None


# ---------- mean reversion ----------


def test_mr_wick_outside_band_close_inside_is_long():
    bar = {"c": 98.5, "l": 97.2, "h": 99.0}
    sig = mr.entry_signal(_feat(), bar, "RANGE", MR_CFG)
    assert sig is not None and sig["side"] == "BUY"
    # range_low = 98.5 - 0.2*6 = 97.3 -> stop = 97.3 - 1.2 = 96.1
    assert abs(sig["stop"] - 96.1) < 1e-9
    assert abs(sig["tp"] - 100.0) < 1e-9


def test_mr_short_mirror():
    bar = {"c": 101.5, "l": 101.0, "h": 102.3}
    sig = mr.entry_signal(_feat(z=2.4), bar, "RANGE", MR_CFG)
    assert sig is not None and sig["side"] == "SELL"
    # range_low = 101.5 - 0.2*6 = 100.3; range_high = 106.3 -> stop 107.5
    assert abs(sig["stop"] - 107.5) < 1e-9


def test_mr_blocks_bbw_below_15():
    bar = {"c": 98.5, "l": 97.2, "h": 99.0}
    assert mr.entry_signal(_feat(bbw_pct=10.0, allow_mr=False), bar, "RANGE", MR_CFG) is None


def test_mr_blocks_when_regime_not_range():
    bar = {"c": 98.5, "l": 97.2, "h": 99.0}
    assert mr.entry_signal(_feat(), bar, "TREND", MR_CFG) is None


def test_mr_blocks_when_close_outside_band():
    # dong cua van duoi band -> khong phai "quay lai trong band"
    bar = {"c": 97.9, "l": 97.0, "h": 98.2}
    assert mr.entry_signal(_feat(), bar, "RANGE", MR_CFG) is None


def test_mr_blocks_both_sides_in_one_bar():
    bar = {"c": 100.0, "l": 97.0, "h": 103.0}
    assert mr.entry_signal(_feat(), bar, "RANGE", MR_CFG) is None


def test_mr_blocks_tp_too_close_to_fees():
    # TP chi cach 0.2% < 0.3% -> khong du bu phi round-trip
    feat = _feat(bb_mid=98.7, bb_dn=98.0)
    bar = {"c": 98.5, "l": 97.2, "h": 99.0}
    assert mr.entry_signal(feat, bar, "RANGE", MR_CFG) is None


# ---------- trend ----------


def _prep_long() -> dict:
    bars = [
        {"o": 9.2, "h": 9.6, "l": 8.9, "c": 9.4, "v": 100},
        {"o": 9.4, "h": 10.4, "l": 9.3, "c": 10.2, "v": 100},
        {"o": 10.2, "h": 11.0, "l": 10.0, "c": 10.6, "v": 100},
        {"o": 10.6, "h": 10.7, "l": 10.0, "c": 10.1, "v": 100},
        {"o": 10.1, "h": 10.2, "l": 9.5, "c": 9.8, "v": 100},
        {"o": 9.8, "h": 10.0, "l": 9.7, "c": 9.8, "v": 100},
    ]
    return {
        "bars": bars,
        "ema20": [9.0, 9.2, 9.5, 9.6, 9.6, 9.6],
        "ema50": [8.8, 9.0, 9.3, 9.5, 9.8, 9.9],
        "ema200": [8.0, 8.1, 8.2, 8.3, 8.4, 8.5],
        "atr": [1.0] * 6,
        "adx": [30.0] * 6,
        "rsi": [30.0, 60.0, 70.0, 50.0, 48.0, 50.0],
        "vol_sma20": [200.0] * 6,
        "pivots": [(0, "L", 8.0), (2, "H", 11.0)],
    }


def test_trend_long_signal_with_proxy_geometry():
    sig = tr.entry_signal(_prep_long(), 5, 1, 1, TR_CFG)
    assert sig is not None and sig["side"] == "BUY"
    assert abs(sig["stop"] - (8.0 - 1.5)) < 1e-9
    assert sig["tp"] is None


def test_trend_no_short_when_trend_dir_up():
    assert tr.entry_signal(_prep_long(), 5, -1, -1, TR_CFG) is None


def test_trend_requires_context_agreement():
    assert tr.entry_signal(_prep_long(), 5, 1, 0, TR_CFG) is None
    assert tr.entry_signal(_prep_long(), 5, 1, -1, TR_CFG) is None


def test_trend_blocks_when_price_not_in_fib_zone():
    prep = _prep_long()
    prep["bars"] = [dict(b) for b in prep["bars"]]
    prep["bars"][5]["c"] = 10.9  # ngoai vung hoi 30-61,8%
    assert tr.entry_signal(prep, 5, 1, 1, TR_CFG) is None


def test_trend_blocks_when_volume_not_declining():
    prep = _prep_long()
    prep["vol_sma20"] = [50.0] * 6
    assert tr.entry_signal(prep, 5, 1, 1, TR_CFG) is None


def test_trend_short_signal_is_mirror():
    # Guong quanh 10: ema50 < ema200, pivot H truoc L, close trong vung hoi nguoc
    prep = {
        "bars": [
            {"o": 10.8, "h": 11.1, "l": 10.4, "c": 10.6, "v": 100},
            {"o": 10.6, "h": 10.7, "l": 9.6, "c": 9.8, "v": 100},
            {"o": 9.8, "h": 10.0, "l": 9.0, "c": 9.4, "v": 100},
            {"o": 9.4, "h": 10.0, "l": 9.3, "c": 9.9, "v": 100},
            {"o": 9.9, "h": 10.5, "l": 9.8, "c": 10.2, "v": 100},
            {"o": 10.2, "h": 10.3, "l": 10.0, "c": 10.2, "v": 100},
        ],
        "ema20": [11.0, 10.8, 10.5, 10.4, 10.4, 10.4],
        "ema50": [11.2, 11.0, 10.7, 10.5, 10.2, 10.1],
        "ema200": [12.0, 11.9, 11.8, 11.7, 11.6, 11.5],
        "atr": [1.0] * 6,
        "adx": [30.0] * 6,
        "rsi": [70.0, 40.0, 30.0, 50.0, 52.0, 50.0],
        "vol_sma20": [200.0] * 6,
        "pivots": [(0, "H", 12.0), (2, "L", 9.0)],
    }
    sig = tr.entry_signal(prep, 5, -1, -1, TR_CFG)
    assert sig is not None and sig["side"] == "SELL"
    assert abs(sig["stop"] - (12.0 + 1.5)) < 1e-9
