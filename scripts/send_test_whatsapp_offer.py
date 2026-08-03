"""Envia uma oferta fictícia pra comunidade real do WhatsApp — validação
manual da automação de UI (Módulo 5), fora da suíte automatizada (que usa
um dublê de subprocess pra não abrir o WhatsApp de verdade a cada
`pytest`).

Rode isto primeiro, sozinho, antes de ligar WHATSAPP_ENABLED=true no .env
de produção — serve pra calibrar os delays em modules/whatsapp_publisher.py
(DELAY_*) até a automação abrir o chat certo e mandar a mensagem por
inteiro, sem cortar nem colar no lugar errado.

Pré-requisitos: WhatsApp Desktop aberto e logado, permissão de
Acessibilidade concedida ao Python (Ajustes do Sistema > Privacidade e
Segurança > Acessibilidade), e WHATSAPP_COMMUNITY_NAME no .env batendo
com o nome exato da conversa.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from modules.whatsapp_publisher import publish_offer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    if not config.WHATSAPP_ENABLED:
        print(
            "WHATSAPP_ENABLED=false no .env — este script ignora essa flag e "
            "envia mesmo assim, já que é o teste manual pra calibrar a automação. "
            "Ctrl+C nos próximos 3s se não era essa a intenção."
        )
        config.WHATSAPP_ENABLED = True

    if not config.WHATSAPP_COMMUNITY_NAME:
        print("Defina WHATSAPP_COMMUNITY_NAME no .env antes de rodar este script.")
        sys.exit(1)

    publish_offer(
        title="[TEST] 7.1 Surround RGB Gaming Headset",
        original_price=299.90,
        discounted_price=149.90,
        discount_percent=50,
        link="https://s.click.aliexpress.com/e/_example123",
    )
    print(f"Mensagem de teste enviada para '{config.WHATSAPP_COMMUNITY_NAME}' com sucesso.")


if __name__ == "__main__":
    main()
