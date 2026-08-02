import sqlite3

import pytest

from database.db_manager import DBManager, compute_score


@pytest.fixture
def db(tmp_path):
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


def _sample_offer(item_id="MLB123", price=99.9, original_price=199.9, discount=50.0):
    return dict(
        item_id=item_id,
        title="Mouse Gamer RGB",
        url="https://mercadolivre.com.br/mouse-gamer",
        affiliate_url="https://mercadolivre.com.br/mouse-gamer?ref=affiliate",
        price=price,
        original_price=original_price,
        discount_percent=discount,
        category="setup_gamer",
    )


def test_creates_db_file_and_schema(tmp_path):
    db_path = tmp_path / "created.db"
    assert not db_path.exists()
    manager = DBManager(db_path=db_path)
    try:
        assert db_path.exists()
        assert manager.count_offers() == 0
    finally:
        manager.close()


def test_save_offer_inserts_and_returns_true(db):
    inserted = db.save_offer(**_sample_offer())
    assert inserted is True
    assert db.count_offers() == 1


def test_save_offer_persists_all_fields(db):
    db.save_offer(**_sample_offer())
    offer = db.get_offer("MLB123")
    assert offer is not None
    assert offer["title"] == "Mouse Gamer RGB"
    assert offer["price"] == 99.9
    assert offer["original_price"] == 199.9
    assert offer["discount_percent"] == 50.0
    assert offer["category"] == "setup_gamer"
    assert offer["posted_at"] is not None


def test_duplicate_offer_is_rejected(db):
    first = db.save_offer(**_sample_offer())
    second = db.save_offer(**_sample_offer())  # mesmo item_id
    assert first is True
    assert second is False
    assert db.count_offers() == 1


def test_is_duplicate_detects_existing_item(db):
    assert db.is_duplicate("MLB123") is False
    db.save_offer(**_sample_offer())
    assert db.is_duplicate("MLB123") is True


def test_different_item_ids_do_not_collide(db):
    db.save_offer(**_sample_offer(item_id="MLB111"))
    db.save_offer(**_sample_offer(item_id="MLB222"))
    assert db.count_offers() == 2
    assert db.is_duplicate("MLB111")
    assert db.is_duplicate("MLB222")
    assert not db.is_duplicate("MLB333")


def test_get_offer_returns_none_for_missing_item(db):
    assert db.get_offer("DOES-NOT-EXIST") is None


def test_data_survives_reconnect(tmp_path):
    """Simula um restart do processo pelo launchd: os dados precisam
    continuar lá quando o DBManager é recriado apontando pro mesmo arquivo.
    """
    db_path = tmp_path / "persist.db"

    manager1 = DBManager(db_path=db_path)
    manager1.save_offer(**_sample_offer())
    manager1.close()

    manager2 = DBManager(db_path=db_path)
    try:
        assert manager2.is_duplicate("MLB123") is True
        assert manager2.count_offers() == 1
    finally:
        manager2.close()


def test_context_manager_closes_connection(tmp_path):
    db_path = tmp_path / "ctx.db"
    with DBManager(db_path=db_path) as manager:
        manager.save_offer(**_sample_offer())
        assert manager.count_offers() == 1


def test_save_offer_persists_image_url(db):
    db.save_offer(**_sample_offer(), image_url="https://ae01.alicdn.com/img.jpg")
    offer = db.get_offer("MLB123")
    assert offer["image_url"] == "https://ae01.alicdn.com/img.jpg"


def test_save_offer_image_url_defaults_to_none(db):
    db.save_offer(**_sample_offer())
    offer = db.get_offer("MLB123")
    assert offer["image_url"] is None


def test_migration_adds_image_url_to_pre_existing_db(tmp_path):
    """Simula um banco criado antes do campo image_url existir — a coluna
    precisa ser adicionada automaticamente na próxima conexão, sem perder
    dados já gravados.
    """
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE posted_offers (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id           TEXT NOT NULL UNIQUE,
            title             TEXT NOT NULL,
            url               TEXT NOT NULL,
            affiliate_url     TEXT NOT NULL,
            price             REAL NOT NULL,
            original_price    REAL,
            discount_percent  REAL,
            category          TEXT,
            posted_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute(
        "INSERT INTO posted_offers (item_id, title, url, affiliate_url, price) "
        "VALUES ('LEGACY1', 'Old Offer', 'https://x.com', 'https://x.com?ref=1', 10.0);"
    )
    conn.commit()
    conn.close()

    manager = DBManager(db_path=db_path)
    try:
        assert manager.count_offers() == 1
        offer = manager.get_offer("LEGACY1")
        assert offer["image_url"] is None
        manager.save_offer(**_sample_offer(item_id="NEW1"), image_url="https://img.jpg")
        assert manager.get_offer("NEW1")["image_url"] == "https://img.jpg"
    finally:
        manager.close()


# --- compute_score / offer_scores ------------------------------------------
# IMPULSE_PRICE_MIN=5.0, IMPULSE_PRICE_MAX=30.0, SCORE_WEIGHTS = price 0.40 /
# discount 0.35 / category 0.25, CATEGORY_VISUAL_APPEAL["setup_gamer"]=90,
# DEFAULT_VISUAL_APPEAL=50 (valores default de config.py).


def test_compute_score_price_within_impulse_range():
    score = compute_score(price=20.0, discount_percent=50.0, category="setup_gamer")
    # 100*0.40 + 50*0.35 + 90*0.25
    assert score == 80.0


def test_compute_score_price_below_impulse_range():
    score = compute_score(price=2.0, discount_percent=50.0, category=None)
    # 60*0.40 + 50*0.35 + 50(default)*0.25
    assert score == 54.0


def test_compute_score_price_above_impulse_range():
    score = compute_score(price=50.0, discount_percent=None, category="categoria-desconhecida")
    # 30*0.40 + 0*0.35 + 50(default)*0.25
    assert score == 24.5


def test_compute_score_price_at_impulse_bounds_is_inclusive():
    assert compute_score(price=5.0, discount_percent=0.0, category=None) == compute_score(
        price=30.0, discount_percent=0.0, category=None
    )


def test_compute_score_discount_none_treated_as_zero():
    with_zero = compute_score(price=20.0, discount_percent=0.0, category="setup_gamer")
    with_none = compute_score(price=20.0, discount_percent=None, category="setup_gamer")
    assert with_zero == with_none


def test_compute_score_unknown_category_uses_default_visual_appeal():
    known = compute_score(price=20.0, discount_percent=50.0, category="setup_gamer")
    unknown = compute_score(price=20.0, discount_percent=50.0, category="nao-existe")
    default_score = compute_score(price=20.0, discount_percent=50.0, category=None)
    assert unknown == default_score
    assert unknown != known


def test_compute_score_matches_offer_scores_view(db):
    offer = _sample_offer(item_id="SCORED1", price=20.0, discount=50.0)
    db.save_offer(**offer)

    expected = compute_score(offer["price"], offer["discount_percent"], offer["category"])
    assert db.get_offer_score("SCORED1") == expected


def test_get_offer_score_returns_none_for_missing_item(db):
    assert db.get_offer_score("DOES-NOT-EXIST") is None


def test_list_offers_by_score_orders_desc_and_breaks_ties_by_recency(tmp_path):
    db_path = tmp_path / "ranked.db"
    manager = DBManager(db_path=db_path)
    try:
        manager.save_offer(**_sample_offer(item_id="LOW", price=200.0, discount=0.0))
        manager.save_offer(**_sample_offer(item_id="HIGH", price=20.0, discount=80.0))
        # Mesmo preço/desconto/categoria -> mesmo score, só posted_at difere,
        # pra testar o desempate por oferta mais recente primeiro.
        manager.save_offer(**_sample_offer(item_id="TIE_OLDER", price=20.0, discount=50.0))
        manager.save_offer(**_sample_offer(item_id="TIE_NEWER", price=20.0, discount=50.0))
        manager._conn.execute(
            "UPDATE posted_offers SET posted_at = '2020-01-01T00:00:00' WHERE item_id = 'TIE_OLDER';"
        )
        manager._conn.execute(
            "UPDATE posted_offers SET posted_at = '2025-01-01T00:00:00' WHERE item_id = 'TIE_NEWER';"
        )
        manager._conn.commit()

        ranked_ids = [row["item_id"] for row in manager.list_offers_by_score(limit=10)]

        assert ranked_ids.index("HIGH") < ranked_ids.index("TIE_NEWER")
        assert ranked_ids.index("TIE_NEWER") < ranked_ids.index("TIE_OLDER")
        assert ranked_ids.index("TIE_OLDER") < ranked_ids.index("LOW")
    finally:
        manager.close()


def test_list_offers_by_score_respects_limit(db):
    for i in range(5):
        db.save_offer(**_sample_offer(item_id=f"ITEM{i}", price=20.0, discount=float(i)))
    assert len(db.list_offers_by_score(limit=2)) == 2
