"""REST client: HMAC SHA256, recvWindow, retry 429/5xx, doc weight, map error code."""

from __future__ import annotations

import hashlib
import hmac
import random
import time
from urllib.parse import urlencode

import httpx

from . import clock as clock_mod

# Ma loi P1.1 phai co test rieng (checklist §test).
ERROR_TEXT = {
    -1002: "UNAUTHENTICATED",
    -1003: "TOO_MANY_REQUESTS",
    -1008: "SERVER_OVERLOADED",
    -1013: "INVALID_QUANTITY",
    -1021: "TIMESTAMP_OUT_OF_WINDOW",
    -1022: "INVALID_SIGNATURE",
    -2010: "DUPLICATE_ID",
    -2019: "MARGIN_INSUFFICIENT",
    -4023: "PRICE_FILTER_FAIL",
    -4014: "STEP_SIZE_FAIL",
    -4131: "TRIGGER_PRICE_FAIL",
    -4120: "STOP_ORDER_SWITCH_ALGO",
    -5021: "FOK_NOT_FILLABLE",
}

RETRY_STATUS = {429, 500, 502, 503, 504}


class RestError(Exception):
    def __init__(self, code: int, msg: str = ""):
        self.code = code
        super().__init__("[%s] %s" % (code, msg or ERROR_TEXT.get(code, "UNKNOWN")))


class RestClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        recv_window: int = 5000,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.secret = api_secret.encode()
        self.recv_window = recv_window
        self.offset_ms = 0
        self.last_weight_1m: int | None = None
        self._http = httpx.Client(base_url=self.base, timeout=timeout, transport=transport)

    # -- ky (giong mock auth.py: sort param, signature nam ngoai chuoi ky) --
    def sign(self, query: str) -> str:
        return hmac.new(self.secret, query.encode(), hashlib.sha256).hexdigest()

    def timestamp(self) -> int:
        return clock_mod.now_ms(self.offset_ms)

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = True,
        max_tries: int = 4,
    ):
        params = dict(params or {})
        headers = {}
        if signed:
            params["timestamp"] = str(self.timestamp())
            params["recvWindow"] = str(self.recv_window)
            qs = urlencode(sorted(params.items()))
            params["signature"] = self.sign(qs)
            headers["X-MBX-APIKEY"] = self.key
        ordered = sorted(params.items())  # truyen dung thu tu da ky
        last_exc: Exception | None = None
        for attempt in range(max_tries):
            try:
                if method == "GET":
                    r = self._http.get(path, params=ordered, headers=headers)
                elif method == "DELETE":
                    r = self._http.request("DELETE", path, params=ordered, headers=headers)
                else:
                    r = self._http.request(method, path, params=ordered, headers=headers)
            except httpx.HTTPError as e:
                last_exc = e
                time.sleep(min(2.0, 0.25 * (2**attempt)) + random.random() * 0.2)
                continue
            w = r.headers.get("X-MBX-USED-WEIGHT-1M") or r.headers.get("x-mbx-used-weight-1m")
            if w is not None:
                try:
                    self.last_weight_1m = int(w)
                except ValueError:
                    pass
            if r.status_code in RETRY_STATUS and attempt < max_tries - 1:
                time.sleep(min(8.0, 0.5 * (2**attempt)) + random.random() * 0.5)
                continue
            body = r.json() if r.text else {}
            if isinstance(body, dict) and body.get("code", 0) < 0:
                raise RestError(int(body["code"]), str(body.get("msg", "")))
            if r.status_code >= 400:
                raise RestError(-1000 - r.status_code, r.text[:200])
            return body
        raise RestError(-1008, "retry exhausted: %s" % last_exc)

    def put_keyalive(self, listen_key: str):
        return self.request("PUT", "/fapi/v1/listenKey", {"listenKey": listen_key})

    def get(self, path: str, params: dict | None = None, signed: bool = True, max_tries: int = 4):
        return self.request("GET", path, params, signed, max_tries)

    def post(self, path: str, params: dict | None = None, signed: bool = True, max_tries: int = 4):
        return self.request("POST", path, params, signed, max_tries)

    def delete(
        self, path: str, params: dict | None = None, signed: bool = True, max_tries: int = 4
    ):
        return self.request("DELETE", path, params, signed, max_tries)
