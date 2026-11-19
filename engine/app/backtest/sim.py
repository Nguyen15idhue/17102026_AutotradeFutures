"""Backtest event-driven 1m cho MR + Trend (P1.4).

Vi sao 1m: tin hieu tinh tren nen 15m/1h da dong, nhung fill/SL phai mo phong
trong noi bo nen — dung 1m de biet gia co xuyen qua limit/SL hay khong. Fill model
bao thu: limit chi khop khi gia XUYEN QUA (strict), SL khop tai gia te hon giua
open va muc SL, moi lenh market chiu slippage bat loi.

Khong co look-ahead: feature/regime tai thoi diem t chi dung nen da dong truoc t.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..data import features as feat_mod
from ..regime import detector as regime_mod
from ..regime.types import RegimeInputs, RegimeLabel
from ..risk import correlation as corr_mod
from ..risk import sizing as sizing_mod
from ..risk.types import OrderRequest, RiskInputs
from ..strategies import mean_reversion as mr_mod
from ..strategies import trend_pullback as trend_mod

MIN_MS = 60_000
H15_MS = 900_000
H1_MS = 3_600_000
H4_MS = 14_400_000
H8_MS = 28_800_000
DAY_MS = 86_400_000


@dataclass(frozen=True)
class Slice:
    name: str
    start_ms: int
    end_ms: int
    kind: str = "IS"  # IS | OOS


@dataclass
class Trade:
    strategy_id: str
    symbol: str
    side: str  # LONG | SHORT
    qty: float
    entry: float
    exit: float
    entry_ms: int
    exit_ms: int
    reason: str
    risk_usd: float
    pnl_gross: float
    fees: float
    funding: float
    r_multiple: float
    slice: str

    @property
    def pnl(self) -> float:
        return self.pnl_gross - self.fees - self.funding

    @property
    def win(self) -> bool:
        return self.pnl > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": round(self.qty, 8),
            "entry": self.entry,
            "exit": self.exit,
            "entry_ms": self.entry_ms,
            "exit_ms": self.exit_ms,
            "reason": self.reason,
            "risk_usd": round(self.risk_usd, 4),
            "pnl": round(self.pnl, 4),
            "pnl_gross": round(self.pnl_gross, 4),
            "fees": round(self.fees, 4),
            "funding": round(self.funding, 4),
            "r_multiple": round(self.r_multiple, 4),
            "slice": self.slice,
        }


@dataclass
class _Pos:
    strategy_id: str
    symbol: str
    direction: int  # +1 long / -1 short
    qty: float
    entry: float
    stop: float
    tp: float | None
    risk_usd: float
    entry_ms: int
    fees_entry: float
    funding_paid: float = 0.0
    extreme: float = 0.0
    atr: float = 0.0
    trail_atr: float = 0.0
    trail_after_atr: float = 0.0
    time_stop_ms: int = 0
    time_stop_bars: int = 0
    group: str = ""

    @property
    def side(self) -> str:
        return "LONG" if self.direction > 0 else "SHORT"


@dataclass
class _Pending:
    strategy_id: str
    symbol: str
    direction: int
    qty: float
    limit: float
    stop: float
    tp: float | None
    risk_usd: float
    expire_ms: int
    chase_price: float
    held_bars: int = 0
    time_stop_bars: int = 12
    entry_ms: int = 0


@dataclass
class SymbolData:
    symbol: str
    bars1m: list[dict[str, Any]]
    bars15: list[dict[str, Any]]
    feat_by_close: dict[int, dict[str, Any]]
    bars1h: list[dict[str, Any]]
    prep1h: dict[str, Any]
    ctx_dir: list[int]
    h1_by_close: dict[int, int]
    regime_by_close: dict[int, Any]
    filters: dict[str, float]
    bar15_by_close: dict[int, dict[str, Any]] = field(default_factory=dict)
    map1m: dict[int, dict[str, Any]] = field(default_factory=dict)
    feat15: list[dict[str, Any] | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.map1m:
            self.map1m = {int(b["open_time"]): b for b in self.bars1m}
        if not self.bar15_by_close:
            self.bar15_by_close = {int(b["open_time"]) + H15_MS: b for b in self.bars15}


def _ema4h_context(bars4h: list[dict[str, Any]], bars1h: list[dict[str, Any]]) -> list[int]:
    """EMA50 vs EMA200 tren 4h, map sang tung nen 1h da dong (khong look-ahead)."""
    closes = [float(b["c"]) for b in bars4h]
    fast = feat_mod.ema_series(closes, 50)
    slow = feat_mod.ema_series(closes, 200)
    out: list[int] = [0] * len(bars1h)
    j = -1
    for i, b in enumerate(bars1h):
        close_ts = int(b["open_time"]) + H1_MS
        while j + 1 < len(bars4h) and int(bars4h[j + 1]["open_time"]) + H4_MS <= close_ts:
            j += 1
        if j < 0:
            continue
        f, s = fast[j], slow[j]
        if f is None or s is None or f == s:
            continue
        out[i] = 1 if f > s else -1
    return out


def build_regime(
    bars15: list[dict[str, Any]],
    feats: list[dict[str, Any] | None],
    funding: dict[int, float] | None,
    btc_ret: dict[int, float] | None,
) -> dict[int, Any]:
    """Chay RegimeMachine tren chuoi 15m; tra close_ts -> RegimeResult."""
    machine = regime_mod.RegimeMachine()
    out: dict[int, Any] = {}
    for bar, f in zip(bars15, feats):
        close_ts = int(bar["open_time"]) + H15_MS
        fund = None
        if funding:
            fund = funding.get(close_ts) or funding.get(close_ts - close_ts % H8_MS)
        ret = (btc_ret or {}).get(close_ts)
        raw, conf, reason = regime_mod.classify(
            RegimeInputs(feature=f, funding=fund, btc_ret_15m=ret)
        )
        res = machine.update(raw, conf, reason, regime_mod.direction_for(f))
        out[close_ts] = res
    return out


class Sim:
    """Mot lan chay tren toan bo khoang du lieu; trade duoc gan slice theo entry_ms."""

    def __init__(
        self,
        cfg: Config,
        data: dict[str, SymbolData],
        funding: dict[str, dict[int, float]],
        slices: list[Slice],
        *,
        funding_fallback: bool = False,
        dd_halt: bool = False,
    ) -> None:
        self.cfg = cfg
        self.data = data
        self.funding = funding
        self.slices = slices
        self.funding_fallback = funding_fallback
        # dd_halt=False cho nghien cuu P1.4: halt o DD 6% se bien cong "Max DD < 8%"
        # thanh vo nghia va cat mat OOS. Live/engine van halt that (ops/commands).
        self.dd_halt = dd_halt
        self.dd_breach_ms: int | None = None
        self.mr_cfg = cfg.strategies.mean_reversion
        self.tr_cfg = cfg.strategies.trend_pullback
        self.maker = cfg.execution.fee_bps_maker / 10_000
        self.taker = cfg.execution.fee_bps_taker / 10_000
        self.slip = cfg.execution.slippage_bps / 10_000
        self.equity_base = cfg.equity_base
        self.realized = 0.0
        self.open: list[_Pos] = []
        self.pending: list[_Pending] = []
        self.trades: list[Trade] = []
        self.orders_today = 0
        self.day_key = -1
        self.week_key = -1
        self.day_start_eq = self.equity_base
        self.week_start_eq = self.equity_base
        self.halted = False
        self.halt_reason = ""
        self.peak_eq = self.equity_base
        self.max_dd_pct = 0.0
        self._groups: dict[str, str] = {}
        self._group_slice = ""
        self._last_price: dict[str, float] = {}
        self.counts: dict[str, int] = {
            "range_bars": 0,
            "mr_signals": 0,
            "mr_placed": 0,
            "trend_signals": 0,
            "trend_placed": 0,
            "caps_blocked": 0,
        }

    # ---------- helpers ----------

    @property
    def equity(self) -> float:
        return self.equity_base + self.realized

    def _slice_for(self, ts: int) -> str:
        for s in self.slices:
            if s.start_ms <= ts < s.end_ms:
                return s.name
        return self.slices[-1].name if self.slices else "ALL"

    def _groups_at(self, ts: int, slice_name: str) -> dict[str, str]:
        if self._group_slice == slice_name and self._groups:
            return self._groups
        lookback = 30 * DAY_MS
        rets: dict[str, list[float]] = {}
        for sym, sd in self.data.items():
            rows = [b for b in sd.bars1h if ts - lookback <= int(b["open_time"]) < ts]
            rets[sym] = _log_returns([float(b["c"]) for b in rows])
        btc = rets.get("BTCUSDT") or []
        self._groups = corr_mod.groups(rets, btc)
        self._group_slice = slice_name
        return self._groups

    def _risk_inputs(self, symbol: str, ts: int, market_ms: int | None) -> RiskInputs:
        sd = self.data[symbol]
        day_pnl = self.equity - self.day_start_eq
        week_pnl = self.equity - self.week_start_eq
        dd = self.max_dd_pct
        return RiskInputs(
            now_ms=ts,
            halted=self.halted,
            last_market_ms=market_ms,
            stale_data_seconds=self.cfg.risk.stale_data_seconds,
            regime="",
            trend_dir=0,
            blackout_until_ms=0,
            open_positions=(),
            equity=self.equity,
            day_pnl=day_pnl,
            week_pnl=week_pnl,
            dd_pct=dd,
            orders_today=self.orders_today,
            spread_bps=0.0,
            min_notional=float(sd.filters.get("min_notional", 5.0)),
            step_size=float(sd.filters.get("step_size", 0.001)),
            tick_size=float(sd.filters.get("tick_size", 0.01)),
            available_balance=self.equity,
            allow_short=True,
            risk_per_trade=self.cfg.risk.risk_per_trade,
            max_positions=self.cfg.risk.max_positions,
            max_positions_per_strategy=self.cfg.strategies.max_positions_per_strategy,
            portfolio_risk_max=self.cfg.risk.portfolio_risk_max,
            max_correlated_risk=self.cfg.risk.max_correlated_risk,
            margin_usage_max=self.cfg.risk.margin_usage_max,
            max_orders_per_day=self.cfg.execution.max_orders_per_day,
            leverage=self.cfg.risk.max_leverage,
            daily_loss_limit=self.cfg.risk.daily_loss_limit,
            weekly_loss_limit=self.cfg.risk.weekly_loss_limit,
            max_drawdown=self.cfg.risk.max_drawdown,
        )

    def _caps_ok(
        self, strategy_id: str, symbol: str, risk_usd: float, margin: float, ts: int
    ) -> bool:
        if self.halted:
            return False
        eq = self.equity
        if eq <= 0:
            return False
        if self.equity - self.day_start_eq <= -self.cfg.risk.daily_loss_limit * self.day_start_eq:
            return False
        if (
            self.equity - self.week_start_eq
            <= -self.cfg.risk.weekly_loss_limit * self.week_start_eq
        ):
            return False
        if self.dd_halt and self.max_dd_pct >= self.cfg.risk.max_drawdown * 100:
            return False
        if len(self.open) >= self.cfg.risk.max_positions:
            return False
        if sum(1 for p in self.open if p.strategy_id == strategy_id) >= (
            self.cfg.strategies.max_positions_per_strategy
        ):
            return False
        if sum(p.risk_usd for p in self.open) + risk_usd > self.cfg.risk.portfolio_risk_max * eq:
            return False
        group = self._groups_at(ts, self._slice_for(ts)).get(symbol, "ALL")
        same = sum(p.risk_usd for p in self.open if p.group == group)
        if same + risk_usd > self.cfg.risk.max_correlated_risk * eq:
            return False
        used_margin = sum(p.qty * p.entry / max(1, self.cfg.risk.max_leverage) for p in self.open)
        if used_margin + margin > self.cfg.risk.margin_usage_max * eq:
            return False
        if self.orders_today >= self.cfg.execution.max_orders_per_day:
            return False
        return True

    def _sized(
        self, symbol: str, side: str, entry: float, stop: float, ts: int
    ) -> tuple[float, float, float] | None:
        """Tra (qty, risk_usd, margin) hoac None neu bi risk tu choi."""
        inp = self._risk_inputs(symbol, ts, ts)
        dec = sizing_mod.plan(
            OrderRequest(
                strategy_id="bt",
                symbol=symbol,
                side=side,
                entry=entry,
                stop=stop,
                tp=None,
                meta={},
            ),
            inp,
        )
        if not dec.ok or dec.qty <= 0:
            return None
        return dec.qty, dec.risk_usd, dec.margin

    def _place(self, sig: dict[str, Any], symbol: str, ts: int, price: float) -> None:
        side = sig["side"]
        direction = 1 if side == "BUY" else -1
        entry = float(price)
        stop = float(sig["stop"])
        if direction > 0 and stop >= entry:
            return
        if direction < 0 and stop <= entry:
            return
        sized = self._sized(symbol, side, entry, stop, ts)
        if sized is None:
            self.counts["caps_blocked"] += 1
            return
        qty, risk_usd, margin = sized
        if not self._caps_ok(sig["strategy_id"], symbol, risk_usd, margin, ts):
            self.counts["caps_blocked"] += 1
            return
        group = self._groups_at(ts, self._slice_for(ts)).get(symbol, "ALL")
        self.orders_today += 1
        if sig["strategy_id"] == mr_mod.STRATEGY_ID:
            self.counts["mr_placed"] += 1
        else:
            self.counts["trend_placed"] += 1
        if sig.get("order_type") == "post_only":
            atr = float(sig.get("atr") or 0.0)
            chase = entry + direction * float(sig.get("max_chase_atr", 0.3)) * atr
            self.pending.append(
                _Pending(
                    strategy_id=sig["strategy_id"],
                    symbol=symbol,
                    direction=direction,
                    qty=qty,
                    limit=entry,
                    stop=stop,
                    tp=sig.get("tp"),
                    risk_usd=risk_usd,
                    expire_ms=ts + int(sig.get("ttl_bars", 2)) * H15_MS,
                    chase_price=chase,
                    time_stop_bars=int(sig.get("time_stop_bars", 12)),
                    entry_ms=ts,
                )
            )
            return
        # market: khop tai gia hien tai + slippage bat loi
        fill = entry * (1 + direction * self.slip)
        fee = qty * fill * self.taker
        self.open.append(
            _Pos(
                strategy_id=sig["strategy_id"],
                symbol=symbol,
                direction=direction,
                qty=qty,
                entry=fill,
                stop=stop,
                tp=sig.get("tp"),
                risk_usd=risk_usd,
                entry_ms=ts,
                fees_entry=fee,
                extreme=fill,
                atr=float(sig.get("atr") or 0.0),
                trail_atr=float(sig.get("trail_atr") or 0.0),
                trail_after_atr=float(sig.get("trail_after_atr") or 0.0),
                time_stop_bars=int(sig.get("time_stop_bars", 36)),
                group=group,
            )
        )

    def _fill_pending(self, symbol: str, bar: dict[str, Any], ts: int) -> None:
        keep: list[_Pending] = []
        for p in self.pending:
            if p.symbol != symbol:
                keep.append(p)
                continue
            if ts >= p.expire_ms:
                continue  # TTL het
            hi, lo = float(bar["h"]), float(bar["l"])
            if p.direction > 0:
                if hi > p.chase_price:  # gia chay qua xa -> huy, khong duoi
                    continue
                if lo < p.limit:
                    fill = p.limit
                    fee = p.qty * fill * self.maker
                    self.open.append(
                        _Pos(
                            strategy_id=p.strategy_id,
                            symbol=p.symbol,
                            direction=1,
                            qty=p.qty,
                            entry=fill,
                            stop=p.stop,
                            tp=p.tp,
                            risk_usd=p.risk_usd,
                            entry_ms=ts,
                            fees_entry=fee,
                            extreme=fill,
                            time_stop_bars=p.time_stop_bars,
                            group=self._groups_at(ts, self._slice_for(ts)).get(symbol, "ALL"),
                        )
                    )
                    continue
            else:
                if lo < p.chase_price:
                    continue
                if hi > p.limit:
                    fill = p.limit
                    fee = p.qty * fill * self.maker
                    self.open.append(
                        _Pos(
                            strategy_id=p.strategy_id,
                            symbol=p.symbol,
                            direction=-1,
                            qty=p.qty,
                            entry=fill,
                            stop=p.stop,
                            tp=p.tp,
                            risk_usd=p.risk_usd,
                            entry_ms=ts,
                            fees_entry=fee,
                            extreme=fill,
                            time_stop_bars=p.time_stop_bars,
                            group=self._groups_at(ts, self._slice_for(ts)).get(symbol, "ALL"),
                        )
                    )
                    continue
            keep.append(p)
        self.pending = keep

    def _close(self, pos: _Pos, price: float, ts: int, reason: str) -> None:
        fill = price
        fee = pos.qty * fill * self.taker
        fees = pos.fees_entry + fee
        gross = (fill - pos.entry) * pos.qty * pos.direction
        pnl = gross - fees - pos.funding_paid
        self.realized += pnl
        risk = max(pos.risk_usd, 1e-12)
        self.trades.append(
            Trade(
                strategy_id=pos.strategy_id,
                symbol=pos.symbol,
                side=pos.side,
                qty=pos.qty,
                entry=pos.entry,
                exit=fill,
                entry_ms=pos.entry_ms,
                exit_ms=ts,
                reason=reason,
                risk_usd=pos.risk_usd,
                pnl_gross=gross,
                fees=fees,
                funding=pos.funding_paid,
                r_multiple=pnl / risk,
                slice=self._slice_for(pos.entry_ms),
            )
        )
        for i, p in enumerate(self.open):
            if p is pos:
                self.open.pop(i)
                break

    def _check_exit(self, pos: _Pos, bar: dict[str, Any], ts: int) -> None:
        hi, lo, op = float(bar["h"]), float(bar["l"]), float(bar["o"])
        if pos.direction > 0:
            if lo <= pos.stop:
                self._close(pos, min(pos.stop, op) * (1 - self.slip), ts, "sl")
                return
            if pos.tp is not None and hi >= pos.tp:
                self._close(pos, pos.tp * (1 - self.slip), ts, "tp")
                return
        else:
            if hi >= pos.stop:
                self._close(pos, max(pos.stop, op) * (1 + self.slip), ts, "sl")
                return
            if pos.tp is not None and lo <= pos.tp:
                self._close(pos, pos.tp * (1 + self.slip), ts, "tp")
                return

    def _apply_funding(self, ts: int) -> None:
        """Tru funding tai dung moc co trong lich su (00/08/16 hoac 4h voi symbol dac biet).

        Dung timestamp that thay vi gia dinh 8h: Binance co symbol funding 4h, gia dinh
        8h se bo sot mot nua so lan tru tien.
        """
        if not self.open:
            return
        key = ts - ts % MIN_MS
        for pos in list(self.open):
            rates = self.funding.get(pos.symbol) or {}
            rate = rates.get(key)
            if rate is None:
                continue
            notional = pos.qty * pos.entry
            pos.funding_paid += pos.direction * rate * notional

    # ---------- main loop ----------

    def run(self) -> list[Trade]:
        all_bars = [b for sd in self.data.values() for b in sd.bars1m]
        if not all_bars:
            return []
        start = min(int(b["open_time"]) for b in all_bars)
        end = max(int(b["open_time"]) for b in all_bars) + MIN_MS
        for ts in range(start, end, MIN_MS):
            day = ts // DAY_MS
            if day != self.day_key:
                self.day_key = day
                self.day_start_eq = self.equity
                self.orders_today = 0
            week = ts // (7 * DAY_MS)
            if week != self.week_key:
                self.week_key = week
                self.week_start_eq = self.equity
            self._apply_funding(ts)

            for symbol, sd in self.data.items():
                bar = sd.map1m.get(ts)
                if bar is None:
                    continue
                self._last_price[symbol] = float(bar["c"])
                self._fill_pending(symbol, bar, ts)
                for pos in list(self.open):
                    if pos.symbol == symbol:
                        self._check_exit(pos, bar, ts)

            if ts % H15_MS == 0:
                self._on_15m(ts)
            if ts % H1_MS == 0:
                self._on_1h(ts)
            if ts % H1_MS == 0:
                self._mark_to_market(ts)
        # dong het cuoi ky
        last = end - MIN_MS
        for pos in list(self.open):
            price = self._last_price.get(pos.symbol, pos.entry)
            self._close(pos, price, last, "end")
        return self.trades

    def _mark_to_market(self, ts: int) -> None:
        eq = self.equity
        for pos in self.open:
            price = self._last_price.get(pos.symbol, pos.entry)
            eq += (price - pos.entry) * pos.qty * pos.direction
        self.peak_eq = max(self.peak_eq, eq)
        if self.peak_eq > 0:
            dd = (self.peak_eq - eq) / self.peak_eq * 100
            self.max_dd_pct = max(self.max_dd_pct, dd)
            if self.dd_breach_ms is None and dd >= self.cfg.risk.max_drawdown * 100:
                # Khong chan entry (xem docs/phase1_task.md P1.4): chi ghi moc de bao cao.
                self.dd_breach_ms = ts

    def _on_15m(self, ts: int) -> None:
        for symbol, sd in self.data.items():
            res = sd.regime_by_close.get(ts)
            if res is None:
                continue
            for pos in list(self.open):
                if pos.symbol != symbol:
                    continue
                if pos.strategy_id == mr_mod.STRATEGY_ID and res.label is not RegimeLabel.RANGE:
                    price = self._last_price.get(symbol)
                    if price:
                        self._close(pos, price * (1 - pos.direction * self.slip), ts, "regime")
                elif pos.strategy_id == trend_mod.STRATEGY_ID:
                    if res.label is not RegimeLabel.TREND or res.trend_dir != pos.direction:
                        price = self._last_price.get(symbol)
                        if price:
                            self._close(pos, price * (1 - pos.direction * self.slip), ts, "regime")
            # time stop MR (12 nen 15m)
            for pos in list(self.open):
                if pos.symbol == symbol and pos.strategy_id == mr_mod.STRATEGY_ID:
                    if pos.time_stop_bars and ts - pos.entry_ms >= pos.time_stop_bars * H15_MS:
                        price = self._last_price.get(symbol)
                        if price:
                            self._close(pos, price * (1 - pos.direction * self.slip), ts, "time")
            # roi RANGE -> huy lenh cho cho khop
            if res.label is not RegimeLabel.RANGE:
                self.pending = [p for p in self.pending if p.symbol != symbol]
                continue
            self.counts["range_bars"] += 1
            if not self.cfg.strategy_enabled("mean_reversion"):
                continue
            feat = sd.feat_by_close.get(ts)
            sig = mr_mod.entry_signal(
                feat,
                sd.bar15_by_close.get(ts),
                res.label.value,
                self.mr_cfg,
                tick_size=float(sd.filters.get("tick_size", 0.01)),
            )
            if sig is None:
                continue
            self.counts["mr_signals"] += 1
            price = self._last_price.get(symbol)
            if price:
                sig["symbol"] = symbol
                self._place(sig, symbol, ts, price)

    def _on_1h(self, ts: int) -> None:
        for symbol, sd in self.data.items():
            idx = sd.h1_by_close.get(ts)
            if idx is None:
                continue
            bar = sd.bars1h[idx]
            price = float(bar["c"])
            # trailing trend
            for pos in list(self.open):
                if pos.symbol != symbol or pos.strategy_id != trend_mod.STRATEGY_ID:
                    continue
                if not pos.trail_atr:
                    continue
                if pos.entry_ms >= int(bar["open_time"]):
                    # khong dung high/low cua nen da bat dau truoc khi vao lenh
                    continue
                pos.extreme = (
                    max(pos.extreme, float(bar["h"]))
                    if pos.direction > 0
                    else min(pos.extreme, float(bar["l"]))
                )
                profit = (pos.extreme - pos.entry) * pos.direction
                if pos.atr and profit >= pos.trail_after_atr * pos.atr:
                    new_stop = pos.extreme - pos.direction * pos.trail_atr * pos.atr
                    if (pos.direction > 0 and new_stop > pos.stop) or (
                        pos.direction < 0 and new_stop < pos.stop
                    ):
                        pos.stop = new_stop
                if pos.time_stop_bars and ts - pos.entry_ms >= pos.time_stop_bars * H1_MS:
                    self._close(pos, price * (1 - pos.direction * self.slip), ts, "time")
            # trend entry
            if not self.cfg.strategy_enabled("trend_pullback"):
                continue
            res = sd.regime_by_close.get(ts)
            if res is None:
                continue
            sig = trend_mod.entry_signal(
                sd.prep1h, idx, int(res.trend_dir), int(sd.ctx_dir[idx]), self.tr_cfg
            )
            if sig is None:
                continue
            self.counts["trend_signals"] += 1
            if res.trend_dir != (1 if sig["side"] == "BUY" else -1):
                continue
            open_px = float(sd.map1m[ts]["o"]) if ts in sd.map1m else price
            sig["symbol"] = symbol
            self._place(sig, symbol, ts, open_px)


def _log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0 and closes[i] > 0:
            out.append(closes[i] / prev - 1.0)
    return out


def build_symbol(
    symbol: str,
    bars1m: list[dict[str, Any]],
    filters: dict[str, float],
    funding: dict[int, float],
    btc_ret: dict[int, float] | None = None,
) -> SymbolData:
    from ..data import bars as bars_mod

    bars15 = bars_mod.aggregate(bars1m, "15m")[0]
    bars1h = bars_mod.aggregate(bars1m, "1h")[0]
    bars4h = bars_mod.aggregate(bars1m, "4h")[0]
    feats = feat_mod.compute_series(bars15)
    feat_by_close = {
        int(b["open_time"]) + H15_MS: f for b, f in zip(bars15, feats) if f is not None
    }
    ctx = _ema4h_context(bars4h, bars1h)
    regime = build_regime(bars15, feats, funding, btc_ret)
    return SymbolData(
        symbol=symbol,
        bars1m=bars1m,
        bars15=bars15,
        feat_by_close=feat_by_close,
        bars1h=bars1h,
        prep1h=trend_mod.prepare(bars1h),
        ctx_dir=ctx,
        h1_by_close={int(b["open_time"]) + H1_MS: i for i, b in enumerate(bars1h)},
        regime_by_close=regime,
        filters=filters,
        feat15=feats,
    )
