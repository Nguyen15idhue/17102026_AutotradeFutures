"""Nap du lieu dung chung cho backtest va chan doan (tranh 2 ban logic lech nhau)."""

from __future__ import annotations

import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from ..config import Config
from ..data import bars as bars_mod
from . import funding as funding_mod
from . import loader
from . import sim as sim_mod


def ms_from_date(d: date) -> int:
    return int(calendar.timegm(d.timetuple())) * 1000


def btc_returns(bars1m: list[dict[str, Any]]) -> dict[int, float]:
    """Return 15m cua BTC theo close_ts — input cho dieu kien CRISIS."""
    bars15 = bars_mod.aggregate(bars1m, "15m")[0]
    out: dict[int, float] = {}
    prev: float | None = None
    for b in bars15:
        close = float(b["c"])
        if prev:
            out[int(b["open_time"]) + sim_mod.H15_MS] = close / prev - 1.0
        prev = close
    return out


def load(
    cfg: Config,
    *,
    data_dir: str | Path,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
    exchange_info: str | Path,
    use_funding: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
    verbose: bool = True,
) -> tuple[dict[str, sim_mod.SymbolData], dict[str, dict[int, float]], bool, dict[str, int]]:
    """Tra (data, funding, funding_ok, so_nen_1m_moi_symbol)."""
    root = Path(data_dir) / "market"
    filters = loader.load_filters(exchange_info)
    raw: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols:
        raw[sym] = loader.load_1m(root, sym, start_ms, end_ms)
        if verbose:
            print(f"load {sym}: {len(raw[sym])} nen 1m", flush=True)

    funding: dict[str, dict[int, float]] = {}
    funding_ok = True
    if use_funding:
        s_date = start_date or date.fromtimestamp(start_ms / 1000)
        e_date = end_date or date.fromtimestamp(end_ms / 1000)

        def _one(sym: str) -> tuple[str, dict[int, float], bool]:
            return (sym, *funding_mod.load_or_fetch(Path(data_dir), sym, s_date, e_date))

        with ThreadPoolExecutor(max_workers=5) as pool:
            for sym, rates, ok in pool.map(_one, symbols):
                funding[sym] = rates
                funding_ok = funding_ok and ok
                if not ok:
                    print(f"funding {sym}: khong tai duoc -> dung 0", flush=True)

    btc_ret = btc_returns(raw["BTCUSDT"]) if raw.get("BTCUSDT") else {}
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
        if verbose:
            print(
                f"build {sym}: 15m={len(data[sym].bars15)} 1h={len(data[sym].bars1h)}",
                flush=True,
            )
    counts = {s: len(raw[s]) for s in data}
    return data, funding, funding_ok, counts
