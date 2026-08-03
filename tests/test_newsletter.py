from datetime import date

import pytest

from database.db_manager import DBManager
from modules import newsletter


@pytest.fixture
def db(tmp_path):
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


def _sample_offer(item_id="1", **overrides):
    defaults = dict(
        item_id=item_id,
        title="Gaming Mouse RGB",
        url="https://aliexpress.com/item/1",
        affiliate_url="https://s.click.aliexpress.com/e/1",
        price=19.99,
        original_price=39.99,
        discount_percent=50.0,
        category="setup_gamer",
        image_url="https://ae01.alicdn.com/img.jpg",
    )
    defaults.update(overrides)
    return defaults


def test_build_newsletter_returns_none_without_recent_offers(db):
    assert newsletter.build_newsletter(db, date(2026, 8, 2)) is None


def test_build_newsletter_includes_recent_offer(db):
    db.save_offer(**_sample_offer())
    content = newsletter.build_newsletter(db, date(2026, 8, 2))

    assert content is not None
    assert content.offer_ids == ["1"]
    assert "Gaming Mouse RGB" in content.html
    assert "£19.99" in content.html


def test_build_newsletter_excludes_offers_outside_lookback_window(db):
    db.save_offer(**_sample_offer())
    db._conn.execute("UPDATE posted_offers SET posted_at = datetime('now', '-1000 hours');")
    db._conn.commit()

    assert newsletter.build_newsletter(db, date(2026, 8, 2)) is None


def test_render_html_contains_unsubscribe_tag():
    html = newsletter.render_html([_sample_offer()])
    assert "{{ unsubscribe }}" in html


def test_render_html_contains_configured_address(monkeypatch):
    import config

    monkeypatch.setattr(config, "NEWSLETTER_ADDRESS_LINE1", "1 Test Street")
    monkeypatch.setattr(config, "NEWSLETTER_ADDRESS_CITY", "Testville")
    monkeypatch.setattr(config, "NEWSLETTER_ADDRESS_POSTAL_CODE", "TE5 7ST")
    monkeypatch.setattr(config, "NEWSLETTER_ADDRESS_COUNTRY", "Testland")

    html = newsletter.render_html([_sample_offer()])

    assert "1 Test Street" in html
    assert "Testville" in html
    assert "TE5 7ST" in html
    assert "Testland" in html


def test_select_offers_respects_max_offers(db, monkeypatch):
    import config

    monkeypatch.setattr(config, "NEWSLETTER_MAX_OFFERS", 2)
    for i in range(5):
        db.save_offer(**_sample_offer(item_id=str(i)))

    assert len(newsletter.select_offers(db)) == 2
