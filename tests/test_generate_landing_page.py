import config
from scripts.generate_landing_page import HIGHLIGHT_SCORE_THRESHOLD, render, render_privacy, render_thank_you


def _offer(**overrides):
    offer = dict(
        item_id="1",
        title="Fone Bluetooth Teste",
        url="https://example.com/1",
        affiliate_url="https://example.com/1?ref=aff",
        price=19.99,
        original_price=39.99,
        discount_percent=50.0,
        category="audio_wearables",
        image_url=None,
        score=50,
    )
    offer.update(overrides)
    return offer


def test_render_includes_all_three_channels(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHANNEL_INVITE_LINK", "https://t.me/ombrotechfinds")
    monkeypatch.setattr(config, "INSTAGRAM_PROFILE_URL", "https://www.instagram.com/ombrotechfinds")

    html = render([_offer()])

    assert "https://t.me/ombrotechfinds" in html
    assert "https://www.instagram.com/ombrotechfinds" in html
    assert 'id="subscribe"' in html


def test_render_highlights_top_pick_above_threshold():
    html = render([_offer(score=HIGHLIGHT_SCORE_THRESHOLD)])
    assert "Top pick" in html


def test_render_does_not_highlight_below_threshold():
    html = render([_offer(score=HIGHLIGHT_SCORE_THRESHOLD - 1)])
    assert "Top pick" not in html


def test_render_shows_original_price_only_when_higher():
    html = render([_offer(price=10.0, original_price=5.0)])
    # original_price menor que price não deve aparecer riscado
    assert "£5.00" not in html


def test_render_empty_state_when_no_offers():
    html = render([])
    assert "No offers published yet." in html


def test_render_privacy_and_thank_you_do_not_raise():
    assert "<html" in render_privacy()
    assert "<html" in render_thank_you()
