"""Test quét tín hiệu P1.4b: máy đo phải đúng trước khi tin kết quả âm."""

from __future__ import annotations

from app.backtest import signal_scan as scan
from app.backtest import sim as sim_mod

H15 = sim_mod.H15_MS


def _symbol(prices: list[float]) -> sim_mod.SymbolData:
    bars15 = [
        {
            "open_time": i * H15,
            "o": p,
            "h": p * 1.001,
            "l": p * 0.999,
            "c": p,
            "v": 1.0,
            "closed": True,
        }
        for i, p in enumerate(prices)
    ]
    return sim_mod.SymbolData(
        symbol="TESTUSDT",
        bars1m=[],
        bars15=bars15,
        feat_by_close={},
        bars1h=[],
        prep1h={},
        ctx_dir=[],
        h1_by_close={},
        regime_by_close={},
        filters={},
        feat15=[None] * len(prices),
    )


def test_rolling_max_min_excludes_current_bar():
    xs = [1.0, 3.0, 2.0, 5.0]
    assert scan._rolling_max(xs, 2) == [None, None, 3.0, 3.0]
    assert scan._rolling_min(xs, 2) == [None, None, 1.0, 2.0]


def test_momentum_up_trend_has_positive_expectancy():
    data = {"TESTUSDT": _symbol([100.0 * (1.0001**i) for i in range(4000)])}
    res = scan.scan_signal("mom24h", data, min_samples=2)
    h96 = res["horizons"]["h96"]
    assert h96["hit_pct"] == 1.0
    assert h96["mean_bps"] > 0


def test_momentum_down_trend_flips_sign():
    data = {"TESTUSDT": _symbol([100.0 * (0.9999**i) for i in range(4000)])}
    res = scan.scan_signal("mom24h", data, min_samples=2)
    assert res["horizons"]["h96"]["mean_bps"] > 0  # short trong downtrend cung la "dung huong"


def test_z25_direction_and_zero_band():
    sd = _symbol([100.0] * 6)
    sd.feat15 = [{"z": -3.0}, {"z": 3.0}, {"z": 0.0}, None, {"z": -2.4}, {"z": 2.6}]
    d = scan.dir_z25(sd)
    assert d[0] == 1
    assert d[1] == -1
    assert d[2] == 0
    assert d[3] == 0
    assert d[4] == 0  # |z| < 2.5
    assert d[5] == -1


def test_breakout_direction_uses_previous_extremes():
    prices = [100.0] * 90 + [110.0]
    sd = _symbol(prices)
    d = scan.dir_brk20h(sd)
    assert d[-1] == 1
    assert all(x == 0 for x in d[:-1])


def test_bars4h_groups_16_bars():
    sd = _symbol([100.0 + i for i in range(64)])
    bars = scan._bars4h(sd)
    assert len(bars) == 4
    assert (
        bars[0]["h"] == max(b["h"] for b in sd.bars15[0:16]) and bars[-1]["c"] == sd.bars15[63]["c"]
    )
