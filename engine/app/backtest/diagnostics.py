"""Chan doan P1.4: tin hieu co edge tho khong, va chi phi anh huong bao nhieu.

Vi sao can: backtest chi noi "lo". De biet sua o dau phai tach 3 tang:
  1. Tin hieu: sau khi vao lenh, gia co di theo huong minh ky vong khong (MFE/MAE)?
  2. Regime: nhan RANGE/TREND co dung khong (corr z -> return, hit rate trend_dir)?
  3. Chi phi: neu slippage = 0 ma van am thi khong phai tai chi phi.

Khong doi tham so chien luoc — chi do.
"""

from __future__ import annotations

import statistics
from typing import Any

from ..config import Config
from ..risk import correlation as corr_mod
from ..strategies import mean_reversion as mr_mod
from ..strategies import trend_pullback as tr_mod
from . import sim as sim_mod

MIN_MS = sim_mod.MIN_MS
H15 = sim_mod.H15_MS
H1 = sim_mod.H1_MS
# Do dai duong gia tinh bang PHUT (path_outcome buoc 1m), khong phai so nen.
MR_PATH_MIN = 12 * 15  # 12 nen 15m = 180 phut
TREND_PATH_MIN = 36 * 60  # 36 nen 1h = 2160 phut


def path_outcome(
    bars: dict[int, dict[str, Any]],
    start_ms: int,
    entry: float,
    stop: float,
    tp: float | None,
    direction: int,
    bars_ahead: int,
    step_ms: int = MIN_MS,
) -> dict[str, Any] | None:
    """Di theo duong gia tu start_ms; tra MFE/MAE (don vi R) va ai cham truoc.

    Cham SL truoc TP trong cung 1 nen (bao thu, giong sim). None neu khong co nen nao.
    """
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return None
    mfe = 0.0
    mae = 0.0
    last_close = entry
    exit_kind = "none"
    seen = 0
    for t in range(start_ms, start_ms + bars_ahead * step_ms, step_ms):
        bar = bars.get(t)
        if bar is None:
            continue
        seen += 1
        hi, lo, close = float(bar["h"]), float(bar["l"]), float(bar["c"])
        last_close = close
        if direction > 0:
            mfe = max(mfe, (hi - entry) / risk)
            mae = min(mae, (lo - entry) / risk)
            if lo <= stop:
                exit_kind = "sl"
                break
            if tp is not None and hi >= tp:
                exit_kind = "tp"
                break
        else:
            mfe = max(mfe, (entry - lo) / risk)
            mae = min(mae, (entry - hi) / risk)
            if hi >= stop:
                exit_kind = "sl"
                break
            if tp is not None and lo <= tp:
                exit_kind = "tp"
                break
    if not seen:
        return None
    return {
        "mfe_r": round(mfe, 3),
        "mae_r": round(mae, 3),
        "exit": exit_kind,
        "close_r": round((last_close - entry) * direction / risk, 3),
    }


def _summ(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    n = len(rows)
    mfe = sorted(r["mfe_r"] for r in rows)
    close_r = [r["close_r"] for r in rows]
    return {
        "n": n,
        "exit_tp_pct": round(sum(1 for r in rows if r["exit"] == "tp") / n, 4),
        "exit_sl_pct": round(sum(1 for r in rows if r["exit"] == "sl") / n, 4),
        "exit_none_pct": round(sum(1 for r in rows if r["exit"] == "none") / n, 4),
        "mfe_r_median": round(statistics.median(mfe), 3),
        "mfe_r_p90": round(mfe[int(0.9 * (n - 1))], 3),
        "mae_r_mean": round(sum(r["mae_r"] for r in rows) / n, 3),
        "close_r_mean": round(sum(close_r) / n, 3),
        "close_r_win_pct": round(sum(1 for x in close_r if x > 0) / n, 4),
        "p_mfe_ge_1r": round(sum(1 for x in mfe if x >= 1.0) / n, 4),
        "p_mfe_ge_1_5r": round(sum(1 for x in mfe if x >= 1.5) / n, 4),
    }


def mr_signals(data: dict[str, sim_mod.SymbolData], cfg: Config) -> dict[str, Any]:
    """Do edge tho cua MR: vao tai close nen tin hieu, di 12 nen 15m."""
    rows: list[dict[str, Any]] = []
    per_symbol: dict[str, list[float]] = {}
    for sym, sd in data.items():
        tick = float(sd.filters.get("tick_size", 0.0))
        for b in sd.bars15:
            close_ts = int(b["open_time"]) + H15
            res = sd.regime_by_close.get(close_ts)
            if res is None or res.label.value != "RANGE":
                continue
            feat = sd.feat_by_close.get(close_ts)
            sig = mr_mod.entry_signal(
                feat, b, res.label.value, cfg.strategies.mean_reversion, tick_size=tick
            )
            if sig is None:
                continue
            direction = 1 if sig["side"] == "BUY" else -1
            entry = float(sig["entry"])
            out = path_outcome(
                sd.map1m,
                close_ts,
                entry,
                float(sig["stop"]),
                sig.get("tp"),
                direction,
                MR_PATH_MIN,
            )
            if out is None:
                continue
            out["symbol"] = sym
            rows.append(out)
            per_symbol.setdefault(sym, []).append(out["close_r"])
    summary = _summ(rows)
    summary["by_symbol_close_r"] = {
        s: round(sum(v) / len(v), 3) for s, v in sorted(per_symbol.items()) if v
    }
    return summary


def trend_signals(data: dict[str, sim_mod.SymbolData], cfg: Config) -> dict[str, Any]:
    """Do edge tho cua Trend: vao tai open nen 1h ke tiep, di 36 nen 1h."""
    rows: list[dict[str, Any]] = []
    per_side: dict[str, list[float]] = {}
    for _sym, sd in data.items():
        bars = sd.bars1h
        for idx in range(len(bars) - 1):
            ts = int(bars[idx]["open_time"]) + H1
            res = sd.regime_by_close.get(ts)
            if res is None or res.label.value != "TREND":
                continue
            sig = tr_mod.entry_signal(
                sd.prep1h,
                idx,
                int(res.trend_dir),
                int(sd.ctx_dir[idx]),
                cfg.strategies.trend_pullback,
            )
            if sig is None:
                continue
            direction = 1 if sig["side"] == "BUY" else -1
            entry = float(bars[idx + 1]["o"])
            out = path_outcome(
                sd.map1m, ts, entry, float(sig["stop"]), None, direction, TREND_PATH_MIN
            )
            if out is None:
                continue
            rows.append(out)
            per_side.setdefault(sig["side"], []).append(out["close_r"])
    summary = _summ(rows)
    summary["by_side_close_r"] = {
        s: round(sum(v) / len(v), 3) for s, v in sorted(per_side.items()) if v
    }
    return summary


def mr_raw(data: dict[str, sim_mod.SymbolData], cfg: Config) -> dict[str, Any]:
    """MR bo qua regime: do edge cua rieng dieu kien wick+close trong band.

    Hai hinh hoc: (a) nhu spec (TP=mid, SL ngoai bien) va (b) doi xung 1R/1R.
    So sanh (a) vs (b) cho biet loi nam o tin hieu hay o hinh hoc TP/SL.
    """
    cfg_mr = cfg.strategies.mean_reversion
    rows_spec: list[dict[str, Any]] = []
    rows_1r: list[dict[str, Any]] = []
    for _sym, sd in data.items():
        for b in sd.bars15:
            close_ts = int(b["open_time"]) + H15
            feat = sd.feat_by_close.get(close_ts)
            if not feat or not feat.get("allow_mr"):
                continue
            mid, dn, up = feat.get("bb_mid"), feat.get("bb_dn"), feat.get("bb_up")
            atr = feat.get("atr")
            rng24, rng_pos = feat.get("range_24h"), feat.get("range_pos")
            if None in (mid, dn, up, atr, rng24, rng_pos) or not atr:
                continue
            close, low, high = float(b["c"]), float(b["l"]), float(b["h"])
            long_ok = low <= dn and close > dn
            short_ok = high >= up and close < up
            if long_ok == short_ok:
                continue
            direction = 1 if long_ok else -1
            range_low = close - float(rng_pos) * float(rng24)
            range_high = range_low + float(rng24)
            stop_spec = range_low - 1.2 * atr if direction > 0 else range_high + 1.2 * atr
            tp_spec = mid
            o = path_outcome(sd.map1m, close_ts, close, stop_spec, tp_spec, direction, MR_PATH_MIN)
            if o is not None:
                rows_spec.append(o)
            r = 1.2 * atr
            stop_1r = close - direction * r
            tp_1r = close + direction * r
            o1 = path_outcome(sd.map1m, close_ts, close, stop_1r, tp_1r, direction, MR_PATH_MIN)
            if o1 is not None:
                rows_1r.append(o1)
    _ = cfg_mr
    return {"spec_geometry": _summ(rows_spec), "symmetric_1r": _summ(rows_1r)}


def trend_raw(data: dict[str, sim_mod.SymbolData], cfg: Config) -> dict[str, Any]:
    """Trend bo qua nhan regime: huong lay tu EMA50/200 + context 4h."""
    cfg_tr = cfg.strategies.trend_pullback
    rows: list[dict[str, Any]] = []
    for _sym, sd in data.items():
        bars = sd.bars1h
        ema50, ema200 = sd.prep1h["ema50"], sd.prep1h["ema200"]
        for idx in range(len(bars) - 1):
            fast, slow = ema50[idx], ema200[idx]
            if fast is None or slow is None or fast == slow:
                continue
            direction = 1 if fast > slow else -1
            sig = tr_mod.entry_signal(sd.prep1h, idx, direction, int(sd.ctx_dir[idx]), cfg_tr)
            if sig is None:
                continue
            entry = float(bars[idx + 1]["o"])
            ts = int(bars[idx]["open_time"]) + H1
            out = path_outcome(
                sd.map1m, ts, entry, float(sig["stop"]), None, direction, TREND_PATH_MIN
            )
            if out is not None:
                rows.append(out)
    return _summ(rows)


def z_ic(data: dict[str, sim_mod.SymbolData]) -> dict[str, Any]:
    """IC cua z voi return tuong lai, tren TOAN BO nen (khong chi RANGE)."""
    out: dict[str, Any] = {}
    for horizon in (4, 8, 16):
        pairs: list[tuple[float, float]] = []
        for _sym, sd in data.items():
            closes = [float(b["c"]) for b in sd.bars15]
            idx_by_close = {int(b["open_time"]) + H15: i for i, b in enumerate(sd.bars15)}
            for close_ts, feat in sd.feat_by_close.items():
                i = idx_by_close.get(close_ts)
                if i is None or i + horizon >= len(closes):
                    continue
                z = feat.get("z")
                if z is None:
                    continue
                pairs.append((float(z), closes[i + horizon] / closes[i] - 1.0))
        c = corr_mod.pearson([p[0] for p in pairs], [p[1] for p in pairs])
        out[f"h{horizon}"] = {"corr": None if c is None else round(c, 5), "n": len(pairs)}
    return out


def regime_quality(data: dict[str, sim_mod.SymbolData]) -> dict[str, Any]:
    """RANGE: corr(z, return 8 nen sau) phai AM. TREND: hit rate cua trend_dir."""
    pairs: list[tuple[float, float]] = []
    trend_hits = 0
    trend_n = 0
    trend_ret: list[float] = []
    label_counts: dict[str, int] = {}
    for _sym, sd in data.items():
        closes = [float(b["c"]) for b in sd.bars15]
        idx_by_close = {int(b["open_time"]) + H15: i for i, b in enumerate(sd.bars15)}
        for close_ts, res in sd.regime_by_close.items():
            label_counts[res.label.value] = label_counts.get(res.label.value, 0) + 1
            i = idx_by_close.get(close_ts)
            if i is None:
                continue
            if res.label.value == "RANGE":
                feat = sd.feat_by_close.get(close_ts)
                if feat and feat.get("z") is not None and i + 8 < len(closes):
                    fwd = closes[i + 8] / closes[i] - 1.0
                    pairs.append((float(feat["z"]), fwd))
            elif res.label.value == "TREND" and res.trend_dir != 0 and i + 96 < len(closes):
                fwd = closes[i + 96] / closes[i] - 1.0
                trend_n += 1
                trend_ret.append(fwd * res.trend_dir)
                if fwd * res.trend_dir > 0:
                    trend_hits += 1
    zs = [p[0] for p in pairs]
    fs = [p[1] for p in pairs]
    corr = corr_mod.pearson(zs, fs)
    return {
        "label_counts": label_counts,
        "range_z_fwd8_corr": None if corr is None else round(corr, 4),
        "range_pairs": len(pairs),
        "range_fwd8_mean_bps": round(sum(fs) / len(fs) * 10_000, 2) if fs else None,
        "trend_hit_pct": round(trend_hits / trend_n, 4) if trend_n else None,
        "trend_signed_fwd96_mean_bps": (
            round(sum(trend_ret) / len(trend_ret) * 10_000, 2) if trend_ret else None
        ),
        "trend_n": trend_n,
    }
