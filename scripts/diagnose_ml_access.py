"""Diagnóstico único: testa se os endpoints de busca do Mercado Livre
(/sites/MLB/search e /sites/MLB) estão acessíveis com o token atual,
rodando DA MÁQUINA ONDE O BOT VAI OPERAR (não de um sandbox na nuvem).

Isso ajuda a distinguir dois cenários bem diferentes:
  1) Bloqueio por política de conta/app (KYC, certificação, etc.) — vai
     falhar igual em qualquer máquina.
  2) Bloqueio por IP de datacenter/nuvem — passa a funcionar rodando de
     uma rede residencial normal, como a do Mac que vai rodar o bot 24/7.

Não escreve nada no .env, só imprime os resultados.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

TESTS = [
    ("users/me (controle - deve sempre funcionar)", "https://api.mercadolibre.com/users/me"),
    ("sites/MLB (info do site)", "https://api.mercadolibre.com/sites/MLB"),
    ("search q= (palavra-chave)", "https://api.mercadolibre.com/sites/MLB/search?q=mouse+gamer&limit=5"),
    ("search category= (categoria)", "https://api.mercadolibre.com/sites/MLB/search?category=MLB1648&limit=5"),
]


def main() -> None:
    if not config.ML_ACCESS_TOKEN:
        print("ML_ACCESS_TOKEN vazio no .env. Rode scripts/get_ml_tokens.py primeiro.")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {config.ML_ACCESS_TOKEN}"}

    for name, url in TESTS:
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode()
                print(f"[OK]  {name}: HTTP {response.status} ({len(body)} bytes)")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            print(f"[ERRO] {name}: HTTP {exc.code}")
            print(f"       {body[:300]}")
        except Exception as exc:  # conexão, timeout, etc.
            print(f"[EXCEÇÃO] {name}: {type(exc).__name__}: {exc}")
        print()


if __name__ == "__main__":
    main()
