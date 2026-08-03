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


def test_list_offers_by_score_since_hours_excludes_old_offers(db):
    db.save_offer(**_sample_offer(item_id="RECENT"))
    db.save_offer(**_sample_offer(item_id="OLD"))
    db._conn.execute(
        "UPDATE posted_offers SET posted_at = datetime('now', '-72 hours') WHERE item_id = 'OLD';"
    )
    db._conn.commit()

    recent_ids = [row["item_id"] for row in db.list_offers_by_score(limit=10, since_hours=48)]
    assert recent_ids == ["RECENT"]

    all_ids = [row["item_id"] for row in db.list_offers_by_score(limit=10)]
    assert set(all_ids) == {"RECENT", "OLD"}


# --- subscribers ------------------------------------------------------------


def test_upsert_subscriber_inserts_new(db):
    db.upsert_subscriber("a@b.com", brevo_contact_id=1, status="active", consented_at="2026-08-01T00:00:00Z")
    subs = db.list_active_subscribers()
    assert len(subs) == 1
    assert subs[0]["email"] == "a@b.com"
    assert subs[0]["consented_at"] == "2026-08-01T00:00:00Z"


def test_upsert_subscriber_updates_status_without_losing_consented_at(db):
    db.upsert_subscriber("a@b.com", brevo_contact_id=1, status="active", consented_at="2026-08-01T00:00:00Z")
    # Um pull subsequente do Brevo pode não trazer o atributo de novo —
    # não pode apagar o que já tínhamos gravado.
    db.upsert_subscriber("a@b.com", brevo_contact_id=1, status="unsubscribed", consented_at=None)

    subs = db.list_active_subscribers()
    assert subs == []
    assert db.count_active_subscribers() == 0


def test_count_active_subscribers_ignores_unsubscribed(db):
    db.upsert_subscriber("a@b.com", brevo_contact_id=1, status="active")
    db.upsert_subscriber("b@b.com", brevo_contact_id=2, status="unsubscribed")
    assert db.count_active_subscribers() == 1


# --- scheduled_sends ---------------------------------------------------------


def test_create_and_get_scheduled_send(db):
    sid = db.create_scheduled_send("2026-08-02", "2026-08-02T18:00:00+00:00", "2026-08-02T17:00:00+00:00")
    row = db.get_scheduled_send(sid)
    assert row["send_date"] == "2026-08-02"
    assert row["status"] == "pending"
    assert db.get_scheduled_send_by_date("2026-08-02")["id"] == sid


def test_update_scheduled_send_changes_only_given_fields(db):
    sid = db.create_scheduled_send("2026-08-02", "2026-08-02T18:00:00+00:00", "2026-08-02T17:00:00+00:00")
    db.update_scheduled_send(sid, status="draft_created")
    row = db.get_scheduled_send(sid)
    assert row["status"] == "draft_created"
    assert row["target_time_utc"] == "2026-08-02T18:00:00+00:00"


def test_delete_scheduled_send_cascades_drafts(db):
    sid = db.create_scheduled_send("2026-08-02", "2026-08-02T18:00:00+00:00", "2026-08-02T17:00:00+00:00")
    db.create_email_draft(sid, "<html></html>", ["1"], brevo_campaign_id=1)
    db.delete_scheduled_send(sid)
    assert db.get_scheduled_send(sid) is None
    assert db.get_draft_by_scheduled_send(sid) is None


# --- email_drafts -------------------------------------------------------------


def test_create_and_list_pending_drafts(db):
    sid = db.create_scheduled_send("2026-08-02", "2026-08-02T18:00:00+00:00", "2026-08-02T17:00:00+00:00")
    did = db.create_email_draft(sid, "<html></html>", ["1", "2"], brevo_campaign_id=42)

    pending = db.list_pending_drafts()
    assert len(pending) == 1
    assert pending[0]["id"] == did
    assert pending[0]["send_date"] == "2026-08-02"


def test_update_draft_status_removes_it_from_pending(db):
    sid = db.create_scheduled_send("2026-08-02", "2026-08-02T18:00:00+00:00", "2026-08-02T17:00:00+00:00")
    did = db.create_email_draft(sid, "<html></html>", ["1"], brevo_campaign_id=42)

    db.update_draft_status(did, "approved")

    assert db.list_pending_drafts() == []
    draft = db.get_email_draft(did)
    assert draft["status"] == "approved"
    assert draft["decided_at"] is not None


def test_has_draft_for_scheduled_send(db):
    sid = db.create_scheduled_send("2026-08-02", "2026-08-02T18:00:00+00:00", "2026-08-02T17:00:00+00:00")
    assert db.has_draft_for_scheduled_send(sid) is False
    db.create_email_draft(sid, "<html></html>", ["1"], brevo_campaign_id=42)
    assert db.has_draft_for_scheduled_send(sid) is True


# --- offers do painel (Home / Ofertas publicadas) --------------------------


def test_count_offers_since_counts_only_recent(db):
    db.save_offer(**_sample_offer(item_id="RECENT"))
    db.save_offer(**_sample_offer(item_id="OLD"))
    db._conn.execute(
        "UPDATE posted_offers SET posted_at = datetime('now', '-72 hours') WHERE item_id = 'OLD';"
    )
    db._conn.commit()

    assert db.count_offers_since(24) == 1
    assert db.count_offers_since(24 * 7) == 2


def test_list_recent_offers_orders_newest_first_and_includes_hidden(db):
    db.save_offer(**_sample_offer(item_id="OLDER"))
    db.save_offer(**_sample_offer(item_id="NEWER"))
    db._conn.execute(
        "UPDATE posted_offers SET posted_at = datetime('now', '-1 hour') WHERE item_id = 'OLDER';"
    )
    db._conn.commit()
    db.hide_offer("OLDER")

    rows = db.list_recent_offers()
    assert [row["item_id"] for row in rows] == ["NEWER", "OLDER"]
    assert next(row for row in rows if row["item_id"] == "OLDER")["hidden"] == 1
    assert next(row for row in rows if row["item_id"] == "NEWER")["hidden"] == 0


def test_hide_offer_removes_it_from_score_view_but_keeps_dedupe(db):
    db.save_offer(**_sample_offer(item_id="BAD1"))
    db.hide_offer("BAD1")

    assert db.list_offers_by_score(limit=10) == []
    assert db.is_duplicate("BAD1") is True
    assert db.get_offer("BAD1") is not None


# --- email_drafts avulsos (compose manual) ----------------------------------


def test_create_adhoc_email_draft_has_no_scheduled_send(db):
    draft_id = db.create_adhoc_email_draft("Assunto", "<p>oi</p>", 42)
    draft = db.get_email_draft(draft_id)

    assert draft["scheduled_send_id"] is None
    assert draft["subject"] == "Assunto"
    assert draft["send_date"] is None
    assert draft["target_time_utc"] is None


def test_list_pending_drafts_includes_adhoc_alongside_scheduled(db):
    scheduled_id = db.create_scheduled_send("2026-08-05", "2026-08-05T18:00:00+00:00", "2026-08-05T17:00:00+00:00")
    db.create_email_draft(scheduled_id, "<html></html>", ["1"], 1)
    db.create_adhoc_email_draft("Avulso", "<p>oi</p>", 2)

    drafts = db.list_pending_drafts()
    assert len(drafts) == 2


def test_email_drafts_migration_is_idempotent(tmp_path):
    # Reabrir o mesmo banco (roda _run_migrations de novo) não deve
    # duplicar colunas nem apagar dados.
    db_path = tmp_path / "migrate.db"
    first = DBManager(db_path=db_path)
    draft_id = first.create_adhoc_email_draft("Assunto", "<p>oi</p>", None)
    first.close()

    second = DBManager(db_path=db_path)
    draft = second.get_email_draft(draft_id)
    second.close()

    assert draft["subject"] == "Assunto"


# --- email_events (webhook do Brevo) ----------------------------------------


def test_record_and_count_email_events(db):
    db.record_email_event(42, "a@b.com", "delivered", "2026-08-03 10:00:00")
    db.record_email_event(42, "a@b.com", "opened", "2026-08-03 10:05:00")
    db.record_email_event(42, "c@d.com", "delivered", "2026-08-03 10:00:00")

    counts = db.campaign_event_counts(42)
    assert counts == {"delivered": 2, "opened": 1}


def test_campaign_event_counts_counts_unique_emails_not_events(db):
    # Duas aberturas da MESMA pessoa contam uma vez só.
    db.record_email_event(42, "a@b.com", "opened", "2026-08-03 10:00:00")
    db.record_email_event(42, "a@b.com", "opened", "2026-08-03 10:05:00")

    assert db.campaign_event_counts(42) == {"opened": 1}


def test_list_campaign_stats_only_includes_sent_campaigns(db):
    db.create_adhoc_email_draft("Sem campanha", "<p>oi</p>", None)
    db.create_adhoc_email_draft("Com campanha", "<p>oi</p>", 7)
    db.record_email_event(7, "a@b.com", "delivered", "2026-08-03 10:00:00")

    stats = db.list_campaign_stats()

    assert len(stats) == 1
    assert stats[0]["brevo_campaign_id"] == 7
    assert stats[0]["events"] == {"delivered": 1}


def test_get_campaign_summary_returns_matching_campaign(db):
    db.create_adhoc_email_draft("Alvo", "<p>oi</p>", 7)
    db.create_adhoc_email_draft("Outra", "<p>oi</p>", 8)

    summary = db.get_campaign_summary(7)

    assert summary["subject"] == "Alvo"


def test_get_campaign_summary_returns_none_for_missing_campaign(db):
    assert db.get_campaign_summary(999) is None


def test_list_campaign_recipients_shows_latest_status_per_email(db):
    db.record_email_event(42, "a@b.com", "delivered", "2026-08-03 10:00:00")
    db.record_email_event(42, "a@b.com", "opened", "2026-08-03 10:05:00")
    db.record_email_event(42, "c@d.com", "delivered", "2026-08-03 10:00:00")

    recipients = db.list_campaign_recipients(42)

    by_email = {r["email"]: r["event"] for r in recipients}
    assert by_email == {"a@b.com": "opened", "c@d.com": "delivered"}


def test_list_campaign_recipients_scoped_to_campaign(db):
    db.record_email_event(1, "a@b.com", "delivered", "2026-08-03 10:00:00")
    db.record_email_event(2, "a@b.com", "delivered", "2026-08-03 10:00:00")

    assert len(db.list_campaign_recipients(1)) == 1


def test_list_recipient_events_returns_full_history_in_order(db):
    db.record_email_event(42, "a@b.com", "opened", "2026-08-03 10:05:00")
    db.record_email_event(42, "a@b.com", "delivered", "2026-08-03 10:00:00")

    events = db.list_recipient_events(42, "a@b.com")

    assert [e["event"] for e in events] == ["delivered", "opened"]


def test_list_recipient_events_scoped_to_recipient(db):
    db.record_email_event(42, "a@b.com", "delivered", "2026-08-03 10:00:00")
    db.record_email_event(42, "c@d.com", "delivered", "2026-08-03 10:00:00")

    assert len(db.list_recipient_events(42, "a@b.com")) == 1


# --- subscribers (busca + descadastro local) --------------------------------


def test_list_subscribers_includes_unsubscribed(db):
    db.upsert_subscriber(email="active@b.com", brevo_contact_id=1, status="active")
    db.upsert_subscriber(email="gone@b.com", brevo_contact_id=2, status="unsubscribed")

    emails = {row["email"] for row in db.list_subscribers()}
    assert emails == {"active@b.com", "gone@b.com"}


def test_list_subscribers_search_filters(db):
    db.upsert_subscriber(email="findme@b.com", brevo_contact_id=1, status="active")
    db.upsert_subscriber(email="other@b.com", brevo_contact_id=2, status="active")

    results = db.list_subscribers(search="findme")
    assert [row["email"] for row in results] == ["findme@b.com"]


def test_mark_subscriber_unsubscribed(db):
    db.upsert_subscriber(email="a@b.com", brevo_contact_id=1, status="active")
    db.mark_subscriber_unsubscribed("a@b.com")

    assert db.list_subscribers()[0]["status"] == "unsubscribed"
