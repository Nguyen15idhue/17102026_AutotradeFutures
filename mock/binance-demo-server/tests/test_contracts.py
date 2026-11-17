"""M0.1 — contract & fixtures: cau truc, golden vector, du lieu that."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = json.loads((ROOT / "contracts" / "contracts.json").read_text(encoding="utf-8"))
FIXTURES = ROOT / "fixtures"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"]

REQUIRED_CONTRACTS = [
    "auth", "error", "time", "listenKey", "balance", "account", "positionRisk",
    "commissionRate", "leverageBracket", "order", "algoOrder", "openAlgoOrders",
    "events",
]


def test_all_contracts_present():
    for key in REQUIRED_CONTRACTS:
        assert key in CONTRACTS, f"thieu contract: {key}"


def test_golden_signature():
    a = CONTRACTS["auth"]
    got = hmac.new(a["secret_example"].encode(), a["payload"].encode(), hashlib.sha256).hexdigest()
    assert got == a["signature_hex"]


def test_exchange_info_snapshot():
    ex = json.loads((FIXTURES / "exchangeInfo.json").read_text(encoding="utf-8"))
    got = {s["symbol"] for s in ex["symbols"]}
    assert got == set(SYMBOLS)
    for s in ex["symbols"]:
        types = {f["filterType"] for f in s["filters"]}
        assert "PRICE_FILTER" in types
        assert "LOT_SIZE" in types
        assert "MIN_NOTIONAL" in types


def test_filters_are_sane():
    ex = json.loads((FIXTURES / "exchangeInfo.json").read_text(encoding="utf-8"))
    for s in ex["symbols"]:
        f = {x["filterType"]: x for x in s["filters"]}
        assert float(f["PRICE_FILTER"]["tickSize"]) > 0
        assert float(f["LOT_SIZE"]["stepSize"]) > 0
        assert float(f["MIN_NOTIONAL"]["notional"]) >= 1


def test_klines_fixture():
    kl = json.loads((FIXTURES / "klines.json").read_text(encoding="utf-8"))
    assert set(kl) == set(SYMBOLS)
    for sym, d in kl.items():
        assert len(d["15m"]) == 500, sym
        assert len(d["1m"]) == 300, sym
        assert len(d["15m"][0]) == 12


def test_meta_fixture():
    meta = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))
    assert meta["source"].startswith("https://")
    assert meta["fetched_at_ms"] > 0
    assert meta["note"]


def test_contract_numbers_are_strings():
    """Binance tra so thap phan dang chuoi — hop dong phai giu dung kieu."""
    o = CONTRACTS["order"]
    for field in ("price", "origQty", "executedQty", "avgPrice"):
        assert isinstance(o[field], str)
    a = CONTRACTS["algoOrder"]
    assert isinstance(a["triggerPrice"], str)
    assert isinstance(a["algoId"], int)


def test_event_contracts_shape():
    ev = CONTRACTS["events"]
    assert ev["ORDER_TRADE_UPDATE"]["e"] == "ORDER_TRADE_UPDATE"
    assert ev["ALGO_UPDATE"]["e"] == "ALGO_UPDATE"
    assert ev["ACCOUNT_UPDATE"]["e"] == "ACCOUNT_UPDATE"
    assert "o" in ev["ORDER_TRADE_UPDATE"]
    for field in ("caid", "aid", "at", "o", "s", "S", "X", "tp", "wt", "cp", "pP"):
        assert field in ev["ALGO_UPDATE"]["o"]
