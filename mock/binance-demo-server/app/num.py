"""Helper so hoc: Decimal, lam tron theo tick/step."""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def dec(v: object, default: str = "0") -> Decimal:
    if v is None or v == "":
        return Decimal(default)
    return Decimal(str(v))


def q_tick(price: Decimal, tick: Decimal) -> Decimal:
    """Lam tron xuong theo tickSize."""
    if tick <= 0:
        return price
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def q_step(qty: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return qty
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def is_multiple(value: Decimal, unit: Decimal) -> bool:
    if unit <= 0:
        return True
    return (value / unit) == (value / unit).to_integral_value()


def fmt(value: Decimal, places: int = 8) -> str:
    """Dinh dang chuoi giong Binance: 0.00100000, 65000.00 ..."""
    q = Decimal(1).scaleb(-places)
    return str(value.quantize(q))
