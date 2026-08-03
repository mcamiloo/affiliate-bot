"""Registra (ou atualiza) o webhook de marketing do Brevo — roda uma vez
manualmente, não faz parte de nenhum processo 24/7.

O segredo vai num header custom (X-Brevo-Webhook-Secret), não na URL —
o Brevo não assina o payload (sem HMAC nativo), e colocar o segredo na
URL arriscaria vazar em log de proxy/Tailscale. Ver approval_panel.py
(_require_brevo_webhook_auth), que confere esse header + allowlist do
IP de origem do Brevo (1.179.112.0/20) como segunda camada.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from modules import brevo_client

EVENTS = ["delivered", "opened", "click", "hardBounce", "softBounce", "unsubscribed", "spam"]


def main() -> None:
    if not config.APPROVAL_PANEL_PUBLIC_URL:
        raise RuntimeError("APPROVAL_PANEL_PUBLIC_URL não definido no .env.")
    if not config.BREVO_WEBHOOK_SECRET:
        raise RuntimeError("BREVO_WEBHOOK_SECRET não definido no .env.")

    webhook_url = f"{config.APPROVAL_PANEL_PUBLIC_URL.rstrip('/')}/api/brevo-webhook"
    webhook_id = brevo_client.create_marketing_webhook(
        url=webhook_url,
        events=EVENTS,
        secret=config.BREVO_WEBHOOK_SECRET,
        description="OmbroPanel — eventos de campanha (analytics do painel)",
    )
    print(f"Webhook registrado: id={webhook_id}, url={webhook_url}, eventos={EVENTS}")


if __name__ == "__main__":
    main()
