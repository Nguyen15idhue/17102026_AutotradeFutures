"""Bu offset dong ho: serverTime - local. REST phai cong offset vao timestamp."""

from __future__ import annotations

import time


def measure_offset(get_server_time) -> int:
    """get_server_time() -> serverTime (ms). Tra ve offset ms."""
    t0 = int(time.time() * 1000)
    srv = int(get_server_time())
    t1 = int(time.time() * 1000)
    rtt_adj = (t1 - t0) // 2
    return (srv + rtt_adj) - t1


def now_ms(offset_ms: int = 0) -> int:
    return int(time.time() * 1000) + offset_ms
