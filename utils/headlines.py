"""Escolhe um gancho (headline) de config.OFFER_HEADLINES pra uma oferta.

Compartilhado entre modules/telegram_publisher.py (mensagem real) e
scripts/approval_panel.py (preview no card do painel), pra garantir que os
dois mostrem exatamente o mesmo texto pra mesma oferta.

A escolha é determinística por item_id (via crc32, estável entre
processos — hash() embutido do Python não serve aqui porque é
aleatorizado por processo) — a mesma oferta sempre mostra o mesmo gancho,
em vez de sortear de novo a cada render.
"""

from __future__ import annotations

import zlib

import config


def pick_offer_headline(category: str | None, item_id: str) -> str:
    pool = config.OFFER_HEADLINES.get(category or "default", config.OFFER_HEADLINES["default"])
    index = zlib.crc32(item_id.encode()) % len(pool)
    return pool[index]
