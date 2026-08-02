"""Cliente da API de afiliados da AliExpress.

Pipeline: busca por palavra-chave -> filtro de relevância pelo nicho
(config.NICHE_KEYWORDS) -> filtro por desconto mínimo
(config.MIN_DISCOUNT_PERCENT) -> filtro de duplicidade (DBManager do
Módulo 1) -> geração de link de afiliado.

Autenticação por App Key/App Secret (assinatura de requisição), sem
OAuth2 — diferente do que tínhamos desenhado para o Mercado Livre.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aliexpress_api import AliexpressApi, models
from aliexpress_api.errors import (
    ApiRequestException,
    ApiRequestResponseException,
    InvalidTrackingIdException,
    ProductsNotFoudException,
)

import config
from database.db_manager import DBManager
from utils.retry import with_retry

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (ApiRequestException, ApiRequestResponseException)


@dataclass
class Offer:
    item_id: str
    title: str
    original_price: float
    sale_price: float
    discount_percent: float
    product_url: str
    affiliate_url: str
    image_url: str


def _client() -> AliexpressApi:
    return AliexpressApi(
        config.ALIEXPRESS_APP_KEY,
        config.ALIEXPRESS_APP_SECRET,
        models.Language.EN,
        models.Currency.GBP,
        config.ALIEXPRESS_TRACKING_ID or None,
    )


def _parse_percent(raw) -> float:
    if not raw:
        return 0.0
    return float(str(raw).replace("%", "").strip())


def matches_niche(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in config.NICHE_KEYWORDS)


@with_retry(exceptions=_RETRYABLE_ERRORS)
def search_products(keyword: str, page_size: int = 50, ship_to_country: str = "GB") -> list:
    """Busca bruta na API por palavra-chave. Lista vazia se nada for encontrado.

    ship_to_country="GB" por padrão — o canal é pro público do Reino Unido,
    então filtramos por itens enviáveis pra lá e com preço já refletindo a
    política fiscal do país (afeta o valor retornado pelos campos target_*).
    """
    api = _client()
    try:
        response = api.get_products(
            keywords=keyword, page_size=page_size, ship_to_country=ship_to_country
        )
    except ProductsNotFoudException:
        return []
    return response.products


def filter_by_niche(products: list) -> list:
    return [p for p in products if matches_niche(p.product_title)]


def filter_by_discount(products: list, min_discount_percent: float | None = None) -> list:
    threshold = config.MIN_DISCOUNT_PERCENT if min_discount_percent is None else min_discount_percent
    return [p for p in products if _parse_percent(p.discount) >= threshold]


def filter_new(products: list, db: DBManager) -> list:
    return [p for p in products if not db.is_duplicate(str(p.product_id))]


@with_retry(exceptions=_RETRYABLE_ERRORS)
def generate_affiliate_link(product_url: str) -> str:
    api = _client()
    links = api.get_affiliate_links(product_url)
    return links[0].promotion_link


def _to_offer(product, affiliate_url: str) -> Offer:
    return Offer(
        item_id=str(product.product_id),
        title=product.product_title,
        original_price=float(product.target_original_price),
        sale_price=float(product.target_sale_price),
        discount_percent=_parse_percent(product.discount),
        product_url=product.product_detail_url,
        affiliate_url=affiliate_url,
        image_url=product.product_main_image_url,
    )


def discover_new_offers(
    keyword: str,
    db: DBManager,
    min_discount_percent: float | None = None,
    page_size: int = 50,
) -> list[Offer]:
    """Pipeline completo: busca -> nicho -> desconto -> duplicidade -> link de afiliado."""
    raw = search_products(keyword, page_size=page_size)
    niche_matches = filter_by_niche(raw)
    discounted = filter_by_discount(niche_matches, min_discount_percent)
    new_products = filter_new(discounted, db)

    offers = []
    for product in new_products:
        try:
            affiliate_url = generate_affiliate_link(product.product_detail_url)
        except InvalidTrackingIdException:
            logger.warning(
                "ALIEXPRESS_TRACKING_ID não configurado — usando promotion_link "
                "da busca como fallback para o item %s. Configure o Tracking ID "
                "no Portal de Afiliados para garantir atribuição de comissão.",
                product.product_id,
            )
            affiliate_url = product.promotion_link
        offers.append(_to_offer(product, affiliate_url))
    return offers
