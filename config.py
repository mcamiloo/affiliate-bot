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
TELEGRAM_CHANNEL_INVITE_LINK = os.getenv("TELEGRAM_CHANNEL_INVITE_LINK", "")

# WhatsApp — automação de UI do WhatsApp Desktop (sem API oficial, ver
# modules/whatsapp_publisher.py). Desligado por padrão: só liga depois de
# calibrar os delays da automação manualmente na máquina de produção.
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").strip().lower() == "true"
# Nome EXATO da comunidade/conversa como aparece na lista lateral do
# WhatsApp Desktop — usado pra buscar e abrir o chat certo.
WHATSAPP_COMMUNITY_NAME = os.getenv("WHATSAPP_COMMUNITY_NAME", "")

# Brevo — newsletter diária por email.
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_LIST_ID = _env_int("BREVO_LIST_ID", 0) if os.getenv("BREVO_LIST_ID") else None
BREVO_DOI_TEMPLATE_ID = _env_int("BREVO_DOI_TEMPLATE_ID", 0) if os.getenv("BREVO_DOI_TEMPLATE_ID") else None
BREVO_DOI_REDIRECT_URL = os.getenv("BREVO_DOI_REDIRECT_URL", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")

# Endereço físico exigido por lei (PECR/CAN-SPAM) no rodapé do email —
# sem isso o envio de email em massa não é compliant.
NEWSLETTER_ADDRESS_LINE1 = os.getenv("NEWSLETTER_ADDRESS_LINE1", "")
NEWSLETTER_ADDRESS_CITY = os.getenv("NEWSLETTER_ADDRESS_CITY", "")
NEWSLETTER_ADDRESS_POSTAL_CODE = os.getenv("NEWSLETTER_ADDRESS_POSTAL_CODE", "")
NEWSLETTER_ADDRESS_COUNTRY = os.getenv("NEWSLETTER_ADDRESS_COUNTRY", "")

# Janela (hora local do Reino Unido) dentro da qual o horário de envio
# diário é sorteado, e quanto tempo antes o rascunho é gerado.
NEWSLETTER_WINDOW_START_HOUR_UK = _env_int("NEWSLETTER_WINDOW_START_HOUR_UK", 8)
NEWSLETTER_WINDOW_END_HOUR_UK = _env_int("NEWSLETTER_WINDOW_END_HOUR_UK", 20)
NEWSLETTER_DRAFT_LEAD_MINUTES = _env_int("NEWSLETTER_DRAFT_LEAD_MINUTES", 60)
NEWSLETTER_LOOKBACK_HOURS = _env_int("NEWSLETTER_LOOKBACK_HOURS", 48)
NEWSLETTER_MAX_OFFERS = _env_int("NEWSLETTER_MAX_OFFERS", 8)

# Intervalo de checagem do agendador e log próprio (separado do log do
# bot principal, pra não misturar as duas linhas de execução).
NEWSLETTER_SCHEDULER_POLL_SECONDS = _env_int("NEWSLETTER_SCHEDULER_POLL_SECONDS", 300)
# A cada quantos polls o agendador sincroniza subscribers a partir do
# Brevo (não precisa ser a cada tick — contatos não mudam tão rápido).
NEWSLETTER_SUBSCRIBER_SYNC_EVERY_N_POLLS = _env_int("NEWSLETTER_SUBSCRIBER_SYNC_EVERY_N_POLLS", 12)
NEWSLETTER_LOG_FILE = LOGS_DIR / "newsletter_scheduler.log"

# Painel de aprovação — bind exclusivo em 127.0.0.1; alcançável de fora só
# via Tailscale Funnel + proxy da Netlify em /sistema (nunca exposto direto
# na rede). Login obrigatório (ver admin_users em database/db_manager.py).
APPROVAL_PANEL_PORT = _env_int("APPROVAL_PANEL_PORT", 8765)
# Assina a sessão de login do painel — precisa ser estável entre reinícios
# do processo (senão todo mundo é deslogado a cada restart do launchd).
APPROVAL_PANEL_SECRET_KEY = os.getenv("APPROVAL_PANEL_SECRET_KEY", "")

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

# Ganchos (headline em caps, tom brincalhão, inglês britânico) por
# categoria — usados no início da mensagem do Telegram e no card do
# painel. Escolhido por categoria, não por produto individual: não temos
# IA escrevendo texto por oferta, então evitamos afirmar qualquer coisa
# específica sobre o item (risco de inventar algo errado sobre um produto
# que só conhecemos pela API) — a piada é sobre o *tipo* de produto.
OFFER_HEADLINES: dict[str, list[str]] = {
    "setup_gamer": [
        "STOP BLAMING YOUR MOUSE FOR THAT LOSS",
        "NO MORE \"IT WAS LAG, I SWEAR\"",
        "YOUR K/D RATIO WILL THANK YOU",
    ],
    "consoles": [
        "STILL ON THE RESTOCK WAITING LIST?",
        "SOFA GAMING JUST LEVELLED UP",
    ],
    "smart_home": [
        "STOP SHOUTING AT LIGHTS THAT DON'T LISTEN",
        "YOUR HOUSE JUST GOT SMARTER THAN YOU",
    ],
    "audio_wearables": [
        "STOP LOSING ONE EARBUD ON THE TUBE",
        "COMMUTE UPGRADE UNLOCKED",
    ],
    "criadores_de_conteudo": [
        "STOP GOING VIRAL FOR THE WRONG REASONS (POTATO CAM)",
        'NO MORE "CAN YOU HEAR ME?" EVERY 5 MINUTES',
    ],
    "default": [
        "BARGAIN ALERT",
        "TOO GOOD TO SCROLL PAST",
    ],
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
