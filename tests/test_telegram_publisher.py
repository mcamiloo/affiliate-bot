import pytest
from telegram.error import TelegramError

import config
import modules.telegram_publisher as tp


def test_format_offer_message_contains_expected_fields():
    msg = tp.format_offer_message(
        title="Gaming Mouse RGB",
        original_price=199.9,
        discounted_price=99.9,
        discount_percent=50,
        link="https://example.com/product",
    )
    assert "Gaming Mouse RGB" in msg
    assert "£199.90" in msg
    assert "£99.90" in msg
    assert "50% OFF" in msg
    assert "Was:" in msg
    assert "Now:" in msg
    assert 'href="https://example.com/product"' in msg


def test_format_offer_message_escapes_html_special_chars():
    msg = tp.format_offer_message(
        title="Headphones <Bluetooth> & Co",
        original_price=100,
        discounted_price=50,
        discount_percent=50,
        link="https://example.com/x?y=1&z=2",
    )
    assert "<Bluetooth>" not in msg
    assert "&lt;Bluetooth&gt;" in msg
    assert "&amp;" in msg


class FakeBot:
    """Dublê de telegram.Bot pra testar publish_offer sem rede real."""

    calls: list = []
    fail_times = 0

    def __init__(self, token):
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def send_message(self, **kwargs):
        FakeBot.calls.append(kwargs)
        if FakeBot.fail_times > 0:
            FakeBot.fail_times -= 1
            raise TelegramError("timeout simulado")


@pytest.fixture(autouse=True)
def reset_fake_bot(monkeypatch):
    FakeBot.calls = []
    FakeBot.fail_times = 0
    monkeypatch.setattr(tp, "Bot", FakeBot)
    monkeypatch.setattr("utils.retry.time.sleep", lambda seconds: None)


def test_publish_offer_sends_formatted_message():
    tp.publish_offer(
        title="Produto Teste",
        original_price=100,
        discounted_price=50,
        discount_percent=50,
        link="https://example.com",
    )

    assert len(FakeBot.calls) == 1
    sent = FakeBot.calls[0]
    assert sent["chat_id"] == config.TELEGRAM_CHAT_ID
    assert "Produto Teste" in sent["text"]


def test_publish_offer_retries_on_telegram_error(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 5)
    FakeBot.fail_times = 2

    tp.publish_offer(
        title="Produto Retry",
        original_price=10,
        discounted_price=5,
        discount_percent=50,
        link="https://example.com",
    )

    assert len(FakeBot.calls) == 3  # 2 falhas simuladas + 1 sucesso


def test_publish_offer_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 1)
    FakeBot.fail_times = 99  # sempre falha

    with pytest.raises(TelegramError):
        tp.publish_offer(
            title="Produto Sempre Falha",
            original_price=10,
            discounted_price=5,
            discount_percent=50,
            link="https://example.com",
        )

    assert len(FakeBot.calls) == config.MAX_RETRIES + 1
