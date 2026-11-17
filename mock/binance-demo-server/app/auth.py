"""Xac thuc chu ky HMAC, timing va gioi han tan suat.

Cach Binance tinh chu ky: totalParams = query_string + request_body (noi chuoi),
signature la tham so cuoi va KHONG nam trong chuoi duoc ky.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qsl

from fastapi import Request

from . import errors as E
from . import state
from .config import CFG

DEFAULT_SECRET = "mock-secret"
WINDOW_MS_1M = 60_000
WINDOW_MS_10S = 10_000

# Trong so theo docs (co the lech nho; ghi ro trong docs/phase0 M0.3)
WEIGHTS: dict[str, dict[str, int]] = {
    "GET": {
        "/fapi/v1/ping": 1,
        "/fapi/v1/time": 1,
        "/fapi/v1/exchangeInfo": 1,
        "/fapi/v1/klines": 1,
        "/fapi/v1/ticker/price": 1,
        "/fapi/v1/ticker/bookTicker": 1,
        "/fapi/v1/premiumIndex": 1,
        "/fapi/v1/fundingRate": 1,
        "/fapi/v1/openInterest": 1,
        "/fapi/v1/depth": 2,
        "/fapi/v1/aggTrades": 20,
        "/fapi/v1/income": 30,
        "/fapi/v1/userTrades": 5,
        "/fapi/v1/commissionRate": 20,
        "/fapi/v1/leverageBracket": 1,
        "/fapi/v2/balance": 5,
        "/fapi/v2/account": 5,
        "/fapi/v2/positionRisk": 5,
        "/fapi/v1/openOrders": 1,
        "/fapi/v1/allOrders": 5,
        "/fapi/v1/order": 1,
        "/fapi/v1/openAlgoOrders": 1,
        "/fapi/v1/algoOrder": 1,
        "/fapi/v1/historicalAlgoOrders": 1,
        "/fapi/v1/listenKey": 1,
    },
    "POST": {
        "/fapi/v1/order": 1,
        "/fapi/v1/order/test": 1,
        "/fapi/v1/algoOrder": 1,
        "/fapi/v1/leverage": 1,
        "/fapi/v1/marginType": 1,
        "/fapi/v1/listenKey": 1,
    },
    "DELETE": {
        "/fapi/v1/order": 1,
        "/fapi/v1/allOpenOrders": 1,
        "/fapi/v1/algoOrder": 1,
        "/fapi/v1/algoOpenOrders": 1,
    },
    "PUT": {"/fapi/v1/listenKey": 1},
}


def weight_for(method: str, path: str) -> int:
    return WEIGHTS.get(method.upper(), {}).get(path, 1)


def is_order_route(method: str, path: str) -> bool:
    return (method.upper() == "POST" and path in (
        "/fapi/v1/order", "/fapi/v1/order/test", "/fapi/v1/algoOrder"))


# ---------------------------------------------------------------- params

def split_total_params(query: str, body: str) -> tuple[dict[str, str], str]:
    """Tra ve (params, chuoi_chua_ky). Loai bo segment signature."""
    total = query + body
    segments = [s for s in total.split("&") if s]
    unsigned = "&".join(s for s in segments if not s.startswith("signature="))
    params = dict(parse_qsl("&".join(segments), keep_blank_values=True))
    return params, unsigned


async def collect(request: Request) -> tuple[dict[str, str], str]:
    query = request.scope.get("query_string", b"").decode()
    body = ""
    if request.method in ("POST", "PUT", "DELETE"):
        raw = await request.body()
        body = raw.decode() if raw else ""
    return split_total_params(query, body)


def sign(secret: str, unsigned_total: str) -> str:
    return hmac.new(secret.encode(), unsigned_total.encode(), hashlib.sha256).hexdigest()


def secret_in_use() -> str:
    return CFG.api_secret_env or DEFAULT_SECRET


async def signed_params(request: Request) -> dict[str, str]:
    """Dependency cho moi endpoint SIGNED."""
    params, unsigned = await collect(request)
    if not CFG.auth_strict:
        return params

    key = request.headers.get("X-MBX-APIKEY") or params.get("apiKey", "")
    if not key:
        raise E.err(E.INVALID_API_KEY)
    if CFG.api_key_env and key != CFG.api_key_env:
        raise E.err(E.INVALID_KEY_IP_PERM)

    sig = params.get("signature", "")
    if not sig:
        raise E.err(E.NO_SIGNATURE)

    expect = sign(secret_in_use(), unsigned)
    if not hmac.compare_digest(expect.lower(), sig.lower()):
        raise E.err(E.BAD_SIGNATURE)

    try:
        ts = int(params.get("timestamp", "0"))
        recv = int(params.get("recvWindow", "5000"))
    except ValueError:
        raise E.err(E.INVALID_PARAM, p="timestamp") from None

    now = state.now_ms()
    if not (ts < now + 1000 and now - ts <= recv):
        raise E.err(E.TIMESTAMP_OUT_OF_WINDOW)

    return params


# ---------------------------------------------------------------- limits

class Limits:
    def __init__(self) -> None:
        self._weight: dict[str, list[float | int]] = {}
        self._order_10s: dict[str, list[float | int]] = {}
        self._order_1m: dict[str, list[float | int]] = {}
        self._banned: dict[str, float] = {}
        self._last_429: dict[str, float] = {}

    # --- weight ---
    def hit(self, ip: str, weight: int) -> tuple[int, bool]:
        now = time.time() * 1000
        start, used = self._weight.get(ip, [now, 0])
        if now - start >= WINDOW_MS_1M:
            start, used = now, 0
        used = int(used) + weight
        self._weight[ip] = [start, used]
        limit = CFG.weight_limit_1m
        return used, used > limit

    def used_weight(self, ip: str) -> int:
        now = time.time() * 1000
        start, used = self._weight.get(ip, [now, 0])
        if now - start >= WINDOW_MS_1M:
            return 0
        return int(used)

    # --- orders ---
    def hit_order(self, ip: str) -> tuple[int, int, bool]:
        """Tang bo dem order. Tra ve (used_10s, used_1m, vuot_limit)."""
        now = time.time() * 1000
        over = False
        for store, window, limit in (
            (self._order_10s, WINDOW_MS_10S, CFG.order_limit_10s),
            (self._order_1m, WINDOW_MS_1M, CFG.order_limit_1m),
        ):
            start, used = store.get(ip, [now, 0])
            if now - start >= window:
                start, used = now, 0
            used = int(used) + 1
            store[ip] = [start, used]
            if used > limit:
                over = True
        return self.used_orders_10s(ip), self.used_orders_1m(ip), over

    def used_orders_10s(self, ip: str) -> int:
        now = time.time() * 1000
        start, used = self._order_10s.get(ip, [now, 0])
        return 0 if now - start >= WINDOW_MS_10S else int(used)

    def used_orders_1m(self, ip: str) -> int:
        now = time.time() * 1000
        start, used = self._order_1m.get(ip, [now, 0])
        return 0 if now - start >= WINDOW_MS_1M else int(used)

    # --- ban ---
    def register_429(self, ip: str) -> bool:
        """Ghi nhan 429. Tra ve True neu IP bi ban (418)."""
        now = time.time() * 1000
        last = self._last_429.get(ip, 0)
        self._last_429[ip] = now
        if last and now - last <= 10_000:
            self._banned[ip] = now + CFG.ban_seconds * 1000
            return True
        return False

    def is_banned(self, ip: str) -> bool:
        until = self._banned.get(ip, 0)
        return until > time.time() * 1000

    def reset(self) -> None:
        self._weight.clear()
        self._order_10s.clear()
        self._order_1m.clear()
        self._banned.clear()
        self._last_429.clear()

    def snapshot(self, ip: str) -> dict:
        return {
            "weight_used_1m": self.used_weight(ip),
            "weight_limit_1m": CFG.weight_limit_1m,
            "orders_10s": self.used_orders_10s(ip),
            "orders_1m": self.used_orders_1m(ip),
            "banned": self.is_banned(ip),
        }


LIMITS = Limits()
