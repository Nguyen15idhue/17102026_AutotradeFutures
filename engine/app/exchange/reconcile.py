"""Reconcile 5s: REST la nguon that. Lech -> HALT + alert, KHONG tu sua mu."""

from __future__ import annotations

import sqlite3
import time

from ..db.store import get_state, set_state
from ..ops.log import log


def _as_map(rows, key: str) -> dict:
    out = {}
    items = (
        rows
        if isinstance(rows, list)
        else rows.get("positions", rows)
        if isinstance(rows, dict)
        else []
    )
    for r in items if isinstance(items, list) else []:
        if isinstance(r, dict) and r.get(key) is not None:
            out[str(r[key])] = r
    return out


class Reconciler:
    def __init__(self, con: sqlite3.Connection, rest, alerter=None, halt_on_diff: bool = True):
        self._con = con
        self._rest = rest
        self._alerter = alerter
        self._halt_on_diff = halt_on_diff
        self.diff_count = 0

    def halted(self) -> bool:
        return get_state(self._con, "halted", "0") == "1"

    def snapshot(self) -> dict:
        """Lay state that tu san. Tra ve dict; loi REST -> {'error': ...}."""
        try:
            pr = self._rest.get("/fapi/v2/positionRisk")
            oo = self._rest.get("/fapi/v1/openOrders")
            ao = self._rest.get("/fapi/v1/openAlgoOrders")
            return {"positionRisk": pr, "openOrders": oo, "openAlgoOrders": ao}
        except Exception as e:
            return {"error": str(e)[:200]}

    def check(self) -> int:
        """So sanh 1 vong. Tra ve so lech. Lech -> HALT (neu bat)."""
        snap = self.snapshot()
        if "error" in snap:
            log("warn", "reconcile.rest_error", error=snap["error"])
            return 0
        diffs = 0
        db_pos = {
            r[0]: r[1] for r in self._con.execute("SELECT symbol,amt FROM positions").fetchall()
        }
        for p in snap["positionRisk"] if isinstance(snap["positionRisk"], list) else []:
            amt = str(p.get("positionAmt", "0"))
            sym = str(p.get("symbol", ""))
            if sym and float(amt or 0) != float(db_pos.get(sym, "0") or 0):
                diffs += 1
                log(
                    "error",
                    "reconcile.diff",
                    where="position",
                    symbol=sym,
                    ex=amt,
                    db=db_pos.get(sym, "0"),
                )
        if diffs:
            self.diff_count += diffs
            now = int(time.time() * 1000)
            self._con.execute(
                "INSERT INTO incidents(kind,detail,ts_ms) VALUES(?,?,?)",
                ("RECONCILE_DIFF", "diff=%d" % diffs, now),
            )
            if self._halt_on_diff:
                set_state(self._con, "halted", "1", now)
                log("error", "reconcile.halt", diff=diffs)
                if self._alerter:
                    self._alerter.push("halt", "HALT: reconcile lech %d" % diffs)
                    self._alerter.flush()
        return diffs
