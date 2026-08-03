import pytest

import config
import modules.orchestrator as orch
from database.db_manager import DBManager
from modules.aliexpress_client import Offer


def make_offer(item_id="1", title="Gaming Mouse RGB", price=50.0, original=100.0, discount=50.0):
    return Offer(
        item_id=item_id,
        title=title,
        original_price=original,
        sale_price=price,
        discount_percent=discount,
        product_url=f"https://aliexpress.com/item/{item_id}.html",
        affiliate_url=f"https://s.click.aliexpress.com/{item_id}",
        image_url="https://ae01.alicdn.com/img.jpg",
    )


@pytest.fixture
def db(tmp_path):
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


def test_process_keyword_publishes_and_saves(monkeypatch, db):
    # Não depender do valor real de config.MAX_OFFERS_PER_KEYWORD (vem do
    # .env do projeto, hoje =1) — este teste precisa de espaço pra 2.
    monkeypatch.setattr(config, "MAX_OFFERS_PER_KEYWORD", 3)
    offers = [make_offer(item_id="1"), make_offer(item_id="2")]
    monkeypatch.setattr(orch, "discover_new_offers", lambda keyword, db: offers)
    published_calls = []
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: published_calls.append(kwargs))
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    count = orch.process_keyword("gaming mouse", db)

    assert count == 2
    assert len(published_calls) == 2
    assert published_calls[0]["discounted_price"] == 50.0
    assert db.is_duplicate("1")
    assert db.is_duplicate("2")
    assert db.get_offer("1")["image_url"] == "https://ae01.alicdn.com/img.jpg"


def test_process_keyword_publishes_highest_score_first(monkeypatch, db):
    # Ordem bruta propositalmente com a oferta de menor score primeiro —
    # discover_new_offers não garante nenhuma ordem específica.
    low_score = make_offer(item_id="low", price=200.0, discount=0.0)
    high_score = make_offer(item_id="high", price=20.0, discount=80.0)
    monkeypatch.setattr(orch, "discover_new_offers", lambda keyword, db: [low_score, high_score])
    monkeypatch.setattr(config, "MAX_OFFERS_PER_KEYWORD", 1)
    published_calls = []
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: published_calls.append(kwargs))
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    count = orch.process_keyword("gaming mouse", db)

    assert count == 1
    assert published_calls[0]["title"] == high_score.title
    assert db.is_duplicate("high")
    assert not db.is_duplicate("low")
    assert db.get_offer("high")["category"] == "setup_gamer"


def test_process_keyword_respects_max_offers_per_keyword(monkeypatch, db):
    monkeypatch.setattr(config, "MAX_OFFERS_PER_KEYWORD", 2)
    offers = [make_offer(item_id=str(i)) for i in range(5)]
    monkeypatch.setattr(orch, "discover_new_offers", lambda keyword, db: offers)
    published_calls = []
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: published_calls.append(kwargs))
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    count = orch.process_keyword("gaming mouse", db)

    assert count == 2
    assert len(published_calls) == 2
    # as 3 restantes não foram publicadas nem marcadas como vistas
    assert not db.is_duplicate("2")
    assert not db.is_duplicate("3")
    assert not db.is_duplicate("4")


def test_process_keyword_continues_after_publish_failure(monkeypatch, db):
    # Idem: precisa de espaço pra 2 publicações, independente do .env real.
    monkeypatch.setattr(config, "MAX_OFFERS_PER_KEYWORD", 3)
    offers = [make_offer(item_id="1"), make_offer(item_id="2")]
    monkeypatch.setattr(orch, "discover_new_offers", lambda keyword, db: offers)

    calls = {"count": 0}

    def publish_side_effect(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("falha simulada de rede")

    monkeypatch.setattr(orch, "publish_offer", publish_side_effect)
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    count = orch.process_keyword("gaming mouse", db)

    assert count == 1  # só a segunda oferta foi publicada com sucesso
    assert not db.is_duplicate("1")  # falhou -> não fica marcada como vista
    assert db.is_duplicate("2")


def test_process_keyword_calls_whatsapp_after_telegram_success(monkeypatch, db):
    offers = [make_offer(item_id="1")]
    monkeypatch.setattr(orch, "discover_new_offers", lambda keyword, db: offers)
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: None)
    whatsapp_calls = []
    monkeypatch.setattr(
        orch, "publish_offer_whatsapp", lambda **kwargs: whatsapp_calls.append(kwargs)
    )

    count = orch.process_keyword("gaming mouse", db)

    assert count == 1
    assert len(whatsapp_calls) == 1
    assert whatsapp_calls[0]["title"] == offers[0].title


def test_process_keyword_whatsapp_failure_does_not_block_publish(monkeypatch, db):
    # Falha no WhatsApp (canal secundário/best-effort) não pode impedir a
    # oferta de ser contabilizada como publicada nem de ser marcada como
    # vista no banco — o Telegram (canal principal) já publicou com sucesso.
    offers = [make_offer(item_id="1")]
    monkeypatch.setattr(orch, "discover_new_offers", lambda keyword, db: offers)
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: None)

    def failing_whatsapp(**kwargs):
        raise RuntimeError("automação de UI falhou")

    monkeypatch.setattr(orch, "publish_offer_whatsapp", failing_whatsapp)

    count = orch.process_keyword("gaming mouse", db)

    assert count == 1
    assert db.is_duplicate("1")


def test_process_keyword_handles_discovery_failure(monkeypatch, db):
    def raise_error(keyword, db):
        raise RuntimeError("falha na busca")

    monkeypatch.setattr(orch, "discover_new_offers", raise_error)

    count = orch.process_keyword("gaming mouse", db)
    assert count == 0


def test_run_cycle_stops_after_first_published_offer(monkeypatch, tmp_path):
    """Trava de segurança do run_cycle: encerra o ciclo assim que 1 oferta é
    publicada, então a segunda keyword nem chega a ser processada — mesmo
    que ambas tivessem ofertas novas disponíveis.
    """
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cycle.db")
    calls = []
    seen_keywords = []

    def fake_discover(keyword, db):
        seen_keywords.append(keyword)
        return [make_offer(item_id=f"{keyword}-1")]

    monkeypatch.setattr(orch, "discover_new_offers", fake_discover)
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    total = orch.run_cycle(keywords=["gaming mouse", "smart tv"])

    assert total == 1
    assert len(calls) == 1
    assert seen_keywords == ["gaming mouse"]


def test_run_cycle_deduplicates_across_keywords_in_same_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cycle2.db")
    calls = []

    def fake_discover(keyword, db):
        # mesma oferta "encontrada" por duas palavras-chave diferentes
        return [] if db.is_duplicate("shared") else [make_offer(item_id="shared")]

    monkeypatch.setattr(orch, "discover_new_offers", fake_discover)
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    total = orch.run_cycle(keywords=["gaming mouse", "mouse pad"])

    assert total == 1
    assert len(calls) == 1


def test_run_cycle_defaults_to_config_niche_keywords(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cycle3.db")
    seen_keywords = []

    def fake_discover(keyword, db):
        seen_keywords.append(keyword)
        return []

    monkeypatch.setattr(orch, "discover_new_offers", fake_discover)
    monkeypatch.setattr(orch, "publish_offer", lambda **kwargs: None)
    monkeypatch.setattr(orch, "publish_offer_whatsapp", lambda **kwargs: None)

    orch.run_cycle()

    assert seen_keywords == config.NICHE_KEYWORDS
