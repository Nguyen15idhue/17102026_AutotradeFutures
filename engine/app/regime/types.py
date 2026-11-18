"""Kieu du lieu cho regime P1.2. Khong phu thuoc strategy (AGENTS §7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegimeLabel(str, Enum):
    CRISIS = "CRISIS"
    SQUEEZE = "SQUEEZE"
    RANGE = "RANGE"
    TREND = "TREND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RegimeInputs:
    """Feature 15m + cac input phu (optional: mock khong co liquidation stream)."""

    feature: dict | None
    spread_bps: float | None = None
    spread_avg_1h: float | None = None
    liq_count_1m: int | None = None
    funding: float | None = None
    btc_ret_15m: float | None = None


@dataclass(frozen=True)
class RegimeResult:
    label: RegimeLabel
    raw_label: RegimeLabel
    confidence: float
    reason: str
    changed: bool = False
