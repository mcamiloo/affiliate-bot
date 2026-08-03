"""Aplica utils.offer_title.clean_offer_title nos títulos já gravados —
roda uma vez manualmente depois que a limpeza foi ligada em
modules/orchestrator.py, pra ofertas antigas também ficarem com o título
arrumado (Telegram já publicado não muda retroativamente, é só texto já
enviado — isso afeta o que aparece daqui pra frente no banco: newsletter,
landing page, painel).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db_manager import DBManager
from utils.offer_title import clean_offer_title


def main() -> None:
    with DBManager() as db:
        offers = db.list_recent_offers(limit=10_000)
        changed = 0
        for offer in offers:
            cleaned = clean_offer_title(offer["title"])
            if cleaned != offer["title"]:
                db._conn.execute(
                    "UPDATE posted_offers SET title = ? WHERE item_id = ?;",
                    (cleaned, offer["item_id"]),
                )
                changed += 1
        db._conn.commit()

    print(f"{changed}/{len(offers)} título(s) atualizado(s).")


if __name__ == "__main__":
    main()
