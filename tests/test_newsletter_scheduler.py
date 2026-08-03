from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import config
from database.db_manager import DBManager
from scripts import newsletter_scheduler as scheduler


@pytest.fixture
def db(tmp_path):
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


def _sample_offer(item_id="1"):
    return dict(
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


def test_pick_target_time_is_within_configured_window(monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_WINDOW_START_HOUR_UK", 8)
    monkeypatch.setattr(config, "NEWSLETTER_WINDOW_END_HOUR_UK", 20)

    for _ in range(50):
        target = scheduler.pick_target_time(date(2026, 8, 2))
        assert target.tzinfo is not None
        assert 8 <= target.hour < 20 or (target.hour == 20 and target.minute == 0 and target.second == 0)


def test_ensure_scheduled_send_for_today_is_idempotent(db):
    scheduler.ensure_scheduled_send_for_today(db)
    scheduler.ensure_scheduled_send_for_today(db)
    assert len(db.list_scheduled_sends()) == 1


def test_ensure_scheduled_send_for_today_respects_lead_minutes(db, monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_DRAFT_LEAD_MINUTES", 90)
    scheduler.ensure_scheduled_send_for_today(db)

    row = db.list_scheduled_sends()[0]
    target = datetime.fromisoformat(row["target_time_utc"])
    draft_time = datetime.fromisoformat(row["draft_generation_time_utc"])
    assert (target - draft_time).total_seconds() == 90 * 60


def test_process_due_drafts_skips_when_generation_time_not_reached(db):
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    sid = db.create_scheduled_send("2026-08-02", future, future)
    db.save_offer(**_sample_offer())

    with patch.object(scheduler.brevo_client, "create_campaign_draft") as create_draft:
        scheduler.process_due_drafts(db)

    create_draft.assert_not_called()
    assert db.get_scheduled_send(sid)["status"] == "pending"


def test_process_due_drafts_cancels_when_no_offers(db):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    sid = db.create_scheduled_send("2026-08-02", past, past)

    with patch.object(scheduler.brevo_client, "create_campaign_draft") as create_draft, \
         patch.object(scheduler, "notify") as notify_mock:
        scheduler.process_due_drafts(db)

    create_draft.assert_not_called()
    notify_mock.assert_not_called()
    assert db.get_scheduled_send(sid)["status"] == "cancelled"


def test_process_due_drafts_creates_draft_and_notifies(db):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    target = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sid = db.create_scheduled_send("2026-08-02", target, past)
    db.save_offer(**_sample_offer())

    with patch.object(scheduler.brevo_client, "create_campaign_draft", return_value=123) as create_draft, \
         patch.object(scheduler, "notify") as notify_mock:
        scheduler.process_due_drafts(db)

    create_draft.assert_called_once()
    notify_mock.assert_called_once()
    assert db.get_scheduled_send(sid)["status"] == "draft_created"

    drafts = db.list_pending_drafts()
    assert len(drafts) == 1
    assert drafts[0]["brevo_campaign_id"] == 123


def test_process_due_drafts_does_not_duplicate_existing_draft(db):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    sid = db.create_scheduled_send("2026-08-02", past, past)
    db.save_offer(**_sample_offer())
    db.create_email_draft(sid, "<html></html>", ["1"], brevo_campaign_id=1)

    with patch.object(scheduler.brevo_client, "create_campaign_draft") as create_draft:
        scheduler.process_due_drafts(db)

    create_draft.assert_not_called()


def test_sync_subscribers_upserts_from_brevo_contacts(db):
    contacts = [
        {"email": "active@x.com", "id": 1, "emailBlacklisted": False, "attributes": {"CONSENT_TIMESTAMP": "t1"}},
        {"email": "unsub@x.com", "id": 2, "emailBlacklisted": True, "attributes": {}},
    ]
    with patch.object(scheduler.brevo_client, "list_list_contacts", return_value=contacts):
        scheduler.sync_subscribers(db)

    assert db.count_active_subscribers() == 1
    assert db.list_active_subscribers()[0]["email"] == "active@x.com"


def test_sync_subscribers_falls_back_to_created_at_when_no_consent_timestamp(db):
    # Contatos criados antes do atributo CONSENT_TIMESTAMP existir (ou por
    # outro caminho que não seja o formulário) não têm esse atributo —
    # createdAt (sempre presente, gerado pelo próprio Brevo) é o fallback.
    contacts = [
        {"email": "old@x.com", "id": 1, "emailBlacklisted": False, "createdAt": "2026-01-01T00:00:00+00:00", "attributes": {}},
    ]
    with patch.object(scheduler.brevo_client, "list_list_contacts", return_value=contacts):
        scheduler.sync_subscribers(db)

    subscriber = db.list_active_subscribers()[0]
    assert subscriber["consented_at"] == "2026-01-01T00:00:00+00:00"


def test_sync_subscribers_prefers_consent_timestamp_over_created_at(db):
    contacts = [
        {
            "email": "new@x.com", "id": 1, "emailBlacklisted": False,
            "createdAt": "2026-01-01T00:00:00+00:00",
            "attributes": {"CONSENT_TIMESTAMP": "2026-02-02T00:00:00+00:00"},
        },
    ]
    with patch.object(scheduler.brevo_client, "list_list_contacts", return_value=contacts):
        scheduler.sync_subscribers(db)

    subscriber = db.list_active_subscribers()[0]
    assert subscriber["consented_at"] == "2026-02-02T00:00:00+00:00"


def test_sync_subscribers_handles_brevo_failure_gracefully(db):
    with patch.object(scheduler.brevo_client, "list_list_contacts", side_effect=RuntimeError("boom")):
        scheduler.sync_subscribers(db)  # não deve levantar
