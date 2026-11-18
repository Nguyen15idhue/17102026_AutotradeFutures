"""Doc + validate config/mvp.{mock,live}.yaml.

Vi sao can loader rieng: engine khong duoc co nhanh `if mock:` (AGENTS §3.11) —
mock va live chi khac config + base_url. Validate som de sai cau hinh thi dung
ngay, khong chay tiep voi tham so sai.

Secret KHONG nam trong YAML; chi doc tu bien moi truong (AGENTS §8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = "config/mvp.mock.yaml"
VALID_ENV = ("mock", "live")
_SECRET_HINTS = ("api_key", "apikey", "secret", "token", "passphrase")


class ConfigError(ValueError):
    """Cau hinh sai — dung ngay, khong doan."""


@dataclass(frozen=True)
class Risk:
    risk_per_trade: float
    max_leverage: int
    max_positions: int
    daily_loss_limit: float
    weekly_loss_limit: float
    max_drawdown: float
    portfolio_risk_max: float
    max_correlated_risk: float
    blackout_minutes: int
    stale_data_seconds: float
    funding_close_bps: float
    margin_usage_max: float
    narrow_stop_warn_pct: float


@dataclass(frozen=True)
class Execution:
    sl_working_type: str
    price_protect: bool
    reconcile_seconds: float
    max_retries: int
    recv_window_ms: int
    fee_bps_maker: float
    fee_bps_taker: float
    slippage_bps: float
    max_orders_per_day: int


@dataclass(frozen=True)
class Strategies:
    allocation: dict[str, float]
    max_positions_per_strategy: int
    mean_reversion: dict[str, Any]
    trend_pullback: dict[str, Any]
    squeeze_breakout: dict[str, Any]


@dataclass(frozen=True)
class Config:
    env: str
    base_url: str
    ws_url: str
    equity_base: float
    universe: dict[str, Any]
    timeframes: dict[str, Any]
    risk: Risk
    regime: dict[str, Any]
    strategies: Strategies
    execution: Execution
    dashboard: dict[str, Any]
    ops: dict[str, Any]
    raw: dict[str, Any] = None  # type: ignore[assignment]

    def strategy_enabled(self, name: str) -> bool:
        block = getattr(self.strategies, name, {}) or {}
        return bool(block.get("enabled", False))


def _req(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _num(block: dict[str, Any], key: str, where: str) -> float:
    val = block.get(key)
    _req(isinstance(val, (int, float)) and not isinstance(val, bool), f"{where}.{key} phai la so")
    return float(val)


def _scan_secrets(node: Any, path: str = "") -> None:
    """YAML khong duoc chua secret — chi duoc dung placeholder rong."""
    if isinstance(node, dict):
        for k, v in node.items():
            key = str(k).lower()
            for hint in _SECRET_HINTS:
                if hint in key:
                    raise ConfigError(f"secret khong duoc nam trong YAML: {path}{k}")
            _scan_secrets(v, f"{path}{k}.")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _scan_secrets(v, f"{path}[{i}].")


def load(path: str | Path | None = None) -> Config:
    """Doc config; `path` mac dinh lay tu CONFIG_PATH hoac config/mvp.mock.yaml."""
    p = Path(path or os.environ.get("CONFIG_PATH", DEFAULT_PATH))
    if not p.is_file():
        raise ConfigError(f"khong thay file config: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    _req(isinstance(raw, dict), "config phai la mapping YAML")
    _scan_secrets(raw)

    env = str(raw.get("env", ""))
    _req(env in VALID_ENV, f"env phai la {VALID_ENV}, nhan duoc {env!r}")

    r = raw.get("risk") or {}
    risk = Risk(
        risk_per_trade=_num(r, "risk_per_trade", "risk"),
        max_leverage=int(_num(r, "max_leverage", "risk")),
        max_positions=int(_num(r, "max_positions", "risk")),
        daily_loss_limit=_num(r, "daily_loss_limit", "risk"),
        weekly_loss_limit=_num(r, "weekly_loss_limit", "risk"),
        max_drawdown=_num(r, "max_drawdown", "risk"),
        portfolio_risk_max=_num(r, "portfolio_risk_max", "risk"),
        max_correlated_risk=_num(r, "max_correlated_risk", "risk"),
        blackout_minutes=int(_num(r, "blackout_minutes", "risk")),
        stale_data_seconds=_num(r, "stale_data_seconds", "risk"),
        funding_close_bps=_num(r, "funding_close_bps", "risk"),
        margin_usage_max=_num(r, "margin_usage_max", "risk"),
        narrow_stop_warn_pct=_num(r, "narrow_stop_warn_pct", "risk"),
    )

    e = raw.get("execution") or {}
    execution = Execution(
        sl_working_type=str(e.get("sl_working_type", "MARK_PRICE")),
        price_protect=bool(e.get("price_protect", True)),
        reconcile_seconds=_num(e, "reconcile_seconds", "execution"),
        max_retries=int(_num(e, "max_retries", "execution")),
        recv_window_ms=int(_num(e, "recv_window_ms", "execution")),
        fee_bps_maker=_num(e, "fee_bps_maker", "execution"),
        fee_bps_taker=_num(e, "fee_bps_taker", "execution"),
        slippage_bps=_num(e, "slippage_bps", "execution"),
        max_orders_per_day=int(_num(e, "max_orders_per_day", "execution")),
    )

    s = raw.get("strategies") or {}
    alloc_raw = s.get("allocation") or {}
    _req(isinstance(alloc_raw, dict) and alloc_raw, "strategies.allocation phai la mapping")
    allocation = {str(k): float(v) for k, v in alloc_raw.items()}
    _req(all(0.0 <= v <= 1.0 for v in allocation.values()), "allocation phai trong [0,1]")
    _req(abs(sum(allocation.values()) - 1.0) < 1e-9, "tong allocation phai = 1.0")
    strategies = Strategies(
        allocation=allocation,
        max_positions_per_strategy=int(s.get("max_positions_per_strategy", 1)),
        mean_reversion=dict(s.get("mean_reversion") or {}),
        trend_pullback=dict(s.get("trend_pullback") or {}),
        squeeze_breakout=dict(s.get("squeeze_breakout") or {}),
    )

    # --- gioi han cung (AGENTS §4) ---
    _req(0.0 < risk.risk_per_trade <= 0.005, "risk_per_trade phai trong (0, 0.005]")
    _req(risk.max_leverage <= 3, "max_leverage <= 3")
    _req(risk.max_positions >= 1, "max_positions >= 1")
    _req(1 <= strategies.max_positions_per_strategy <= risk.max_positions,
         "max_positions_per_strategy phai trong [1, max_positions]")
    _req(0.0 < risk.portfolio_risk_max <= 0.02, "portfolio_risk_max <= 0.02")
    _req(0.0 < risk.max_correlated_risk <= 0.02, "max_correlated_risk <= 0.02")
    _req(0.0 < risk.margin_usage_max <= 0.60, "margin_usage_max <= 0.60")
    _req(0.0 < risk.daily_loss_limit <= risk.weekly_loss_limit <= risk.max_drawdown,
         "daily <= weekly <= max_drawdown")
    _req(0.0 < risk.stale_data_seconds <= 10.0, "stale_data_seconds phai trong (0, 10]")
    _req(risk.blackout_minutes >= 0, "blackout_minutes >= 0")

    if env == "live":
        _req(risk.risk_per_trade <= 0.0025, "live: risk_per_trade <= 0.0025 (AGENTS §4)")
        _req(execution.max_orders_per_day <= 5, "live: max_orders_per_day <= 5")

    return Config(
        env=env,
        base_url=str(raw.get("base_url", "")),
        ws_url=str(raw.get("ws_url", "")),
        equity_base=float(raw.get("equity_base", 0.0)),
        universe=dict(raw.get("universe") or {}),
        timeframes=dict(raw.get("timeframes") or {}),
        risk=risk,
        regime=dict(raw.get("regime") or {}),
        strategies=strategies,
        execution=execution,
        dashboard=dict(raw.get("dashboard") or {}),
        ops=dict(raw.get("ops") or {}),
        raw=raw,
    )
