"""Cau hinh mock server: chi doc tu bien moi truong, khong doc .env cua du an."""
from __future__ import annotations

import os


def _s(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _i(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


def _f(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except ValueError:
        return default


def _b(key: str, default: bool) -> bool:
    return _s(key, str(default)).lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self) -> None:
        # --- che do du lieu thi truong ---
        self.market_mode = _s("MARKET_MODE", "proxy").lower()
        self.upstream = _s("UPSTREAM", "https://fapi.binance.com").rstrip("/")
        self.fixtures_dir = _s("FIXTURES_DIR", "/app/fixtures")

        # --- mo phong ---
        self.seed = _i("SEED", 42)
        self.speed = _f("SPEED", 1.0)          # 1 = thoi gian thuc, 60 = nen 60x
        self.initial_balance = _f("INITIAL_BALANCE", 5000.0)
        self.fee_maker_bps = _f("FEE_MAKER_BPS", 2.0)
        self.fee_taker_bps = _f("FEE_TAKER_BPS", 5.0)
        self.fill_model = _s("FILL_MODEL", "pessimistic").lower()
        self.slippage_bps = _f("SLIPPAGE_BPS", 5.0)
        self.max_leverage = _i("MAX_LEVERAGE", 125)
        self.synth_jump_prob = _f("SYNTH_JUMP_PROB", 0.0)   # xac suat 1 nen co cu nhay (test crash)

        # --- bao mat / loi ---
        self.auth_strict = _b("AUTH_STRICT", True)
        self.fail_rate = _f("FAIL_RATE", 0.0)
        self.fail_codes = _s("FAIL_CODES", "")
        self.latency_ms = _i("LATENCY_MS", 0)
        self.ws_drop_every = _i("WS_DROP_EVERY", 0)

        # --- gioi han tan suat (tach rieng de test de dieu chinh) ---
        self.weight_limit_1m = _i("WEIGHT_LIMIT_1M", 2400)
        self.order_limit_10s = _i("ORDER_LIMIT_10S", 300)
        self.order_limit_1m = _i("ORDER_LIMIT_1M", 1200)
        self.ban_seconds = _i("BAN_SECONDS", 120)
        self.listenkey_ttl_s = _i("LISTENKEY_TTL_S", 3600)

        # --- ha tang ---
        self.db_path = _s("DB_PATH", "/app/data/mock.db")
        self.log_level = _s("LOG_LEVEL", "INFO").upper()
        self.api_key_env = _s("MOCK_API_KEY", "")      # rong = chap nhan moi key
        self.api_secret_env = _s("MOCK_API_SECRET", "")

    @property
    def is_dev_local(self) -> bool:
        return not self.db_path.startswith("/app/")


CFG = Config()
