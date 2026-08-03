"""Limpa o título bruto que vem da API da AliExpress — cheio de ruído
pensado pro buscador deles, não pra gente que lê (prefixo de SKU tipo
"(A60I]", prefixo de vendedor grudado tipo "skBluetooth...", palavras
soltas tipo "update." no início).

De propósito só remove/normaliza — nunca reescreve ou resume o texto
(isso ficaria pra um LLM, com risco de inventar algo errado sobre o
produto; mesmo motivo que já vale pra utils/headlines.py). Aplicado uma
única vez em modules/orchestrator.py, antes de publicar/gravar, pra
Telegram/WhatsApp/newsletter/landing page/painel mostrarem sempre o
mesmo texto já limpo.
"""

from __future__ import annotations

import re

# Tag de SKU entre colchetes/parênteses no início — o próprio scraper da
# AliExpress às vezes mistura o tipo de colchete ("(A60I]"), então casa
# qualquer combinação de abre/fecha.
_LEADING_SKU_TAG_RE = re.compile(r"^[\(\[]\s*[A-Za-z0-9]{2,8}\s*[\)\]]\s*")

# Prefixo de 2-3 letras minúsculas grudado na próxima palavra (maiúscula)
# sem espaço — ex. "skBluetooth". Exige 2+ pra não arriscar cortar marcas
# legítimas de uma letra só (iPhone, eBike, ...).
_LEADING_GLUED_PREFIX_RE = re.compile(r"^[a-z]{2,3}(?=[A-Z])")

# Palavras de preenchimento comuns nesse tipo de título, quando aparecem
# bem no início seguidas de pontuação/espaço.
_LEADING_FILLER_RE = re.compile(r"^(?:update|new|hot|sale|sales)[\.,:\-]?\s+", re.IGNORECASE)

_WHITESPACE_RE = re.compile(r"\s+")


def clean_offer_title(title: str) -> str:
    # De propósito NÃO trunca por tamanho — a mediana real desses títulos
    # já é ~124 caracteres (a AliExpress escreve pro buscador dela, não
    # pra gente), então qualquer limite curto reescreveria a maioria das
    # ofertas em vez de só limpar o ruído. Onde precisar de recorte visual
    # (landing page), isso já é CSS (line-clamp), não o texto guardado.
    cleaned = title.strip()
    cleaned = _LEADING_SKU_TAG_RE.sub("", cleaned)
    cleaned = _LEADING_GLUED_PREFIX_RE.sub("", cleaned)
    cleaned = _LEADING_FILLER_RE.sub("", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" -,.")

    # Nada de "corrigir" letra minúscula no início — marcas de verdade
    # começam assim de propósito (iPhone, eBike, eBay...) e virariam
    # "IPhone"/"EBike", pior que deixar como está.

    return cleaned or title.strip()
