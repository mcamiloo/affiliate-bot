"""Baixa e guarda uma cópia local da imagem de cada oferta.

O CDN da AliExpress (atrás de Cloudflare) bloqueia hotlinking de forma
intermitente — a mesma URL responde 200 ou 403 dependendo de padrão de
tráfego/heurística anti-scraping deles, sem relação com nada que a gente
configure. Um download feito daqui (servidor, sem Referer de navegador)
não dispara esse bloqueio nos testes que fizemos, então cacheamos uma vez
na publicação (ver modules/orchestrator.py) e o painel/landing
page/widget passam a servir essa cópia em vez de linkar direto pro CDN
deles.

Best-effort de propósito: qualquer falha (rede, 403, tipo de conteúdo
inesperado) retorna None em vez de propagar — uma imagem que não baixou
não pode impedir a oferta de ser publicada.
"""

from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

_EXTENSION_BY_CONTENT_TYPE = {
    "image/webp": "webp",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
}


def cache_offer_image(item_id: str, image_url: str | None) -> str | None:
    """Baixa image_url e salva como config.OFFER_IMAGE_CACHE_DIR/<item_id>.<ext>.

    Retorna só o nome do arquivo (não o caminho completo) em caso de
    sucesso, ou None se não deu — nesse caso quem chamou deve continuar
    usando a URL original da AliExpress como fallback.
    """
    if not image_url:
        return None

    try:
        response = httpx.get(image_url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Não foi possível baixar a imagem da oferta %s (%s)", item_id, image_url)
        return None

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type)
    if extension is None:
        logger.warning(
            "Tipo de conteúdo inesperado (%s) pra imagem da oferta %s — não cacheado", content_type, item_id
        )
        return None

    filename = f"{item_id}.{extension}"
    (config.OFFER_IMAGE_CACHE_DIR / filename).write_bytes(response.content)
    return filename
