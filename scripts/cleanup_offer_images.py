"""Apaga cópias locais de imagem (config.OFFER_IMAGE_CACHE_DIR, ver
utils/image_cache.py) de ofertas que não estão mais "em uso" há mais de
N dias — sem isso o diretório cresce pra sempre, já que toda oferta
publicada baixa uma imagem e elas nunca são removidas sozinhas.

"Em uso" = não oculta E (publicada nos últimos N dias OU ainda no top da
landing page atual — ver scripts/generate_landing_page.py). A segunda
condição cobre o caso raro de uma oferta antiga continuar bem rankeada
e visível no site mesmo depois da janela de N dias.

Roda periodicamente via launchd (com.miguelcamilo.affiliatebot.imagecleanup),
mas também pode ser chamado na mão — idempotente, só apaga o que não
está referenciado por nenhuma oferta em uso.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from database.db_manager import DBManager
from scripts.generate_landing_page import DEFAULT_LIMIT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_MAX_UNUSED_DAYS = 5


def in_use_image_filenames(db: DBManager, max_unused_days: int, landing_page_limit: int = DEFAULT_LIMIT) -> set[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_unused_days)

    recently_posted = {
        o["local_image_path"]
        for o in db.list_recent_offers(limit=10_000)
        if o["local_image_path"] and not o["hidden"] and datetime.fromisoformat(o["posted_at"]).replace(
            tzinfo=timezone.utc
        ) >= cutoff
    }
    still_on_landing_page = {
        o["local_image_path"] for o in db.list_offers_by_score(limit=landing_page_limit) if o["local_image_path"]
    }
    return recently_posted | still_on_landing_page


def cleanup(max_unused_days: int = DEFAULT_MAX_UNUSED_DAYS, landing_page_limit: int = DEFAULT_LIMIT) -> int:
    if not config.OFFER_IMAGE_CACHE_DIR.exists():
        return 0

    with DBManager() as db:
        keep = in_use_image_filenames(db, max_unused_days, landing_page_limit)

    removed = 0
    for cached_file in config.OFFER_IMAGE_CACHE_DIR.iterdir():
        if cached_file.is_file() and cached_file.name not in keep:
            cached_file.unlink()
            removed += 1

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-unused-days",
        type=int,
        default=DEFAULT_MAX_UNUSED_DAYS,
        help="Dias sem uso antes de apagar (default: 5).",
    )
    args = parser.parse_args()

    removed = cleanup(args.max_unused_days)
    logger.info("%d imagem(ns) em cache removida(s) (sem uso há mais de %d dias).", removed, args.max_unused_days)


if __name__ == "__main__":
    main()
