"""Cliente HTTP pra API do Brevo (contatos + campanhas de email).

Cobre só o que a newsletter precisa: cadastro de contato via double
opt-in, leitura da lista de contatos (pra sincronizar a tabela local
`subscribers`) e o ciclo de vida de uma campanha (criar como rascunho,
agendar/enviar, cancelar). Nenhuma chamada aqui envia email de fato sem
que o resto do pipeline (aprovação manual no painel) já tenha decidido
fazer isso — este módulo só fala com o Brevo.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

import config
from utils.retry import with_retry
from utils.unsubscribe import compute_unsub_token

logger = logging.getLogger(__name__)

BASE_URL = "https://api.brevo.com/v3"


class BrevoError(RuntimeError):
    """Erro de API do Brevo (HTTP 4xx/5xx) com o corpo da resposta anexado."""


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={
            "api-key": config.BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30.0,
    )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise BrevoError(f"Brevo {response.status_code}: {response.text}")


@with_retry(exceptions=(httpx.TransportError,))
def create_doi_contact(
    email: str,
    consent_timestamp: str,
    redirect_url: Optional[str] = None,
) -> None:
    """Cadastra um email via fluxo de double opt-in.

    O contato só entra de fato na lista depois de clicar no link do
    email de confirmação que o Brevo dispara automaticamente — até lá
    ele não recebe a newsletter. `consent_timestamp` é gravado como
    atributo do contato pra servir de prova de quando o formulário foi
    submetido (auditoria de consentimento, UK GDPR/PECR).
    """
    with _client() as client:
        response = client.post(
            "/contacts/doubleOptinConfirmation",
            json={
                "email": email,
                "includeListIds": [config.BREVO_LIST_ID],
                "templateId": config.BREVO_DOI_TEMPLATE_ID,
                "redirectionUrl": redirect_url or config.BREVO_DOI_REDIRECT_URL,
                "attributes": {
                    "CONSENT_TIMESTAMP": consent_timestamp,
                    # Mesmo HMAC que netlify/functions/subscribe.js calcula (o
                    # cadastro de produção passa por lá, não por esta função —
                    # ver utils/unsubscribe.py) — mantido aqui só pra quem
                    # eventualmente cadastrar via este client Python direto.
                    "UNSUB_TOKEN": compute_unsub_token(email),
                },
            },
        )
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def list_list_contacts(list_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Retorna todos os contatos da lista configurada, paginando.

    Usado pelo agendador pra sincronizar a tabela local `subscribers` —
    o Brevo é a fonte de verdade sobre quem está ativo/descadastrado.
    """
    list_id = list_id if list_id is not None else config.BREVO_LIST_ID
    contacts: list[dict[str, Any]] = []
    limit, offset = 500, 0

    with _client() as client:
        while True:
            response = client.get(
                f"/contacts/lists/{list_id}/contacts",
                params={"limit": limit, "offset": offset},
            )
            _raise_for_status(response)
            batch = response.json().get("contacts", [])
            contacts.extend(batch)
            if len(batch) < limit:
                break
            offset += limit

    return contacts


@with_retry(exceptions=(httpx.TransportError,))
def create_campaign_draft(subject: str, html_content: str) -> int:
    """Cria uma campanha em estado de rascunho (não agenda, não envia).

    Retorna o campaign_id do Brevo, guardado localmente em email_drafts
    até a aprovação manual decidir o que fazer com ela.
    """
    with _client() as client:
        response = client.post(
            "/emailCampaigns",
            json={
                "name": f"Newsletter {subject}",
                "subject": subject,
                "sender": {"name": config.BREVO_SENDER_NAME, "email": config.BREVO_SENDER_EMAIL},
                "type": "classic",
                "htmlContent": html_content,
                "recipients": {"listIds": [config.BREVO_LIST_ID]},
            },
        )
        _raise_for_status(response)
        return response.json()["id"]


@with_retry(exceptions=(httpx.TransportError,))
def schedule_campaign(campaign_id: int, scheduled_at_iso: str) -> None:
    """Agenda uma campanha rascunho pro horário-alvo (ISO 8601 com timezone)."""
    with _client() as client:
        response = client.put(
            f"/emailCampaigns/{campaign_id}",
            json={"scheduledAt": scheduled_at_iso},
        )
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def send_campaign_now(campaign_id: int) -> None:
    """Dispara o envio imediato de uma campanha (usado quando a aprovação
    chega depois do horário-alvo já ter passado)."""
    with _client() as client:
        response = client.post(f"/emailCampaigns/{campaign_id}/sendNow")
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def delete_campaign(campaign_id: int) -> None:
    """Cancela/apaga uma campanha rascunho — usado quando o draft é rejeitado."""
    with _client() as client:
        response = client.delete(f"/emailCampaigns/{campaign_id}")
        if response.status_code == 404:
            return
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def send_test_email(campaign_id: int, emails: list[str]) -> None:
    """Manda uma cópia de teste da campanha (ainda rascunho) só pros
    endereços indicados — usado pelo botão "Mandar teste" do compose
    manual, antes do rascunho entrar na fila de aprovação de verdade.
    Limite do próprio Brevo: 50 testes/dia."""
    with _client() as client:
        response = client.post(
            f"/emailCampaigns/{campaign_id}/sendTest",
            json={"emailTo": emails},
        )
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def set_contact_attributes(email: str, attributes: dict[str, Any]) -> None:
    """Atualiza atributos de um contato já existente — usado pelo
    backfill do UNSUB_TOKEN (scripts/backfill_unsub_tokens.py) pra quem
    assinou antes desse token existir."""
    with _client() as client:
        response = client.put(f"/contacts/{quote(email, safe='')}", json={"attributes": attributes})
        if response.status_code == 404:
            return
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def unsubscribe_contact(email: str) -> None:
    """Bloqueia o contato pra emails de marketing no Brevo (emailBlacklisted)
    — chamado assim que alguém clica no link de descadastro próprio
    (ver utils/unsubscribe.py), pra não esperar o próximo sync periódico."""
    with _client() as client:
        response = client.put(f"/contacts/{quote(email, safe='')}", json={"emailBlacklisted": True})
        if response.status_code == 404:
            return
        _raise_for_status(response)


@with_retry(exceptions=(httpx.TransportError,))
def create_marketing_webhook(url: str, events: list[str], secret: str, description: str) -> int:
    """Registra o webhook de eventos de campanha no Brevo, com o segredo
    num header custom em vez de na URL — evita que ele apareça em log de
    proxy/Tailscale (o Brevo não assina o payload, então essa é a única
    forma de autenticação que não seja "qualquer um que souber a URL").
    Chamado uma única vez por scripts/setup_brevo_webhook.py."""
    with _client() as client:
        response = client.post(
            "/webhooks",
            json={
                "url": url,
                "type": "marketing",
                "events": events,
                "description": description,
                "headers": [{"key": "X-Brevo-Webhook-Secret", "value": secret}],
            },
        )
        _raise_for_status(response)
        return response.json()["id"]
