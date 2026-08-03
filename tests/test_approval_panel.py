from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

import config
from database.db_manager import DBManager
from scripts import approval_panel


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    approval_panel.app.config.update(TESTING=True)
    test_client = approval_panel.app.test_client()

    # Seed já com must_change_password=False — os testes de negócio abaixo
    # não são sobre o fluxo de login em si (esse tem sua própria classe).
    with DBManager() as db:
        db.create_admin_user_if_absent(
            approval_panel.DEFAULT_ADMIN_USERNAME,
            generate_password_hash(approval_panel.DEFAULT_ADMIN_PASSWORD),
            must_change_password=False,
        )
    test_client.post(
        "/login",
        data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": approval_panel.DEFAULT_ADMIN_PASSWORD},
    )
    return test_client


@pytest.fixture
def anon_client(tmp_path, monkeypatch):
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


# --- login / troca de senha -------------------------------------------------


def test_queue_redirects_to_login_when_unauthenticated(anon_client):
    response = anon_client.get("/queue")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_with_wrong_password_is_rejected(anon_client):
    with DBManager() as db:
        db.create_admin_user_if_absent(
            approval_panel.DEFAULT_ADMIN_USERNAME,
            generate_password_hash(approval_panel.DEFAULT_ADMIN_PASSWORD),
            must_change_password=False,
        )
    response = anon_client.post(
        "/login", data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": "wrong"}
    )
    assert response.status_code == 401

    follow = anon_client.get("/queue")
    assert follow.status_code == 302


def test_first_login_forces_password_change(anon_client):
    with DBManager() as db:
        db.create_admin_user_if_absent(
            approval_panel.DEFAULT_ADMIN_USERNAME,
            generate_password_hash(approval_panel.DEFAULT_ADMIN_PASSWORD),
        )
    login_response = anon_client.post(
        "/login",
        data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": approval_panel.DEFAULT_ADMIN_PASSWORD},
    )
    assert login_response.status_code == 302
    assert "/change-password" in login_response.headers["Location"]

    # Tentar pular direto pra /queue com a troca ainda pendente é barrado.
    blocked = anon_client.get("/queue")
    assert blocked.status_code == 302
    assert "/change-password" in blocked.headers["Location"]


def test_change_password_rejects_short_password(anon_client):
    with DBManager() as db:
        db.create_admin_user_if_absent(
            approval_panel.DEFAULT_ADMIN_USERNAME, generate_password_hash(approval_panel.DEFAULT_ADMIN_PASSWORD)
        )
    anon_client.post(
        "/login",
        data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": approval_panel.DEFAULT_ADMIN_PASSWORD},
    )
    response = anon_client.post("/change-password", data={"new_password": "short", "confirm_password": "short"})
    assert response.status_code == 400


def test_change_password_rejects_mismatch(anon_client):
    with DBManager() as db:
        db.create_admin_user_if_absent(
            approval_panel.DEFAULT_ADMIN_USERNAME, generate_password_hash(approval_panel.DEFAULT_ADMIN_PASSWORD)
        )
    anon_client.post(
        "/login",
        data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": approval_panel.DEFAULT_ADMIN_PASSWORD},
    )
    response = anon_client.post(
        "/change-password", data={"new_password": "longenough1", "confirm_password": "longenough2"}
    )
    assert response.status_code == 400


def test_change_password_success_unlocks_queue_and_new_password_works(anon_client):
    with DBManager() as db:
        db.create_admin_user_if_absent(
            approval_panel.DEFAULT_ADMIN_USERNAME, generate_password_hash(approval_panel.DEFAULT_ADMIN_PASSWORD)
        )
    anon_client.post(
        "/login",
        data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": approval_panel.DEFAULT_ADMIN_PASSWORD},
    )
    response = anon_client.post(
        "/change-password", data={"new_password": "a-new-strong-pw", "confirm_password": "a-new-strong-pw"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")

    assert anon_client.get("/queue").status_code == 200

    anon_client.post("/logout")
    relogin = anon_client.post(
        "/login", data={"username": approval_panel.DEFAULT_ADMIN_USERNAME, "password": "a-new-strong-pw"}
    )
    assert relogin.status_code == 302
    assert relogin.headers["Location"].endswith("/home")


def test_logout_requires_login_again(client):
    assert client.get("/queue").status_code == 200
    client.post("/logout")
    response = client.get("/queue")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- home ---------------------------------------------------------------


def _save_offer(item_id: str, **overrides) -> None:
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
    with DBManager() as db:
        db.save_offer(**defaults)


def test_home_renders_service_status(client):
    with patch.object(approval_panel, "job_is_loaded", return_value=True), \
         patch.object(approval_panel, "last_successful_cycle", return_value=(datetime.now(), 3)), \
         patch.object(approval_panel, "_service_running", return_value=False), \
         patch.object(approval_panel, "_whatsapp_app_running", return_value=True):
        response = client.get("/home")

    assert response.status_code == 200
    assert b"rodando" in response.data
    assert b"parado" in response.data


def test_home_shows_offer_counts(client):
    _save_offer("H1")
    _save_offer("H2")

    with patch.object(approval_panel, "job_is_loaded", return_value=True), \
         patch.object(approval_panel, "last_successful_cycle", return_value=None), \
         patch.object(approval_panel, "_service_running", return_value=True), \
         patch.object(approval_panel, "_whatsapp_app_running", return_value=False):
        response = client.get("/home")

    assert response.status_code == 200
    assert b"2" in response.data  # ofertas hoje


def test_home_shows_latest_offers_excluding_hidden(client):
    _save_offer("VISIBLE", title="Visible Offer")
    _save_offer("HIDDEN", title="Hidden Offer")
    with DBManager() as db:
        db.hide_offer("HIDDEN")

    with patch.object(approval_panel, "job_is_loaded", return_value=True), \
         patch.object(approval_panel, "last_successful_cycle", return_value=None), \
         patch.object(approval_panel, "_service_running", return_value=True), \
         patch.object(approval_panel, "_whatsapp_app_running", return_value=False):
        response = client.get("/home")

    assert b"Visible Offer" in response.data
    assert b"Hidden Offer" not in response.data


def test_home_requires_login(anon_client):
    response = anon_client.get("/home")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- ofertas --------------------------------------------------------------


def test_offers_lists_recent_offers(client):
    _save_offer("O1", title="Wireless Mouse")
    response = client.get("/offers")
    assert response.status_code == 200
    assert b"Wireless Mouse" in response.data


def test_hide_offer_marks_hidden_and_removes_from_score_view(client):
    _save_offer("O2")
    response = client.post("/offers/O2/hide")
    assert response.status_code == 302

    with DBManager() as db:
        offer = db.get_offer("O2")
        assert offer["hidden"] == 1
        assert db.list_offers_by_score(limit=10) == []
        # dedupe continua reconhecendo o item mesmo oculto
        assert db.is_duplicate("O2") is True


def test_offers_requires_login(anon_client):
    response = anon_client.get("/offers")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- rodar ciclo agora -----------------------------------------------------


def test_run_cycle_now_spawns_subprocess(client):
    with patch.object(approval_panel.subprocess, "Popen") as popen_mock:
        response = client.post("/cycle/run")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")
    popen_mock.assert_called_once()
    args = popen_mock.call_args[0][0]
    assert args[0] == approval_panel.sys.executable
    assert str(approval_panel.RUN_CYCLE_SCRIPT) in args


def test_run_cycle_now_requires_login(anon_client):
    response = anon_client.post("/cycle/run")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- API do widget (Mac/iPad) -----------------------------------------------


def test_api_widget_snapshot_rejects_missing_token(anon_client):
    response = anon_client.get("/api/widget-snapshot")
    assert response.status_code == 401


def test_api_widget_snapshot_rejects_wrong_token(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "WIDGET_API_TOKEN", "right-token")
    response = anon_client.get("/api/widget-snapshot", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_api_widget_snapshot_503_when_file_missing(anon_client, monkeypatch, tmp_path):
    monkeypatch.setattr(approval_panel.config, "WIDGET_API_TOKEN", "right-token")
    monkeypatch.setattr(approval_panel.config, "WIDGET_SNAPSHOT_PATH", tmp_path / "missing.json")
    response = anon_client.get("/api/widget-snapshot", headers={"Authorization": "Bearer right-token"})
    assert response.status_code == 503


def test_api_widget_snapshot_returns_file_contents(anon_client, monkeypatch, tmp_path):
    monkeypatch.setattr(approval_panel.config, "WIDGET_API_TOKEN", "right-token")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text('{"offers_today": 3}')
    monkeypatch.setattr(approval_panel.config, "WIDGET_SNAPSHOT_PATH", snapshot_path)

    response = anon_client.get("/api/widget-snapshot", headers={"Authorization": "Bearer right-token"})

    assert response.status_code == 200
    assert response.get_json() == {"offers_today": 3}


def test_api_run_cycle_now_rejects_missing_token(anon_client):
    response = anon_client.post("/api/cycle/run")
    assert response.status_code == 401


def test_api_run_cycle_now_spawns_subprocess_with_valid_token(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "WIDGET_API_TOKEN", "right-token")
    with patch.object(approval_panel.subprocess, "Popen") as popen_mock:
        response = anon_client.post("/api/cycle/run", headers={"Authorization": "Bearer right-token"})

    assert response.status_code == 200
    popen_mock.assert_called_once()


# --- descadastro próprio (HMAC) --------------------------------------------


def test_unsubscribe_with_valid_token_marks_locally_and_calls_brevo(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "NEWSLETTER_UNSUB_SECRET", "test-secret")
    with DBManager() as db:
        db.upsert_subscriber(email="a@b.com", brevo_contact_id=1, status="active")

    from utils.unsubscribe import compute_unsub_token

    token = compute_unsub_token("a@b.com")

    with patch.object(approval_panel.brevo_client, "unsubscribe_contact") as unsub_mock:
        response = anon_client.get(f"/newsletter/unsubscribe?email=a@b.com&token={token}")

    assert response.status_code == 200
    unsub_mock.assert_called_once_with("a@b.com")
    with DBManager() as db:
        assert db.list_subscribers()[0]["status"] == "unsubscribed"


def test_unsubscribe_with_invalid_token_rejected(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "NEWSLETTER_UNSUB_SECRET", "test-secret")
    with DBManager() as db:
        db.upsert_subscriber(email="a@b.com", brevo_contact_id=1, status="active")

    response = anon_client.get("/newsletter/unsubscribe?email=a@b.com&token=wrong")

    assert response.status_code == 403
    with DBManager() as db:
        assert db.list_subscribers()[0]["status"] == "active"


def test_unsubscribe_does_not_require_login(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "NEWSLETTER_UNSUB_SECRET", "test-secret")
    response = anon_client.get("/newsletter/unsubscribe?email=a@b.com&token=wrong")
    assert response.status_code == 403  # não redirecionou pro /login


# --- webhook de marketing do Brevo ------------------------------------------


def test_brevo_webhook_rejects_missing_secret(anon_client):
    response = anon_client.post("/api/brevo-webhook", json={"email": "a@b.com", "event": "opened"})
    assert response.status_code == 401


def test_brevo_webhook_rejects_wrong_secret(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "BREVO_WEBHOOK_SECRET", "right-secret")
    response = anon_client.post(
        "/api/brevo-webhook",
        json={"email": "a@b.com", "event": "opened"},
        headers={"X-Brevo-Webhook-Secret": "wrong-secret"},
    )
    assert response.status_code == 401


def test_brevo_webhook_rejects_right_secret_wrong_ip(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "BREVO_WEBHOOK_SECRET", "right-secret")
    response = anon_client.post(
        "/api/brevo-webhook",
        json={"email": "a@b.com", "event": "opened", "camp_id": 1, "date_event": "2026-08-03 10:00:00"},
        headers={"X-Brevo-Webhook-Secret": "right-secret"},
        environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
    )
    assert response.status_code == 401


def test_brevo_webhook_accepts_right_secret_and_ip_in_range(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "BREVO_WEBHOOK_SECRET", "right-secret")
    response = anon_client.post(
        "/api/brevo-webhook",
        json={"email": "a@b.com", "event": "opened", "camp_id": 1, "date_event": "2026-08-03 10:00:00"},
        headers={"X-Brevo-Webhook-Secret": "right-secret"},
        environ_overrides={"REMOTE_ADDR": "1.179.112.5"},
    )
    assert response.status_code == 200
    with DBManager() as db:
        assert db.campaign_event_counts(1) == {"opened": 1}


def test_brevo_webhook_rejects_incomplete_payload(anon_client, monkeypatch):
    monkeypatch.setattr(approval_panel.config, "BREVO_WEBHOOK_SECRET", "right-secret")
    response = anon_client.post(
        "/api/brevo-webhook",
        json={"email": "a@b.com"},
        headers={"X-Brevo-Webhook-Secret": "right-secret"},
        environ_overrides={"REMOTE_ADDR": "1.179.112.5"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "raw_event, normalized",
    [
        ("hard_bounce", "hardBounce"),
        ("soft_bounce", "softBounce"),
        ("soft_bounced", "softBounce"),
        ("unsubscribe", "unsubscribed"),
        ("delivered", "delivered"),  # já igual nas duas convenções, não mexe
    ],
)
def test_brevo_webhook_normalizes_event_name(anon_client, monkeypatch, raw_event, normalized):
    # A documentação do Brevo é inconsistente sobre camelCase vs
    # snake_case no payload real — normaliza pra não depender de acertar
    # qual convenção está em vigor (ver _BREVO_EVENT_ALIASES).
    monkeypatch.setattr(approval_panel.config, "BREVO_WEBHOOK_SECRET", "right-secret")
    response = anon_client.post(
        "/api/brevo-webhook",
        json={"email": "a@b.com", "event": raw_event, "camp_id": 1, "date_event": "2026-08-03 10:00:00"},
        headers={"X-Brevo-Webhook-Secret": "right-secret"},
        environ_overrides={"REMOTE_ADDR": "1.179.112.5"},
    )
    assert response.status_code == 200
    with DBManager() as db:
        assert db.campaign_event_counts(1) == {normalized: 1}


# --- compose manual + mandar teste ------------------------------------------


def test_compose_get_requires_login(anon_client):
    response = anon_client.get("/newsletter/compose")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_compose_post_creates_adhoc_draft_in_queue(client):
    with patch.object(approval_panel.brevo_client, "create_campaign_draft", return_value=555) as create_mock:
        response = client.post(
            "/newsletter/compose",
            data={"subject": "Assunto de teste", "html_content": "<p>oi</p>"},
        )

    assert response.status_code == 302
    create_mock.assert_called_once_with("Assunto de teste", "<p>oi</p>")

    with DBManager() as db:
        drafts = db.list_pending_drafts()
    assert len(drafts) == 1
    assert drafts[0]["subject"] == "Assunto de teste"
    assert drafts[0]["scheduled_send_id"] is None
    assert drafts[0]["brevo_campaign_id"] == 555


def test_compose_post_with_uploaded_file_uses_file_contents(client):
    import io

    with patch.object(approval_panel.brevo_client, "create_campaign_draft", return_value=777) as create_mock:
        response = client.post(
            "/newsletter/compose",
            data={
                "subject": "Assunto via arquivo",
                "html_content": "",
                "html_file": (io.BytesIO(b"<p>conteudo do arquivo</p>"), "email.html"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    create_mock.assert_called_once_with("Assunto via arquivo", "<p>conteudo do arquivo</p>")


def test_compose_post_missing_fields_shows_error(client):
    response = client.post("/newsletter/compose", data={"subject": "", "html_content": ""})
    assert response.status_code == 400
    with DBManager() as db:
        assert db.list_pending_drafts() == []


def test_send_test_draft_calls_brevo(client):
    draft_id = _create_draft(timedelta(hours=2), campaign_id=42)

    with patch.object(approval_panel.brevo_client, "send_test_email") as test_mock:
        response = client.post(f"/queue/{draft_id}/test")

    assert response.status_code == 302
    test_mock.assert_called_once_with(42, [approval_panel.config.NEWSLETTER_TEST_EMAIL])


# --- assinantes + estatísticas -----------------------------------------------


def test_subscribers_lists_all_statuses(client):
    with DBManager() as db:
        db.upsert_subscriber(email="active@b.com", brevo_contact_id=1, status="active")
        db.upsert_subscriber(email="gone@b.com", brevo_contact_id=2, status="unsubscribed")

    response = client.get("/subscribers")
    assert response.status_code == 200
    assert b"active@b.com" in response.data
    assert b"gone@b.com" in response.data


def test_subscribers_search_filters_by_email(client):
    with DBManager() as db:
        db.upsert_subscriber(email="findme@b.com", brevo_contact_id=1, status="active")
        db.upsert_subscriber(email="other@b.com", brevo_contact_id=2, status="active")

    response = client.get("/subscribers?q=findme")
    assert b"findme@b.com" in response.data
    assert b"other@b.com" not in response.data


def test_subscribers_requires_login(anon_client):
    response = anon_client.get("/subscribers")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_newsletter_stats_shows_campaign_event_counts(client):
    draft_id = _create_draft(timedelta(hours=-2), campaign_id=42)
    with DBManager() as db:
        db.update_draft_status(draft_id, "sent")
        db.record_email_event(42, "a@b.com", "delivered", "2026-08-03 10:00:00")
        db.record_email_event(42, "a@b.com", "opened", "2026-08-03 10:05:00")

    response = client.get("/newsletter/stats")
    assert response.status_code == 200
    assert b"campaign_id 42" in response.data


def test_newsletter_stats_requires_login(anon_client):
    response = anon_client.get("/newsletter/stats")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
