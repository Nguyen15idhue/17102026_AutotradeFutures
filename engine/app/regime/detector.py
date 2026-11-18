"""Regime detector P1.2: 5 nhan, thu tu uu tien CRISIS -> SQUEEZE -> RANGE -> TREND -> UNKNOWN.

Nguong lay tu spec §3.6/§6.2. Hysteresis 3 nen + cooldown 5 nen; CRISIS vao ngay
(1 nen) vi day la trang thai an toan — cho 45 phut la trai nguyen tac "CRISIS = khong mo lenh moi".
"""

from __future__ import annotations

from .types import RegimeInputs, RegimeLabel, RegimeResult

# --- Nguong (khong doi neu chua co walk-forward + ly do ghi lai) ---
ADX_RANGE_MAX = 20.0
ADX_TREND_MIN = 22.0
SQUEEZE_BBW_PCT_MAX = 20.0
SQUEEZE_RANGE_PCT_MAX = 30.0
RANGE_RANGE_PCT_MAX = 50.0
RANGE_BBW_PCT_MIN = 15.0
RANGE_VOL_PCT_MIN = 20.0
RANGE_VOL_PCT_MAX = 60.0
CRISIS_SPREAD_MULT = 3.0
CRISIS_LIQ_COUNT = 5
CRISIS_FUNDING_ABS = 0.001
CRISIS_BTC_RET_15M = -0.04
HYSTERESIS_BARS = 3
COOLDOWN_BARS = 5
CRISIS_CONFIRM_BARS = 1


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.4f}"


def _crisis(inputs: RegimeInputs) -> tuple[bool, list[str], list[str]]:
    """Tra ve (triggered, ly do kich hoat, input thieu)."""
    hits, missing = [], []
    if inputs.spread_bps is None or inputs.spread_avg_1h is None:
        missing.append("spread")
    elif inputs.spread_avg_1h > 0 and inputs.spread_bps > CRISIS_SPREAD_MULT * inputs.spread_avg_1h:
        hits.append(
            f"spread={_fmt(inputs.spread_bps)}>{CRISIS_SPREAD_MULT}x{_fmt(inputs.spread_avg_1h)}"
        )
    if inputs.liq_count_1m is None:
        missing.append("liq")
    elif inputs.liq_count_1m > CRISIS_LIQ_COUNT:
        hits.append(f"liq={inputs.liq_count_1m}>{CRISIS_LIQ_COUNT}")
    if inputs.funding is None:
        missing.append("funding")
    elif abs(inputs.funding) > CRISIS_FUNDING_ABS:
        hits.append(f"funding={_fmt(inputs.funding)}")
    if inputs.btc_ret_15m is None:
        missing.append("btc")
    elif inputs.btc_ret_15m < CRISIS_BTC_RET_15M:
        hits.append(f"btc_15m={_fmt(inputs.btc_ret_15m)}")
    return bool(hits), hits, missing


def classify(inputs: RegimeInputs) -> tuple[RegimeLabel, float, str]:
    """Phan loai 1 nen, chua hysteresis. Tra ve (label, confidence, reason)."""
    f = inputs.feature
    triggered, hits, missing = _crisis(inputs)
    if triggered:
        return RegimeLabel.CRISIS, 1.0, "crisis:" + ",".join(hits)
    if f is None:
        return RegimeLabel.UNKNOWN, 0.0, "missing:feature"

    checks: list[tuple[str, bool, str]] = []
    bbw_pct, vol_pct = f.get("bbw_pct"), f.get("vol_pct")
    adx, rng_pct = f.get("adx"), f.get("range_pct")
    vol5, vol20 = f.get("vol_sma5"), f.get("vol_sma20")

    # SQUEEZE: bbw_pct <= 20, range_24h/ATR trong 30% thap nhat, volume giam
    if bbw_pct is None or rng_pct is None or vol5 is None or vol20 is None:
        checks.append(("squeeze", False, "missing"))
    else:
        checks.append(("squeeze", bbw_pct <= SQUEEZE_BBW_PCT_MAX, f"bbw_pct={_fmt(bbw_pct)}"))
        checks.append(("squeeze", rng_pct < SQUEEZE_RANGE_PCT_MAX, f"range_pct={_fmt(rng_pct)}"))
        checks.append(("squeeze", vol5 < vol20, f"vol5={_fmt(vol5)},vol20={_fmt(vol20)}"))
    # RANGE: adx<20, range_24h/ATR duoi trung vi, vol_pct 20..60, bbw_pct>15
    if adx is None or rng_pct is None or vol_pct is None or bbw_pct is None:
        checks.append(("range", False, "missing"))
    else:
        checks.append(("range", adx < ADX_RANGE_MAX, f"adx={_fmt(adx)}"))
        checks.append(("range", rng_pct < RANGE_RANGE_PCT_MAX, f"range_pct={_fmt(rng_pct)}"))
        checks.append(
            ("range", RANGE_VOL_PCT_MIN <= vol_pct <= RANGE_VOL_PCT_MAX, f"vol_pct={_fmt(vol_pct)}")
        )
        checks.append(("range", bbw_pct > RANGE_BBW_PCT_MIN, f"bbw_pct={_fmt(bbw_pct)}"))
    # TREND: adx>22 va ema50>ema200
    ema50, ema200 = f.get("ema50"), f.get("ema200")
    if adx is None or ema50 is None or ema200 is None:
        checks.append(("trend", False, "missing"))
    else:
        checks.append(("trend", adx > ADX_TREND_MIN, f"adx={_fmt(adx)}"))
        checks.append(("trend", ema50 > ema200, "ema50>ema200"))

    def passed(name: str) -> bool:
        return all(ok for n, ok, _ in checks if n == name)

    def conf(name: str) -> float:
        row = [ok for n, ok, _ in checks if n == name]
        return round(sum(row) / len(row), 4) if row else 0.0

    # Uu tien SQUEEZE truoc RANGE (hop dang nen thi khong fade)
    if passed("squeeze"):
        return RegimeLabel.SQUEEZE, conf("squeeze"), "squeeze:ok"
    if passed("range"):
        reason = "range:ok"
        if missing:
            reason += ";missing:" + ",".join(missing)
        return RegimeLabel.RANGE, conf("range"), reason
    if passed("trend"):
        return RegimeLabel.TREND, conf("trend"), "trend:ok"

    failed = [f"{n}:{r}" for n, ok, r in checks if not ok]
    if missing:
        failed.append("missing:" + ",".join(missing))
    return RegimeLabel.UNKNOWN, 0.0, ";".join(failed)


class RegimeMachine:
    """Hysteresis: nhan moi giu 3 nen; sau khi doi, 5 nen khong doi lai. CRISIS vao ngay."""

    def __init__(
        self,
        confirm_bars: int = HYSTERESIS_BARS,
        cooldown_bars: int = COOLDOWN_BARS,
        crisis_confirm_bars: int = CRISIS_CONFIRM_BARS,
        initial: RegimeLabel = RegimeLabel.UNKNOWN,
    ) -> None:
        self.confirm_bars = confirm_bars
        self.cooldown_bars = cooldown_bars
        self.crisis_confirm_bars = crisis_confirm_bars
        self.current = initial
        self.pending: RegimeLabel | None = None
        self.streak = 0
        self.since_change = cooldown_bars  # du dieu kien ngay tu dau

    def update(self, raw: RegimeLabel, confidence: float, reason: str) -> RegimeResult:
        self.since_change += 1
        changed = False
        if raw == self.current:
            self.pending, self.streak = None, 0
        else:
            if raw == self.pending:
                self.streak += 1
            else:
                self.pending, self.streak = raw, 1
            need = self.crisis_confirm_bars if raw is RegimeLabel.CRISIS else self.confirm_bars
            # sau khi doi nhan: 5 nen ke tiep KHONG doi lai -> som nhat la nen thu 6
            cooldown_ok = self.since_change > self.cooldown_bars
            if raw is RegimeLabel.CRISIS or (self.streak >= need and cooldown_ok):
                self.current = raw
                self.pending, self.streak = None, 0
                self.since_change = 0
                changed = True

        held_conf = confidence if raw == self.current else 0.0
        return RegimeResult(
            label=self.current,
            raw_label=raw,
            confidence=round(held_conf, 4),
            reason=reason,
            changed=changed,
        )
