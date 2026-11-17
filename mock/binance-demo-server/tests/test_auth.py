"""M0.3 â€” xac thuc HMAC, timing, weight, 429/418."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import auth, state
from app.config import CFG
from app.main import app

client = TestClient(app)
SECRET = auth.DEFAULT_SECRET
CONTRACTS_PATH = Path(__file__).resolve().parents[2] / "contracts" / "contracts.json"
CONTRACTS = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))


def _sig(secret: str, unsigned: str) -> str:
    return hmac.new(secret.encode(), unsigned.encode(), hashlib.sha256).hexdigest()


def make_qs(params: dict, secret: str = SECRET, sign_over: str | None = None) -> str:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    payload = sign_over if sign_over is not None else qs
    return qs + "&signature=" + _sig(secret, payload)


def signed_get(path: str, extra: dict | None = None, secret: str = SECRET,
               sign_over: str | None = None, key: str | None = "mock-key"):
    params = {"symbol": "BTCUSDT", "timestamp": state.now_ms(), "recvWindow": 5000}
    params.update(extra or {})
    qs = make_qs(params, secret, sign_over)
    headers = {"X-MBX-APIKEY": key} if key is not None else {}
    return client.get(f"{path}?{qs}", headers=headers)


# ---------------------------------------------------------------- golden vector

def test_golden_vector_signature():
    a = CONTRACTS["auth"]
    assert _sig(a["secret_example"], a["payload"]) == a["signature_hex"]
    assert auth.sign(a["secret_example"], a["payload"]) == a["signature_hex"]


def test_split_total_params_drops_signature():
    params, unsigned = auth.split_total_params(
        "a=1&b=2&signature=deadbeef", "")
    assert params == {"a": "1", "b": "2", "signature": "deadbeef"}
    assert unsigned == "a=1&b=2"


# ---------------------------------------------------------------- happy path

def test_signed_ok_and_headers():
    r = signed_get("/fapi/v1/commissionRate")
    assert r.status_code == 200, r.text
    assert r.json()["makerCommissionRate"] == "0.000200"
    assert "X-MBX-USED-WEIGHT-1M" in r.headers
    assert "X-MBX-ORDER-COUNT-10S" in r.headers
    assert "X-MBX-ORDER-COUNT-1M" in r.headers


# ---------------------------------------------------------------- failures

def test_missing_api_key():
    r = signed_get("/fapi/v1/commissionRate", key=None)
    assert r.status_code == 400
    assert r.json()["code"] == -2014


def test_missing_signature():
    qs = f"symbol=BTCUSDT&timestamp={state.now_ms()}&recvWindow=5000"
    r = client.get(f"/fapi/v1/commissionRate?{qs}", headers={"X-MBX-APIKEY": "k"})
    assert r.json()["code"] == -1102


def test_bad_secret():
    r = signed_get("/fapi/v1/commissionRate", secret="sai-mat-khau")
    assert r.json()["code"] == -1022


def test_param_order_matters():
    """Ky tren chuoi co thu tu khac -> phai bi tu choi."""
    params = {"symbol": "BTCUSDT", "timestamp": state.now_ms(), "recvWindow": 5000}
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    wrong_order = "&".join(f"{k}={v}" for k, v in reversed(list(params.items())))

    r = client.get(
        f"/fapi/v1/commissionRate?{qs}&signature={_sig(SECRET, wrong_order)}",
        headers={"X-MBX-APIKEY": "k"},
    )
    assert r.json()["code"] == -1022

    r2 = client.get(
        f"/fapi/v1/commissionRate?{qs}&signature={_sig(SECRET, qs)}",
        headers={"X-MBX-APIKEY": "k"},
    )
    assert r2.status_code == 200, r2.text


def test_timestamp_skew():
    r = signed_get("/fapi/v1/commissionRate", extra={"timestamp": state.now_ms() - 20_000})
    assert r.json()["code"] == -1021


def test_tiny_recv_window():
    r = signed_get("/fapi/v1/commissionRate", extra={"timestamp": state.now_ms() - 1500, "recvWindow": 100})
    assert r.json()["code"] == -1021


def test_auth_strict_false_allows_unsigned(monkeypatch):
    monkeypatch.setattr(CFG, "auth_strict", False)
    r = client.get("/fapi/v1/commissionRate?symbol=BTCUSDT")
    assert r.status_code == 200


def test_wrong_api_key_when_configured(monkeypatch):
    """Chi tra -2015 khi MOCK_API_KEY duoc dat; mac dinh mock chap nhan moi key khong rong."""
    monkeypatch.setattr(CFG, "api_key_env", "dung-key")
    r = signed_get("/fapi/v1/commissionRate", key="sai-key")
    assert r.json()["code"] == -2015
    monkeypatch.setattr(CFG, "api_key_env", "")
    r2 = signed_get("/fapi/v1/commissionRate", key="bat-ky")
    assert r2.status_code == 200


# ---------------------------------------------------------------- rate limit

def test_weight_accumulates(monkeypatch):
    monkeypatch.setattr(CFG, "weight_limit_1m", 100)
    r1 = signed_get("/fapi/v1/commissionRate")
    w1 = int(r1.headers["X-MBX-USED-WEIGHT-1M"])
    r2 = signed_get("/fapi/v1/commissionRate")
    w2 = int(r2.headers["X-MBX-USED-WEIGHT-1M"])
    assert w2 == w1 + 20  # commissionRate weight = 20


def test_429_then_418(monkeypatch):
    monkeypatch.setattr(CFG, "weight_limit_1m", 30)
    r1 = signed_get("/fapi/v1/commissionRate")
    assert r1.status_code == 200
    r2 = signed_get("/fapi/v1/commissionRate")  # 40 > 30
    assert r2.status_code == 429
    assert r2.json()["code"] == -1003
    r3 = signed_get("/fapi/v1/commissionRate")  # spam tiep -> ban
    assert r3.status_code == 418


def test_banned_ip_blocked(monkeypatch):
    monkeypatch.setattr(CFG, "weight_limit_1m", 1)
    signed_get("/fapi/v1/commissionRate")   # 20 > 1 -> 429
    signed_get("/fapi/v1/commissionRate")   # -> 418 ban
    r = signed_get("/fapi/v1/commissionRate")
    assert r.status_code == 418


def test_reset_clears(monkeypatch):
    monkeypatch.setattr(CFG, "weight_limit_1m", 1)
    signed_get("/fapi/v1/commissionRate")
    auth.LIMITS.reset()
    monkeypatch.setattr(CFG, "weight_limit_1m", 2400)
    r = signed_get("/fapi/v1/commissionRate")
    assert r.status_code == 200


def signed_post(path: str, body: dict, secret: str = SECRET, key: str | None = "mock-key"):
    params = {k: str(v) for k, v in body.items()}
    params["timestamp"] = str(state.now_ms())
    params["recvWindow"] = "5000"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full = f"{qs}&signature={_sig(secret, qs)}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if key:
        headers["X-MBX-APIKEY"] = key
    return client.post(f"{path}?{full}", headers=headers)

def signed_delete(path: str, params: dict, secret: str = SECRET, key: str | None = "mock-key"):
    p = {k: str(v) for k, v in params.items()}
    p["timestamp"] = str(state.now_ms())
    p["recvWindow"] = "5000"
    qs = "&".join(f"{k}={v}" for k, v in p.items())
    headers = {}
    if key:
        headers["X-MBX-APIKEY"] = key
    return client.delete(f"{path}?{qs}&signature={_sig(secret, qs)}", headers=headers)

def signed_put(path: str, body: dict, secret: str = SECRET, key: str | None = "mock-key"):
    params = {k: str(v) for k, v in body.items()}
    params["timestamp"] = str(state.now_ms())
    params["recvWindow"] = "5000"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    headers = {}
    if key:
        headers["X-MBX-APIKEY"] = key
    return client.put(f"{path}?{qs}&signature={_sig(secret, qs)}", headers=headers)
