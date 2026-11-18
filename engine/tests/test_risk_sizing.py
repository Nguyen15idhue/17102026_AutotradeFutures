"""Test sizing P1.3: floor step/tick, minNotional reject, stop sai phia."""

from __future__ import annotations

import pytest

from app.risk import correlation, sizing
from app.risk.types import OrderRequest, RiskInputs  # noqa: F401  (dung cho type hint ro rang)
from tests.test_risk_limits import inp, req


def test_floor_to_step():
    assert sizing.floor_to(0.0034567, 0.001) == pytest.approx(0.003)
    assert sizing.floor_to(123.456, 0.1) == pytest.approx(123.4)


def test_round_price_to_tick():
    assert sizing.round_price(100.567, 0.1) == pytest.approx(100.5)
    assert sizing.round_price(100.0, 0.1) == pytest.approx(100.0)


def test_size_never_above_risk():
    d = sizing.plan(req(entry=100.0, stop=99.0), inp())
    assert d.ok and d.risk_usd <= 0.75 + 1e-12
    assert d.qty == pytest.approx(0.75)  # 0.75 USD / 1.0, step 0.001


def test_min_notional_rejects_without_increasing_size():
    # stop rat rong -> qty nho -> notional duoi min
    d = sizing.plan(req(entry=100.0, stop=50.0), inp(min_notional=5.0))
    assert not d.ok and d.reason == sizing.REASON_MIN_NOTIONAL
    assert d.qty == 0.0


def test_stop_wrong_side_long():
    d = sizing.plan(req(entry=100.0, stop=101.0), inp())
    assert not d.ok and d.reason == sizing.REASON_INVALID_STOP


def test_stop_wrong_side_short():
    d = sizing.plan(req(side="SELL", entry=100.0, stop=99.0), inp())
    assert not d.ok and d.reason == sizing.REASON_INVALID_STOP


def test_tp_wrong_side():
    d = sizing.plan(req(entry=100.0, stop=99.0, tp=95.0), inp())
    assert not d.ok and d.reason == sizing.REASON_INVALID_STOP


def test_meta_risk_above_limit_rejected():
    d = sizing.plan(req(meta={"risk_usd": 5.0}), inp())
    assert not d.ok and d.reason == sizing.REASON_RISK_TOO_LARGE


def test_meta_risk_within_limit_ok():
    d = sizing.plan(req(meta={"risk_usd": 0.5}), inp())
    assert d.ok and d.risk_usd <= 0.5 + 1e-12


def test_correlation_groups():
    btc = [0.01, -0.02, 0.015, 0.005, -0.01]
    close = [0.011, -0.019, 0.014, 0.004, -0.009]
    far = [0.01, 0.02, -0.015, -0.005, 0.01]
    g = correlation.groups({"BTCUSDT": btc, "AUSDT": close, "BUSDT": far}, btc)
    assert g["BTCUSDT"] == "BTC" and g["AUSDT"] == "BTC" and g["BUSDT"] == "BUSDT"


def test_correlation_missing_data_fail_closed():
    assert correlation.groups({"AUSDT": []}, [])["AUSDT"] == correlation.GROUP_UNKNOWN


def test_risk_inputs_are_immutable():
    i = inp()
    with pytest.raises(Exception):
        i.equity = 1.0  # type: ignore[misc]


def test_decision_carries_sizing_fields():
    d = sizing.plan(req(), inp())
    assert d.ok and d.notional == pytest.approx(d.qty * 100.0)
    assert d.margin == pytest.approx(d.notional / 3)
