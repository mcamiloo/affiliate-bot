"""Oculta ofertas sem image_url — sem foto, o card na landing page mostra
só o ícone de carrinho, o que parece quebrado. "Ocultar" (não apagar)
porque o dedupe (is_duplicate) precisa continuar reconhecendo o item_id,
senão a AliExpress API devolveria a mesma oferta de novo num ciclo
futuro. Roda manualmente quando quiser (idempotente — ofertas já
ocultas são ignoradas).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db_manager import DBManager


def main() -> None:
    with DBManager() as db:
        offers = db.list_recent_offers(limit=10_000)
        to_hide = [o for o in offers if not o["image_url"] and not o["hidden"]]
        for offer in to_hide:
            db.hide_offer(offer["item_id"])

    print(f"{len(to_hide)} oferta(s) sem imagem ocultada(s).")


if __name__ == "__main__":
    main()
