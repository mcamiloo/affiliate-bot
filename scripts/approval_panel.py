"""Painel de aprovação da newsletter — Flask, SÓ local (bind 127.0.0.1).

Não deve nunca ser exposto publicamente: sem autenticação, porque a
segurança aqui é a própria máquina em que roda (seu Mac). Mostra a fila
de rascunhos pendentes de aprovação (com preview do HTML) e a lista de
horários agendados (criar/editar/excluir). Aprovar/rejeitar é a única
ação neste processo que fala com o Brevo pra decidir o destino de uma
campanha — o agendador (newsletter_scheduler.py) só cria rascunhos, nunca
agenda ou envia sozinho.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, redirect, render_template, request, url_for

import config
from database.db_manager import DBManager
from modules import brevo_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")

app = Flask(__name__, template_folder=str(config.BASE_DIR / "templates" / "panel"))


def _to_uk_local(iso_utc: str) -> datetime:
    return datetime.fromisoformat(iso_utc).astimezone(UK_TZ)


@app.context_processor
def _inject_helpers():
    return {"to_uk_local": _to_uk_local}


@app.route("/")
def index():
    return redirect(url_for("queue"))


@app.route("/queue")
def queue():
    with DBManager() as db:
        drafts = db.list_pending_drafts()
    for draft in drafts:
        draft["offer_ids"] = json.loads(draft["offer_ids"])
    return render_template("queue.html", drafts=drafts)


@app.route("/queue/<int:draft_id>/preview")
def preview_draft(draft_id: int):
    with DBManager() as db:
        draft = db.get_email_draft(draft_id)
    if draft is None:
        return "Rascunho não encontrado.", 404
    return draft["html_content"]


@app.route("/queue/<int:draft_id>/approve", methods=["POST"])
def approve_draft(draft_id: int):
    with DBManager() as db:
        draft = db.get_email_draft(draft_id)
        if draft is None:
            return "Rascunho não encontrado.", 404

        target_time = datetime.fromisoformat(draft["target_time_utc"])
        now = datetime.now(timezone.utc)

        try:
            if now < target_time:
                brevo_client.schedule_campaign(draft["brevo_campaign_id"], draft["target_time_utc"])
                db.update_draft_status(draft_id, "approved")
                logger.info("Draft %d agendado no Brevo para %s", draft_id, draft["target_time_utc"])
            else:
                brevo_client.send_campaign_now(draft["brevo_campaign_id"])
                db.update_draft_status(draft_id, "sent")
                logger.info("Draft %d aprovado após o horário-alvo — enviado imediatamente", draft_id)
        except Exception:
            logger.exception("Falha ao aprovar draft %d no Brevo", draft_id)
            return "Falha ao falar com o Brevo — veja os logs.", 502

    return redirect(url_for("queue"))


@app.route("/queue/<int:draft_id>/reject", methods=["POST"])
def reject_draft(draft_id: int):
    with DBManager() as db:
        draft = db.get_email_draft(draft_id)
        if draft is None:
            return "Rascunho não encontrado.", 404

        try:
            brevo_client.delete_campaign(draft["brevo_campaign_id"])
        except Exception:
            logger.exception("Falha ao cancelar campanha %s no Brevo (draft %d)", draft["brevo_campaign_id"], draft_id)

        db.update_draft_status(draft_id, "rejected")

    return redirect(url_for("queue"))


@app.route("/schedule")
def schedule():
    with DBManager() as db:
        rows = db.list_scheduled_sends()
    return render_template("schedule.html", rows=rows, today=datetime.now(UK_TZ).date().isoformat())


@app.route("/schedule/create", methods=["POST"])
def create_schedule():
    send_date = request.form["send_date"]
    local_time = request.form["local_time"]
    hour, minute = (int(part) for part in local_time.split(":"))

    target_local = datetime.combine(date.fromisoformat(send_date), dtime(hour, minute), tzinfo=UK_TZ)
    target_utc = target_local.astimezone(timezone.utc)
    draft_utc = target_utc - timedelta(minutes=config.NEWSLETTER_DRAFT_LEAD_MINUTES)

    with DBManager() as db:
        if db.get_scheduled_send_by_date(send_date) is None:
            db.create_scheduled_send(send_date, target_utc.isoformat(), draft_utc.isoformat())

    return redirect(url_for("schedule"))


@app.route("/schedule/<int:scheduled_send_id>/update", methods=["POST"])
def update_schedule(scheduled_send_id: int):
    local_time = request.form["local_time"]
    hour, minute = (int(part) for part in local_time.split(":"))

    with DBManager() as db:
        row = db.get_scheduled_send(scheduled_send_id)
        if row is None:
            return "Horário não encontrado.", 404

        send_date = date.fromisoformat(row["send_date"])
        target_local = datetime.combine(send_date, dtime(hour, minute), tzinfo=UK_TZ)
        target_utc = target_local.astimezone(timezone.utc)
        draft_utc = target_utc - timedelta(minutes=config.NEWSLETTER_DRAFT_LEAD_MINUTES)
        db.update_scheduled_send(
            scheduled_send_id,
            target_time_utc=target_utc.isoformat(),
            draft_generation_time_utc=draft_utc.isoformat(),
        )

    return redirect(url_for("schedule"))


@app.route("/schedule/<int:scheduled_send_id>/delete", methods=["POST"])
def delete_schedule(scheduled_send_id: int):
    with DBManager() as db:
        draft = db.get_draft_by_scheduled_send(scheduled_send_id)
        if draft is not None and draft["brevo_campaign_id"] and draft["status"] == "pending_approval":
            try:
                brevo_client.delete_campaign(draft["brevo_campaign_id"])
            except Exception:
                logger.exception("Falha ao cancelar campanha ao excluir scheduled_send %d", scheduled_send_id)
        db.delete_scheduled_send(scheduled_send_id)

    return redirect(url_for("schedule"))


if __name__ == "__main__":
    # Bind exclusivo em loopback — nunca 0.0.0.0. Este painel não tem
    # autenticação porque não deve ser alcançável por mais ninguém além
    # de quem está sentado neste Mac.
    app.run(host="127.0.0.1", port=config.APPROVAL_PANEL_PORT, debug=False)
