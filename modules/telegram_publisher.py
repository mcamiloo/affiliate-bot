"""Publica ofertas formatadas no canal do Telegram.

Usa a API assíncrona da python-telegram-bot por baixo de uma interface
síncrona (via asyncio.run), pra manter a mesma convenção do resto do
projeto (config, database) — nenhum outro módulo precisa lidar com
async/await. Retry com backoff exponencial (utils.retry) cobre quedas de
rede, já que o bot roda 24/7 num Mac sem garantia de conexão estável.
"""

from __future__ import annotations

import asyncio
import html
import logging

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

import config
from utils.retry import with_retry

logger = logging.getLogger(__name__)

# httpx (usado por baixo pela python-telegram-bot) loga a URL completa da
# requisição em INFO, incluindo o bot token no path — mantido em WARNING
# aqui pra não vazar o token em logs, independente do nível configurado
# por quem importa este módulo.
logging.getLogger("httpx").setLevel(logging.WARNING)


def format_offer_message(
    title: str,
    original_price: float,
    discounted_price: float,
    discount_percent: float,
    link: str,
    headline: str,
) -> str:
    safe_title = html.escape(title)
    safe_link = html.escape(link, quote=True)
    # quote=False: aspas retas não têm significado especial em texto (só em
    # valor de atributo), e alguns ganchos usam aspas de propósito.
    headline = html.escape(headline, quote=False)
    return (
        f"🚨 <b>{headline}</b>\n\n"
        f"<b>{safe_title}</b>\n\n"
        f"Was: <s>£{original_price:.2f}</s>\n"
        f"Now: <b>£{discounted_price:.2f}</b> 👑\n"
        f"💥 <b>{discount_percent:.0f}% OFF</b>\n\n"
        f'🔗 <a href="{safe_link}">Grab the deal</a>'
    )


async def _send_async(text: str) -> None:
    async with Bot(token=config.TELEGRAM_BOT_TOKEN) as bot:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )


@with_retry(exceptions=(TelegramError,))
def _send_with_retry(text: str) -> None:
    asyncio.run(_send_async(text))


def publish_offer(
    title: str,
    original_price: float,
    discounted_price: float,
    discount_percent: float,
    link: str,
    headline: str,
) -> None:
    text = format_offer_message(
        title, original_price, discounted_price, discount_percent, link, headline
    )
    _send_with_retry(text)
    logger.info("Oferta publicada no Telegram: %s", title)
