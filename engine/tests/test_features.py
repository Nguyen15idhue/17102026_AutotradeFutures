"""Test P1.2 feature engine: gia tri biet truoc, khong look-ahead, warmup, gap."""

from __future__ import annotations

import math
import random

import pytest

from app.data import features as F

START = 1_767_225_600_000  # 2026-01-01T00:00:00Z, chia het 15m
M15 = 15 * 60_000


def synth(
    n: int,
    *,
    base: float = 100.0,
    drift: float = 0.0,
    noise: float = 0.0,
    volume: float = 10.0,
    seed: int = 3,
    start: int = START,
) -> list[dict]:
    rnd = random.Random(seed)
    out, prev = [], base
    for i in range(n):
        c = base + drift * i + (rnd.uniform(-noise, noise) if noise else 0.0)
        o = prev
        out.append(
            {
                "open_time": start + i * M15,
                "close_time": start + i * M15 + M15 - 1,
                "o": o,
                "h": max(o, c) + 0.5,
                "l": min(o, c) - 0.5,
                "c": c,
                "v": volume,
                "closed": True,
            }
        )
        prev = c
    return out


def test_atr14_wilder_known():
    bars = synth(60, drift=1.0)
    atr = F.atr_series([b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars], 14)
    assert atr[13] is None and atr[14] == pytest.approx(2.0)
    assert atr[40] == pytest.approx(2.0)


def test_adx_pure_uptrend_is_100():
    bars = synth(80, drift=1.0)
    adx = F.adx_series([b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars], 14)
    assert adx[27] is None
    assert adx[28] == pytest.approx(100.0, abs=1e-6)


def test_bb20_mid_sd_z_manual():
    bars = synth(41, drift=0.3, noise=0.7, seed=11)
    closes = [b["c"] for b in bars]
    series = F.compute_series(bars, bbw_min_samples=5, vol_min_samples=5)
    i = 40
    seg = closes[i - 19 : i + 1]
    mid = sum(seg) / 20
    sd = math.sqrt(sum((x - mid) ** 2 for x in seg) / 20)
    f = series[i]
    assert f is not None
    assert f["bb_mid"] == pytest.approx(mid, abs=1e-12)
    assert f["bb_sd"] == pytest.approx(sd, abs=1e-12)
    assert f["bb_up"] == pytest.approx(mid + 2 * sd, abs=1e-12)
    assert f["bb_dn"] == pytest.approx(mid - 2 * sd, abs=1e-12)
    assert f["z"] == pytest.approx((closes[i] - mid) / sd, abs=1e-12)
    assert f["bbw"] == pytest.approx(4 * sd / mid, abs=1e-12)


def test_pct_rank_matches_bruteforce_10_points():
    rnd = random.Random(7)
    window = [rnd.uniform(0, 100) for _ in range(50)]
    srt = sorted(window)
    for x in [rnd.uniform(0, 100) for _ in range(10)]:
        assert F._pct_rank_sorted(srt, x) == pytest.approx(F.pct_rank(window, x))


def test_vol_pct_is_realized_vol_not_volume():
    a = synth(60, drift=0.2, noise=0.5, volume=10.0, seed=5)
    b = [dict(x, v=x["v"] * 10) for x in a]  # volume x10, gia y nguyen
    fa = F.compute_series(a, bbw_min_samples=5, vol_min_samples=5)
    fb = F.compute_series(b, bbw_min_samples=5, vol_min_samples=5)
    for i in range(28, 60):
        assert fa[i] is not None and fb[i] is not None
        assert fa[i]["vol_pct"] == pytest.approx(fb[i]["vol_pct"])


def test_vol_pct_matches_percentile_of_rv():
    bars = synth(40, drift=0.2, noise=0.6, seed=9)
    closes = [b["c"] for b in bars]
    series = F.compute_series(bars, bbw_min_samples=5, vol_min_samples=5)
    i = 30
    past = [F.realized_vol_1h(closes, j) for j in range(4, i)]
    expected = F.pct_rank([x for x in past if x is not None], series[i]["rv_1h"])
    assert series[i]["vol_pct"] == pytest.approx(expected)


def test_bbw_pct_requires_8640_samples():
    bars = synth(8665, drift=0.05, noise=0.4, seed=13)
    s = F.compute_series(bars)
    assert s[8658]["bbw_pct"] is None  # 8639 mau
    assert s[8659]["bbw_pct"] is not None  # 8640 mau
    assert "bbw_pct" in s[8658]["warmup"]


@pytest.mark.parametrize(
    "value, allowed",
    [(None, False), (14.9, False), (15.0, False), (15.1, True), (80.0, True)],
)
def test_bbw_pct_15_blocks_mean_reversion(value, allowed):
    assert F.allow_mean_reversion(value) is allowed


def test_no_lookahead_future_bars_do_not_change_past():
    past = synth(500, drift=0.1, noise=0.5, seed=21)
    future = synth(550, drift=0.1, noise=0.5, seed=21)
    a = F.compute_series(past, bbw_min_samples=50, vol_min_samples=50)
    b = F.compute_series(future, bbw_min_samples=50, vol_min_samples=50)
    assert a[499] is not None
    assert a[499] == b[499]


def test_gap_disables_features_for_affected_window():
    bars = synth(300, drift=0.1, noise=0.5, seed=31)
    gapped = bars[:100] + bars[101:]  # thieu 1 nen 15m
    s = F.compute_series(gapped, bbw_min_samples=5, vol_min_samples=5)
    assert all(s[i] is None for i in range(100, 119))
    assert s[119] is not None  # du 20 nen lien tuc sau gap
    assert F.gap_boundaries(gapped) == [100]


def test_missing_data_gives_unknown_inputs_none():
    s = F.compute_series(synth(10), bbw_min_samples=5, vol_min_samples=5)
    assert all(x is None for x in s)  # chua du BB20


def test_warmup_lists_missing_features():
    s = F.compute_series(
        synth(40, drift=0.1, noise=0.4, seed=17), bbw_min_samples=50, vol_min_samples=50
    )
    assert "bbw_pct" in s[30]["warmup"] and "ema200" in s[30]["warmup"]
    assert s[30]["oi"] is None and s[30]["funding"] is None


def test_oi_funding_parse():
    assert F.funding_from_premium({"lastFundingRate": "0.00010000"}) == 0.0001
    assert F.funding_from_premium({}) is None
    assert F.funding_from_premium({"lastFundingRate": "x"}) is None
    assert F.oi_from_payload({"openInterest": "12345.678"}) == 12345.678
    assert F.oi_from_payload({}) is None


def test_oi_funding_attached_by_ts():
    bars = synth(40, drift=0.1, noise=0.4, seed=41)
    ts = bars[30]["open_time"]
    s = F.compute_series(
        bars, bbw_min_samples=5, vol_min_samples=5, oi={ts: 999.0}, funding={ts: -0.0002}
    )
    assert s[30]["oi"] == 999.0 and s[30]["funding"] == -0.0002


def test_range_pct_matches_percentile_of_past_ratio():
    bars = synth(120, drift=0.1, noise=0.6, seed=23)
    s = F.compute_series(bars, bbw_min_samples=5, vol_min_samples=5, range_min_samples=5)
    i = 100
    closes = [b["c"] for b in bars]
    atr = F.atr_series([b["h"] for b in bars], [b["l"] for b in bars], closes)
    ratios = []
    for j in range(i):
        if atr[j] is None:
            continue
        seg = bars[max(0, j - F.RANGE_N + 1): j + 1]
        hi, lo = max(b["h"] for b in seg), min(b["l"] for b in seg)
        ratios.append((hi - lo) / atr[j])
    expected = F.pct_rank(ratios, s[i]["range_ratio"])
    assert s[i]["range_pct"] == pytest.approx(expected)
    assert s[i]["range_ratio"] == pytest.approx(s[i]["range_24h"] / s[i]["atr"])


def test_range_pct_warmup_is_none_and_listed():
    s = F.compute_series(
        synth(60, drift=0.1, noise=0.4, seed=29), bbw_min_samples=5, vol_min_samples=5
    )
    assert s[40]["range_pct"] is None and "range_pct" in s[40]["warmup"]


def test_compute_at_matches_series():
    bars = synth(120, drift=0.1, noise=0.5, seed=51)
    s = F.compute_series(bars)
    assert F.compute_at(bars, 99) == s[99]
    assert F.compute_at(bars, -1) is None
