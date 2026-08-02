from types import SimpleNamespace

import pytest
from aliexpress_api.errors import ApiRequestException, InvalidTrackingIdException

import config
import modules.aliexpress_client as ac
from database.db_manager import DBManager


def make_product(
    product_id=1,
    title="Gaming Mouse RGB 7200 DPI",
    original_price="199.90",
    sale_price="99.90",
    discount="50%",
    detail_url="https://aliexpress.com/item/1.html",
    promotion_link="https://s.click.aliexpress.com/fallback/1",
    image_url="https://ae01.alicdn.com/img1.jpg",
):
    return SimpleNamespace(
        product_id=product_id,
        product_title=title,
        original_price=original_price,
        target_original_price=original_price,
        sale_price=sale_price,
        target_sale_price=sale_price,
        discount=discount,
        product_detail_url=detail_url,
        promotion_link=promotion_link,
        product_main_image_url=image_url,
    )


@pytest.fixture
def db(tmp_path):
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


def test_matches_niche_true_for_niche_title():
    assert ac.matches_niche("Wireless Gaming Mouse RGB") is True


def test_matches_niche_false_for_unrelated_title():
    assert ac.matches_niche("Electric Pressure Cooker 5L") is False


def test_parse_percent_handles_various_formats():
    assert ac._parse_percent("50%") == 50.0
    assert ac._parse_percent("0%") == 0.0
    assert ac._parse_percent(None) == 0.0
    assert ac._parse_percent("") == 0.0


def test_filter_by_discount_uses_config_default(monkeypatch):
    monkeypatch.setattr(config, "MIN_DISCOUNT_PERCENT", 30)
    products = [make_product(discount="50%"), make_product(discount="10%")]
    result = ac.filter_by_discount(products)
    assert len(result) == 1
    assert result[0].discount == "50%"


def test_filter_by_discount_with_explicit_threshold():
    products = [make_product(discount="50%"), make_product(discount="60%")]
    result = ac.filter_by_discount(products, min_discount_percent=55)
    assert len(result) == 1
    assert result[0].discount == "60%"


def test_filter_new_excludes_items_already_in_db(db):
    db.save_offer(
        item_id="1",
        title="Gaming Mouse RGB",
        url="https://aliexpress.com/item/1.html",
        affiliate_url="https://s.click.aliexpress.com/1",
        price=99.9,
    )
    products = [make_product(product_id=1), make_product(product_id=2)]
    result = ac.filter_new(products, db)
    assert len(result) == 1
    assert result[0].product_id == 2


def test_discover_new_offers_full_pipeline(monkeypatch, db):
    products = [
        make_product(product_id=1, title="Gaming Mouse RGB", discount="50%"),
        make_product(product_id=2, title="Electric Pressure Cooker", discount="80%"),  # off-niche
        make_product(product_id=3, title="Mechanical Gaming Keyboard", discount="10%"),  # low discount
    ]
    monkeypatch.setattr(ac, "search_products", lambda keyword, page_size=50: products)
    monkeypatch.setattr(
        ac, "generate_affiliate_link", lambda url: "https://s.click.aliexpress.com/generated"
    )

    offers = ac.discover_new_offers("gaming mouse", db)

    assert len(offers) == 1
    assert offers[0].item_id == "1"
    assert offers[0].affiliate_url == "https://s.click.aliexpress.com/generated"
    assert offers[0].discount_percent == 50.0


def test_discover_new_offers_falls_back_to_promotion_link_without_tracking_id(monkeypatch, db):
    products = [make_product(product_id=1, discount="50%")]
    monkeypatch.setattr(ac, "search_products", lambda keyword, page_size=50: products)

    def raise_invalid_tracking(url):
        raise InvalidTrackingIdException("no tracking id")

    monkeypatch.setattr(ac, "generate_affiliate_link", raise_invalid_tracking)

    offers = ac.discover_new_offers("gaming mouse", db)

    assert len(offers) == 1
    assert offers[0].affiliate_url == "https://s.click.aliexpress.com/fallback/1"


def test_discover_new_offers_excludes_duplicates(monkeypatch, db):
    db.save_offer(
        item_id="1",
        title="Gaming Mouse RGB",
        url="https://aliexpress.com/item/1.html",
        affiliate_url="https://s.click.aliexpress.com/1",
        price=99.9,
    )
    products = [make_product(product_id=1, discount="50%")]
    monkeypatch.setattr(ac, "search_products", lambda keyword, page_size=50: products)
    monkeypatch.setattr(ac, "generate_affiliate_link", lambda url: "https://example.com")

    offers = ac.discover_new_offers("gaming mouse", db)

    assert offers == []


def test_search_products_retries_on_api_error(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 2)
    monkeypatch.setattr("utils.retry.time.sleep", lambda seconds: None)

    calls = {"count": 0}

    class FakeApi:
        def get_products(self, **kwargs):
            calls["count"] += 1
            if calls["count"] < 2:
                raise ApiRequestException("falha simulada de rede")
            return SimpleNamespace(products=[make_product()], current_record_count=1)

    monkeypatch.setattr(ac, "_client", lambda: FakeApi())

    result = ac.search_products("gaming mouse")
    assert calls["count"] == 2
    assert len(result) == 1
