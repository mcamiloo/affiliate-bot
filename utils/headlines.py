"""Escolhe um gancho (headline) de config.OFFER_HEADLINES pra uma oferta.

Usado por modules/orchestrator.py no momento da publicação (única fonte
de verdade — o resultado é gravado em posted_offers.headline e lido dali
por scripts/approval_panel.py e scripts/write_widget_snapshot.py, nunca
recalculado depois, pra não divergir do texto que já saiu no Telegram).

A escolha é determinística por item_id (via crc32, estável entre
processos — hash() embutido do Python não serve aqui porque é
aleatorizado por processo) — a mesma oferta sempre mostra o mesmo gancho
"natural". O parâmetro avoid é um empurrão pro próximo item do pool
quando esse gancho natural bateria com o da oferta publicada
imediatamente antes na mesma categoria (ver DBManager.get_last_headline)
— evita repetição visível sem sacrificar o determinismo por item.
"""

from __future__ import annotations

import zlib

import config


def pick_offer_headline(category: str | None, item_id: str, avoid: str | None = None) -> str:
    pool = config.OFFER_HEADLINES.get(category or "default", config.OFFER_HEADLINES["default"])
    index = zlib.crc32(item_id.encode()) % len(pool)
    headline = pool[index]
    if avoid is not None and headline == avoid and len(pool) > 1:
        headline = pool[(index + 1) % len(pool)]
    return headline
