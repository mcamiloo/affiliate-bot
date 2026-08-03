import config
from utils.headlines import pick_offer_headline


def test_pick_offer_headline_returns_one_from_category_pool():
    headline = pick_offer_headline("setup_gamer", "ITEM1")
    assert headline in config.OFFER_HEADLINES["setup_gamer"]


def test_pick_offer_headline_unknown_category_falls_back_to_default():
    headline = pick_offer_headline("nao_existe", "ITEM1")
    assert headline in config.OFFER_HEADLINES["default"]


def test_pick_offer_headline_none_category_falls_back_to_default():
    headline = pick_offer_headline(None, "ITEM1")
    assert headline in config.OFFER_HEADLINES["default"]


def test_pick_offer_headline_is_deterministic_per_item_id():
    first = pick_offer_headline("audio_wearables", "SAME_ID")
    second = pick_offer_headline("audio_wearables", "SAME_ID")
    assert first == second


def test_pick_offer_headline_varies_across_items_in_same_category():
    pool = config.OFFER_HEADLINES["setup_gamer"]
    picks = {pick_offer_headline("setup_gamer", f"ITEM{i}") for i in range(20)}
    # com 20 itens distintos e pool pequeno, espera-se ver mais de um gancho
    assert len(picks) > 1
    assert picks <= set(pool)
