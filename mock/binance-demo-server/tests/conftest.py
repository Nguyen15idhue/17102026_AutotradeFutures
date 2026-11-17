import pytest

from app import auth
from app.chaos import CHAOS
from app.config import CFG
from app.market import MARKET
from app.store import STORE


@pytest.fixture(autouse=True)
def reset_all():
    auth.LIMITS.reset()
    CHAOS.reset()
    MARKET.boot("replay")
    STORE.init(":memory:", CFG.initial_balance)
    yield
    auth.LIMITS.reset()
    CHAOS.reset()
    STORE.close()
