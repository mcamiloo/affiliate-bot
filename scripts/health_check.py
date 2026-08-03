"""Verifica se o bot está rodando corretamente e manda uma notificação
nativa do macOS com o resultado — pensado pra rodar via launchd de forma
independente (não depende de nenhuma conversa aberta com o assistente).

Checa duas coisas:
  1. O job do launchd (com.miguelcamilo.affiliatebot) está carregado?
  2. O último ciclo bem-sucedido no log foi recente o suficiente?

"Recente o suficiente" = menos de 3h50 desde o último "Ciclo completo"
no log — um pouco mais que o intervalo de 3h entre execuções, pra não
disparar alarme falso se um ciclo atrasar alguns minutos.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from utils.notifications import notify

LAUNCHD_LABEL = "com.miguelcamilo.affiliatebot"
STALE_AFTER = timedelta(hours=3, minutes=50)

CYCLE_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO [\w.]+: "
    r"Ciclo completo: (?P<count>\d+) oferta"
)


def job_is_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
        capture_output=True,
    )
    return result.returncode == 0


def last_successful_cycle(log_file: Path = None) -> tuple[datetime, int] | None:
    log_file = log_file or config.LOG_FILE
    if not log_file.exists():
        return None

    last_match = None
    with log_file.open(errors="replace") as f:
        for line in f:
            match = CYCLE_LINE_RE.match(line)
            if match:
                last_match = match

    if last_match is None:
        return None

    timestamp = datetime.strptime(last_match.group("ts"), "%Y-%m-%d %H:%M:%S")
    count = int(last_match.group("count"))
    return timestamp, count


def main() -> None:
    if not job_is_loaded():
        notify(
            "Affiliate Bot ⚠️ Parado",
            "O job do launchd não está carregado — o bot não vai rodar sozinho.",
            sound="Basso",
        )
        return

    result = last_successful_cycle()
    if result is None:
        notify(
            "Affiliate Bot ⚠️",
            "Nenhum ciclo completo encontrado no log ainda.",
            sound="Basso",
        )
        return

    timestamp, count = result
    age = datetime.now() - timestamp

    if age > STALE_AFTER:
        hours = int(age.total_seconds() // 3600)
        notify(
            "Affiliate Bot ⚠️ Parado?",
            f"Último ciclo bem-sucedido foi às {timestamp:%d/%m %H:%M} "
            f"({hours}h atrás) — mais que o esperado.",
            sound="Basso",
        )
    else:
        notify(
            "Affiliate Bot ✅ Tudo certo",
            f"Último ciclo às {timestamp:%H:%M} publicou {count} oferta(s).",
        )


if __name__ == "__main__":
    main()
