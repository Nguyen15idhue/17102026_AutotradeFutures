"""Regime P1.2 (nhan + hysteresis). Khong phu thuoc strategy."""

from .detector import RegimeMachine, classify
from .types import RegimeInputs, RegimeLabel, RegimeResult

__all__ = ["RegimeMachine", "classify", "RegimeInputs", "RegimeLabel", "RegimeResult"]
