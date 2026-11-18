"""Executor P1.3: entry + SL ngay + TP (MR). Fake REST, khong mang."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.config import load as load_cfg
from app.db.store import connect
from app.exec.executor import Executor
from app.risk.types import OrderRequest
from tests.test_risk_limits import inp

ROOT = Path(__file__).resolve().parents[2]
CFG = load_cfg(ROOT / "config" / "mvp.mock.yaml")


class FakeRest:
    """Ghi lai moi call; tra response toi thieu giong mock."""

    def __init__(self, fill_status: str = "FILLED", avg: str = "100.0") -> None:
        self.calls: list[tuple[str, str, dict, float]] = []
        self.fill_status = fill_status
        self.avg = avg
        self.deny_post = False

    def get(self, path, params=None, signed=True, max_tries=4):
        self.calls.append(("GET", path, dict(params or {}), time.monotonic()))
        if path == "/fapi/v1/exchangeInfo":
            return {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "filters": [
                            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                            {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                            {"filterType": "MIN_NOTIONAL", "notional": "5"},
                        ],
                    }
                ]
            }
        if path == "/fapi/v1/order":
            return {"status": self.fill_status, "avgPrice": self.avg, "executedQty": "0.75"}
        return {}

    def post(self, path, params=None, signed=True, max_tries=4):
        self.calls.append(("POST", path, dict(params or {}), time.monotonic()))
        if self.deny_post:
            raise RuntimeError("khong duoc gui lenh")
        if path == "/fapi/v1/algoOrder":
            return {"algoId": f"A{len(self.calls)}"}
        return {"orderId": f"O{len(self.calls)}"}

    def delete(self, path, params=None, signed=True, max_tries=4):
        self.calls.append(("DELETE", path, dict(params or {}), time.monotonic()))
        return {}

    def posts(self, path: str) -> list[tuple[str, str, dict, float]]:
        return [c for c in self.calls if c[0] == "POST" and c[1] == path]


@pytest.fixture()
def ex(tmp_path):
    con = connect(str(tmp_path / "p13.db"))
    rest = FakeRest()
    e = Executor(con, rest, CFG, sleep=lambda _s: None)
    yield e, rest, con
    con.close()


def mr_req(**over) -> OrderRequest:
    base = dict(
        strategy_id="mean_reversion",
        symbol="BTCUSDT",
        side="BUY",
        entry=100.0,
        stop=99.0,
        tp=102.0,
        order_type="post_only",
    )
    base.update(over)
    return OrderRequest(**base)


def test_mr_open_places_limit_then_sl_then_tp(ex):
    e, rest, con = ex
    r = e.open(mr_req(), inputs=inp())
    assert r["ok"] and r["sl_id"] and r["tp_id"]
    order = rest.posts("/fapi/v1/order")[0][2]
    assert order["type"] == "LIMIT" and order["timeInForce"] == "GTX"
    algos = rest.posts("/fapi/v1/algoOrder")
    assert [a[2]["type"] for a in algos] == ["STOP_MARKET", "TAKE_PROFIT_MARKET"]
    assert algos[0][2]["side"] == "SELL" and algos[0][2]["closePosition"] == "true"
    row = con.execute("SELECT side,sl,tp,strategy_id,state FROM positions").fetchone()
    assert row[0] == "LONG" and row[3] == "mean_reversion" and row[4] == "OPEN"


def test_trend_open_market_and_no_tp(ex):
    e, rest, con = ex
    r = e.open(mr_req(strategy_id="trend_pullback", order_type="market", tp=None), inputs=inp())
    assert r["ok"]
    order = rest.posts("/fapi/v1/order")[0][2]
    assert order["type"] == "MARKET" and "timeInForce" not in order
    assert len(rest.posts("/fapi/v1/algoOrder")) == 1


def test_short_sl_is_buy_stop_above(ex):
    e, rest, _ = ex
    r = e.open(
        mr_req(side="SELL", entry=100.0, stop=101.0, tp=98.0, strategy_id="trend_pullback"),
        inputs=inp(allow_short=True),
    )
    assert r["ok"]
    sl = rest.posts("/fapi/v1/algoOrder")[0][2]
    assert sl["side"] == "BUY" and float(sl["triggerPrice"]) > 100.0


def test_reject_means_no_orders(ex):
    e, rest, _ = ex
    r = e.open(mr_req(), inputs=inp(halted=True))
    assert not r["ok"] and r["reason"] == "halted"
    assert rest.posts("/fapi/v1/order") == [] and rest.posts("/fapi/v1/algoOrder") == []


def test_min_notional_rejects_before_any_call(ex):
    e, rest, _ = ex
    r = e.open(mr_req(stop=50.0), inputs=inp(min_notional=1000.0))
    assert not r["ok"] and r["reason"] == "min_notional"
    assert rest.posts("/fapi/v1/order") == []


def test_sl_placed_within_300ms_of_fill(ex):
    e, rest, _ = ex
    e.open(mr_req(), inputs=inp())
    fill_at = next(c[3] for c in rest.calls if c[0] == "GET" and c[1] == "/fapi/v1/order")
    sl_at = rest.posts("/fapi/v1/algoOrder")[0][3]
    assert (sl_at - fill_at) * 1000 < 300


def test_sl_trigger_rounded_to_tick(ex):
    e, rest, _ = ex
    e.open(mr_req(stop=98.987), inputs=inp())
    assert rest.posts("/fapi/v1/algoOrder")[0][2]["triggerPrice"] == "98.9"


def test_no_fill_cancels_and_expires(tmp_path):
    con = connect(str(tmp_path / "p13.db"))
    rest = FakeRest(fill_status="NEW")
    e = Executor(con, rest, CFG, sleep=lambda _s: None)
    r = e.open(mr_req(), inputs=inp())
    assert not r["ok"] and r["reason"] == "no_fill"
    assert len(rest.calls) >= 12  # 10 lan poll + cancel
    assert any(c[0] == "DELETE" for c in rest.calls)
    assert con.execute("SELECT status FROM signals").fetchone()[0] == "EXPIRED"
    con.close()


def test_duplicate_place_does_not_duplicate_sl(tmp_path):
    con = connect(str(tmp_path / "p13.db"))
    rest = FakeRest()
    e = Executor(con, rest, CFG, sleep=lambda _s: None)
    # gia lap OrderManager tra deduped (id da ton tai) cho lan goi thu 2
    calls = {"n": 0}
    orig = e._mgr.place

    def place_twice(*a, **kw):
        calls["n"] += 1
        res = orig(*a, **kw)
        return res

    e._mgr.place = place_twice
    r = e.open(mr_req(), inputs=inp())
    assert r["ok"] and calls["n"] == 1
    assert len(rest.posts("/fapi/v1/algoOrder")) == 2  # dung 1 SL + 1 TP
    con.close()


def test_open_records_signal_filled(ex):
    e, rest, con = ex
    e.open(mr_req(), inputs=inp())
    row = con.execute("SELECT status, strategy_id, risk_usd FROM signals").fetchone()
    assert row[0] == "FILLED" and row[1] == "mean_reversion" and row[2] > 0


def test_format_step():
    from app.exec.executor import fmt_step

    assert fmt_step(0.75, 0.001) == "0.750"
    assert fmt_step(1.2, 0.1) == "1.2"
