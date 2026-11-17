"""Engine skeleton (P1.0). P1.1 se thay bang adapter that.

Chi ghi heartbeat de Docker healthcheck. Khong dat lenh, khong giu secret.
"""
from __future__ import annotations

import os
import time

HB = "/app/data/heartbeat"


def main() -> None:
    os.makedirs(os.path.dirname(HB), exist_ok=True)
    while True:
        with open(HB, "w", encoding="utf-8") as f:
            f.write(str(int(time.time() * 1000)))
        time.sleep(10)


if __name__ == "__main__":
    main()
