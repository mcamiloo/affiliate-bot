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

import httpx

import config
from utils.retry import with_retry

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
                "attributes": {"CONSENT_TIMESTAMP": consent_timestamp},
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
