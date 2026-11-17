"""Fault injection: ty le loi, do tre, 503 'execution unknown', throttle -1008.

Chi bat khi duoc cau hinh qua env hoac POST /_admin/chaos.
RNG co seed => ket qua tai lap duoc trong test.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from .config import CFG

UNKNOWN_503 = {
    "code": -1000,
    "msg": "Unknown error, please check your request or try again later.",
}


class Chaos:
    def __init__(self) -> None:
        self.fail_rate = 0.0
        self.latency_ms = 0
        self.codes: list[int] = []
        self.throttle_1008 = False
        self.unknown_503 = False
        self._n = 0
        self._rng = random.Random(CFG.seed)

    def reset(self) -> None:
        self.fail_rate = 0.0
        self.latency_ms = 0
        self.codes = []
        self.throttle_1008 = False
        self.unknown_503 = False
        self._rng = random.Random(CFG.seed)
        self._n = 0

    def configure(self, body: dict[str, Any]) -> dict[str, Any]:
        if "fail_rate" in body:
            self.fail_rate = max(0.0, min(1.0, float(body["fail_rate"])))
        if "latency_ms" in body:
            self.latency_ms = max(0, int(body["latency_ms"]))
        if "codes" in body:
            self.codes = [int(c) for c in body["codes"]]
        if "throttle_1008" in body:
            self.throttle_1008 = bool(body["throttle_1008"])
        if "unknown_503" in body:
            self.unknown_503 = bool(body["unknown_503"])
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "fail_rate": self.fail_rate,
            "latency_ms": self.latency_ms,
            "codes": self.codes,
            "throttle_1008": self.throttle_1008,
            "unknown_503": self.unknown_503,
        }

    # ------------------------------------------------------------ quyet dinh

    def roll(self) -> tuple[int, dict] | None:
        """Tra ve (http_status, body) neu lan goi nay bi bom loi."""
        if self.fail_rate <= 0:
            return None
        self._n += 1
        # RNG tat dinh theo (seed, so thu tu) de test tai lap duoc
        h = hashlib.sha256(f"{CFG.seed}:{self._n}".encode()).digest()
        p = int.from_bytes(h[:8], "big") / float(1 << 64)
        if p >= self.fail_rate:
            return None
        if self.unknown_503:
            return 503, dict(UNKNOWN_503)
        if self.codes:
            code = self.codes[self._n % len(self.codes)]
            return 400, {"code": code, "msg": f"Injected error {code}"}
        return 500, {"code": -1000, "msg": "Injected internal error"}


CHAOS = Chaos()
