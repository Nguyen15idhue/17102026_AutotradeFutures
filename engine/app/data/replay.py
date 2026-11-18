"""Replay P1.2: doc Parquet -> aggregate 15m -> features -> regime, hash tat dinh.

Khong doc wall-clock, khong random, khong phu thuoc thu tu dict/set.
Cung input -> cung sha256, chay lai bao nhieu lan cung vay.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ..ops.log import log
from ..regime.detector import (
    ADX_RANGE_MAX,
    ADX_TREND_MIN,
    COOLDOWN_BARS,
    CRISIS_BTC_RET_15M,
    CRISIS_CONFIRM_BARS,
    CRISIS_FUNDING_ABS,
    CRISIS_LIQ_COUNT,
    CRISIS_SPREAD_MULT,
    HYSTERESIS_BARS,
    RANGE_BBW_PCT_MIN,
    RANGE_RANGE_PCT_MAX,
    RANGE_VOL_PCT_MAX,
    RANGE_VOL_PCT_MIN,
    SQUEEZE_BBW_PCT_MAX,
    SQUEEZE_RANGE_PCT_MAX,
    TREND_DIR_CONFIRM_BARS,
    RegimeMachine,
    classify,
    direction_for,
)
from ..regime.types import RegimeInputs, RegimeLabel
from . import bars as bars_mod
from . import features as feat_mod
from . import parquet_io, persist

TF = "15m"
VERSION = "p1.2.0"
M15 = 15 * 60_000


@dataclass
class ReplayOutput:
    symbol: str
    start_ts: int
    end_ts: int
    rows: list[dict] = field(default_factory=list)
    label_counts: dict[str, int] = field(default_factory=dict)
    raw_counts: dict[str, int] = field(default_factory=dict)
    transitions: int = 0
    raw_transitions: int = 0
    hash: str = ""
    raw_hash: str = ""
    report: dict = field(default_factory=dict)


def params_sha256() -> str:
    """Hash bo tham so dang chay — de doi chieu report voi code."""
    p = {
        "atr": 14,
        "adx": 14,
        "bb_period": 20,
        "bb_std": 2,
        "bbw_lookback": feat_mod.BBW_LOOKBACK,
        "vol_lookback": feat_mod.VOL_LOOKBACK,
        "range_lookback": feat_mod.RANGE_LOOKBACK,
        "range_n": feat_mod.RANGE_N,
        "rv_n": feat_mod.RV_N,
        "bbw_min_samples": feat_mod.BBW_MIN_SAMPLES,
        "adx_range_max": ADX_RANGE_MAX,
        "adx_trend_min": ADX_TREND_MIN,
        "squeeze_bbw_pct_max": SQUEEZE_BBW_PCT_MAX,
        "squeeze_range_pct_max": SQUEEZE_RANGE_PCT_MAX,
        "range_range_pct_max": RANGE_RANGE_PCT_MAX,
        "range_bbw_pct_min": RANGE_BBW_PCT_MIN,
        "range_vol_pct_min": RANGE_VOL_PCT_MIN,
        "range_vol_pct_max": RANGE_VOL_PCT_MAX,
        "crisis_spread_mult": CRISIS_SPREAD_MULT,
        "crisis_liq_count": CRISIS_LIQ_COUNT,
        "crisis_funding_abs": CRISIS_FUNDING_ABS,
        "crisis_btc_ret_15m": CRISIS_BTC_RET_15M,
        "hysteresis_bars": HYSTERESIS_BARS,
        "cooldown_bars": COOLDOWN_BARS,
        "crisis_confirm_bars": CRISIS_CONFIRM_BARS,
        "trend_dir_confirm_bars": TREND_DIR_CONFIRM_BARS,
        # P1.2b: dinh dang canonical_line doi (them trend_dir) -> bump de report cu
        # khong bi so sanh nham voi report moi.
        "hash_format": 2,
    }
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _f(x: float | None, nd: int = 10) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def canonical_line(ts: int, label: str, conf: float, f: dict | None, trend_dir: int = 0) -> str:
    """1 dong hash co dinh dinh dang, khong dung repr float tran.

    Format v2 (P1.2b): them `trend_dir` o cuoi. Doi format = doi hash -> params_sha256
    cung bump `hash_format`, de khong ai so sanh report cu voi report moi.
    """
    if f is None:
        return f"{ts},{label},{conf:.4f},-,-,-,-,-,-,{trend_dir}"
    return (
        f"{ts},{label},{conf:.4f},{_f(f['atr'])},{_f(f['adx'])},{_f(f['bbw'])},"
        f"{_f(f.get('bbw_pct'))},{_f(f['z'])},{_f(f.get('vol_pct'))},{trend_dir}"
    )


def hash_rows(lines: list[str]) -> str:
    h = hashlib.sha256()
    for line in lines:
        h.update((line + "\n").encode("utf-8"))
    return h.hexdigest()


def data_sha256(root: str, symbol: str, days: list[str]) -> str:
    h = hashlib.sha256()
    for d in sorted(days):
        p = parquet_io.day_path(root, symbol, "1m", d)
        h.update(f"{d}:{parquet_io.sha256_file(p)}\n".encode())
    return h.hexdigest()


def load_1m(root: str, symbol: str, start: date, end: date) -> tuple[list[dict], list[str]]:
    out, used, cur = [], [], start
    while cur <= end:
        ds = cur.isoformat()
        part = parquet_io.load_day(root, symbol, "1m", ds)
        if part:
            out.extend(part)
            used.append(ds)
        cur += timedelta(days=1)
    return out, used


def to_15m(bars_1m: list[dict], symbol: str) -> list[dict]:
    bars15, gaps = bars_mod.aggregate(bars_1m, TF)
    for prev_close, nxt_open in gaps:
        log("warn", "data.gap", symbol=symbol, from_ms=prev_close, to_ms=nxt_open)
    return bars15


def btc_return_map(bars15: list[dict]) -> dict[int, float]:
    out: dict[int, float] = {}
    for i in range(1, len(bars15)):
        prev_c = bars15[i - 1]["c"]
        if prev_c:
            out[bars15[i]["open_time"]] = bars15[i]["c"] / prev_c - 1.0
    return out


def run_bars(
    symbol: str,
    bars15: list[dict],
    *,
    btc_ret: dict[int, float] | None = None,
    funding: dict[int, float] | None = None,
    oi: dict[int, float] | None = None,
    bbw_min_samples: int = feat_mod.BBW_MIN_SAMPLES,
    vol_min_samples: int = feat_mod.VOL_MIN_SAMPLES,
    data_hash: str = "",
) -> ReplayOutput:
    """Chay features + regime tren chuoi 15m da dong. Thuan ham, tat dinh."""
    feats = feat_mod.compute_series(
        bars15,
        bbw_min_samples=bbw_min_samples,
        vol_min_samples=vol_min_samples,
        oi=oi,
        funding=funding,
    )
    machine = RegimeMachine()
    rows: list[dict] = []
    final_lines: list[str] = []
    raw_lines: list[str] = []
    label_counts: dict[str, int] = {k.value: 0 for k in RegimeLabel}
    raw_counts: dict[str, int] = {k.value: 0 for k in RegimeLabel}
    transitions = raw_transitions = 0
    prev_label: str | None = None
    prev_raw: str | None = None

    for i, bar in enumerate(bars15):
        ts = bar["open_time"]
        f = feats[i]
        inputs = RegimeInputs(
            feature=f,
            funding=(f.get("funding") if f else None),
            btc_ret_15m=(btc_ret or {}).get(ts),
        )
        raw_label, conf, reason = classify(inputs)
        res = machine.update(raw_label, conf, reason, direction_for(f))
        rows.append(
            {
                "ts": ts,
                "label": res.label.value,
                "raw_label": res.raw_label.value,
                "confidence": res.confidence,
                "reason": res.reason,
                "trend_dir": res.trend_dir,
                "feature": f,
            }
        )
        label_counts[res.label.value] += 1
        raw_counts[res.raw_label.value] += 1
        if prev_label is not None and res.label.value != prev_label:
            transitions += 1
        if prev_raw is not None and res.raw_label.value != prev_raw:
            raw_transitions += 1
        prev_label, prev_raw = res.label.value, res.raw_label.value
        final_lines.append(canonical_line(ts, res.label.value, res.confidence, f, res.trend_dir))
        raw_lines.append(
            canonical_line(ts, res.raw_label.value, conf, f, direction_for(f))
        )

    start_ts = bars15[0]["open_time"] if bars15 else 0
    end_ts = bars15[-1]["open_time"] if bars15 else 0
    days = max(1.0, (end_ts - start_ts + M15) / 86_400_000)
    out = ReplayOutput(
        symbol=symbol,
        start_ts=start_ts,
        end_ts=end_ts,
        rows=rows,
        label_counts=label_counts,
        raw_counts=raw_counts,
        transitions=transitions,
        raw_transitions=raw_transitions,
        hash=hash_rows(final_lines),
        raw_hash=hash_rows(raw_lines),
    )
    out.report = {
        "symbol": symbol,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "bars": len(bars15),
        "days": round(days, 4),
        "label_counts": label_counts,
        "raw_label_counts": raw_counts,
        "transitions": transitions,
        "raw_transitions": raw_transitions,
        "transitions_per_day": round(transitions / days, 4),
        "raw_transitions_per_day": round(raw_transitions / days, 4),
        "hash": out.hash,
        "raw_hash": out.raw_hash,
        "params_sha256": params_sha256(),
        "data_files_sha256": data_hash,
        "generated_by_version": VERSION,
    }
    return out


def persist_run(
    con: sqlite3.Connection,
    symbol: str,
    bars15: list[dict],
    out: ReplayOutput,
    *,
    with_bars: bool = True,
) -> None:
    if with_bars:
        persist.upsert_bars(con, symbol, TF, bars15)
    persist.upsert_features(con, symbol, TF, [r["feature"] for r in out.rows])
    persist.upsert_regime(
        con,
        symbol,
        [(r["ts"], _result_from_row(r)) for r in out.rows],
    )


def _result_from_row(r: dict):
    from ..regime.types import RegimeResult

    return RegimeResult(
        label=RegimeLabel(r["label"]),
        raw_label=RegimeLabel(r["raw_label"]),
        confidence=float(r["confidence"]),
        reason=r["reason"],
        changed=False,
    )


def replay_symbol(
    symbol: str,
    start: date,
    end: date,
    *,
    root: str,
    db_path: str | None = None,
    with_bars: bool = True,
    btc_ret: dict[int, float] | None = None,
) -> ReplayOutput:
    bars_1m, used = load_1m(root, symbol, start, end)
    if not bars_1m:
        raise FileNotFoundError(f"khong co du lieu {symbol} {start}..{end} tai {root}")
    bars15 = to_15m(bars_1m, symbol)
    out = run_bars(symbol, bars15, btc_ret=btc_ret, data_hash=data_sha256(root, symbol, used))
    if db_path:
        from ..db.store import connect

        con = connect(db_path)
        persist_run(con, symbol, bars15, out, with_bars=with_bars)
        con.close()
    return out


def write_report(out: ReplayOutput, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(out.report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Replay data + regime P1.2 (tat dinh)")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"))
    ap.add_argument("--db", default=None, help="mac dinh {data-dir}/p1.2.db")
    ap.add_argument("--report", default=None)
    ap.add_argument("--no-persist", action="store_true")
    ap.add_argument("--no-bars", action="store_true")
    args = ap.parse_args(argv)

    root = str(Path(args.data_dir) / "market")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    symbol = args.symbol.upper()
    btc_ret = None
    if symbol != "BTCUSDT":
        btc_1m, _ = load_1m(root, "BTCUSDT", start, end)
        if btc_1m:
            btc_ret = btc_return_map(to_15m(btc_1m, "BTCUSDT"))

    db = None if args.no_persist else (args.db or str(Path(args.data_dir) / "p1.2.db"))
    out = replay_symbol(
        symbol, start, end, root=root, db_path=db, with_bars=not args.no_bars, btc_ret=btc_ret
    )
    rep = args.report or str(Path(args.data_dir) / "reports" / f"p1.2-replay-{symbol}.json")
    write_report(out, rep)
    print(json.dumps(out.report, sort_keys=True))
    print(f"report={rep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
