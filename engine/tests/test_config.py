"""Test P1.3 config loader: doc that 2 file trong config/ + validate cung."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app import config as C

ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "config" / "mvp.mock.yaml"
LIVE = ROOT / "config" / "mvp.live.yaml"


def _mut(path: Path, tmp_path: Path, fn) -> Path:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(d)
    out = tmp_path / "cfg.yaml"
    out.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return out


def test_load_mock_real():
    cfg = C.load(MOCK)
    assert cfg.env == "mock"
    assert cfg.risk.risk_per_trade == 0.005
    assert cfg.risk.max_positions == 4
    assert cfg.strategies.max_positions_per_strategy == 2
    assert cfg.strategy_enabled("mean_reversion") and cfg.strategy_enabled("trend_pullback")
    assert not cfg.strategy_enabled("squeeze_breakout")


def test_load_live_real():
    cfg = C.load(LIVE)
    assert cfg.env == "live"
    assert cfg.risk.risk_per_trade == 0.0025
    assert cfg.risk.max_correlated_risk == 0.005
    assert cfg.execution.max_orders_per_day == 5
    assert cfg.base_url.startswith("https://")


def test_allocation_must_sum_one(tmp_path):
    p = _mut(MOCK, tmp_path, lambda d: d["strategies"]["allocation"].update(mean_reversion=0.6))
    with pytest.raises(C.ConfigError, match="allocation"):
        C.load(p)


def test_risk_per_trade_above_limit(tmp_path):
    p = _mut(MOCK, tmp_path, lambda d: d["risk"].update(risk_per_trade=0.006))
    with pytest.raises(C.ConfigError, match="risk_per_trade"):
        C.load(p)


def test_live_risk_above_limit(tmp_path):
    p = _mut(LIVE, tmp_path, lambda d: d["risk"].update(risk_per_trade=0.005))
    with pytest.raises(C.ConfigError, match="live: risk_per_trade"):
        C.load(p)


def test_live_orders_per_day_limit(tmp_path):
    p = _mut(LIVE, tmp_path, lambda d: d["execution"].update(max_orders_per_day=10))
    with pytest.raises(C.ConfigError, match="max_orders_per_day"):
        C.load(p)


def test_margin_cap_above_limit(tmp_path):
    p = _mut(MOCK, tmp_path, lambda d: d["risk"].update(margin_usage_max=0.8))
    with pytest.raises(C.ConfigError, match="margin_usage_max"):
        C.load(p)


def test_slot_per_strategy_above_total(tmp_path):
    p = _mut(MOCK, tmp_path, lambda d: d["strategies"].update(max_positions_per_strategy=9))
    with pytest.raises(C.ConfigError, match="max_positions_per_strategy"):
        C.load(p)


def test_missing_file():
    with pytest.raises(C.ConfigError, match="khong thay file"):
        C.load("config/khong-co.yaml")


def test_invalid_env(tmp_path):
    p = _mut(MOCK, tmp_path, lambda d: d.update(env="prod"))
    with pytest.raises(C.ConfigError, match="env"):
        C.load(p)


def test_secret_in_yaml_rejected(tmp_path):
    p = _mut(MOCK, tmp_path, lambda d: d["ops"].update(telegram_bot_token="abc"))
    with pytest.raises(C.ConfigError, match="secret"):
        C.load(p)


def test_env_path_override(monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", str(LIVE))
    assert C.load().env == "live"
