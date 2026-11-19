"""Chia cua so walk-forward: slice 2 thang + out-of-sample 6 thang cuoi.

Tham so da dong bang (khong tune) nen "train" khong ton tai theo nghia toi uu:
moi slice la mot mau out-of-sample cua cung mot bo tham so. OOS 6 thang cuoi
chi duoc chay 1 lan (script khong cho chay lai voi tham so khac trong cung ngay
ma khong ghi log — ky luat nam o quy trinh, khong phai o code).
"""

from __future__ import annotations

from datetime import UTC, datetime

from .sim import Slice

MS_PER_DAY = 86_400_000


def month_start_ms(year: int, month: int) -> int:
    return int(datetime(year, month, 1, tzinfo=UTC).timestamp() * 1000)


def add_months(year: int, month: int, n: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + n
    return idx // 12, idx % 12 + 1


def build_slices(
    start_ms: int,
    end_ms: int,
    *,
    oos_months: int = 6,
    slice_months: int = 2,
) -> list[Slice]:
    """Slice lien tuc phu [start_ms, end_ms); phan cuoi la OOS."""
    start_dt = datetime.fromtimestamp(start_ms / 1000, tz=UTC)
    end_dt = datetime.fromtimestamp(end_ms / 1000, tz=UTC)
    y, m = start_dt.year, start_dt.month
    first = month_start_ms(y, m)
    cur = max(first, start_ms)

    oy, om = add_months(end_dt.year, end_dt.month, -oos_months + 1)
    oos_start = max(month_start_ms(oy, om), cur)

    out: list[Slice] = []
    idx = 1
    while cur < oos_start:
        ny, nm = add_months(
            datetime.fromtimestamp(cur / 1000, tz=UTC).year,
            datetime.fromtimestamp(cur / 1000, tz=UTC).month,
            slice_months,
        )
        nxt = min(month_start_ms(ny, nm), oos_start)
        if nxt <= cur:
            break
        out.append(Slice(name=f"S{idx:02d}", start_ms=cur, end_ms=nxt, kind="IS"))
        cur = nxt
        idx += 1
    if oos_start < end_ms:
        out.append(Slice(name="OOS", start_ms=oos_start, end_ms=end_ms, kind="OOS"))
    return out
