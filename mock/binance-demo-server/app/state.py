"""Trang thai runtime: dong ho server, uptime, snapshot cho /_debug.

Giai doan M0.2 chi co phan khung; cac buoc sau (M0.5/M0.6/M0.7/M0.8) se lap day.
"""
from __future__ import annotations

import time
from typing import Any

from .config import CFG

START_MS = int(time.time() * 1000)

# offset giua dong ho "server" va dong ho he thong (ms); co the chinh bang /_admin
CLOCK_OFFSET_MS = 0


def now_ms() -> int:
    """Thoi gian server (ms). Co the chay nhanh hon thuc te theo SPEED."""
    elapsed = int(time.time() * 1000) - START_MS
    return START_MS + CLOCK_OFFSET_MS + int(elapsed * CFG.speed)


def uptime_s() -> int:
    return int((time.time() * 1000 - START_MS) / 1000)


def snapshot() -> dict[str, Any]:
    """Du lieu cho GET /_debug/json. Cac buoc sau bo sung mang du lieu."""
    return {
        "market_mode": CFG.market_mode,
        "speed": CFG.speed,
        "uptime_s": uptime_s(),
        "server_time": now_ms(),
        "config": {
            "upstream": CFG.upstream if CFG.market_mode == "proxy" else "-",
            "initial_balance": CFG.initial_balance,
            "fee_maker_bps": CFG.fee_maker_bps,
            "fee_taker_bps": CFG.fee_taker_bps,
            "fill_model": CFG.fill_model,
            "slippage_bps": CFG.slippage_bps,
            "auth_strict": CFG.auth_strict,
            "seed": CFG.seed,
        },
        "account": {},
        "positions": [],
        "orders": [],
        "algo_orders": [],
        "events": [],
    }
