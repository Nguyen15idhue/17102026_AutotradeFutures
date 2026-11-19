"""Test backtest engine P1.4: fill model, funding, caps, report, walk-forward."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import config as config_mod
from app.backtest import diagnostics, loader, pipeline, walkforward
from app.backtest import report as report_mod
from app.backtest import sim as sim_mod

ROOT = Path(__file__).resolve().parents[2]
CFG = config_mod.load(ROOT / "config" / "mvp.mock.yaml")
H15 = sim_mod.H15_MS
H1 = sim_mod.H1_MS
H8 = sim_mod.H8_MS


def _ms(y, m, d) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def _sim(**kw) -> sim_mod.Sim:
    slices = kw.pop("slices", [sim_mod.Slice("S01", 0, 10**14)])
    s = sim_mod.Sim(CFG, {}, {}, slices, **kw)
    s._groups = {"BTCUSDT": "BTC", "ETHUSDT": "BTC"}
    s._group_slice = slices[0].name
    return s


def _pos(direction: int = 1, qty: float = 1.0, entry: float = 100.0, risk: float = 10.0):
    return sim_mod._Pos(
        strategy_id="mean_reversion",
        symbol="BTCUSDT",
        direction=direction,
        qty=qty,
        entry=entry,
        stop=entry - direction * 2.0,
        tp=None,
        risk_usd=risk,
        entry_ms=0,
        fees_entry=0.02,
    )


def _pending(
    limit: float = 100.0, direction: int = 1, expire_ms: int = 10 * H15
) -> sim_mod._Pending:
    return sim_mod._Pending(
        strategy_id="mean_reversion",
        symbol="BTCUSDT",
        direction=direction,
        qty=1.0,
        limit=limit,
        stop=98.0 if direction > 0 else 102.0,
        tp=None,
        risk_usd=10.0,
        expire_ms=expire_ms,
        chase_price=limit + direction * 1.0,
    )


# ---------- loader ----------


def test_aggregate_1m_to_15m():
    start = _ms(2026, 1, 1)
    bars = [
        {
            "open_time": start + i * sim_mod.MIN_MS,
            "close_time": start + i * sim_mod.MIN_MS + 59_999,
            "o": 100 + i,
            "h": 101 + i,
            "l": 99 + i,
            "c": 100.5 + i,
            "v": 2.0,
            "closed": True,
        }
        for i in range(15)
    ]
    out = loader.aggregate(bars, "15m")
    assert len(out) == 1
    assert out[0]["h"] == 115 and out[0]["l"] == 99 and out[0]["v"] == 30.0


def test_load_filters_from_exchange_info():
    f = loader.load_filters(ROOT / "mock" / "fixtures" / "exchangeInfo.json")
    assert f["BTCUSDT"]["min_notional"] == 50.0
    assert f["ETHUSDT"]["step_size"] > 0
    assert "SUIUSDT" in f


# ---------- fill model ----------


def test_limit_does_not_fill_without_trade_through():
    s = _sim()
    s.pending = [_pending(100.0)]
    s._fill_pending("BTCUSDT", {"o": 100.2, "h": 100.4, "l": 100.0, "c": 100.3}, 1)
    assert s.open == []
    assert len(s.pending) == 1


def test_limit_fills_only_when_price_trades_through():
    s = _sim()
    s.pending = [_pending(100.0)]
    s._fill_pending("BTCUSDT", {"o": 100.2, "h": 100.4, "l": 99.9, "c": 100.0}, 1)
    assert len(s.open) == 1
    assert s.open[0].entry == 100.0
    assert s.pending == []


def test_limit_cancelled_when_price_chases():
    s = _sim()
    s.pending = [_pending(100.0)]
    s._fill_pending("BTCUSDT", {"o": 100.2, "h": 102.0, "l": 99.5, "c": 101.8}, 1)
    assert s.open == [] and s.pending == []


def test_pending_expires_after_ttl():
    s = _sim()
    s.pending = [_pending(100.0, expire_ms=5 * H15)]
    s._fill_pending("BTCUSDT", {"o": 100.0, "h": 100.1, "l": 99.0, "c": 99.5}, 5 * H15)
    assert s.open == [] and s.pending == []


def test_short_limit_fills_on_upside_break():
    s = _sim()
    p = _pending(100.0, direction=-1)
    s.pending = [p]
    s._fill_pending("BTCUSDT", {"o": 99.9, "h": 100.1, "l": 99.5, "c": 100.0}, 1)
    assert len(s.open) == 1 and s.open[0].direction == -1


# ---------- funding ----------


def test_funding_applied_only_at_00_08_16_and_signed():
    s = _sim()
    long = _pos(1)
    s.open = [long]
    ts = _ms(2026, 1, 1)  # 00:00 UTC
    s.funding = {"BTCUSDT": {ts: 0.0002}}
    s._apply_funding(ts)
    assert long.funding_paid == pytest.approx(0.0002 * 100.0)
    s._apply_funding(ts + H1)  # 01:00 -> khong ap dung
    assert long.funding_paid == pytest.approx(0.0002 * 100.0)
    s._apply_funding(ts + H8)  # 08:00 nhung khong co rate -> khong doi
    assert long.funding_paid == pytest.approx(0.0002 * 100.0)

    short = _pos(-1)
    s.open = [short]
    s.funding = {"BTCUSDT": {ts: 0.0002}}
    s._apply_funding(ts)
    assert short.funding_paid == pytest.approx(-0.0002 * 100.0)


# ---------- risk caps ----------


def test_caps_block_when_max_positions_reached():
    s = _sim()
    s.open = [_pos() for _ in range(CFG.risk.max_positions)]
    assert s._caps_ok("trend_pullback", "ETHUSDT", 1.0, 1.0, 1) is False


def test_caps_block_per_strategy_even_with_free_slot():
    s = _sim()
    s.open = [_pos() for _ in range(CFG.strategies.max_positions_per_strategy)]
    assert s._caps_ok("mean_reversion", "ETHUSDT", 1.0, 1.0, 1) is False
    assert s._caps_ok("trend_pullback", "ETHUSDT", 1.0, 1.0, 1) is True


def test_caps_block_daily_loss_but_not_dd_by_default():
    s = _sim()
    s.realized = -CFG.risk.daily_loss_limit * s.equity_base * 1.01
    assert s._caps_ok("mean_reversion", "BTCUSDT", 1.0, 1.0, 1) is False
    s.realized = 0.0
    s.max_dd_pct = CFG.risk.max_drawdown * 100
    # mac dinh khong halt o DD (nghien cuu P1.4); bat dd_halt thi phai chan
    assert s._caps_ok("mean_reversion", "BTCUSDT", 1.0, 1.0, 1) is True
    s.dd_halt = True
    assert s._caps_ok("mean_reversion", "BTCUSDT", 1.0, 1.0, 1) is False


def test_caps_block_margin_usage():
    s = _sim()
    s.open = [
        _pos(qty=100.0, entry=100.0) for _ in range(CFG.risk.max_positions)
    ]  # notional 10k/vi the, margin ~3.3k > 60% cua 5k
    assert s._caps_ok("mean_reversion", "ETHUSDT", 1.0, 1.0, 1) is False


def test_close_computes_net_and_r_multiple():
    s = _sim()
    p = _pos(1, qty=2.0, entry=100.0, risk=10.0)
    p.funding_paid = 0.5
    s.open = [p]
    s._close(p, 103.0, 10, "tp")
    t = s.trades[0]
    gross = (103.0 - 100.0) * 2.0
    fee_exit = 103.0 * 2.0 * (CFG.execution.fee_bps_taker / 10_000)
    assert t.pnl_gross == pytest.approx(gross)
    assert t.fees == pytest.approx(0.02 + fee_exit)
    assert t.pnl == pytest.approx(gross - t.fees - 0.5)
    assert t.r_multiple == pytest.approx(t.pnl / 10.0)


# ---------- report ----------


def _trade(
    r: float, symbol: str, side: str = "LONG", strategy: str = "mean_reversion", sl: str = "S01"
):
    risk = 10.0
    return sim_mod.Trade(
        strategy_id=strategy,
        symbol=symbol,
        side=side,
        qty=1.0,
        entry=100.0,
        exit=100.0 + r * risk,
        entry_ms=0,
        exit_ms=1,
        reason="tp" if r > 0 else "sl",
        risk_usd=risk,
        pnl_gross=r * risk,
        fees=0.0,
        funding=0.0,
        r_multiple=r,
        slice=sl,
    )


def test_stats_and_gates():
    trades = [_trade(0.5, "BTCUSDT") for _ in range(200)]
    trades += [_trade(2.0, "ETHUSDT", "SHORT", "trend_pullback") for _ in range(25)]
    trades += [_trade(2.0, "SOLUSDT", "LONG", "trend_pullback") for _ in range(25)]
    slices = [sim_mod.Slice("S01", 0, 10)]
    rep = report_mod.build(
        trades,
        equity_base=5000.0,
        slices=slices,
        sim_summary={"max_dd_pct": 3.0},
        data_summary={},
    )
    assert rep["overall"]["n"] == 250
    assert rep["by_strategy"]["mean_reversion"]["win_rate"] == 1.0
    gates = {g["id"]: g for g in rep["gates"]}
    assert gates[1]["ok"] and gates[2]["ok"] and gates[3]["ok"]
    assert gates[4]["ok"] is True  # MR chi co BTCUSDT -> 1/1 coin duong
    assert gates[7]["ok"] is True


def test_gate7_fails_when_branch_under_20():
    trades = [_trade(0.1, "BTCUSDT", "LONG", "trend_pullback") for _ in range(5)]
    rep = report_mod.build(
        trades,
        equity_base=5000.0,
        slices=[sim_mod.Slice("S01", 0, 10)],
        sim_summary={"max_dd_pct": 0.0},
        data_summary={},
    )
    gates = {g["id"]: g for g in rep["gates"]}
    assert gates[7]["ok"] is False


# ---------- walk-forward ----------


def test_walkforward_slices_contiguous_and_oos_last_6_months():
    start, end = _ms(2024, 12, 1), _ms(2026, 11, 18)
    slices = walkforward.build_slices(start, end, oos_months=6, slice_months=2)
    assert slices[0].start_ms == start
    assert slices[-1].end_ms == end
    assert slices[-1].name == "OOS" and slices[-1].kind == "OOS"
    for a, b in zip(slices, slices[1:]):
        assert a.end_ms == b.start_ms  # khong chong, khong ho
    months = (slices[-1].end_ms - slices[-1].start_ms) / (30.4 * 86_400_000)
    assert 5.5 <= months <= 6.5


def test_run_cli_end_to_end(tmp_path):
    """Chay that tren 120 ngay du lieu tong hop: khong crash, ghi report, khong look-ahead crash."""
    from app.backtest import run as run_mod
    from app.data import parquet_io

    start = _ms(2026, 1, 1)
    days = 120
    root = tmp_path / "market"
    for sym, base in (("BTCUSDT", 100.0), ("ETHUSDT", 50.0)):
        for d in range(days):
            ts0 = start + d * 86_400_000
            bars = []
            for i in range(1440):
                px = base * (1 + 0.0005 * ((i % 60) - 30) / 30 + 0.0001 * d)
                bars.append(
                    {
                        "open_time": ts0 + i * 60_000,
                        "close_time": ts0 + i * 60_000 + 59_999,
                        "o": px,
                        "h": px * 1.0004,
                        "l": px * 0.9996,
                        "c": px * 1.0001,
                        "v": 10.0,
                        "closed": True,
                    }
                )
            parquet_io.save_day(
                root, sym, "1m", datetime.fromtimestamp(ts0 / 1000, tz=UTC).date().isoformat(), bars
            )
    out = tmp_path / "rep.json"
    code = run_mod.main(
        [
            "--config",
            str(ROOT / "config" / "mvp.mock.yaml"),
            "--data-dir",
            str(tmp_path),
            "--symbols",
            "BTCUSDT,ETHUSDT",
            "--start",
            "2026-01-01",
            "--end",
            "2026-05-01",
            "--exchange-info",
            str(ROOT / "mock" / "fixtures" / "exchangeInfo.json"),
            "--out",
            str(out),
            "--no-funding",
        ]
    )
    assert code == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["data"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert len(rep["slices"]) >= 1
    assert "gates" in rep


# ---------- diagnostics ----------


def test_path_outcome_sl_first():
    bars = {i * 60_000: {"h": 100.0, "l": 98.5, "c": 98.6} for i in range(1, 4)}
    out = diagnostics.path_outcome(bars, 60_000, 100.0, 99.0, 103.0, 1, 3)
    assert out["exit"] == "sl"
    assert out["mae_r"] == pytest.approx(-1.5)


def test_path_outcome_tp_first():
    bars = {i * 60_000: {"h": 103.5, "l": 99.4, "c": 103.0} for i in range(1, 4)}
    out = diagnostics.path_outcome(bars, 60_000, 100.0, 99.0, 103.0, 1, 3)
    assert out["exit"] == "tp"
    assert out["mfe_r"] == pytest.approx(3.5)


def test_path_outcome_same_bar_prefers_sl():
    bars = {60_000: {"h": 104.0, "l": 98.0, "c": 100.0}}
    out = diagnostics.path_outcome(bars, 60_000, 100.0, 99.0, 103.0, 1, 3)
    assert out["exit"] == "sl"


def test_path_outcome_short_mirror_and_close_r():
    bars = {i * 60_000: {"h": 100.5, "l": 98.0, "c": 99.0} for i in range(1, 4)}
    out = diagnostics.path_outcome(bars, 60_000, 100.0, 101.0, 98.0, -1, 3)
    assert out["exit"] == "tp"
    bars2 = {i * 60_000: {"h": 100.2, "l": 99.1, "c": 99.5} for i in range(1, 5)}
    out2 = diagnostics.path_outcome(bars2, 60_000, 100.0, 101.0, 98.0, -1, 4)
    assert out2["exit"] == "none"
    assert out2["close_r"] == pytest.approx(0.5)


def test_summary_percentages():
    rows = [
        {"mfe_r": 3.0, "mae_r": -0.2, "exit": "tp", "close_r": 2.0},
        {"mfe_r": 0.5, "mae_r": -1.0, "exit": "sl", "close_r": -1.0},
    ]
    s = diagnostics._summ(rows)
    assert s["n"] == 2
    assert s["exit_tp_pct"] == 0.5 and s["exit_sl_pct"] == 0.5
    assert s["p_mfe_ge_1r"] == 0.5
    assert s["close_r_win_pct"] == 0.5


def test_btc_returns_only_closed_15m():
    start = _ms(2026, 1, 1)
    bars = []
    for i in range(30):  # 2 nen 15m
        px = 100.0 + i
        bars.append(
            {
                "open_time": start + i * 60_000,
                "close_time": start + i * 60_000 + 59_999,
                "o": px,
                "h": px + 0.5,
                "l": px - 0.5,
                "c": px,
                "v": 1.0,
                "closed": True,
            }
        )
    rets = pipeline.btc_returns(bars)
    assert len(rets) == 1
    first_close = int(bars[14]["c"])
    second_close = int(bars[29]["c"])
    assert rets[start + 2 * H15] == pytest.approx(second_close / first_close - 1.0)
