"""Liga os módulos anteriores: busca de ofertas -> publicação no Telegram
(e, se ligado, espelhado no WhatsApp) -> gravação no banco (pra não
duplicar em execuções futuras).

Uma chamada de run_cycle() processa as palavras-chave do nicho uma vez e
retorna — o agendamento pra rodar 24/7 é responsabilidade do launchd
(que invoca main.py periodicamente), não deste módulo. Assim um erro
fatal numa execução falha só aquele ciclo, não trava o serviço pra
sempre.
"""

from __future__ import annotations

import logging

import config
from database.db_manager import DBManager, compute_score
from modules.aliexpress_client import discover_new_offers
from modules.telegram_publisher import publish_offer
from modules.whatsapp_publisher import publish_offer as publish_offer_whatsapp
from utils.headlines import pick_offer_headline
from utils.image_cache import cache_offer_image
from utils.offer_title import clean_offer_title

logger = logging.getLogger(__name__)


def process_keyword(keyword: str, db: DBManager) -> int:
    """Busca, publica e grava as ofertas novas de uma palavra-chave.

    Candidatas são ordenadas por compute_score() (desc) antes de publicar,
    pra priorizar as com maior potencial de conversão em tráfego pago —
    não a ordem bruta em que a API devolveu os resultados. Publicação é
    limitada a config.MAX_OFFERS_PER_KEYWORD por ciclo, pra não inundar o
    canal quando uma palavra-chave tem muitos resultados. Cada oferta só é
    gravada no banco (marcada como vista) DEPOIS de publicada com sucesso —
    se falhar, tenta de novo no próximo ciclo.

    Retorna quantas ofertas foram publicadas.
    """
    try:
        offers = discover_new_offers(keyword, db)
    except Exception:
        logger.exception("Falha ao buscar ofertas para '%s' — pulando essa palavra-chave", keyword)
        return 0

    category = config.KEYWORD_TO_GROUP.get(keyword.lower())
    offers = sorted(
        offers,
        key=lambda offer: compute_score(offer.sale_price, offer.discount_percent, category),
        reverse=True,
    )

    published = 0
    for offer in offers[: config.MAX_OFFERS_PER_KEYWORD]:
        # Limpo uma única vez aqui — Telegram, WhatsApp e o banco (de onde
        # newsletter/landing page/painel leem depois) usam esse mesmo
        # offer.title daqui em diante, então ficam todos consistentes.
        offer.title = clean_offer_title(offer.title)
        # avoid=última oferta publicada nessa categoria: sem isso o gancho é
        # só determinístico por item_id, e com pools pequenos duas ofertas
        # seguidas da mesma categoria acabam mostrando o mesmo texto.
        headline = pick_offer_headline(category, offer.item_id, avoid=db.get_last_headline(category))
        try:
            publish_offer(
                title=offer.title,
                original_price=offer.original_price,
                discounted_price=offer.sale_price,
                discount_percent=offer.discount_percent,
                link=offer.affiliate_url,
                headline=headline,
            )
        except Exception:
            logger.exception(
                "Falha ao publicar oferta %s ('%s') — não será marcada como vista, "
                "tenta de novo no próximo ciclo",
                offer.item_id,
                offer.title,
            )
            continue

        # WhatsApp é canal secundário/best-effort: dispara logo após o
        # Telegram publicar com sucesso, mesma oferta, mesmo instante do
        # ciclo. A automação de UI é mais frágil que a API do Telegram —
        # uma falha aqui não desfaz a publicação já feita no Telegram nem
        # impede o save_offer abaixo.
        try:
            publish_offer_whatsapp(
                title=offer.title,
                original_price=offer.original_price,
                discounted_price=offer.sale_price,
                discount_percent=offer.discount_percent,
                link=offer.affiliate_url,
            )
        except Exception:
            logger.exception(
                "Falha ao publicar oferta %s ('%s') no WhatsApp — Telegram já "
                "publicado, seguindo em frente",
                offer.item_id,
                offer.title,
            )

        # Best-effort: baixa uma cópia local da imagem pra não depender do
        # CDN da AliExpress (bloqueia hotlinking de forma intermitente) —
        # None se falhar, e quem exibe a oferta cai de volta pra image_url.
        local_image_path = cache_offer_image(offer.item_id, offer.image_url)

        db.save_offer(
            item_id=offer.item_id,
            title=offer.title,
            url=offer.product_url,
            affiliate_url=offer.affiliate_url,
            price=offer.sale_price,
            original_price=offer.original_price,
            discount_percent=offer.discount_percent,
            image_url=offer.image_url,
            category=category,
            headline=headline,
            local_image_path=local_image_path,
        )
        published += 1

    return published


def run_cycle(keywords: list[str] | None = None) -> int:
    """Roda uma varredura do nicho até encontrar e publicar 1 oferta."""
    keywords = config.NICHE_KEYWORDS if keywords is None else keywords
    total_published = 0

    with DBManager() as db:
        for keyword in keywords:
            published = process_keyword(keyword, db)
            total_published += published
            logger.info("'%s': %d oferta(s) publicada(s)", keyword, published)

            # TRAVA DE SEGURANÇA: Se já publicou 1 oferta, encerra a busca do ciclo imediatamente
            if total_published >= 1:
                logger.info("🎯 Limite do ciclo atingido (1 oferta enviada). Pausando até o próximo ciclo.")
                break

    logger.info("Ciclo completo: %d oferta(s) publicada(s) no total", total_published)
    return total_published
