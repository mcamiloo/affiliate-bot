import pytest

import config
from utils.unsubscribe import compute_unsub_token, verify_unsub_token


@pytest.fixture(autouse=True)
def unsub_secret(monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_UNSUB_SECRET", "test-secret")


def test_compute_unsub_token_is_deterministic():
    assert compute_unsub_token("a@b.com") == compute_unsub_token("a@b.com")


def test_compute_unsub_token_is_case_and_whitespace_insensitive():
    assert compute_unsub_token("A@B.com") == compute_unsub_token(" a@b.com ")


def test_compute_unsub_token_differs_per_email():
    assert compute_unsub_token("a@b.com") != compute_unsub_token("c@d.com")


def test_verify_unsub_token_accepts_matching_token():
    token = compute_unsub_token("a@b.com")
    assert verify_unsub_token("a@b.com", token) is True


def test_verify_unsub_token_rejects_wrong_token():
    assert verify_unsub_token("a@b.com", "not-the-right-token") is False


def test_verify_unsub_token_rejects_token_for_different_email():
    token = compute_unsub_token("a@b.com")
    assert verify_unsub_token("c@d.com", token) is False


def test_verify_unsub_token_rejects_empty_token():
    assert verify_unsub_token("a@b.com", "") is False


def test_verify_unsub_token_rejects_when_secret_missing(monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_UNSUB_SECRET", "")
    token = compute_unsub_token("a@b.com")
    assert verify_unsub_token("a@b.com", token) is False
