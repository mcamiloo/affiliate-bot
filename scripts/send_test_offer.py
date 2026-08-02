"""Envia uma oferta fictícia pro canal real do Telegram — validação
manual de ponta a ponta do Módulo 4, fora da suíte automatizada (que usa
um dublê de Bot pra não postar no canal a cada `pytest`).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.telegram_publisher import publish_offer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# httpx loga a URL completa da requisição (inclui o bot token no path) em
# INFO — sobe pra WARNING aqui pra não vazar o token no terminal/logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    publish_offer(
        title="[TEST] 7.1 Surround RGB Gaming Headset",
        original_price=299.90,
        discounted_price=149.90,
        discount_percent=50,
        link="https://s.click.aliexpress.com/e/_example123",
    )
    print("Mensagem de teste enviada com sucesso.")


if __name__ == "__main__":
    main()
