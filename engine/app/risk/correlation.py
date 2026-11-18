"""Nhom tuong quan P1.3: corr 1h 30 ngay voi BTC > 0.8 -> cung nhom.

Vi sao fail-closed: thieu du lieu thi coi TAT CA cung nhom. Sai theo huong chan
bot lai an toan hon sai theo huong cho phep mo 4 vi the cung mot cuoc.
"""

from __future__ import annotations

import math

GROUP_UNKNOWN = "ALL"


def pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 2:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(va * vb)


def groups(
    returns_by_symbol: dict[str, list[float]],
    btc: list[float],
    threshold: float = 0.8,
) -> dict[str, str]:
    """Tra ve symbol -> group key. Cung nhom khi corr voi BTC >= threshold."""
    out: dict[str, str] = {}
    for symbol, rets in returns_by_symbol.items():
        if symbol == "BTCUSDT":
            out[symbol] = "BTC"
            continue
        r = pearson(rets, btc)
        if r is None:
            out[symbol] = GROUP_UNKNOWN
        else:
            out[symbol] = "BTC" if r >= threshold else symbol
    if len(out) > 1 and all(v == GROUP_UNKNOWN for v in out.values()):
        # thieu du lieu toan bo -> gop 1 nhom (fail-closed)
        return {k: GROUP_UNKNOWN for k in out}
    return out
