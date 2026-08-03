"""Dispara manualmente um ciclo do bot (a mesma run_cycle() usada pelo loop
de main.py), acionado pelo botão "Rodar ciclo agora" do painel.

Loga no mesmo arquivo e com o mesmo formato de main.py — inclusive a linha
"Ciclo completo: N oferta(s)..." que scripts/health_check.py já sabe ler —
então nem o healthcheck nem a Home do painel precisam de lógica extra pra
enxergar o resultado de um ciclo manual igual a um automático.

Rodar isso em paralelo ao loop de main.py (que já está sempre ativo via
launchd) é seguro: DBManager abre o SQLite em modo WAL pensando exatamente
nesse cenário de múltiplos acessos concorrentes.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    logging.info("🖱️ Ciclo disparado manualmente pelo painel de aprovação.")
    run_cycle()


if __name__ == "__main__":
    main()
