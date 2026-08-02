import pytest

import config
from utils.retry import with_retry


class FlakyError(Exception):
    pass


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr("utils.retry.time.sleep", lambda seconds: None)


def test_retries_until_success(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 5)
    calls = {"count": 0}

    @with_retry(exceptions=(FlakyError,))
    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise FlakyError("falha temporária")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3


def test_raises_after_max_retries(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 2)
    calls = {"count": 0}

    @with_retry(exceptions=(FlakyError,))
    def always_fails():
        calls["count"] += 1
        raise FlakyError("sempre falha")

    with pytest.raises(FlakyError):
        always_fails()
    assert calls["count"] == config.MAX_RETRIES + 1  # tentativa inicial + retries


def test_unrelated_exceptions_are_not_retried():
    calls = {"count": 0}

    @with_retry(exceptions=(FlakyError,))
    def raises_other():
        calls["count"] += 1
        raise ValueError("erro não relacionado a rede")

    with pytest.raises(ValueError):
        raises_other()
    assert calls["count"] == 1


def test_succeeds_on_first_try_without_retrying():
    calls = {"count": 0}

    @with_retry(exceptions=(FlakyError,))
    def always_works():
        calls["count"] += 1
        return "ok"

    assert always_works() == "ok"
    assert calls["count"] == 1
