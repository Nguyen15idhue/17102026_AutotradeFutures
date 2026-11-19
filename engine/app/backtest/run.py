"""CLI backtest P1.4.

    python -m app.backtest.run --start 2024-12-01 --end 2026-11-18 \
        --symbols BTCUSDT,... --data-dir ..\\data --out ..\\data\\reports\\p1.4-report.json

In toi da ~10 dong de doc nhanh; chi tiet trong JSON.
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
from . import pipeline, walkforward
from . import report as report_mod
from . import sim as sim_mod


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _ms(d: date) -> int:
    return int(calendar.timegm(d.timetuple())) * 1000


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest P1.4 (MR + Trend long/short)")
    ap.add_argument("--config", default="config/mvp.mock.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True, help="khong bao gom")
    ap.add_argument("--exchange-info", default="mock/fixtures/exchangeInfo.json")
    ap.add_argument("--out", default="data/reports/p1.4-report.json")
    ap.add_argument("--oos-months", type=int, default=6)
    ap.add_argument("--slice-months", type=int, default=2)
    ap.add_argument("--no-funding", action="store_true", help="khong tai funding, dung 0")
    ap.add_argument(
        "--dd-halt",
        action="store_true",
        help="halt khi DD >= max_drawdown (mac dinh TAT cho nghien cuu P1.4)",
    )
    ap.add_argument(
        "--slippage-bps",
        type=float,
        default=None,
        help="ghi de slippage (dung cho do nhay chi phi); mac dinh lay tu config",
    )
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    if args.slippage_bps is not None:
        cfg = dataclasses.replace(
            cfg,
            execution=dataclasses.replace(cfg.execution, slippage_bps=args.slippage_bps),
        )
    start_ms, end_ms = _ms(_parse_date(args.start)), _ms(_parse_date(args.end))
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or [
        str(s) for s in cfg.universe.get("symbols", [])
    ]
    t0 = time.time()

    data, funding, funding_ok, bar_counts = pipeline.load(
        cfg,
        data_dir=args.data_dir,
        symbols=symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        exchange_info=args.exchange_info,
        use_funding=not args.no_funding,
        start_date=_parse_date(args.start),
        end_date=_parse_date(args.end),
    )
    if not data:
        print("khong co du lieu 1m — kiem tra data-dir/--start/--end")
        return 2

    slices = walkforward.build_slices(
        start_ms, end_ms, oos_months=args.oos_months, slice_months=args.slice_months
    )
    sim = sim_mod.Sim(
        cfg, data, funding, slices, funding_fallback=not funding_ok, dd_halt=args.dd_halt
    )
    trades = sim.run()
    elapsed = round(time.time() - t0, 1)

    data_summary = {
        "symbols": sorted(data),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "bars_1m": bar_counts,
        "funding_from_history": funding_ok,
        "fee_bps_maker": cfg.execution.fee_bps_maker,
        "fee_bps_taker": cfg.execution.fee_bps_taker,
        "slippage_bps": cfg.execution.slippage_bps,
        "risk_per_trade": cfg.risk.risk_per_trade,
        "equity_base": cfg.equity_base,
        "elapsed_s": elapsed,
        "notes": [
            "spread guard 2bps khong mo phong duoc (khong co book trong parquet)",
            "DD la mark-to-market tai moi nen 1h",
            "walk-forward khong tune: cung tham so cho moi slice",
            "dd_halt=false: khong halt o DD 6% de do duoc DD that va con du lieu OOS",
        ],
    }
    sim_summary = {
        "max_dd_pct": round(sim.max_dd_pct, 2),
        "halted": sim.halted,
        "halt_reason": sim.halt_reason,
        "dd_halt": args.dd_halt,
        "dd_breach_ms": sim.dd_breach_ms,
        "equity_end": round(sim.equity, 2),
        "counts": sim.counts,
    }
    rep = report_mod.build(
        trades,
        equity_base=cfg.equity_base,
        slices=slices,
        sim_summary=sim_summary,
        data_summary=data_summary,
    )
    rep["generated_ms"] = int(time.time() * 1000)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")

    ov = rep["overall"]
    mr = rep["by_strategy"].get(report_mod.MR) or {"n": 0}
    tr = rep["by_strategy"].get(report_mod.TREND) or {"n": 0}
    sides = rep["trend_by_side"]
    passed = sum(1 for g in rep["gates"] if g["ok"])
    print(f"ket qua: {ov['n']} lenh, net {ov['net']} USD, DD {sim_summary['max_dd_pct']}%")
    print(f"MR: n={mr.get('n', 0)} WR={mr.get('win_rate', 0)} E[R]={mr.get('expectancy_r', 0)}")
    print(
        f"Trend: n={tr.get('n', 0)} "
        + " ".join(f"{s}={sides.get(s, {}).get('n', 0)}" for s in ("LONG", "SHORT"))
    )
    print(
        f"cong dat: {passed}/8 — truot: "
        + ",".join(str(g["id"]) for g in rep["gates"] if not g["ok"])
    )
    print(f"report: {out} ({elapsed}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
