"""Nguon du lieu thi truong: 3 che do proxy | replay | synthetic.

- proxy     : chuyen tiep API public cua Binance (cache ngan), gia that
- replay    : doc fixture da tai, dich thoi gian de nen cuoi = hien tai
- synthetic : random walk tat dinh theo (seed, symbol, chi so nen)
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from typing import Any

import httpx

from . import errors as E
from . import state
from .config import CFG
from .num import dec

INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
}


def _rand01(*parts: object) -> float:
    h = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def _dec_strs(row: list) -> list:
    """Binance tra gia/khoi luong dang chuoi."""
    out = list(row)
    for i in (1, 2, 3, 4, 5, 7, 9, 10):
        out[i] = str(out[i])
    out[6] = int(out[6])
    out[8] = int(out[8])
    out[11] = str(out[11])
    return out


class Market:
    def __init__(self) -> None:
        self.mode = CFG.market_mode
        self._symbols: dict[str, dict[str, Decimal]] = {}
        self._raw_symbols: list[dict] = []
        self._klines: dict[str, dict[str, list]] = {}
        self._cache: dict[str, tuple[float, Any]] = {}
        self._client: httpx.AsyncClient | None = None
        self._base_price: dict[str, Decimal] = {}
        self.booted = False

    # ------------------------------------------------------------ boot

    def fixtures_dir(self) -> Path:
        p = Path(CFG.fixtures_dir)
        if p.is_dir():
            return p
        return Path(__file__).resolve().parents[2] / "fixtures"

    def boot(self, mode: str | None = None) -> None:
        self.mode = (mode or CFG.market_mode).lower()
        d = self.fixtures_dir()
        ex = json.loads((d / "exchangeInfo.json").read_text(encoding="utf-8"))
        self._raw_symbols = ex["symbols"]
        for s in ex["symbols"]:
            f = {x["filterType"]: x for x in s["filters"]}
            self._symbols[s["symbol"]] = {
                "tick": dec(f.get("PRICE_FILTER", {}).get("tickSize", "0.01")),
                "step": dec(f.get("LOT_SIZE", {}).get("stepSize", "0.001")),
                "min_notional": dec(f.get("MIN_NOTIONAL", {}).get("notional", "5")),
                "trigger_protect": dec(s.get("triggerProtect", "0.05")),
                "price_precision": Decimal(int(s.get("pricePrecision", 2))),
                "qty_precision": Decimal(int(s.get("quantityPrecision", 3))),
            }
        kl_path = d / "klines.json"
        if kl_path.exists():
            self._klines = json.loads(kl_path.read_text(encoding="utf-8"))
        for sym, dct in self._klines.items():
            bars = dct.get("1m") or dct.get("15m") or []
            if bars:
                self._base_price[sym] = dec(bars[-1][4])
        for sym in self._symbols:
            self._base_price.setdefault(sym, Decimal("100"))
        self.booted = True

    # ------------------------------------------------------------ helpers

    def symbols(self) -> dict[str, dict[str, Decimal]]:
        if not self.booted:
            self.boot()
        return self._symbols

    def has_symbol(self, symbol: str) -> bool:
        return symbol.upper() in self.symbols()

    def filters(self, symbol: str) -> dict[str, Decimal]:
        s = symbol.upper()
        if s not in self.symbols():
            raise E.err(E.INVALID_SYMBOL)
        return self.symbols()[s]

    def raw_exchange_info(self, symbol: str | None = None) -> dict:
        if not self.booted:
            self.boot()
        if symbol:
            s = symbol.upper()
            for item in self._raw_symbols:
                if item["symbol"] == s:
                    return {"symbols": [item]}
            raise E.err(E.INVALID_SYMBOL)
        return {"symbols": self._raw_symbols}

    async def _upstream(self, path: str, params: dict | None = None) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=CFG.upstream, timeout=10.0)
        r = await self._client.get(path, params=params or {})
        if r.status_code != 200:
            raise E.BinanceError(-1000, f"Upstream error {r.status_code}", 502)
        return r.json()

    def _cached(self, key: str, ttl_ms: int) -> Any | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        expires, value = hit
        if time.time() * 1000 >= expires:
            return None
        return value

    def _store(self, key: str, ttl_ms: int, value: Any) -> Any:
        self._cache[key] = (time.time() * 1000 + ttl_ms, value)
        return value

    # ------------------------------------------------------------ price

    def last_price(self, symbol: str) -> Decimal:
        s = symbol.upper()
        self.filters(s)  # validate
        if self.mode == "replay":
            bars = (self._klines.get(s) or {}).get("1m") or []
            if bars:
                return dec(bars[-1][4])
        if self.mode == "synthetic":
            now = state.now_ms()
            idx = now // 60_000
            return self._syn_close(s, idx)
        # proxy: cache 1s, fallback synthetic neu loi
        c = self._cached("price:" + s, 0)
        if c is not None:
            return c
        return self._base_price.get(s, Decimal("100"))

    def _syn_close(self, symbol: str, idx: int) -> Decimal:
        base = self._base_price.get(symbol, Decimal("100"))
        wave = 0.02 * math.sin(2 * math.pi * idx / 480.0)
        drift = ((idx % 5000) / 5000.0 - 0.5) * 0.06
        noise = (_rand01(CFG.seed, symbol, idx) - 0.5) * 0.002
        jump = 0.0
        if CFG.synth_jump_prob > 0 and _rand01(CFG.seed, symbol, idx, "jump") < CFG.synth_jump_prob:
            jump = (_rand01(CFG.seed, symbol, idx, "mag") - 0.5) * 0.08
        return (base * dec(1 + wave + drift + noise + jump)).quantize(Decimal("0.00000001"))

    def quote(self, symbol: str) -> tuple[Decimal, Decimal]:
        """(bid, ask) — da snap ve tickSize, dung cho matching."""
        s = symbol.upper()
        f = self.filters(s)
        tick = f["tick"]
        mid = self.last_price(s)
        spread = max(tick, (mid * Decimal("0.00005")).quantize(tick))
        bid = ((mid - spread / 2) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
        ask = ((mid + spread / 2) / tick).to_integral_value(rounding=ROUND_UP) * tick
        if ask <= bid:
            ask = bid + tick
        return bid, ask

    # ------------------------------------------------------------ klines

    def klines(self, symbol: str, interval: str, limit: int) -> list[list]:
        s = symbol.upper()
        self.filters(s)
        if interval not in INTERVAL_MS:
            raise E.err(E.INVALID_PARAM, p="interval")
        limit = max(1, min(int(limit), 1500))

        if self.mode == "replay":
            bars = (self._klines.get(s) or {}).get(interval)
            if not bars:
                return []
            shifted = self._shift_bars(bars, INTERVAL_MS[interval])
            return [_dec_strs(b) for b in shifted[-limit:]]

        return self._synth_klines(s, interval, limit)

    def _shift_bars(self, bars: list, step_ms: int) -> list[list]:
        """Dich thoi gian de nen cuoi ket thuc tai hien tai (replay van 'tuoi')."""
        now = state.now_ms()
        last_open = int(bars[-1][0])
        shift = (now // step_ms) * step_ms - step_ms - last_open
        out = []
        for b in bars:
            row = list(b)
            row[0] = int(row[0]) + shift
            row[6] = int(row[6]) + shift
            out.append(row)
        return out

    def _synth_klines(self, symbol: str, interval: str, limit: int) -> list[list]:
        step = INTERVAL_MS[interval]
        now = state.now_ms()
        last_open = (now // step) * step - step
        rows = []
        for k in range(limit - 1, -1, -1):
            open_ms = last_open - k * step
            idx = open_ms // 60_000
            mid = self._syn_close(symbol, idx)
            r1 = _rand01(CFG.seed, symbol, interval, idx, "o")
            r2 = _rand01(CFG.seed, symbol, interval, idx, "hi")
            r3 = _rand01(CFG.seed, symbol, interval, idx, "lo")
            o = mid * dec(1 + (r1 - 0.5) * 0.0004)
            c = mid
            hi = max(o, c) * dec(1 + r2 * 0.0008)
            lo = min(o, c) * dec(1 - r3 * 0.0008)
            vol = dec(50 + r1 * 950)
            row = [
                open_ms, str(o), str(hi), str(lo), str(c), str(vol),
                open_ms + step - 1, str(vol * mid), int(100 + r2 * 900),
                str(vol * dec(0.5)), str(vol * mid * dec(0.5)), "0",
            ]
            rows.append(row)
        return rows

    # ------------------------------------------------------------ tickers

    def book_ticker(self, symbol: str) -> dict:
        s = symbol.upper()
        bid, ask = self.quote(s)
        f = self.filters(s)
        p = int(f["price_precision"])
        q = int(f["qty_precision"])
        r = _rand01(CFG.seed, s, state.now_ms() // 1000)
        return {
            "symbol": s,
            "bidPrice": f"{bid:.{p}f}",
            "bidQty": f"{(1 + r * 20):.{q}f}",
            "askPrice": f"{ask:.{p}f}",
            "askQty": f"{(1 + (1 - r) * 20):.{q}f}",
            "time": state.now_ms(),
        }

    def premium_index(self, symbol: str) -> dict:
        s = symbol.upper()
        last = self.last_price(s)
        mark = last * Decimal("1.0002")
        now = state.now_ms()
        step = 8 * 3600 * 1000
        nxt = ((now // step) + 1) * step
        return {
            "symbol": s,
            "markPrice": f"{mark:.8f}",
            "indexPrice": f"{last:.8f}",
            "estimatedSettlePrice": f"{last:.8f}",
            "lastFundingRate": "0.00010000",
            "nextFundingTime": nxt,
            "interestRate": "0.00010000",
            "time": now,
        }

    def funding_rate(self, symbol: str, limit: int = 100) -> list[dict]:
        s = symbol.upper()
        now = state.now_ms()
        step = 8 * 3600 * 1000
        out = []
        for i in range(limit):
            out.append({
                "symbol": s,
                "fundingTime": now - i * step,
                "fundingRate": "0.00010000",
                "markPrice": f"{self.last_price(s):.8f}",
            })
        return out

    def open_interest(self, symbol: str) -> dict:
        s = symbol.upper()
        r = _rand01(CFG.seed, s, "oi")
        return {"symbol": s, "openInterest": f"{10000 + r * 90000:.3f}", "time": state.now_ms()}


MARKET = Market()
