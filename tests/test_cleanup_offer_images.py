import pytest

import config
from database.db_manager import DBManager
from scripts.cleanup_offer_images import cleanup


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    directory = tmp_path / "offer_images"
    directory.mkdir()
    monkeypatch.setattr(config, "OFFER_IMAGE_CACHE_DIR", directory)
    return directory


def _offer(item_id, **overrides):
    defaults = dict(
        item_id=item_id,
        title=f"Offer {item_id}",
        url="https://example.com",
        affiliate_url="https://example.com/aff",
        price=19.99,
        original_price=29.99,
        discount_percent=33.0,
        category="setup_gamer",
    )
    defaults.update(overrides)
    return defaults


def test_cleanup_removes_files_for_old_offers_not_on_landing_page(db, cache_dir):
    db.save_offer(**_offer("OLD", local_image_path="OLD.webp"))
    db._conn.execute("UPDATE posted_offers SET posted_at = datetime('now', '-10 days') WHERE item_id = 'OLD';")
    db._conn.commit()
    (cache_dir / "OLD.webp").write_bytes(b"x")

    # landing_page_limit=0: força a segunda condição (ainda no top da
    # landing page) a nunca salvar ninguém, isolando o teste na primeira
    # condição (dias desde a publicação) — sem isso a única oferta do
    # banco sempre "rankeia em 1º" e o teste não provaria nada.
    removed = cleanup(max_unused_days=5, landing_page_limit=0)

    assert removed == 1
    assert not (cache_dir / "OLD.webp").exists()


def test_cleanup_keeps_files_for_recent_offers(db, cache_dir):
    db.save_offer(**_offer("NEW", local_image_path="NEW.webp"))
    (cache_dir / "NEW.webp").write_bytes(b"x")

    removed = cleanup(max_unused_days=5)

    assert removed == 0
    assert (cache_dir / "NEW.webp").exists()


def test_cleanup_keeps_old_offer_still_on_landing_page(db, cache_dir):
    # score alto o bastante pra continuar no top da landing page mesmo velha
    db.save_offer(**_offer("OLD_HIGH_SCORE", local_image_path="OLD_HIGH_SCORE.webp", price=15.0, discount_percent=90.0))
    db._conn.execute(
        "UPDATE posted_offers SET posted_at = datetime('now', '-10 days') WHERE item_id = 'OLD_HIGH_SCORE';"
    )
    db._conn.commit()
    (cache_dir / "OLD_HIGH_SCORE.webp").write_bytes(b"x")

    removed = cleanup(max_unused_days=5)

    assert removed == 0
    assert (cache_dir / "OLD_HIGH_SCORE.webp").exists()


def test_cleanup_removes_files_for_hidden_offers(db, cache_dir):
    db.save_offer(**_offer("HIDDEN", local_image_path="HIDDEN.webp"))
    db.hide_offer("HIDDEN")
    (cache_dir / "HIDDEN.webp").write_bytes(b"x")

    removed = cleanup(max_unused_days=5)

    assert removed == 1
    assert not (cache_dir / "HIDDEN.webp").exists()


def test_cleanup_removes_orphan_files_with_no_matching_offer(db, cache_dir):
    (cache_dir / "orphan.webp").write_bytes(b"x")

    removed = cleanup(max_unused_days=5)

    assert removed == 1
    assert not (cache_dir / "orphan.webp").exists()


def test_cleanup_returns_zero_when_cache_dir_missing(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OFFER_IMAGE_CACHE_DIR", tmp_path / "does-not-exist")
    assert cleanup(max_unused_days=5) == 0
