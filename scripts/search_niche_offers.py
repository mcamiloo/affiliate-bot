"""Busca real de ofertas por palavra-chave — validação manual de ponta a
ponta do Módulo 2, contra o banco de produção (essas são ofertas reais,
não fictícias, então faz sentido já registrar a deduplicação nele).

Uso:
    python scripts/search_niche_offers.py "gaming mouse"
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db_manager import DBManager
from modules.aliexpress_client import discover_new_offers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "gaming mouse"

    with DBManager() as db:
        offers = discover_new_offers(keyword, db)

    print(f"\n{len(offers)} new offer(s) found for '{keyword}':\n")
    for offer in offers:
        print("=" * 70)
        print(f"Title:         {offer.title}")
        print(f"Original price: £{offer.original_price:.2f}")
        print(f"Sale price:    £{offer.sale_price:.2f}")
        print(f"Discount:      {offer.discount_percent:.0f}%")
        print(f"Product link:  {offer.product_url}")
        print(f"Affiliate link: {offer.affiliate_url}")
    print("=" * 70)


if __name__ == "__main__":
    main()
