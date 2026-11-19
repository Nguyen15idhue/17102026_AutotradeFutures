"""Chi bao thuan cho strategy (khong goi API, khong doc DB).

Vi sao tach rieng: backtest va live phai dung CUNG mot ham. Neu live tinh RSI bang
thu vien khac backtest thi ket qua backtest khong con nghia gi.
"""

from __future__ import annotations


def rsi_series(closes: list[float], n: int = 14) -> list[float | None]:
    """RSI Wilder. Phan tu < n la None (chua du mau), khong doan."""

    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        diff = closes[i] - closes[i - 1]
        gains += max(diff, 0.0)
        losses += max(-diff, 0.0)
    avg_g, avg_l = gains / n, losses / n
    out[n] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    for i in range(n + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(diff, 0.0)) / n
        avg_l = (avg_l * (n - 1) + max(-diff, 0.0)) / n
        out[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def pivots(highs: list[float], lows: list[float], k: int = 3) -> list[tuple[int, str, float]]:
    """Fractal k=3: tra (idx, 'H'|'L', price).

    Pivot tai i chi duoc XAC NHAN khi da co k nen sau no, nen caller phai loc
    `idx + k <= i_hien_tai`. Tra ve ca pivot chua xac nhan la de danh cho test;
    strategy luon loc theo `confirmed_at`.
    """

    out: list[tuple[int, str, float]] = []
    n = len(highs)
    for i in range(k, n - k):
        win_h = highs[i - k : i + k + 1]
        peak = max(win_h)
        if highs[i] == peak and win_h.count(peak) == 1:
            out.append((i, "H", highs[i]))
        win_l = lows[i - k : i + k + 1]
        trough = min(win_l)
        if lows[i] == trough and win_l.count(trough) == 1:
            out.append((i, "L", lows[i]))
    return out


def confirmed(
    pivs: list[tuple[int, str, float]], k: int, i_now: int
) -> list[tuple[int, str, float]]:
    """Chi giu pivot da du k nen xac nhan tai thoi diem i_now (chong look-ahead)."""
    return [p for p in pivs if p[0] + k <= i_now]


def last_impulse(
    pivs: list[tuple[int, str, float]], direction: int
) -> tuple[tuple[int, float], tuple[int, float]] | None:
    """Impulse gan nhat: (low_idx, low), (high_idx, high).

    Long: swing low -> swing high SAU no va cao hon. Short: nguoc lai.
    Tra None neu chua du 2 pivot hop le.
    """

    if direction > 0:
        for low in reversed([p for p in pivs if p[1] == "L"]):
            highs = [p for p in pivs if p[1] == "H" and p[0] > low[0] and p[2] > low[2]]
            if highs:
                high = highs[-1]
                return (low[0], low[2]), (high[0], high[2])
        return None
    for high in reversed([p for p in pivs if p[1] == "H"]):
        lows = [p for p in pivs if p[1] == "L" and p[0] > high[0] and p[2] < high[2]]
        if lows:
            low = lows[-1]
            return (low[0], low[2]), (high[0], high[2])
    return None


def ema_slope(series: list[float | None], i: int, lookback: int = 3) -> float | None:
    """Do doc EMA trong `lookback` nen (giá trị tuyệt đối/nen). None nếu thiếu mẫu."""
    if i - lookback < 0:
        return None
    a, b = series[i - lookback], series[i]
    if a is None or b is None:
        return None
    return (b - a) / lookback
