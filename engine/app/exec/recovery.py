"""Recovery P1.3: sau restart, bao dam moi vi the trong DB deu co SL tren san.

Nguyen tac (AGENTS §3.6): REST la nguon su that. Lech khong tu sua mu -> HALT.
Chi duoc tu sua mot thu: dat lai SL con thieu, vi do la hanh dong an toan.
"""

from __future__ import annotations

import time

from ..config import Config
from ..exchange import orders as orders_mod
from ..ops.log import log
from .executor import Executor


def _now_ms() -> int:
    return int(time.time() * 1000)


def recover(con, rest, cfg: Config, ex: Executor | None = None) -> dict:
    ex = ex or Executor(con, rest, cfg, mgr=orders_mod.OrderManager(con, rest))
    snap_pos = rest.get("/fapi/v2/positionRisk")
    snap_algo = rest.get("/fapi/v1/openAlgoOrders")
    algo_items = snap_algo.get("orders", []) if isinstance(snap_algo, dict) else snap_algo
    exchange_open = {
        str(p.get("symbol"))
        for p in (snap_pos if isinstance(snap_pos, list) else [])
        if abs(float(p.get("positionAmt", 0) or 0)) > 0
    }
    has_sl = {
        str(a.get("symbol"))
        for a in (algo_items if isinstance(algo_items, list) else [])
        if str(a.get("algoStatus", "")).upper() not in ("CANCELED", "EXPIRED", "FINISHED")
        and str(a.get("type", "")).upper() == "STOP_MARKET"
    }
    db_rows = con.execute(
        "SELECT symbol, amt, sl, side FROM positions WHERE state='OPEN' AND CAST(amt AS REAL) != 0"
    ).fetchall()
    db_syms = {str(r[0]) for r in db_rows}

    repaired = halted = 0
    for sym, amt, sl_price, _side in db_rows:
        if sym not in exchange_open:
            ex._halt(f"recovery_db_position_missing:{sym}")
            halted += 1
            continue
        if sym in has_sl:
            continue
        if not sl_price:
            ex._halt(f"recovery_sl_price_missing:{sym}")
            halted += 1
            continue
        close_side = "SELL" if float(amt) > 0 else "BUY"
        try:
            res = ex._mgr.place_algo(sym, close_side, "STOP_MARKET", str(sl_price))
            con.execute(
                "UPDATE positions SET sl_id=?, updated_ms=? WHERE symbol=?",
                (str(res.get("client_id", "")), _now_ms(), sym),
            )
            repaired += 1
            log("warn", "recovery.sl_replaced", symbol=sym, sl=str(sl_price))
        except Exception as e:
            ex._halt(f"recovery_sl_place_fail:{sym}")
            log("error", "recovery.sl_fail", symbol=sym, error=str(e)[:150])
            halted += 1

    for sym in exchange_open - db_syms:
        ex._halt(f"recovery_exchange_position_not_in_db:{sym}")
        halted += 1

    return {
        "db_positions": len(db_rows),
        "exchange_positions": len(exchange_open),
        "repaired_sl": repaired,
        "halted": halted,
    }
