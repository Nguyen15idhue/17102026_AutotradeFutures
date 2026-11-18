"""Executor P1.3: entry -> SL ngay -> TP (MR). Moi lenh deu qua risk.check.

Bat bien (AGENTS §3.1): sau khi co fill thi viec tiep theo BAT BUOC la dat SL.
Thu tu call duoc test bang fake REST: risk -> place -> fetch fill -> place_algo(SL).
"""

from __future__ import annotations

import time
from typing import Callable

from ..config import Config
from ..exchange import orders as orders_mod
from ..ops.log import log
from ..risk import check as risk_check
from ..risk.sizing import round_price
from ..risk.types import OrderRequest, Position, RiskDecision, RiskInputs

SL_TIMEOUT_MS = 300  # muc tieu dat SL sau fill (do o integration)


def _now_ms() -> int:
    return int(time.time() * 1000)


def fmt_step(value: float, step: float) -> str:
    """Format so theo so chu so thap phan cua step (0.001 -> 3 chu so)."""
    if step <= 0:
        return str(value)
    text = f"{step:.10f}".rstrip("0").rstrip(".")
    decimals = len(text.split(".")[1]) if "." in text else 0
    return f"{value:.{decimals}f}"


class Executor:
    def __init__(
        self,
        con,
        rest,
        cfg: Config,
        mgr=None,
        now: Callable[[], int] = _now_ms,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._con = con
        self._rest = rest
        self._cfg = cfg
        self._mgr = mgr or orders_mod.OrderManager(con, rest)
        self._now = now
        self._sleep = sleep

    # -- snapshot -------------------------------------------------------------
    def _state(self, key: str, default: str = "") -> str:
        row = self._con.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def positions(self) -> tuple[Position, ...]:
        rows = self._con.execute(
            "SELECT symbol,strategy_id,side,amt,entry,sl,risk_usd,opened_ms FROM positions"
            " WHERE state='OPEN' AND CAST(amt AS REAL) != 0"
        ).fetchall()
        out = []
        for sym, strat, side, amt, entry, stop, risk_usd, opened in rows:
            out.append(
                Position(
                    symbol=str(sym),
                    strategy_id=str(strat or ""),
                    side=str(side or ""),
                    qty=abs(float(amt or 0)),
                    entry=float(entry or 0),
                    stop=float(stop or 0),
                    risk_usd=float(risk_usd or 0),
                    opened_ms=int(opened or 0),
                )
            )
        return tuple(out)

    def symbol_filters(self, symbol: str) -> dict:
        info = self._rest.get("/fapi/v1/exchangeInfo", signed=False)
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol:
                out = {"min_notional": 5.0, "step_size": 0.001, "tick_size": 0.01}
                for f in s.get("filters", []):
                    if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                        out["min_notional"] = float(f.get("notional", 5.0))
                    if f.get("filterType") == "LOT_SIZE":
                        out["step_size"] = float(f.get("stepSize", 0.001))
                    if f.get("filterType") == "PRICE_FILTER":
                        out["tick_size"] = float(f.get("tickSize", 0.01))
                return out
        raise ValueError(f"khong thay symbol {symbol} trong exchangeInfo")

    def build_inputs(self, req: OrderRequest) -> RiskInputs:
        r = self._cfg.risk
        flt = self.symbol_filters(req.symbol)
        row = self._con.execute(
            "SELECT label, trend_dir FROM regime ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        day_start = self._now() - self._now() % 86_400_000
        orders_today = self._con.execute(
            "SELECT COUNT(*) FROM orders WHERE created_ms>=?", (day_start,)
        ).fetchone()[0]
        equity = float(self._state("equity", str(self._cfg.equity_base)))
        spread_raw = self._state("spread_bps")
        return RiskInputs(
            now_ms=self._now(),
            halted=self._state("halted", "0") == "1",
            last_market_ms=int(self._state("last_market_ms", "0")) or None,
            stale_data_seconds=r.stale_data_seconds,
            regime=str(row[0]) if row else "UNKNOWN",
            trend_dir=int(row[1]) if row else 0,
            blackout_until_ms=int(self._state("blackout_until_ms", "0") or 0),
            open_positions=self.positions(),
            equity=equity,
            day_pnl=float(self._state("day_pnl", "0")),
            week_pnl=float(self._state("week_pnl", "0")),
            dd_pct=float(self._state("dd_pct", "0")),
            orders_today=int(orders_today),
            spread_bps=None if spread_raw == "" else float(spread_raw),
            min_notional=flt["min_notional"],
            step_size=flt["step_size"],
            tick_size=flt["tick_size"],
            available_balance=equity,
            allow_short=bool(self._cfg.strategies.trend_pullback.get("allow_short", False)),
            risk_per_trade=r.risk_per_trade,
            max_positions=r.max_positions,
            max_positions_per_strategy=self._cfg.strategies.max_positions_per_strategy,
            portfolio_risk_max=r.portfolio_risk_max,
            max_correlated_risk=r.max_correlated_risk,
            margin_usage_max=r.margin_usage_max,
            max_orders_per_day=self._cfg.execution.max_orders_per_day,
            leverage=r.max_leverage,
            daily_loss_limit=r.daily_loss_limit,
            weekly_loss_limit=r.weekly_loss_limit,
            max_drawdown=r.max_drawdown,
            paused=self._state("paused", "0") == "1",
        )

    # -- mo lenh --------------------------------------------------------------
    def open(self, req: OrderRequest, inputs: RiskInputs | None = None) -> dict:
        """Risk -> entry -> SL. Tra ve dict {ok, reason, client_id, sl_id, fill_price}."""
        inp = inputs or self.build_inputs(req)
        decision: RiskDecision = risk_check(req, inp)
        if not decision.ok:
            self._signal(req, "", "REJECTED", decision.reason)
            log("warn", "exec.reject", symbol=req.symbol, reason=decision.reason)
            return {"ok": False, "reason": decision.reason}

        sl_side = "SELL" if req.side.upper() == "BUY" else "BUY"
        cid = orders_mod.new_client_id(req.strategy_id, req.symbol)
        post_only = req.order_type == "post_only"
        qty = fmt_step(decision.qty, inp.step_size)
        price = fmt_step(round_price(req.entry, inp.tick_size), inp.tick_size) if post_only else ""
        res = self._mgr.place(
            req.symbol,
            req.side.upper(),
            "LIMIT" if post_only else "MARKET",
            qty,
            price,
            client_id=cid,
            time_in_force="GTX" if post_only else "",
        )
        cid = res.get("client_id", cid)

        fill = self._wait_fill(req.symbol, cid)
        if fill is None:
            if post_only:
                self._safe_cancel(req.symbol, cid)
            self._signal(req, cid, "EXPIRED", "no_fill")
            return {"ok": False, "reason": "no_fill", "client_id": cid}

        fill_price = float(fill.get("avgPrice") or fill.get("price") or req.entry)
        trigger = fmt_step(round_price(req.stop, inp.tick_size), inp.tick_size)
        # Bat bien: dat SL NGAY sau fill, truoc moi viec khac.
        sl = self._mgr.place_algo(req.symbol, sl_side, "STOP_MARKET", trigger)
        sl_client = str(sl.get("client_id", ""))
        tp_client = ""
        if req.strategy_id == "mean_reversion" and req.tp is not None:
            tp_trigger = fmt_step(round_price(req.tp, inp.tick_size), inp.tick_size)
            tp = self._mgr.place_algo(req.symbol, sl_side, "TAKE_PROFIT_MARKET", tp_trigger)
            tp_client = str(tp.get("client_id", ""))

        self._persist(req, cid, fill_price, trigger, sl_client, tp_client, decision, qty)
        self._signal(req, cid, "FILLED", "ok", decision.risk_usd)
        log(
            "info",
            "exec.open",
            symbol=req.symbol,
            side=req.side,
            qty=qty,
            sl=sl_client,
            tp=tp_client,
        )
        return {
            "ok": True,
            "client_id": cid,
            "sl_id": sl_client,
            "tp_id": tp_client,
            "fill_price": fill_price,
        }

    # -- doi SL / dong lenh ---------------------------------------------------
    def _row(self, symbol: str):
        return self._con.execute(
            "SELECT amt, side, sl, sl_id FROM positions WHERE symbol=? AND state='OPEN'",
            (symbol,),
        ).fetchone()

    def _halt(self, reason: str) -> None:
        now = self._now()
        self._con.execute(
            "INSERT INTO incidents(kind,detail,ts_ms) VALUES('halt',?,?)", (reason, now)
        )
        self._con.execute(
            "INSERT INTO runtime_state(key,value,updated_ms) VALUES('halted','1',?) "
            "ON CONFLICT(key) DO UPDATE SET value='1',updated_ms=excluded.updated_ms",
            (now,),
        )
        log("error", "exec.halt", reason=reason)

    def trail(self, symbol: str, new_stop: float) -> dict:
        """Make-before-break: dat SL moi TRUOC, huy SL cu SAU.

        Khong bao gio de vi the khong co SL trong luc doi — ke ca 200ms.
        """
        row = self._row(symbol)
        if not row:
            raise ValueError(f"khong co vi the mo: {symbol}")
        amt, _side, _old_stop, old_id = row
        close_side = "SELL" if float(amt) > 0 else "BUY"
        tick = self.symbol_filters(symbol)["tick_size"]
        trigger = fmt_step(round_price(new_stop, tick), tick)
        new = self._mgr.place_algo(symbol, close_side, "STOP_MARKET", trigger)
        new_id = str(new.get("client_id", ""))
        if not new_id:
            raise RuntimeError("dat SL moi that bai")
        try:
            if old_id:
                self._mgr.cancel_algo(symbol, old_id)
        except Exception as e:
            # 2 SL cung song la trang thai nguy hiem -> HALT, khong tu xu ly mu.
            self._halt(f"trail_cancel_fail:{old_id}")
            raise RuntimeError(f"huy SL cu that bai: {e}") from e
        self._con.execute(
            "UPDATE positions SET sl=?, sl_id=?, updated_ms=? WHERE symbol=?",
            (trigger, new_id, self._now(), symbol),
        )
        log("info", "exec.trail", symbol=symbol, stop=trigger, sl_id=new_id)
        return {"ok": True, "sl_id": new_id, "old_id": old_id, "stop": trigger}

    def close(self, symbol: str, reason: str = "manual") -> dict:
        row = self._row(symbol)
        if not row:
            return {"ok": True, "reason": "already_flat"}
        amt, _side, _sl, sl_id = row
        qty = fmt_step(abs(float(amt)), self.symbol_filters(symbol)["step_size"])
        close_side = "SELL" if float(amt) > 0 else "BUY"
        res = self._mgr.place(symbol, close_side, "MARKET", qty, reduce_only=True)
        cid = str(res.get("client_id", ""))
        fill = self._wait_fill(symbol, cid)
        if fill is None:
            return {"ok": False, "reason": "close_no_fill", "client_id": cid}
        if sl_id:  # closePosition tu het han; huy cho chac neu con song
            try:
                self._mgr.cancel_algo(symbol, sl_id)
            except Exception as e:
                log("warn", "exec.close_sl_cancel", error=str(e)[:120])
        self._con.execute(
            "UPDATE positions SET amt='0', state='CLOSED', updated_ms=? WHERE symbol=?",
            (self._now(), symbol),
        )
        self._con.execute(
            "INSERT INTO events(kind,payload,ts_ms) VALUES('position_closed',?,?)",
            (f"{symbol}:{reason}", self._now()),
        )
        log("info", "exec.close", symbol=symbol, reason=reason)
        return {"ok": True, "client_id": cid, "reason": reason}

    def _wait_fill(
        self, symbol: str, cid: str, tries: int = 10, delay: float = 0.05
    ) -> dict | None:
        for _ in range(tries):
            try:
                o = self._mgr.fetch_order(symbol, cid)
            except Exception as e:  # lenh co the chua kip hien
                log("warn", "exec.fetch_fail", error=str(e)[:120])
                self._sleep(delay)
                continue
            if str(o.get("status", "")).upper() == "FILLED":
                return o
            if str(o.get("status", "")).upper() in ("CANCELED", "EXPIRED", "REJECTED"):
                return None
            self._sleep(delay)
        return None

    def _safe_cancel(self, symbol: str, cid: str) -> None:
        try:
            self._mgr.cancel_order(symbol, cid)
        except Exception as e:
            log("warn", "exec.cancel_fail", error=str(e)[:120])

    def _persist(
        self,
        req: OrderRequest,
        cid: str,
        fill_price: float,
        sl_price: str,
        sl_id: str,
        tp_id: str,
        dec: RiskDecision,
        qty: str,
    ) -> None:
        now = self._now()
        is_long = req.side.upper() == "BUY"
        amt = qty if is_long else f"-{qty}"
        self._con.execute(
            "INSERT INTO positions(symbol,amt,entry,updated_ms,strategy_id,side,sl,tp,"
            "sl_id,tp_id,risk_usd,opened_ms,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'OPEN') "
            "ON CONFLICT(symbol) DO UPDATE SET amt=excluded.amt,entry=excluded.entry,"
            "updated_ms=excluded.updated_ms,strategy_id=excluded.strategy_id,"
            "side=excluded.side,sl=excluded.sl,tp=excluded.tp,sl_id=excluded.sl_id,"
            "tp_id=excluded.tp_id,risk_usd=excluded.risk_usd,"
            "opened_ms=excluded.opened_ms,state='OPEN'",
            (
                req.symbol,
                amt,
                str(fill_price),
                now,
                req.strategy_id,
                "LONG" if is_long else "SHORT",
                sl_price,
                str(req.tp or ""),
                sl_id,
                tp_id,
                dec.risk_usd,
                now,
            ),
        )

    def _signal(
        self,
        req: OrderRequest,
        cid: str,
        status: str,
        reason: str,
        risk_usd: float = 0.0,
    ) -> None:
        self._con.execute(
            "INSERT INTO signals(strategy_id,symbol,side,ts_ms,entry,stop,tp,risk_usd,"
            "reason,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                req.strategy_id,
                req.symbol,
                req.side,
                self._now(),
                str(req.entry),
                str(req.stop),
                str(req.tp or ""),
                risk_usd,
                f"{reason}:{cid}" if cid else reason,
                status,
            ),
        )
