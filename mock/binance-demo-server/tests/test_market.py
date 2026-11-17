"""M0.4 â€” market data 3 che do: proxy | replay | synthetic."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import state
from app.config import CFG
from app.main import app
from app.market import MARKET

client = TestClient(app)

KLINE_KEYS = 12


@pytest.fixture(autouse=True)
def boot_replay():
    MARKET.boot("replay")
    yield
    MARKET.boot("replay")


def test_exchange_info_10_symbols():
    r = client.get("/fapi/v1/exchangeInfo")
    assert r.status_code == 200
    body = r.json()
    assert len(body["symbols"]) == 10
    syms = {s["symbol"] for s in body["symbols"]}
    assert "BTCUSDT" in syms
    btc = next(s for s in body["symbols"] if s["symbol"] == "BTCUSDT")
    types = {f["filterType"] for f in btc["filters"]}
    assert "PRICE_FILTER" in types and "LOT_SIZE" in types
    assert body["rateLimits"][0]["limit"] == 2400


def test_replay_klines_deterministic():
    a = client.get("/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=50").json()
    b = client.get("/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=50").json()
    assert a == b
    assert len(a) == 50
    assert len(a[0]) == KLINE_KEYS
    assert isinstance(a[0][0], int)
    assert isinstance(a[0][1], str)      # gia luon la chuoi


def test_replay_last_bar_is_fresh():
    """Replay phai dich thoi gian de nen cuoi ket thuc gan hien tai."""
    bars = client.get("/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=5").json()
    now = state.now_ms()
    assert now - bars[-1][6] < 15 * 60 * 1000
    assert bars[-1][0] < now


def test_synthetic_deterministic(monkeypatch):
    MARKET.boot("synthetic")
    frozen = 1_764_000_000_000
    monkeypatch.setattr(state, "now_ms", lambda: frozen)
    a = MARKET.klines("ETHUSDT", "1m", 20)
    b = MARKET.klines("ETHUSDT", "1m", 20)
    assert a == b
    assert len(a) == 20
    # nen lien tiep nhau theo buoc 60s
    assert a[1][0] - a[0][0] == 60_000


def test_synthetic_differs_by_seed(monkeypatch):
    frozen = 1_764_000_000_000
    monkeypatch.setattr(state, "now_ms", lambda: frozen)
    MARKET.boot("synthetic")
    a = MARKET.klines("ETHUSDT", "1m", 5)
    monkeypatch.setattr(CFG, "seed", 99)
    b = MARKET.klines("ETHUSDT", "1m", 5)
    assert a != b


def test_mark_price_differs_from_last(monkeypatch):
    MARKET.boot("synthetic")
    monkeypatch.setattr(state, "now_ms", lambda: 1_764_000_000_000)
    last = float(MARKET.last_price("BTCUSDT"))
    mark = float(MARKET.premium_index("BTCUSDT")["markPrice"])
    assert abs(mark - last) / last > 1e-6


def test_book_ticker_spread_positive():
    q = client.get("/fapi/v1/ticker/bookTicker?symbol=ETHUSDT").json()
    assert float(q["askPrice"]) > float(q["bidPrice"])
    assert q["symbol"] == "ETHUSDT"


def test_invalid_symbol():
    assert client.get("/fapi/v1/klines?symbol=KHONGCO&interval=1m").json()["code"] == -1121


def test_invalid_interval():
    assert client.get("/fapi/v1/klines?symbol=BTCUSDT&interval=7m").json()["code"] == -1130


def test_missing_symbol():
    assert client.get("/fapi/v1/klines?interval=1m").json()["code"] == -1102


def test_quote_inside_tick():
    MARKET.boot("synthetic")
    bid, ask = MARKET.quote("BTCUSDT")
    tick = MARKET.filters("BTCUSDT")["tick"]
    assert ask > bid
    assert (ask - bid) <= max(tick, bid * Decimal("0.001"))


def test_cache_ttl_helper():
    MARKET.boot("synthetic")
    MARKET._store("k", 50, {"v": 1})
    assert MARKET._cached("k", 0) == {"v": 1}
    import time as _t
    _t.sleep(0.08)
    assert MARKET._cached("k", 0) is None


def test_synthetic_jump_creates_crash(monkeypatch):
    MARKET.boot("synthetic")
    monkeypatch.setattr(state, "now_ms", lambda: 1_764_000_000_000)
    monkeypatch.setattr(CFG, "synth_jump_prob", 0.05)
    bars = MARKET.klines("BTCUSDT", "1m", 400)
    closes = [float(b[4]) for b in bars]
    moves = [abs(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    assert max(moves) > 0.02, "phai co it nhat 1 cu nhay > 2%"
