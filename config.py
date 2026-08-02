"""Configuração central do bot de afiliados.

Todo o resto do projeto deve ler parâmetros daqui em vez de acessar
variáveis de ambiente ou caminhos diretamente. Isso mantém um único lugar
de verdade e facilita testes (basta importar e sobrescrever atributos).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --- Caminhos base -----------------------------------------------------
# Resolvido a partir deste arquivo (não do cwd), porque o launchd invoca
# o script com um working directory imprevisível.
BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
LOGS_DIR = BASE_DIR / "logs"

DATABASE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

DB_PATH = DATABASE_DIR / "affiliate_bot.db"
LOG_FILE = LOGS_DIR / "affiliate_bot.log"

load_dotenv(BASE_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Variável de ambiente {name!r} deve ser um inteiro, recebeu {raw!r}")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"Variável de ambiente {name!r} deve ser um número, recebeu {raw!r}")


# --- Credenciais -----------------------------------------------------------
# Mercado Livre foi abandonado como fonte de dados: a API pública de
# catálogo/busca está bloqueada pela própria plataforma desde 2026-08-01
# (403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES, confirmado em duas redes
# diferentes, com e sem token — não é algo resolvível do nosso lado).
# Mantido comentado como referência histórica:
# ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
# ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
# ML_ACCESS_TOKEN = os.getenv("ML_ACCESS_TOKEN", "")
# ML_REFRESH_TOKEN = os.getenv("ML_REFRESH_TOKEN", "")
# ML_AFFILIATE_TAG = os.getenv("ML_AFFILIATE_TAG", "")

# AliExpress Affiliate API — autenticação por App Key/App Secret (assinatura
# de requisição), sem OAuth2, então não há access/refresh token aqui.
ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY", "")
ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET", "")
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Regras de negócio ---------------------------------------------------
MIN_DISCOUNT_PERCENT = _env_int("MIN_DISCOUNT_PERCENT", 30)
# Teto de publicações por palavra-chave a cada ciclo do orquestrador — sem
# isso, uma palavra-chave popular pode gerar dezenas de mensagens de uma
# vez só no canal, o que é spam, não cadência de canal de ofertas.
MAX_OFFERS_PER_KEYWORD = _env_int("MAX_OFFERS_PER_KEYWORD", 3)

# Nicho: Eletrônicos & Tech. Usado para filtrar título/descrição das ofertas.
# Mantido em grupos só para facilitar manutenção; o filtro final é uma lista
# achatada (NICHE_KEYWORDS). Termos em inglês (não português) — o canal é
# pro público do Reino Unido/inglês, e a busca na AliExpress rende
# resultados mais relevantes no idioma certo.
NICHE_KEYWORD_GROUPS: dict[str, list[str]] = {
    "setup_gamer": [
        "gaming mouse",
        "mechanical keyboard",
        "gaming keyboard",
        "gaming headset",
        "gaming chair",
        "mouse pad",
        "gaming monitor",
        "graphics card",
        "gpu",
        "gaming pc case",
        "game controller",
        "joystick",
    ],
    "consoles": [
        "playstation",
        "ps5",
        "ps4",
        "xbox",
        "nintendo switch",
        "steam deck",
        "gaming console",
    ],
    "smart_home": [
        "smart tv",
        "alexa",
        "echo dot",
        "google home",
        "smart bulb",
        "smart plug",
        "smart lock",
        "security camera",
        "smart home",
    ],
    "audio_wearables": [
        "headphones",
        "wireless earbuds",
        "earbuds",
        "soundbar",
        "bluetooth speaker",
        "smartwatch",
        "fitness tracker",
    ],
    "criadores_de_conteudo": [
        "webcam",
        "microphone",
        "tripod",
        "ring light",
        "capture card",
        "gimbal",
        "camera stabilizer",
    ],
}

NICHE_KEYWORDS: list[str] = sorted(
    {keyword.lower() for group in NICHE_KEYWORD_GROUPS.values() for keyword in group}
)

# Mapa inverso keyword -> grupo (usado pra gravar a "category" de cada
# oferta com base em qual palavra-chave do nicho gerou a busca).
KEYWORD_TO_GROUP: dict[str, str] = {
    keyword.lower(): group
    for group, keywords in NICHE_KEYWORD_GROUPS.items()
    for keyword in keywords
}

# --- Score de ofertas (priorização pra tráfego pago) ----------------------
# Heurística simples e objetiva — nada de ML aqui — pra ordenar ofertas por
# potencial de conversão num anúncio: preço na faixa de "compra por
# impulso" (barato o suficiente pra não exigir muita deliberação, mas não
# tão barato que pareça de baixa qualidade), desconto alto, categoria com
# bom apelo visual em foto de anúncio. Pesos e faixas ajustáveis aqui sem
# mexer em SQL — a view no banco (offer_scores) é gerada a partir destes
# valores.
IMPULSE_PRICE_MIN = _env_float("IMPULSE_PRICE_MIN", 5.0)
IMPULSE_PRICE_MAX = _env_float("IMPULSE_PRICE_MAX", 30.0)

# 0-100, julgamento subjetivo de quão bem cada categoria fotografa/vende
# num anúncio (RGB e devices coloridos > gadgets utilitários pequenos).
CATEGORY_VISUAL_APPEAL: dict[str, int] = {
    "setup_gamer": 90,
    "consoles": 85,
    "audio_wearables": 75,
    "criadores_de_conteudo": 65,
    "smart_home": 55,
}
DEFAULT_VISUAL_APPEAL = 50

# Pesos devem somar 1.0 — validado em db_manager ao montar a view.
SCORE_WEIGHTS: dict[str, float] = {
    "price": 0.40,
    "discount": 0.35,
    "category": 0.25,
}

# --- Retry / backoff exponencial -----------------------------------------
# Usado por qualquer chamada de rede (API do Mercado Livre, Telegram, etc.)
MAX_RETRIES = _env_int("MAX_RETRIES", 5)
BACKOFF_BASE_SECONDS = _env_float("BACKOFF_BASE_SECONDS", 1.0)
BACKOFF_MAX_SECONDS = _env_float("BACKOFF_MAX_SECONDS", 60.0)
