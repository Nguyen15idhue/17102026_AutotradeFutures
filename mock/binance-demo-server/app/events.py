"""Phat event noi bo (ORDER_TRADE_UPDATE, ACCOUNT_UPDATE, ALGO_UPDATE...).

M0.6: chi log vao DB + goi subscriber (WS o M0.8).
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from . import state
from .store import STORE

log = logging.getLogger("mock.events")

_subscribers: list[Callable[[str, dict], None]] = []


def subscribe(fn: Callable[[str, dict], None]) -> None:
    _subscribers.append(fn)


def unsubscribe(fn: Callable[[str, dict], None]) -> None:
    if fn in _subscribers:
        _subscribers.remove(fn)


def publish(kind: str, payload: dict) -> None:
    STORE.log_event(state.now_ms(), kind, _short(payload))
    for fn in list(_subscribers):
        try:
            fn(kind, payload)
        except Exception:  # pragma: no cover - subscriber loi khong duoc lam sap engine
            log.exception("subscriber loi khi phat %s", kind)


def _short(payload: dict) -> str:
    if "o" in payload:
        o = payload["o"]
        return f"{o.get('s')} {o.get('S')} {o.get('o')} {o.get('X')}"
    if "e" in payload:
        return payload["e"]
    return str(payload)[:120]
