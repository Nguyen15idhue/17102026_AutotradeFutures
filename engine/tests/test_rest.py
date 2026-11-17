"""REST: ky HMAC, retry 429/5xx, map error code. Hermetic (MockTransport)."""

import hashlib
import hmac

import httpx
import pytest

from app.exchange.rest import ERROR_TEXT, RestClient, RestError


def _client(handler):
    return RestClient("http://x", "k", "mock-secret", transport=httpx.MockTransport(handler))


def test_sign_matches_binance_rule():
    c = _client(lambda r: httpx.Response(200, json={}))
    qs = "quantity=10&symbol=DOGEUSDT&timestamp=1"
    expect = hmac.new(b"mock-secret", qs.encode(), hashlib.sha256).hexdigest()
    assert c.sign(qs) == expect and len(expect) == 64


def test_retry_429_then_ok():
    calls = []

    def h(r):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"code": -1003, "msg": "throttle"})
        return httpx.Response(200, json={"ok": True}, headers={"X-MBX-USED-WEIGHT-1M": "12"})

    c = _client(h)
    assert c.get("/fapi/v1/ping", signed=False) == {"ok": True}
    assert len(calls) == 3 and c.last_weight_1m == 12


def test_retry_exhausted_raises():
    c = _client(lambda r: httpx.Response(503, json={}))
    with pytest.raises(RestError):
        c.get("/fapi/v1/ping", signed=False, max_tries=2)


@pytest.mark.parametrize("code", [-1021, -1022, -2019, -4120, -4131, -1003, -1008])
def test_error_codes_mapped(code):
    assert code in ERROR_TEXT
    c = _client(lambda r: httpx.Response(400, json={"code": code, "msg": "m"}))
    with pytest.raises(RestError) as e:
        c.get("/fapi/v1/order", signed=False)
    assert e.value.code == code


def test_duplicate_id_is_error_not_retry():
    c = _client(lambda r: httpx.Response(400, json={"code": -2010, "msg": "dup"}))
    with pytest.raises(RestError) as e:
        c.post("/fapi/v1/order", {"symbol": "X"})
    assert e.value.code == -2010


def test_timestamp_uses_offset():
    c = _client(lambda r: httpx.Response(200, json={}))
    c.offset_ms = 1500
    import time

    assert abs(c.timestamp() - (int(time.time() * 1000) + 1500)) < 1000
