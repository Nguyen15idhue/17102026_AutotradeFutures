"""Quet tin hieu P1.4b — CHI de chon gia thuyet, khong phai de chon tham so.

Vi sao phai dat truoc: quet 6 tin hieu x 5 horizon x 10 coin = 300 phep thu.
Neu chon cai "dep nhat" thi gan nhu chac chan la overfit. Cach lam o day:
  - moi tin hieu phai co CO CHE viet truoc (khong phai "thay so dep");
  - do tren IS, lay mau KHONG chong lan (buoc = horizon);
  - chi 1 tin hieu duoc sang OOS moi, va phai dat nguong dat truoc.

Khong dung regime label: chinh no da bi chung minh khong co thong tin huong.
"""

from __future__ import annotations

import argparse
import calendar
import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .. import config as config_mod
from . import pipeline
from . import sim as sim_mod

H15 = sim_mod.H15_MS


def _closes(sd: sim_mod.SymbolData) -> list[float]:
    return [float(b["c"]) for b in sd.bars15]


def _feat(sd: sim_mod.SymbolData, i: int) -> dict[str, Any] | None:
    return sd.feat15[i] if i < len(sd.feat15) else None


def _rolling_max(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    for i in range(len(xs)):
        if i >= n:
            out[i] = max(xs[i - n : i])
    return out


def _rolling_min(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    for i in range(len(xs)):
        if i >= n:
            out[i] = min(xs[i - n : i])
    return out


# ---------- dinh nghia tin hieu (co che ghi ro) ----------


def dir_mom24(sd: sim_mod.SymbolData) -> list[int]:
    """Momentum 24h: return 24h duong -> long. Co che: autocorrelation duong cap ngay."""
    closes = _closes(sd)
    out = [0] * len(closes)
    for i in range(96, len(closes)):
        r = closes[i] / closes[i - 96] - 1.0
        out[i] = 1 if r > 0 else -1
    return out


def dir_brk20h(sd: sim_mod.SymbolData) -> list[int]:
    """Breakout 20h: dong cua tren dinh 80 nen 15m -> long, duoi day -> short."""
    highs = [float(b["h"]) for b in sd.bars15]
    lows = [float(b["l"]) for b in sd.bars15]
    closes = _closes(sd)
    hi, lo = _rolling_max(highs, 80), _rolling_min(lows, 80)
    out = [0] * len(closes)
    for i in range(len(closes)):
        if hi[i] is None or lo[i] is None:
            continue
        if closes[i] > hi[i]:
            out[i] = 1
        elif closes[i] < lo[i]:
            out[i] = -1
    return out


def dir_z25(sd: sim_mod.SymbolData) -> list[int]:
    """MR manh: |z| >= 2.5 (thay vi 2.0) -> fade. Co che: cuc tri thong ke."""
    out = [0] * len(sd.bars15)
    for i in range(len(sd.bars15)):
        f = _feat(sd, i)
        if not f or f.get("z") is None:
            continue
        z = float(f["z"])
        if z <= -2.5:
            out[i] = 1
        elif z >= 2.5:
            out[i] = -1
    return out


def dir_bandfade_lowvol(sd: sim_mod.SymbolData) -> list[int]:
    """Wick ra band + dong trong band, chi khi bbw_pct 15-30 (khong qua rong)."""
    out = [0] * len(sd.bars15)
    for i, b in enumerate(sd.bars15):
        f = _feat(sd, i)
        if not f or not f.get("allow_mr"):
            continue
        bbw = f.get("bbw_pct")
        dn, up = f.get("bb_dn"), f.get("bb_up")
        if bbw is None or dn is None or up is None or not (15 <= float(bbw) <= 30):
            continue
        close, low, high = float(b["c"]), float(b["l"]), float(b["h"])
        long_ok = low <= dn and close > dn
        short_ok = high >= up and close < up
        if long_ok != short_ok:
            out[i] = 1 if long_ok else -1
    return out


def dir_volexp(sd: sim_mod.SymbolData) -> list[int]:
    """Vol expansion: vol_pct >= 80 va gia cung phia EMA50 -> theo huong do."""
    out = [0] * len(sd.bars15)
    for i, b in enumerate(sd.bars15):
        f = _feat(sd, i)
        if not f or f.get("vol_pct") is None or f.get("ema50") is None:
            continue
        if float(f["vol_pct"]) < 80:
            continue
        close, ema = float(b["c"]), float(f["ema50"])
        if close > ema:
            out[i] = 1
        elif close < ema:
            out[i] = -1
    return out


def _bars4h(sd: sim_mod.SymbolData) -> list[dict[str, Any]]:
    """Gom 16 nen 15m thanh 1 nen 4h (chi cua so du 16 nen lien tiep)."""
    out: list[dict[str, Any]] = []
    bars = sd.bars15
    for start in range(0, len(bars) - 15, 16):
        grp = bars[start : start + 16]
        if any(int(grp[k]["open_time"]) + H15 != int(grp[k + 1]["open_time"]) for k in range(15)):
            continue
        out.append(
            {
                "open_time": int(grp[0]["open_time"]),
                "o": float(grp[0]["o"]),
                "h": max(float(b["h"]) for b in grp),
                "l": min(float(b["l"]) for b in grp),
                "c": float(grp[-1]["c"]),
                "v": sum(float(b["v"]) for b in grp),
            }
        )
    return out


def dir_brk4h(sd: sim_mod.SymbolData) -> list[int]:
    """Breakout 20 nen 4h (~3,3 ngay).

    Co che: pha dinh khung dai hon la tin hieu manh hon "hoi ve EMA" (pullback).
    """
    bars = _bars4h(sd)
    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    hi, lo = _rolling_max(highs, 20), _rolling_min(lows, 20)
    out = [0] * len(bars)
    for i in range(len(bars)):
        if hi[i] is None or lo[i] is None:
            continue
        if closes[i] > hi[i]:
            out[i] = 1
        elif closes[i] < lo[i]:
            out[i] = -1
    return out


SIGNALS: dict[str, dict[str, Any]] = {
    "mom24h": {"fn": dir_mom24, "tf": "15m", "horizons": (96, 192)},
    "brk20h": {"fn": dir_brk20h, "tf": "15m", "horizons": (8, 24, 96)},
    "z2.5": {"fn": dir_z25, "tf": "15m", "horizons": (4, 8, 16)},
    "bandfade_lowvol": {"fn": dir_bandfade_lowvol, "tf": "15m", "horizons": (4, 8, 16)},
    "volexp": {"fn": dir_volexp, "tf": "15m", "horizons": (8, 24, 96)},
    "brk4h20": {"fn": dir_brk4h, "tf": "4h", "horizons": (6, 12)},
}


def _prices(sd: sim_mod.SymbolData, tf: str) -> list[float]:
    if tf == "15m":
        return _closes(sd)
    return [float(b["c"]) for b in _bars4h(sd)]


def scan_signal(
    name: str,
    data: dict[str, sim_mod.SymbolData],
    *,
    min_samples: int = 100,
) -> dict[str, Any]:
    spec = SIGNALS[name]
    fn: Callable[[sim_mod.SymbolData], list[int]] = spec["fn"]
    dirs = {sym: fn(sd) for sym, sd in data.items()}
    prices = {sym: _prices(sd, spec["tf"]) for sym, sd in data.items()}
    out: dict[str, Any] = {"name": name, "tf": spec["tf"], "horizons": {}}
    for h in spec["horizons"]:
        signed: list[float] = []
        per_symbol: dict[str, float] = {}
        hits = 0
        for sym, d in dirs.items():
            px = prices[sym]
            n = min(len(d), len(px))
            sym_vals: list[float] = []
            for i in range(0, n - h, h):  # mau khong chong lan
                if d[i] == 0:
                    continue
                fwd = px[i + h] / px[i] - 1.0
                v = d[i] * fwd
                signed.append(v)
                sym_vals.append(v)
                if v > 0:
                    hits += 1
            if sym_vals:
                per_symbol[sym] = sum(sym_vals) / len(sym_vals) * 10_000
        if len(signed) < min_samples:
            out["horizons"][f"h{h}"] = {"n": len(signed), "note": "khong du mau"}
            continue
        mean = sum(signed) / len(signed)
        var = sum((x - mean) ** 2 for x in signed) / max(1, len(signed) - 1)
        sd_ = var**0.5
        out["horizons"][f"h{h}"] = {
            "n": len(signed),
            "hit_pct": round(hits / len(signed), 4),
            "mean_bps": round(mean * 10_000, 2),
            "median_bps": round(sorted(signed)[len(signed) // 2] * 10_000, 2),
            "t_stat": round(mean / (sd_ / len(signed) ** 0.5), 2) if sd_ > 0 else None,
            "symbols_positive_pct": round(
                sum(1 for x in per_symbol.values() if x > 0) / len(per_symbol), 3
            )
            if per_symbol
            else None,
            "by_symbol_bps": {k: round(v, 2) for k, v in sorted(per_symbol.items())},
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Quet tin hieu P1.4b (IS only)")
    ap.add_argument("--config", default="config/mvp.mock.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--exchange-info", default="mock/fixtures/exchangeInfo.json")
    ap.add_argument("--out", default="data/reports/p1.4b-scan.json")
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    start_date, end_date = date.fromisoformat(args.start), date.fromisoformat(args.end)
    start_ms = int(calendar.timegm(start_date.timetuple())) * 1000
    end_ms = int(calendar.timegm(end_date.timetuple())) * 1000
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or [
        str(s) for s in cfg.universe.get("symbols", [])
    ]
    t0 = time.time()
    data, _funding, _ok, counts = pipeline.load(
        cfg,
        data_dir=args.data_dir,
        symbols=symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        exchange_info=args.exchange_info,
        use_funding=False,
    )
    if not data:
        print("khong co du lieu")
        return 2
    res = {name: scan_signal(name, data) for name in SIGNALS}
    out = {"period": {"start": args.start, "end": args.end}, "bars_1m": counts, "signals": res}
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"quet {len(SIGNALS)} tin hieu tren {len(data)} symbol, {args.start}->{args.end}")
    for name, r in res.items():
        for hk, v in r["horizons"].items():
            if "note" in v:
                print(f"{name:16s} {hk:4s} n={v['n']} (khong du mau)")
                continue
            print(
                f"{name:16s} {hk:4s} n={v['n']:6d} hit={v['hit_pct']:.3f} "
                f"mean={v['mean_bps']:7.2f}bps t={v['t_stat']} "
                f"coin+={v['symbols_positive_pct']}"
            )
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
