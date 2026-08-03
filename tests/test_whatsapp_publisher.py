import pytest

import config
import modules.whatsapp_publisher as wp


def test_format_offer_message_contains_expected_fields():
    msg = wp.format_offer_message(
        title="Gaming Mouse RGB",
        original_price=199.9,
        discounted_price=99.9,
        discount_percent=50,
        link="https://example.com/product",
    )
    assert "*Gaming Mouse RGB*" in msg
    assert "£199.90" in msg
    assert "£99.90" in msg
    assert "*50% OFF*" in msg
    assert "https://example.com/product" in msg


class FakeCompletedProcess:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ENABLED", True)
    monkeypatch.setattr(config, "WHATSAPP_COMMUNITY_NAME", "OmbroTechFinds")
    monkeypatch.setattr("utils.retry.time.sleep", lambda seconds: None)


def test_publish_offer_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ENABLED", False)
    calls = []
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: calls.append((a, k)))

    wp.publish_offer(
        title="Produto",
        original_price=100,
        discounted_price=50,
        discount_percent=50,
        link="https://example.com",
    )

    assert calls == []


def test_publish_offer_skips_when_no_community_name(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_COMMUNITY_NAME", "")
    calls = []
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: calls.append((a, k)))

    wp.publish_offer(
        title="Produto",
        original_price=100,
        discounted_price=50,
        discount_percent=50,
        link="https://example.com",
    )

    assert calls == []


def test_publish_offer_invokes_osascript_with_community_name(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(wp.subprocess, "run", fake_run)

    wp.publish_offer(
        title="Produto Teste",
        original_price=100,
        discounted_price=50,
        discount_percent=50,
        link="https://example.com",
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    command = args[0]
    assert command[0] == "osascript"
    script = command[2]
    assert "OmbroTechFinds" in script
    assert "Produto Teste" in script


def test_publish_offer_retries_on_osascript_failure(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 5)
    attempts = {"count": 0}

    def fake_run(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return FakeCompletedProcess(returncode=1, stderr="erro simulado")
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(wp.subprocess, "run", fake_run)

    wp.publish_offer(
        title="Produto Retry",
        original_price=10,
        discounted_price=5,
        discount_percent=50,
        link="https://example.com",
    )

    assert attempts["count"] == 3  # 2 falhas simuladas + 1 sucesso


def test_publish_offer_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 1)
    monkeypatch.setattr(
        wp.subprocess, "run", lambda *a, **k: FakeCompletedProcess(returncode=1, stderr="sempre falha")
    )

    with pytest.raises(RuntimeError):
        wp.publish_offer(
            title="Produto Sempre Falha",
            original_price=10,
            discounted_price=5,
            discount_percent=50,
            link="https://example.com",
        )
