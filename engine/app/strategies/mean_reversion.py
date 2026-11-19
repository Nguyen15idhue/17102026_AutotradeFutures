"""Mean Reversion trong RANGE (spec §6.3, chốt 19/11/2026).

Dieu kien vao (tat ca phai dung):
  - regime = RANGE
  - wick xuyen ra ngoai band VA nen dong quay lai trong band
  - bbw_pct > 15 (luat an toan so 1 cua he thong)
  - guard kinh te: (TP - entry)/entry >= 0.3% (thay cho range_pct >= 50 da bi bo
    vi mau thuan voi RANGE)

Ham thuan: khong doc DB, khong goi API. Backtest va live dung chung.
"""

from __future__ import annotations

from typing import Any

STRATEGY_ID = "mean_reversion"
TP_MIN_PCT = 0.003  # 0,3% ~ 3x phi round-trip (0,1%) + slippage
BBW_PCT_MIN = 15.0


def entry_signal(
    feature: dict[str, Any] | None,
    bar: dict[str, Any] | None,
    regime: str,
    cfg: dict[str, Any],
    *,
    tick_size: float = 0.0,
) -> dict[str, Any] | None:
    """Tra ve dict lenh (chua qua risk) hoac None.

    `cfg` la block strategies.mean_reversion trong YAML. `bar` la nen 15m vua dong
    (can high/low vi feature chi luu close).
    """

    if not feature or not bar or regime != "RANGE":
        return None
    if not feature.get("allow_mr"):
        return None
    bbw_pct = feature.get("bbw_pct")
    if bbw_pct is None or bbw_pct <= max(BBW_PCT_MIN, float(cfg.get("bbw_pct_min", 0.0))):
        return None

    mid, dn, up = feature.get("bb_mid"), feature.get("bb_dn"), feature.get("bb_up")
    atr = feature.get("atr")
    if mid is None or dn is None or up is None or not atr:
        return None
    close, low, high = float(bar["c"]), float(bar["l"]), float(bar["h"])
    stop_atr = float(cfg.get("stop_atr", 1.2))
    rng24 = feature.get("range_24h")
    rng_pos = feature.get("range_pos")
    if rng24 is None or rng_pos is None:
        return None
    range_low = close - float(rng_pos) * float(rng24)
    range_high = range_low + float(rng24)

    long_ok = low <= dn and close > dn
    short_ok = high >= up and close < up
    if long_ok == short_ok:  # ca hai hoac khong cai nao -> khong doan
        return None

    if long_ok:
        side = "BUY"
        stop = range_low - stop_atr * atr
        tp = mid
        if stop >= close or tp <= close:
            return None
    else:
        side = "SELL"
        stop = range_high + stop_atr * atr
        tp = mid
        if stop <= close or tp >= close:
            return None

    if (tp - close) / close < TP_MIN_PCT and side == "BUY":
        return None
    if (close - tp) / close < TP_MIN_PCT and side == "SELL":
        return None

    entry = close
    if tick_size > 0:
        # Xap xi best_bid + 1 tick khi khong co book trong backtest.
        entry = close + tick_size if side == "BUY" else close - tick_size

    return {
        "strategy_id": STRATEGY_ID,
        "symbol": None,  # caller gan
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp": tp,
        "order_type": "post_only",
        "ttl_bars": int(cfg.get("ttl_bars", 2)),
        "max_chase_atr": 0.3,
        "time_stop_bars": int(cfg.get("time_stop_bars", 12)),
        "atr": atr,
        "meta": {"z": feature.get("z"), "bbw_pct": bbw_pct},
    }
