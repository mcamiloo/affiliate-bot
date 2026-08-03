from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import config
from database.db_manager import DBManager
from scripts import approval_panel


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    approval_panel.app.config.update(TESTING=True)
    return approval_panel.app.test_client()


def _create_draft(target_offset: timedelta, campaign_id: int = 999) -> int:
    target = (datetime.now(timezone.utc) + target_offset).isoformat()
    with DBManager() as db:
        sid = db.create_scheduled_send("2026-08-02", target, target)
        return db.create_email_draft(sid, "<html>hi {{ unsubscribe }}</html>", ["1"], campaign_id)


def test_queue_lists_pending_drafts(client):
    _create_draft(timedelta(hours=2))
    response = client.get("/queue")
    assert response.status_code == 200
    assert b"campaign_id 999" in response.data


def test_preview_returns_raw_html(client):
    draft_id = _create_draft(timedelta(hours=2))
    response = client.get(f"/queue/{draft_id}/preview")
    assert response.status_code == 200
    assert b"unsubscribe" in response.data


def test_preview_404_for_missing_draft(client):
    response = client.get("/queue/999/preview")
    assert response.status_code == 404


def test_approve_before_target_time_schedules_campaign(client):
    draft_id = _create_draft(timedelta(hours=2))

    with patch.object(approval_panel.brevo_client, "schedule_campaign") as schedule_mock, \
         patch.object(approval_panel.brevo_client, "send_campaign_now") as send_mock:
        response = client.post(f"/queue/{draft_id}/approve")

    assert response.status_code == 302
    schedule_mock.assert_called_once()
    send_mock.assert_not_called()

    with DBManager() as db:
        assert db.get_email_draft(draft_id)["status"] == "approved"


def test_approve_after_target_time_sends_immediately(client):
    draft_id = _create_draft(timedelta(minutes=-5))

    with patch.object(approval_panel.brevo_client, "schedule_campaign") as schedule_mock, \
         patch.object(approval_panel.brevo_client, "send_campaign_now") as send_mock:
        response = client.post(f"/queue/{draft_id}/approve")

    assert response.status_code == 302
    send_mock.assert_called_once()
    schedule_mock.assert_not_called()

    with DBManager() as db:
        assert db.get_email_draft(draft_id)["status"] == "sent"


def test_approve_returns_502_on_brevo_failure(client):
    draft_id = _create_draft(timedelta(hours=2))

    with patch.object(approval_panel.brevo_client, "schedule_campaign", side_effect=RuntimeError("boom")):
        response = client.post(f"/queue/{draft_id}/approve")

    assert response.status_code == 502
    with DBManager() as db:
        assert db.get_email_draft(draft_id)["status"] == "pending_approval"


def test_reject_cancels_campaign_and_marks_rejected(client):
    draft_id = _create_draft(timedelta(hours=2))

    with patch.object(approval_panel.brevo_client, "delete_campaign") as delete_mock:
        response = client.post(f"/queue/{draft_id}/reject")

    assert response.status_code == 302
    delete_mock.assert_called_once_with(999)
    with DBManager() as db:
        assert db.get_email_draft(draft_id)["status"] == "rejected"


def test_create_schedule_creates_row(client):
    response = client.post("/schedule/create", data={"send_date": "2026-08-05", "local_time": "14:30"})
    assert response.status_code == 302

    with DBManager() as db:
        row = db.get_scheduled_send_by_date("2026-08-05")
    assert row is not None


def test_create_schedule_is_idempotent_per_date(client):
    client.post("/schedule/create", data={"send_date": "2026-08-05", "local_time": "14:30"})
    client.post("/schedule/create", data={"send_date": "2026-08-05", "local_time": "09:00"})

    with DBManager() as db:
        assert len(db.list_scheduled_sends()) == 1


def test_update_schedule_recomputes_draft_lead_time(client):
    client.post("/schedule/create", data={"send_date": "2026-08-05", "local_time": "14:30"})
    with DBManager() as db:
        row_id = db.list_scheduled_sends()[0]["id"]

    client.post(f"/schedule/{row_id}/update", data={"local_time": "09:15"})

    with DBManager() as db:
        row = db.get_scheduled_send(row_id)
    target = datetime.fromisoformat(row["target_time_utc"])
    draft_time = datetime.fromisoformat(row["draft_generation_time_utc"])
    assert (target - draft_time).total_seconds() == config.NEWSLETTER_DRAFT_LEAD_MINUTES * 60


def test_delete_schedule_cancels_pending_draft_campaign(client):
    draft_id = _create_draft(timedelta(hours=2))
    with DBManager() as db:
        scheduled_send_id = db.get_email_draft(draft_id)["scheduled_send_id"]

    with patch.object(approval_panel.brevo_client, "delete_campaign") as delete_mock:
        response = client.post(f"/schedule/{scheduled_send_id}/delete")

    assert response.status_code == 302
    delete_mock.assert_called_once_with(999)
    with DBManager() as db:
        assert db.get_scheduled_send(scheduled_send_id) is None
