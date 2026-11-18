"""Test P1.2 regime: nguong spec, thu tu uu tien, hysteresis/cooldown, CRISIS."""

from __future__ import annotations

import pytest

from app.regime import detector as D
from app.regime.types import RegimeInputs, RegimeLabel


def feat(**over) -> dict:
    """Baseline thoa RANGE: adx 15, range 200 < 2.5*100, vol_pct 40, bbw_pct 30."""
    f = {
        "adx": 15.0,
        "atr": 100.0,
        "range_24h": 200.0,
        "bbw_pct": 30.0,
        "vol_pct": 40.0,
        "ema50": 110.0,
        "ema200": 100.0,
        "vol_sma5": 8.0,
        "vol_sma20": 10.0,
    }
    f.update(over)
    return f


def labels():
    return [
        RegimeLabel.CRISIS,
        RegimeLabel.SQUEEZE,
        RegimeLabel.RANGE,
        RegimeLabel.TREND,
        RegimeLabel.UNKNOWN,
    ]


def test_thresholds_match_spec():
    assert (D.ADX_RANGE_MAX, D.ADX_TREND_MIN) == (20.0, 22.0)
    assert (D.SQUEEZE_BBW_PCT_MAX, D.SQUEEZE_RANGE_ATR_MULT) == (20.0, 1.5)
    assert (D.RANGE_ATR_MULT, D.RANGE_BBW_PCT_MIN) == (2.5, 15.0)
    assert (D.RANGE_VOL_PCT_MIN, D.RANGE_VOL_PCT_MAX) == (20.0, 60.0)
    assert (D.CRISIS_SPREAD_MULT, D.CRISIS_LIQ_COUNT) == (3.0, 5)
    assert (D.CRISIS_FUNDING_ABS, D.CRISIS_BTC_RET_15M) == (0.001, -0.04)
    assert (D.HYSTERESIS_BARS, D.COOLDOWN_BARS, D.CRISIS_CONFIRM_BARS) == (3, 5, 1)


def test_range_baseline():
    label, conf, reason = D.classify(RegimeInputs(feat()))
    assert label is RegimeLabel.RANGE and conf == 1.0 and reason.startswith("range:ok")


def test_squeeze_wins_over_range():
    f = feat(bbw_pct=10.0, range_24h=100.0, vol_sma5=5.0, vol_sma20=10.0)
    label, conf, _ = D.classify(RegimeInputs(f))
    assert label is RegimeLabel.SQUEEZE and conf == 1.0


def test_crisis_wins_over_squeeze():
    f = feat(bbw_pct=10.0, range_24h=100.0)
    label, conf, reason = D.classify(RegimeInputs(f, funding=0.01))
    assert label is RegimeLabel.CRISIS and conf == 1.0 and "funding" in reason


@pytest.mark.parametrize(
    "kw",
    [
        {"spread_bps": 40.0, "spread_avg_1h": 5.0},
        {"liq_count_1m": 6},
        {"funding": -0.0011},
        {"btc_ret_15m": -0.041},
    ],
)
def test_each_crisis_condition_triggers(kw):
    label, _, reason = D.classify(RegimeInputs(feat(), **kw))
    assert label is RegimeLabel.CRISIS, reason


@pytest.mark.parametrize(
    "kw",
    [
        {"spread_bps": 10.0, "spread_avg_1h": 5.0},
        {"liq_count_1m": 5},
        {"funding": 0.001},
        {"btc_ret_15m": -0.04},
    ],
)
def test_crisis_boundaries_do_not_trigger(kw):
    label, _, _ = D.classify(RegimeInputs(feat(), **kw))
    assert label is RegimeLabel.RANGE


def test_crisis_missing_inputs_are_not_triggered_but_reported():
    label, _, reason = D.classify(RegimeInputs(feat()))
    assert label is RegimeLabel.RANGE
    assert "missing:spread,liq,funding,btc" in reason


def test_trend_requires_adx_and_ema_order():
    f = feat(
        adx=30.0, ema50=120.0, ema200=100.0, bbw_pct=30.0, vol_pct=40.0, range_24h=400.0
    )  # range 400 > 2.5*ATR nen khong phai RANGE
    label, conf, _ = D.classify(RegimeInputs(f))
    assert label is RegimeLabel.TREND and conf == 1.0
    assert (
        D.classify(RegimeInputs(feat(adx=30.0, ema50=90.0, range_24h=400.0)))[0]
        is RegimeLabel.UNKNOWN
    )


def test_dead_zone_between_adx_thresholds_is_unknown():
    label, conf, reason = D.classify(RegimeInputs(feat(adx=21.0)))
    assert label is RegimeLabel.UNKNOWN and conf == 0.0 and "adx" in reason


def test_bbw_pct_14_9_never_range_or_squeeze():
    # range 200: squeeze fail (can <150), range fail vi bbw_pct<=15
    label, _, _ = D.classify(RegimeInputs(feat(bbw_pct=14.9)))
    assert label is RegimeLabel.UNKNOWN


def test_missing_feature_is_unknown_zero_confidence():
    label, conf, reason = D.classify(RegimeInputs(None))
    assert label is RegimeLabel.UNKNOWN and conf == 0.0 and reason == "missing:feature"


def test_missing_optional_fields_block_squeeze():
    f = feat(vol_sma5=None, vol_sma20=None, bbw_pct=10.0)
    label, _, _ = D.classify(RegimeInputs(f))
    assert label is not RegimeLabel.SQUEEZE


def _raw(label: RegimeLabel, conf: float = 1.0) -> tuple[RegimeLabel, float, str]:
    return label, conf, "x"


def test_crisis_confirms_on_first_bar():
    m = D.RegimeMachine()
    r = m.update(*_raw(RegimeLabel.CRISIS))
    assert r.label is RegimeLabel.CRISIS and r.changed and r.confidence == 1.0


def test_other_labels_need_three_bars():
    m = D.RegimeMachine()
    out = [m.update(*_raw(RegimeLabel.RANGE)).label for _ in range(3)]
    assert out == [RegimeLabel.UNKNOWN, RegimeLabel.UNKNOWN, RegimeLabel.RANGE]
    assert m.since_change == 0


def test_cooldown_blocks_change_five_bars_then_allows():
    m = D.RegimeMachine()
    for _ in range(3):
        m.update(*_raw(RegimeLabel.RANGE))
    assert m.current is RegimeLabel.RANGE
    seen = [m.update(*_raw(RegimeLabel.TREND)).label for _ in range(5)]
    assert all(x is RegimeLabel.RANGE for x in seen)  # 5 nen dau: cooldown chan
    assert m.update(*_raw(RegimeLabel.TREND)).label is RegimeLabel.TREND


def test_streak_resets_when_raw_changes():
    m = D.RegimeMachine()
    m.update(*_raw(RegimeLabel.RANGE))
    m.update(*_raw(RegimeLabel.RANGE))
    m.update(*_raw(RegimeLabel.SQUEEZE))  # streak SQUEEZE = 1
    m.update(*_raw(RegimeLabel.RANGE))  # streak RANGE = 1, khong du 3
    assert m.current is RegimeLabel.UNKNOWN


def test_held_label_with_other_raw_has_zero_confidence():
    m = D.RegimeMachine()
    for _ in range(3):
        m.update(*_raw(RegimeLabel.RANGE))
    r = m.update(*_raw(RegimeLabel.SQUEEZE))
    assert r.label is RegimeLabel.RANGE and r.confidence == 0.0
    assert r.raw_label is RegimeLabel.SQUEEZE


def test_unknown_confidence_is_zero():
    m = D.RegimeMachine()
    r = m.update(RegimeLabel.UNKNOWN, 0.0, "missing:feature")
    assert r.label is RegimeLabel.UNKNOWN and r.confidence == 0.0
