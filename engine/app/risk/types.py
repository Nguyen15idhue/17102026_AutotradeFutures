"""Kieu du lieu cho risk engine P1.3. Thuan du lieu, khong goi REST/DB."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Position:
    """Vi the dang mo, du de tinh risk/slot tu DB."""

    symbol: str
    strategy_id: str
    side: str  # LONG | SHORT
    qty: float
    entry: float
    stop: float
    risk_usd: float
    opened_ms: int = 0
    group: str = ""  # nhom tuong quan; "" = chua biet -> fail-closed


@dataclass(frozen=True)
class OrderRequest:
    """Yeu cau mo lenh (chua qua risk)."""

    strategy_id: str
    symbol: str
    side: str  # BUY = long entry, SELL = short entry
    entry: float
    stop: float
    tp: float | None = None
    order_type: str = "post_only"  # post_only | market
    group: str = ""
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RiskInputs:
    """Anh chup trang thai tai thoi diem xet. Executor build, risk khong tu doc."""

    now_ms: int
    halted: bool
    last_market_ms: int | None
    stale_data_seconds: float
    regime: str
    trend_dir: int
    blackout_until_ms: int
    open_positions: tuple[Position, ...]
    equity: float
    day_pnl: float
    week_pnl: float
    dd_pct: float
    orders_today: int
    spread_bps: float | None
    min_notional: float
    step_size: float
    tick_size: float
    available_balance: float
    allow_short: bool
    risk_per_trade: float
    max_positions: int
    max_positions_per_strategy: int
    portfolio_risk_max: float
    max_correlated_risk: float
    margin_usage_max: float
    max_orders_per_day: int
    leverage: int
    daily_loss_limit: float
    weekly_loss_limit: float
    max_drawdown: float
    paused: bool = False


@dataclass(frozen=True)
class RiskDecision:
    ok: bool
    reason: str = ""
    qty: float = 0.0
    notional: float = 0.0
    margin: float = 0.0
    risk_usd: float = 0.0
