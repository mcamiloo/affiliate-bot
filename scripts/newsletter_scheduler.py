"""Agendador da newsletter diária — roda 24/7 via launchd, mesmo padrão
de main.py (RunAtLoad + KeepAlive, loop infinito com sleep interno).

A cada ciclo:
  1. Garante que existe um horário-alvo sorteado pro dia (UK, dentro da
     janela configurada) em `scheduled_sends`.
  2. De tempos em tempos, sincroniza `subscribers` a partir da lista do
     Brevo (fonte de verdade sobre quem está ativo/descadastrado).
  3. Pra qualquer scheduled_send cujo horário de geração de rascunho já
     chegou e que ainda não tem draft: monta o conteúdo, cria a campanha
     no Brevo como rascunho (não envia) e notifica no macOS pra revisão
     no painel local — o envio de fato só acontece por ação manual lá.
"""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from database.db_manager import DBManager
from modules import brevo_client, newsletter
from utils.notifications import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.NEWSLETTER_LOG_FILE),
        logging.StreamHandler(),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")


def pick_target_time(send_date: date) -> datetime:
    """Sorteia um horário uniforme dentro da janela UK configurada."""
    start = datetime.combine(send_date, dtime(config.NEWSLETTER_WINDOW_START_HOUR_UK, 0), tzinfo=UK_TZ)
    end = datetime.combine(send_date, dtime(config.NEWSLETTER_WINDOW_END_HOUR_UK, 0), tzinfo=UK_TZ)
    offset_seconds = random.randint(0, int((end - start).total_seconds()))
    return start + timedelta(seconds=offset_seconds)


def ensure_scheduled_send_for_today(db: DBManager) -> None:
    send_date = datetime.now(UK_TZ).date()
    if db.get_scheduled_send_by_date(send_date.isoformat()) is not None:
        return

    target_time_utc = pick_target_time(send_date).astimezone(timezone.utc)
    draft_generation_time_utc = target_time_utc - timedelta(minutes=config.NEWSLETTER_DRAFT_LEAD_MINUTES)

    db.create_scheduled_send(
        send_date=send_date.isoformat(),
        target_time_utc=target_time_utc.isoformat(),
        draft_generation_time_utc=draft_generation_time_utc.isoformat(),
    )
    logger.info(
        "Horário de envio sorteado para %s: %s UTC (rascunho às %s UTC)",
        send_date,
        target_time_utc.strftime("%H:%M"),
        draft_generation_time_utc.strftime("%H:%M"),
    )


def sync_subscribers(db: DBManager) -> None:
    try:
        contacts = brevo_client.list_list_contacts()
    except Exception:
        logger.exception("Falha ao sincronizar subscribers a partir do Brevo")
        return

    for contact in contacts:
        email = contact.get("email")
        if not email:
            continue
        status = "unsubscribed" if contact.get("emailBlacklisted") else "active"
        consented_at = (contact.get("attributes") or {}).get("CONSENT_TIMESTAMP")
        db.upsert_subscriber(
            email=email,
            brevo_contact_id=contact.get("id"),
            status=status,
            consented_at=consented_at,
        )
    logger.info("Subscribers sincronizados: %d contato(s)", len(contacts))


def process_due_drafts(db: DBManager) -> None:
    now_utc = datetime.now(timezone.utc)

    for row in db.list_scheduled_sends():
        if row["status"] != "pending":
            continue

        draft_generation_time = datetime.fromisoformat(row["draft_generation_time_utc"])
        if now_utc < draft_generation_time:
            continue

        if db.has_draft_for_scheduled_send(row["id"]):
            continue

        send_date = date.fromisoformat(row["send_date"])
        content = newsletter.build_newsletter(db, send_date)

        if content is None:
            logger.warning(
                "Sem ofertas recentes o suficiente para a newsletter de %s — pulando o dia.",
                send_date,
            )
            db.update_scheduled_send(row["id"], status="cancelled")
            continue

        try:
            campaign_id = brevo_client.create_campaign_draft(content.subject, content.html)
        except Exception:
            logger.exception("Falha ao criar campanha rascunho no Brevo para %s", send_date)
            continue

        db.create_email_draft(row["id"], content.html, content.offer_ids, campaign_id)
        db.update_scheduled_send(row["id"], status="draft_created")

        logger.info(
            "Rascunho criado para %s: %d oferta(s), campaign_id=%s",
            send_date,
            len(content.offer_ids),
            campaign_id,
        )
        notify(
            "📬 Newsletter pronta para revisão",
            f"{len(content.offer_ids)} oferta(s) selecionada(s) — aprove no painel local antes do envio.",
        )


def main() -> None:
    logger.info(
        "🗓️ Agendador de newsletter iniciado. Janela UK: %02d-%02dh, poll a cada %ds.",
        config.NEWSLETTER_WINDOW_START_HOUR_UK,
        config.NEWSLETTER_WINDOW_END_HOUR_UK,
        config.NEWSLETTER_SCHEDULER_POLL_SECONDS,
    )
    poll_count = 0

    while True:
        try:
            with DBManager() as db:
                ensure_scheduled_send_for_today(db)
                if poll_count % config.NEWSLETTER_SUBSCRIBER_SYNC_EVERY_N_POLLS == 0:
                    sync_subscribers(db)
                process_due_drafts(db)
        except Exception:
            logger.exception("Erro não tratado no ciclo do agendador de newsletter.")

        poll_count += 1
        time.sleep(config.NEWSLETTER_SCHEDULER_POLL_SECONDS)


if __name__ == "__main__":
    main()
