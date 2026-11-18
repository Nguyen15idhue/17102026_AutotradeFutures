"""Spot-check P1.2: tu tim 3 giai doan (crash / range / squeeze) trong du lieu that.

Khong hardcode ngay. Cuong do:
  A. Tuan RANGE tot nhat: RANGE phai troi trong 3 nhan tradable (RANGE/SQUEEZE/TREND),
     loai UNKNOWN khoi mau so — do classifier co nhan ra chop khong.
  B. Phan biet: share_RANGE(tuan RANGE tot nhat) >= 2 x share_RANGE(tuan TREND manh nhat).
  C. Ngay crash (giam 15m manh nhat): phai co nhan CRISIS.
  D. Chong nhay nhan: transitions/ngay <= 50% so voi raw (khong hysteresis).
Ti le tuyet doi (tren tong so nen) chi ghi de tham khao, khong phai pass/fail.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from ..regime.types import RegimeLabel
from . import replay

DAY = 86_400_000
WEEK = 7 * DAY
TRADABLE = (RegimeLabel.RANGE, RegimeLabel.SQUEEZE, RegimeLabel.TREND)


def _epoch_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _bucket(ts: int, size: int) -> int:
    return ts // size * size


def _counts(rows: list[dict]) -> dict[str, int]:
    out = {k.value: 0 for k in RegimeLabel}
    for r in rows:
        out[r["label"]] = out.get(r["label"], 0) + 1
    return out


def _tradable_counts(rows: list[dict]) -> dict[str, int]:
    out = {k.value: 0 for k in TRADABLE}
    for r in rows:
        if r["label"] in out:
            out[r["label"]] += 1
    return out


def _share(counts: dict[str, int], label: RegimeLabel) -> float:
    total = sum(counts.values())
    return round(counts.get(label.value, 0) / total, 4) if total else 0.0


def _window_hash(rows: list[dict]) -> str:
    return replay.hash_rows(
        [replay.canonical_line(r["ts"], r["label"], r["confidence"], r["feature"]) for r in rows]
    )


def _weeks(rows: list[dict]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(_bucket(r["ts"], WEEK), []).append(r)
    return groups


def _week_report(rows: list[dict]) -> dict:
    counts = _counts(rows)
    tradable = _tradable_counts(rows)
    return {
        "start_ts": rows[0]["ts"],
        "end_ts": rows[-1]["ts"],
        "start_date": date.fromtimestamp(rows[0]["ts"] / 1000).isoformat(),
        "label_counts": counts,
        "tradable_counts": tradable,
        "share_tradable": {k.value: _share(tradable, k) for k in TRADABLE},
        "share_abs": {k.value: _share(counts, k) for k in TRADABLE},
        "hash": _window_hash(rows),
    }


def run_spotcheck(
    symbol: str,
    start: date,
    end: date,
    root: str,
    *,
    history_start: date | None = None,
    out_path: str | None = None,
) -> dict:
    load_start = min(start, history_start) if history_start else start
    bars_1m, used = replay.load_1m(root, symbol, load_start, end)
    if not bars_1m:
        raise FileNotFoundError(f"khong co du lieu {symbol} {load_start}..{end} tai {root}")
    bars15 = replay.to_15m(bars_1m, symbol)
    btc_ret = replay.btc_return_map(bars15) if symbol == "BTCUSDT" else None
    out = replay.run_bars(
        symbol, bars15, btc_ret=btc_ret, data_hash=replay.data_sha256(root, symbol, used)
    )

    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end) + DAY
    week_rows = [r for r in out.rows if start_ms <= r["ts"] < end_ms]
    groups = _weeks(week_rows)
    # chi so sanh tuan du 7 ngay: tuan le cuoi ky bi cat ngang se lam sai ti le
    full = {k: v for k, v in groups.items() if k + WEEK <= end_ms}
    if full:
        groups = full
    if not groups:
        raise ValueError(f"khong co nen nao trong {start}..{end} de spot-check")

    def _transitions(rows: list[dict], key: str) -> int:
        return sum(1 for a, b in zip(rows, rows[1:]) if a[key] != b[key])

    win_final_t = _transitions(week_rows, "label")
    win_raw_t = _transitions(week_rows, "raw_label")

    # Tuan RANGE tot nhat theo share trong nhan tradable; tuan TREND manh nhat tuong tu
    def best_week(label: RegimeLabel) -> tuple[int, list[dict]]:
        return max(
            groups.items(),
            key=lambda kv: (_share(_tradable_counts(kv[1]), label), -kv[0]),
        )

    range_key, range_rows = best_week(RegimeLabel.RANGE)
    trend_key, trend_rows = best_week(RegimeLabel.TREND)
    range_week = _week_report(range_rows)
    trend_week = _week_report(trend_rows)

    range_share = range_week["share_tradable"][RegimeLabel.RANGE.value]
    trend_week_range_share = trend_week["share_tradable"][RegimeLabel.RANGE.value]
    ratio = round(range_share / trend_week_range_share, 4) if trend_week_range_share else None
    two_x = range_share >= 2 * trend_week_range_share
    dominant = range_share >= max(range_week["share_tradable"][k.value] for k in TRADABLE)

    # Ngay crash: muc giam 15m manh nhat trong toan bo lich su da tai
    worst = None
    for i in range(1, len(bars15)):
        prev_c = bars15[i - 1]["c"]
        if not prev_c:
            continue
        ret = bars15[i]["c"] / prev_c - 1.0
        if worst is None or ret < worst[1]:
            worst = (bars15[i]["open_time"], ret)
    crash_day = None
    if worst is not None:
        day = _bucket(worst[0], DAY)
        rows = [r for r in out.rows if _bucket(r["ts"], DAY) == day]
        counts = _counts(rows)
        crash_day = {
            "date": date.fromtimestamp(day / 1000).isoformat(),
            "return_15m": round(worst[1], 6),
            "label_counts": counts,
            "crisis_bars": counts.get(RegimeLabel.CRISIS.value, 0),
            "bars": len(rows),
            "hash": _window_hash(rows),
        }

    # Fallback: 60 ngay cuoi -> chua du 90 ngay mau, khong duoc crash
    cutoff = bars15[-1]["open_time"] - 60 * DAY if bars15 else 0
    short = [b for b in bars15 if b["open_time"] >= cutoff]
    short_out = replay.run_bars(symbol, short)
    short_feats = [r["feature"] for r in short_out.rows if r["feature"]]
    bbw_none = all(f.get("bbw_pct") is None for f in short_feats) if short_feats else True
    first_valid = next(
        (r["ts"] for r in out.rows if r["feature"] and r["feature"].get("bbw_pct") is not None),
        None,
    )

    raw_t, fin_t = out.raw_transitions, out.transitions
    gates = {
        # A: trong tuan RANGE tot nhat, RANGE troi trong 3 nhan tradable
        "range_week_dominant_nonunknown": bool(dominant),
        # B: RANGE o tuan tot nhat gap >= 2 lan RANGE o tuan TREND manh nhat
        "range_vs_trend_2x": bool(two_x),
        "crash_has_crisis": bool(crash_day and crash_day["crisis_bars"] > 0),
        # D do tren dung cua so phan tich (khong tron 90 ngay warmup)
        "transitions_reduced_50pct": bool(win_final_t <= 0.5 * win_raw_t) if win_raw_t else True,
        "bbw_fallback_safe": bbw_none,
    }
    report = {
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "history_start": load_start.isoformat(),
        "bars_15m": len(bars15),
        "weeks_analysed": len(groups),
        "first_valid_label": first_valid,
        "data_files_sha256": out.report["data_files_sha256"],
        "params_sha256": out.report["params_sha256"],
        "replay_hash": out.hash,
        "raw_hash": out.raw_hash,
        "label_counts": out.label_counts,
        "transitions": fin_t,
        "raw_transitions": raw_t,
        "transitions_per_day": out.report["transitions_per_day"],
        "raw_transitions_per_day": out.report["raw_transitions_per_day"],
        "window_transitions": win_final_t,
        "window_raw_transitions": win_raw_t,
        "window_bars": len(week_rows),
        "range_week": range_week,
        "trend_week": trend_week,
        "range_week_key": range_key,
        "trend_week_key": trend_key,
        "range_vs_trend_ratio": ratio,
        "crash_day": crash_day,
        "bbw_fallback_60d": {
            "bars": len(short),
            "features": len(short_feats),
            "bbw_pct_all_none": bbw_none,
            "label_counts": short_out.label_counts,
            "hash": short_out.hash,
        },
        "gates": gates,
        "gates_note": (
            "A/B do kha nang phan biet cua classifier, khong do do pho bien cua RANGE; "
            "share_abs chi de tham khao"
        ),
    }
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spot-check 3 giai doan P1.2")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", required=True, help="bat dau cua so tuan (YYYY-MM-DD)")
    ap.add_argument("--end", required=True)
    ap.add_argument(
        "--history-start", default=None, help="moc bat dau tim ngay crash (mac dinh = --start)"
    )
    ap.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = str(Path(args.data_dir) / "market")
    out_path = args.out or str(Path(args.data_dir) / "reports" / "p1.2-spotcheck.json")
    rep = run_spotcheck(
        args.symbol.upper(),
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        root,
        history_start=date.fromisoformat(args.history_start) if args.history_start else None,
        out_path=out_path,
    )
    print(
        json.dumps(
            {
                "gates": rep["gates"],
                "range_week": {
                    k: rep["range_week"][k] for k in ("start_date", "share_tradable", "share_abs")
                },
                "trend_week": {k: rep["trend_week"][k] for k in ("start_date", "share_tradable")},
                "range_vs_trend_ratio": rep["range_vs_trend_ratio"],
                "crash_day": rep["crash_day"],
                "bbw_fallback_60d": rep["bbw_fallback_60d"],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    print(f"report={out_path}")
    return 0 if all(rep["gates"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
