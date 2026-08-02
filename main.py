"""Ponto de entrada do bot para execução contínua no Docker.

Roda uma varredura do nicho, envia 1 oferta, aguarda o intervalo configurado
(2 horas / 7200 segundos) e repete o processo em loop infinito.
"""

from __future__ import annotations

import logging
import time

import config
from modules.orchestrator import run_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(),
    ],
)
# httpx loga a URL completa da requisição (inclui o bot token no path) em
# INFO — sobe pra WARNING aqui pra não vazar o token no log de produção.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Intervalo em segundos (7200s = 2 horas). Lê do .env ou usa 7200 como padrão.
INTERVALO_SEGUNDOS = getattr(config, "LOOP_INTERVAL_SECONDS", 7200)


def main() -> None:
    logging.info("🤖 Bot de Afiliados iniciado no Docker. Intervalo: %d segundos.", INTERVALO_SEGUNDOS)
    
    while True:
        try:
            logging.info("🚀 Iniciando novo ciclo de busca de ofertas...")
            run_cycle()
        except Exception:
            logging.exception("⚠️ Erro não tratado durante o ciclo. O bot continuará no próximo ciclo.")
        
        logging.info("⏳ Aguardando %d segundos (%.1f horas) até o próximo ciclo...", INTERVALO_SEGUNDOS, INTERVALO_SEGUNDOS / 3600)
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    main()
