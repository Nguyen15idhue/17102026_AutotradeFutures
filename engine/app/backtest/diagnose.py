"""CLI chan doan P1.4 (khong doi tham so chien luoc).

    python -m app.backtest.diagnose --start 2024-12-01 --end 2026-11-18 \
        --data-dir ..\\data --out ..\\data\\reports\\p1.4-diagnose.json

Tra loi 3 cau hoi: tin hieu co edge tho?, regime co dung?, chi phi co phai thu pham?
"""

from __future__ import annotations

import argparse
import calendar
import dataclasses
import json
import time
from datetime import date
from pathlib import Path

from .. import config as config_mod
from . import diagnostics, pipeline, walkforward
from . import report as report_mod
from . import sim as sim_mod

SLIPS = (0.0, 2.0, 5.0, 10.0)


def _ms(d: date) -> int:
    return int(calendar.timegm(d.timetuple())) * 1000


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chan doan P1.4: signal edge + regime + cost")
    ap.add_argument("--config", default="config/mvp.mock.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--exchange-info", default="mock/fixtures/exchangeInfo.json")
    ap.add_argument("--out", default="data/reports/p1.4-diagnose.json")
    ap.add_argument("--no-cost", action="store_true", help="bo qua phan do nhay chi phi")
    ap.add_argument("--slices", type=int, default=2)
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    start_date, end_date = date.fromisoformat(args.start), date.fromisoformat(args.end)
    start_ms, end_ms = _ms(start_date), _ms(end_date)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or [
        str(s) for s in cfg.universe.get("symbols", [])
    ]
    t0 = time.time()
    data, funding, _funding_ok, bar_counts = pipeline.load(
        cfg,
        data_dir=args.data_dir,
        symbols=symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        exchange_info=args.exchange_info,
        start_date=start_date,
        end_date=end_date,
    )
    if not data:
        print("khong co du lieu 1m")
        return 2

    print("dang do tin hieu...", flush=True)
    mr = diagnostics.mr_signals(data, cfg)
    tr = diagnostics.trend_signals(data, cfg)
    mr_raw = diagnostics.mr_raw(data, cfg)
    tr_raw = diagnostics.trend_raw(data, cfg)
    zic = diagnostics.z_ic(data)
    regime = diagnostics.regime_quality(data)

    cost: dict[str, dict[str, float]] = {}
    if not args.no_cost:
        slices = walkforward.build_slices(start_ms, end_ms, oos_months=6, slice_months=args.slices)
        for slip in SLIPS:
            cfg2 = dataclasses.replace(
                cfg, execution=dataclasses.replace(cfg.execution, slippage_bps=slip)
            )
            sim = sim_mod.Sim(cfg2, data, funding, slices)
            trades = sim.run()
            stats = report_mod.stats(trades, cfg.equity_base)
            by = {
                sid: report_mod.stats([t for t in trades if t.strategy_id == sid], cfg.equity_base)
                for sid in (report_mod.MR, report_mod.TREND)
            }
            cost[f"slip_{slip:g}"] = {
                "n": stats["n"],
                "expectancy_r": stats["expectancy_r"],
                "net": stats["net"],
                "mr_expectancy_r": by[report_mod.MR]["expectancy_r"],
                "trend_expectancy_r": by[report_mod.TREND]["expectancy_r"],
            }
            print(f"  slip={slip:g} bps: E[R]={stats['expectancy_r']}", flush=True)

    out = {
        "data": {
            "symbols": sorted(data),
            "bars_1m": bar_counts,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "elapsed_s": round(time.time() - t0, 1),
        },
        "mr_signal": mr,
        "trend_signal": tr,
        "mr_raw_no_regime": mr_raw,
        "trend_raw_no_regime": tr_raw,
        "z_ic_all_bars": zic,
        "regime": regime,
        "cost_sensitivity": cost,
        "notes": [
            "signal study vao tai close nen tin hieu (khong mo phong limit/TTL) — do edge tho",
            "path tinh tren nen 1m; SL cham truoc TP neu cung nen",
            "corr z -> return 8 nen: ky vong AM neu RANGE mean-revert",
        ],
    }
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"MR signal: n={mr.get('n', 0)} tp={mr.get('exit_tp_pct')} sl={mr.get('exit_sl_pct')} "
        f"P(MFE>=1R)={mr.get('p_mfe_ge_1r')} close_r12={mr.get('close_r_mean')}"
    )
    print(
        f"Trend signal: n={tr.get('n', 0)} MFE median={tr.get('mfe_r_median')} "
        f"P(MFE>=1.5R)={tr.get('p_mfe_ge_1_5r')} close_r36={tr.get('close_r_mean')}"
    )
    print(
        f"MR raw (bo regime): n={mr_raw['spec_geometry'].get('n', 0)} "
        f"tp_spec={mr_raw['spec_geometry'].get('exit_tp_pct')} "
        f"1R/1R_tp={mr_raw['symmetric_1r'].get('exit_tp_pct')} "
        f"1R/1R_close_r={mr_raw['symmetric_1r'].get('close_r_mean')}"
    )
    print(
        f"Trend raw (bo regime): n={tr_raw.get('n', 0)} MFE median={tr_raw.get('mfe_r_median')} "
        f"P(MFE>=1.5R)={tr_raw.get('p_mfe_ge_1_5r')} close_r36={tr_raw.get('close_r_mean')}"
    )
    print(f"z IC toan bo nen: {zic}")
    print(
        f"Regime: corr(z,fwd8)={regime.get('range_z_fwd8_corr')} "
        f"trend_hit={regime.get('trend_hit_pct')} n_trend={regime.get('trend_n')}"
    )
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
