"""Testes do cliente Brevo — usam httpx.MockTransport pra nunca bater na
rede de verdade, só verificar que os requests são montados corretamente.
"""

import httpx
import pytest

import config
from modules import brevo_client


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=brevo_client.BASE_URL)


@pytest.fixture(autouse=True)
def brevo_config(monkeypatch):
    monkeypatch.setattr(config, "BREVO_API_KEY", "fake-key")
    monkeypatch.setattr(config, "BREVO_LIST_ID", 5)
    monkeypatch.setattr(config, "BREVO_DOI_TEMPLATE_ID", 3)
    monkeypatch.setattr(config, "BREVO_DOI_REDIRECT_URL", "https://example.com/thanks")
    monkeypatch.setattr(config, "BREVO_SENDER_NAME", "Test Sender")
    monkeypatch.setattr(config, "BREVO_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setattr(config, "NEWSLETTER_UNSUB_SECRET", "test-unsub-secret")


def test_create_doi_contact_sends_expected_payload(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(201, json={})

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.create_doi_contact("a@b.com", consent_timestamp="2026-08-02T00:00:00Z")

    assert captured["url"].endswith("/contacts/doubleOptinConfirmation")
    import json

    body = json.loads(captured["body"])
    assert body["email"] == "a@b.com"
    assert body["includeListIds"] == [5]
    assert body["templateId"] == 3
    assert body["attributes"]["CONSENT_TIMESTAMP"] == "2026-08-02T00:00:00Z"
    # Mesmo HMAC calculado por utils/unsubscribe.py — os dois lados (aqui e
    # netlify/functions/subscribe.js) têm que concordar no mesmo valor.
    from utils.unsubscribe import compute_unsub_token

    assert body["attributes"]["UNSUB_TOKEN"] == compute_unsub_token("a@b.com")


def test_create_doi_contact_raises_on_error_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    with pytest.raises(brevo_client.BrevoError):
        brevo_client.create_doi_contact("a@b.com", consent_timestamp="2026-08-02T00:00:00Z")


def test_list_list_contacts_paginates(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(dict(request.url.params).get("offset", 0))
        calls.append(offset)
        if offset == 0:
            return httpx.Response(200, json={"contacts": [{"email": f"user{i}@x.com"} for i in range(500)]})
        return httpx.Response(200, json={"contacts": [{"email": "last@x.com"}]})

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    contacts = brevo_client.list_list_contacts()

    assert len(contacts) == 501
    assert calls == [0, 500]


def test_create_campaign_draft_returns_id(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": 777})

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    campaign_id = brevo_client.create_campaign_draft("Subject", "<html></html>")
    assert campaign_id == 777


def test_delete_campaign_ignores_404(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.delete_campaign(999)  # não deve levantar


def test_schedule_campaign_sends_scheduled_at(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(204)

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.schedule_campaign(1, "2026-08-02T18:00:00+00:00")

    import json

    body = json.loads(captured["body"])
    assert body["scheduledAt"] == "2026-08-02T18:00:00+00:00"


def test_send_test_email_sends_email_to_list(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(204)

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.send_test_email(42, ["me@example.com"])

    import json

    assert captured["url"].endswith("/emailCampaigns/42/sendTest")
    assert json.loads(captured["body"])["emailTo"] == ["me@example.com"]


def test_unsubscribe_contact_blacklists_email(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(204)

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.unsubscribe_contact("a@b.com")

    import json

    assert captured["method"] == "PUT"
    assert captured["url"].endswith("/contacts/a@b.com")
    assert json.loads(captured["body"])["emailBlacklisted"] is True


def test_unsubscribe_contact_ignores_404(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.unsubscribe_contact("ghost@b.com")  # não deve levantar


def test_set_contact_attributes_sends_attributes(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(204)

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    brevo_client.set_contact_attributes("a@b.com", {"UNSUB_TOKEN": "abc123"})

    import json

    assert json.loads(captured["body"])["attributes"] == {"UNSUB_TOKEN": "abc123"}


def test_create_marketing_webhook_sends_header_secret_not_url(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(201, json={"id": 5})

    monkeypatch.setattr(brevo_client, "_client", lambda: _mock_client(handler))

    webhook_id = brevo_client.create_marketing_webhook(
        "https://example.com/api/brevo-webhook", ["delivered", "opened"], "s3cr3t", "desc"
    )

    import json

    assert webhook_id == 5
    # o segredo vai no corpo (header custom pro Brevo mandar de volta),
    # nunca embutido na URL do webhook em si.
    assert "s3cr3t" not in captured["url"]
    body = json.loads(captured["body"])
    assert body["headers"] == [{"key": "X-Brevo-Webhook-Secret", "value": "s3cr3t"}]
    assert body["type"] == "marketing"
