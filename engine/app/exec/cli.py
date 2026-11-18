"""Cong cu tay P1.3 — CHI chay tren mock.

Vi sao: P1.4 chua co strategy, nhung P1.3 can chung minh fill -> SL -> close tren
mock that. Cli tu choi env != mock de khong bao gio dat lenh that bang tay.
"""

from __future__ import annotations

import json
import os
import sys

from .. import config as config_mod
from ..db import store
from ..exchange import rest as rest_mod
from ..exec.executor import Executor
from ..risk.types import OrderRequest

USAGE = (
    "open --symbol BTCUSDT --side BUY --stop-bps 80 [--risk-pct 0.25] [--tp-bps 150]\n"
    "close --symbol BTCUSDT\n"
    "trail --symbol BTCUSDT --stop-bps 50"
)


def _ctx(cfg=None, con=None, rest=None, ex=None):
    cfg = cfg or config_mod.load()
    if cfg.env != "mock":
        raise SystemExit("CLI chi dung cho mock: env hien tai = " + cfg.env)
    key = os.environ.get("BINANCE_API_KEY") or os.environ.get("MOCK_API_KEY", "verify-key")
    secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get(
        "MOCK_API_SECRET", "mock-secret"
    )
    rest = rest or rest_mod.RestClient(cfg.base_url, key, secret)
    con = con or store.connect(os.environ.get("DB_PATH", "/app/data/bot.db"))
    ex = ex or Executor(con, rest, cfg)
    return cfg, con, rest, ex


def _price(ex, symbol: str, side: str) -> tuple[float, dict]:
    m = ex.refresh_market(symbol)
    if not m["mid"]:
        raise SystemExit("khong lay duoc gia " + symbol)
    return (m["ask"] if side.upper() == "BUY" else m["bid"]), m


def run(argv: list[str] | None = None, cfg=None, con=None, rest=None, ex=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(USAGE)
        return 2
    cmd = args[0]
    opts = {args[i].lstrip("-"): args[i + 1] for i in range(1, len(args) - 1, 2)}
    cfg, con, rest, ex = _ctx(cfg, con, rest, ex)

    if cmd == "open":
        symbol = opts.get("symbol", "BTCUSDT")
        side = opts.get("side", "BUY").upper()
        stop_bps = float(opts.get("stop-bps", "80"))
        risk_pct = float(opts.get("risk-pct", "0.25"))
        price, _m = _price(ex, symbol, side)
        sign = -1 if side == "BUY" else 1
        stop = price * (1 + sign * stop_bps / 10_000)
        tp_bps = opts.get("tp-bps")
        tp = price * (1 - sign * float(tp_bps) / 10_000) if tp_bps else None
        req = OrderRequest(
            strategy_id="manual",
            symbol=symbol,
            side=side,
            entry=price,
            stop=stop,
            tp=tp,
            order_type="market",
            meta={"risk_usd": cfg.risk.risk_per_trade * cfg.equity_base * risk_pct / 0.25},
        )
        res = ex.open(req)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    if cmd == "close":
        symbol = opts.get("symbol", "BTCUSDT")
        res = ex.close(symbol, "cli")
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    if cmd == "trail":
        symbol = opts.get("symbol", "BTCUSDT")
        row = ex._row(symbol)
        if not row:
            print(json.dumps({"ok": False, "reason": "no_position"}))
            return 1
        price, _m = _price(ex, symbol, "BUY" if float(row[0]) > 0 else "SELL")
        bps = float(opts.get("stop-bps", "50"))
        sign = -1 if float(row[0]) > 0 else 1
        res = ex.trail(symbol, price * (1 + sign * bps / 10_000))
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    print(USAGE)
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
