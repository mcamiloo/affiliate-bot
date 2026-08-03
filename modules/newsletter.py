"""Monta o conteúdo da newsletter diária a partir das ofertas já publicadas.

Reaproveita a mesma tabela/score usados pelo canal do Telegram e pela
landing page (offer_scores, via DBManager) — a newsletter não tem uma
fonte de ofertas própria, só uma janela de tempo e um limite de itens
diferentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from jinja2 import Environment, FileSystemLoader

import config
from database.db_manager import DBManager

TEMPLATES_DIR = config.BASE_DIR / "templates"

SITE_TITLE = "Tech & Gaming Deals"


@dataclass
class NewsletterContent:
    subject: str
    html: str
    offer_ids: list[str]


def select_offers(db: DBManager) -> list[dict[str, Any]]:
    return db.list_offers_by_score(
        limit=config.NEWSLETTER_MAX_OFFERS,
        since_hours=config.NEWSLETTER_LOOKBACK_HOURS,
    )


def render_html(offers: list[dict[str, Any]]) -> str:
    if not config.APPROVAL_PANEL_PUBLIC_URL:
        raise RuntimeError(
            "APPROVAL_PANEL_PUBLIC_URL não definido no .env — necessário pro link de "
            "descadastro próprio no rodapé do email (ver templates/newsletter_email.html.j2)."
        )

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("newsletter_email.html.j2")
    return template.render(
        site_title=SITE_TITLE,
        subtitle="Today's hand-picked discounts, straight to your inbox.",
        offers=offers,
        telegram_invite_link=config.TELEGRAM_CHANNEL_INVITE_LINK,
        sender_name=config.BREVO_SENDER_NAME,
        address_line1=config.NEWSLETTER_ADDRESS_LINE1,
        address_city=config.NEWSLETTER_ADDRESS_CITY,
        address_postal_code=config.NEWSLETTER_ADDRESS_POSTAL_CODE,
        address_country=config.NEWSLETTER_ADDRESS_COUNTRY,
        unsubscribe_base_url=config.APPROVAL_PANEL_PUBLIC_URL.rstrip("/"),
    )


def build_newsletter(db: DBManager, send_date: date) -> NewsletterContent | None:
    """Monta o conteúdo do dia, ou None se não houver ofertas recentes o
    suficiente pra justificar um envio (o agendador decide pular o dia
    nesse caso, em vez de mandar uma newsletter vazia).
    """
    offers = select_offers(db)
    if not offers:
        return None

    subject = f"Today's Top Tech Deals — {send_date.strftime('%d %b')}"
    html = render_html(offers)
    offer_ids = [offer["item_id"] for offer in offers]
    return NewsletterContent(subject=subject, html=html, offer_ids=offer_ids)
