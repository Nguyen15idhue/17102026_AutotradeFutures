import pytest

from app import auth


@pytest.fixture(autouse=True)
def reset_limits():
    auth.LIMITS.reset()
    yield
    auth.LIMITS.reset()
