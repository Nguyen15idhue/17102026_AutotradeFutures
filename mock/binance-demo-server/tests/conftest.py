import pytest

from app import auth
from app.config import CFG
from app.market import MARKET
from app.store import STORE


@pytest.fixture(autouse=True)
def reset_all():
    auth.LIMITS.reset()
    MARKET.boot("replay")
    STORE.init(":memory:", CFG.initial_balance)
    yield
    auth.LIMITS.reset()
    STORE.close()
