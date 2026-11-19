"""CLI backtest P1.4.

    python -m app.backtest.run --start 2024-12-01 --end 2026-11-18 \
        --symbols BTCUSDT,... --data-dir ..\\data --out ..\\data\\reports\\p1.4-report.json

In toi da ~10 dong de doc nhanh; chi tiet trong JSON.
"""

from __future__ import annotations

import argparse
import calendar
import json
import time
from datetime import date
from pathlib import Path

from .. import config as config_mod
from ..data import bars as bars_mod
from . import funding as funding_mod
from . import loader, walkforward
from . import report as report_mod
from . import sim as sim_mod

MS_PER_DAY = 86_400_000


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _ms(d: date) -> int:
    return int(calendar.timegm(d.timetuple())) * 1000


def _btc_returns(bars1m: list[dict]) -> dict[int, float]:
    bars15 = bars_mod.aggregate(bars1m, "15m")[0]
    out: dict[int, float] = {}
    prev: float | None = None
    for b in bars15:
        close = float(b["c"])
        if prev:
            out[int(b["open_time"]) + sim_mod.H15_MS] = close / prev - 1.0
        prev = close
    return out


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
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    root = Path(args.data_dir) / "market"
    start_ms, end_ms = _ms(_parse_date(args.start)), _ms(_parse_date(args.end))
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or [
        str(s) for s in cfg.universe.get("symbols", [])
    ]
    filters = loader.load_filters(args.exchange_info)
    t0 = time.time()

    raw: dict[str, list[dict]] = {}
    for sym in symbols:
        raw[sym] = loader.load_1m(root, sym, start_ms, end_ms)
        print(f"load {sym}: {len(raw[sym])} nen 1m", flush=True)
    if not raw or not any(raw.values()):
        print("khong co du lieu 1m — kiem tra data-dir/--start/--end")
        return 2

    funding: dict[str, dict[int, float]] = {}
    funding_ok = True
    if not args.no_funding:
        from concurrent.futures import ThreadPoolExecutor

        s_date, e_date = _parse_date(args.start), _parse_date(args.end)

        def _one(sym: str) -> tuple[str, dict[int, float], bool]:
            return (sym, *funding_mod.load_or_fetch(root.parent, sym, s_date, e_date))

        with ThreadPoolExecutor(max_workers=5) as pool:
            for sym, rates, ok in pool.map(_one, symbols):
                funding[sym] = rates
                funding_ok = funding_ok and ok
                if not ok:
                    print(f"funding {sym}: khong tai duoc -> dung 0", flush=True)

    btc_ret = _btc_returns(raw["BTCUSDT"]) if raw.get("BTCUSDT") else {}
    data: dict[str, sim_mod.SymbolData] = {}
    for sym in symbols:
        if not raw.get(sym):
            continue
        data[sym] = sim_mod.build_symbol(
            sym,
            raw[sym],
            filters.get(sym, loader.DEFAULT_FILTERS),
            funding.get(sym, {}),
            btc_ret if sym != "BTCUSDT" else None,
        )
        print(f"build {sym}: 15m={len(data[sym].bars15)} 1h={len(data[sym].bars1h)}", flush=True)

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
        "bars_1m": {s: len(raw[s]) for s in data},
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
