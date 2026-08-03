"""Painel de aprovação da newsletter — Flask, bind local (127.0.0.1).

Alcançável de fora só via Tailscale Funnel + proxy da Netlify em
/sistema — nunca exposto direto na rede, e nunca linkado no HTML do site
principal (ver netlify.toml e README). Exige login (tabela admin_users em
database/db_manager.py) porque, diferente da v1 local-only, essa URL
pode ser alcançada por qualquer um que a descubra.

Mostra a fila de rascunhos pendentes de aprovação (com preview do HTML) e
a lista de horários agendados (criar/editar/excluir). Aprovar/rejeitar é
a única ação neste processo que fala com o Brevo pra decidir o destino de
uma campanha — o agendador (newsletter_scheduler.py) só cria rascunhos,
nunca agenda ou envia sozinho.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import config
from database.db_manager import DBManager
from modules import brevo_client, newsletter
from scripts.health_check import job_is_loaded, last_successful_cycle
from utils.headlines import pick_offer_headline
from utils.unsubscribe import compute_unsub_token, verify_unsub_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")

NEWSLETTER_LABEL = "com.miguelcamilo.affiliatebot.newsletter"
RUN_CYCLE_SCRIPT = Path(__file__).resolve().parent / "run_cycle_now.py"
_WHATSAPP_LOG_LINE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .+ no WhatsApp.*$")

# A documentação do Brevo é inconsistente sobre o valor exato do campo
# "event" no payload do webhook — exemplos oficiais mostram tanto
# camelCase (hardBounce/unsubscribed) quanto snake_case (hard_bounce/
# soft_bounced/unsubscribe) dependendo da página. Normaliza pro nome
# camelCase (o mesmo usado em templates/panel/stats.html) pra não
# depender de acertar qual convenção está em vigor.
_BREVO_EVENT_ALIASES = {
    "hard_bounce": "hardBounce",
    "soft_bounce": "softBounce",
    "soft_bounced": "softBounce",
    "unsubscribe": "unsubscribed",
}

# Bootstrap: criado uma única vez (create_admin_user_if_absent não
# sobrescreve se já existir admin) — força troca no primeiro login, então
# a senha fraca só vale até o primeiro acesso de verdade.
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "123456"

# Rotas acessíveis sem sessão — tudo mais passa pelo guard em before_request.
# As /api/* não usam cookie de sessão (widget do iPad via Scriptable não tem
# como fazer login interativo) — se autenticam sozinhas via
# _require_widget_token, então também entram aqui. newsletter_unsubscribe é
# clicada por qualquer assinante (não faz login) — se autentica pelo HMAC
# na própria URL (ver verify_unsub_token). api_brevo_webhook é o Brevo
# chamando de fora — se autentica por header secreto + allowlist de IP.
_PUBLIC_ENDPOINTS = {
    "login",
    "api_widget_snapshot",
    "api_run_cycle_now",
    "newsletter_unsubscribe",
    "api_brevo_webhook",
}

if not config.APPROVAL_PANEL_SECRET_KEY:
    raise RuntimeError(
        "APPROVAL_PANEL_SECRET_KEY não definido no .env — gere com "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
    )

if not config.WIDGET_API_TOKEN:
    raise RuntimeError(
        "WIDGET_API_TOKEN não definido no .env — gere com "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
    )

if not config.NEWSLETTER_UNSUB_SECRET:
    raise RuntimeError(
        "NEWSLETTER_UNSUB_SECRET não definido no .env — gere com "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "(a mesma chave também precisa estar nas env vars da Netlify)."
    )

if not config.BREVO_WEBHOOK_SECRET:
    raise RuntimeError(
        "BREVO_WEBHOOK_SECRET não definido no .env — gere com "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "e rode scripts/setup_brevo_webhook.py depois."
    )

app = Flask(__name__, template_folder=str(config.BASE_DIR / "templates" / "panel"))
app.secret_key = config.APPROVAL_PANEL_SECRET_KEY
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
# O Flask só enxerga HTTP puro (Tailscale Funnel e o proxy da Netlify
# terminam o TLS na frente e repassam local); sem isso, request.is_secure
# nunca seria True e o cookie Secure nunca seria de fato enviado de volta
# pelo navegador, quebrando o login pela URL pública.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=1, x_host=1)

with DBManager() as _db:
    _db.create_admin_user_if_absent(
        DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD)
    )


def _to_uk_local(iso_utc: str) -> datetime:
    return datetime.fromisoformat(iso_utc).astimezone(UK_TZ)


@app.context_processor
def _inject_helpers():
    return {"to_uk_local": _to_uk_local}


def _service_running(label: str) -> bool:
    """True se o launchd reporta um PID ativo pra esse label — mesmo
    formato compacto de `launchctl list` (PID, status, label) usado no
    dia a dia pra inspecionar os serviços na mão."""
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] == label:
            return parts[0] != "-"
    return False


def _whatsapp_app_running() -> bool:
    return subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True).returncode == 0


def _last_whatsapp_log_line() -> Optional[dict[str, Any]]:
    """Última linha do log do bot principal mencionando WhatsApp (sucesso
    ou falha — ambas já logadas por modules/whatsapp_publisher.py e
    orchestrator.py) — não há canal de log separado pro WhatsApp."""
    if not config.LOG_FILE.exists():
        return None

    last_match = None
    last_line = None
    with config.LOG_FILE.open(errors="replace") as f:
        for line in f:
            match = _WHATSAPP_LOG_LINE_RE.match(line)
            if match:
                last_match = match
                last_line = line.strip()

    if last_match is None:
        return None

    timestamp = datetime.strptime(last_match.group("ts"), "%Y-%m-%d %H:%M:%S")
    return {"timestamp": timestamp, "success": " ERROR " not in last_line, "line": last_line}


@app.before_request
def _require_login():
    if request.endpoint in _PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if "admin_user_id" not in session:
        return redirect(url_for("login"))
    if session.get("must_change_password") and request.endpoint not in {"change_password", "logout"}:
        return redirect(url_for("change_password"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "")
    password = request.form.get("password", "")

    with DBManager() as db:
        user = db.get_admin_user(username)

    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Usuário ou senha inválidos."), 401

    session.clear()
    session["admin_user_id"] = user["id"]
    session["must_change_password"] = bool(user["must_change_password"])
    return redirect(url_for("change_password") if session["must_change_password"] else url_for("home"))


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if request.method == "GET":
        return render_template("change_password.html", error=None, forced=session.get("must_change_password", False))

    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if len(new_password) < 8:
        error = "A senha precisa ter pelo menos 8 caracteres."
    elif new_password != confirm_password:
        error = "As senhas não coincidem."
    else:
        error = None

    if error:
        return render_template("change_password.html", error=error, forced=session.get("must_change_password", False)), 400

    with DBManager() as db:
        db.update_admin_password(session["admin_user_id"], generate_password_hash(new_password))
    session["must_change_password"] = False
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("home"))


@app.route("/home")
def home():
    with DBManager() as db:
        pending_drafts = len(db.list_pending_drafts())
        next_send = next(
            (row for row in db.list_scheduled_sends() if row["status"] == "pending"), None
        )
        offers_today = db.count_offers_since(24)
        offers_week = db.count_offers_since(24 * 7)
        # busca uma folga (10) e filtra ocultas no Python — não vale a pena
        # um método de DB só pra isso, é uma lista pequena.
        latest_offers = [o for o in db.list_recent_offers(limit=10) if not o["hidden"]][:3]

    for offer in latest_offers:
        offer["headline"] = pick_offer_headline(offer["category"], offer["item_id"])

    main_bot = {"running": job_is_loaded(), "last_cycle": last_successful_cycle()}
    newsletter = {"running": _service_running(NEWSLETTER_LABEL)}
    whatsapp = {
        "enabled": config.WHATSAPP_ENABLED,
        "app_running": _whatsapp_app_running(),
        "last_attempt": _last_whatsapp_log_line(),
    }

    return render_template(
        "home.html",
        main_bot=main_bot,
        newsletter=newsletter,
        whatsapp=whatsapp,
        pending_drafts=pending_drafts,
        next_send=next_send,
        offers_today=offers_today,
        offers_week=offers_week,
        latest_offers=latest_offers,
    )


@app.route("/cycle/run", methods=["POST"])
def run_cycle_now():
    subprocess.Popen([sys.executable, str(RUN_CYCLE_SCRIPT)])
    flash("Ciclo disparado — pode levar alguns minutos. Atualize a página pra ver o resultado.")
    return redirect(url_for("home"))


def _require_widget_token() -> Optional[tuple[Any, int]]:
    """Guard das rotas /api/* — sem cookie de sessão (o widget do iPad via
    Scriptable não tem como fazer login interativo), então autentica pelo
    header Authorization: Bearer <WIDGET_API_TOKEN>. compare_digest evita
    timing attack na comparação do token."""
    expected = f"Bearer {config.WIDGET_API_TOKEN}"
    provided = request.headers.get("Authorization", "")
    if not secrets.compare_digest(provided, expected):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.route("/api/widget-snapshot")
def api_widget_snapshot():
    """Serve pro widget do iPad (Scriptable) o mesmo JSON que o widget
    nativo do Mac lê localmente — ver scripts/write_widget_snapshot.py,
    que já mantém esse arquivo atualizado a cada poucos minutos."""
    if (auth_error := _require_widget_token()) is not None:
        return auth_error
    if not config.WIDGET_SNAPSHOT_PATH.exists():
        return jsonify({"error": "snapshot not ready"}), 503
    return Response(config.WIDGET_SNAPSHOT_PATH.read_text(), mimetype="application/json")


@app.route("/api/cycle/run", methods=["POST"])
def api_run_cycle_now():
    """Equivalente do botão "Rodar ciclo agora" pro widget do iPad —
    mesma ação de /cycle/run, só que autenticada por token em vez de
    sessão de login."""
    if (auth_error := _require_widget_token()) is not None:
        return auth_error
    subprocess.Popen([sys.executable, str(RUN_CYCLE_SCRIPT)])
    return jsonify({"status": "started"})


@app.route("/newsletter/unsubscribe")
def newsletter_unsubscribe():
    """Link de descadastro próprio — convive com o {{ unsubscribe }}
    nativo do Brevo no rodapé do email, não o substitui (ver
    templates/newsletter_email.html.j2). Marca localmente na hora (não
    espera o próximo sync periódico a partir do Brevo) e também bloqueia
    o contato no Brevo de fato, pra parar de receber campanhas futuras."""
    email = (request.args.get("email") or "").strip().lower()
    token = request.args.get("token") or ""

    if not email or not verify_unsub_token(email, token):
        return render_template("unsubscribed.html", ok=False), 403

    with DBManager() as db:
        db.mark_subscriber_unsubscribed(email)

    try:
        brevo_client.unsubscribe_contact(email)
    except Exception:
        logger.exception("Falha ao bloquear %s no Brevo (já marcado localmente)", email)

    return render_template("unsubscribed.html", ok=True, email=email)


def _require_brevo_webhook_auth() -> Optional[tuple[Any, int]]:
    """Guard de /api/brevo-webhook — o Brevo não assina o payload (sem
    HMAC nativo), então autentica só pelo segredo num header custom
    (configurado via scripts/setup_brevo_webhook.py, nunca na URL — evita
    vazar em log de proxy/Tailscale). Chegou a ter um allowlist de IP
    publicado pelo Brevo como segunda camada, mas foi removido: a faixa
    documentada (1.179.112.0/20) não bateu com o IP real de origem
    (172.246.240.0/20, região Europa) na primeira vez que um evento de
    verdade chegou — o Brevo já mudou de infraestrutura de rede antes
    (ver status page deles), então travar nisso é frágil. Um segredo de
    256 bits comparado em tempo constante já é autenticação forte por si
    só — mesmo padrão de confiança do WIDGET_API_TOKEN."""
    provided_secret = request.headers.get("X-Brevo-Webhook-Secret", "")
    if not secrets.compare_digest(provided_secret, config.BREVO_WEBHOOK_SECRET):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.route("/api/brevo-webhook", methods=["POST"])
def api_brevo_webhook():
    """Recebe um evento de campanha por vez (o Brevo não manda em lote) —
    ver scripts/setup_brevo_webhook.py pro registro do webhook e
    database/db_manager.py (email_events) pro que é feito com isso."""
    if (auth_error := _require_brevo_webhook_auth()) is not None:
        return auth_error

    payload = request.get_json(silent=True) or {}
    email = payload.get("email")
    event = payload.get("event")
    campaign_id = payload.get("camp_id")
    occurred_at = payload.get("date_event") or payload.get("date_sent")

    if not email or not event or not occurred_at:
        return jsonify({"error": "missing fields"}), 400

    event = _BREVO_EVENT_ALIASES.get(event, event)

    with DBManager() as db:
        db.record_email_event(campaign_id, email, event, occurred_at)

    return jsonify({"status": "recorded"})


@app.route("/offers")
def offers():
    with DBManager() as db:
        recent_offers = db.list_recent_offers()
    return render_template("offers.html", offers=recent_offers)


@app.route("/offers/<item_id>/hide", methods=["POST"])
def hide_offer(item_id: str):
    with DBManager() as db:
        db.hide_offer(item_id)
    return redirect(url_for("offers"))


@app.route("/subscribers")
def subscribers():
    search = (request.args.get("q") or "").strip()
    with DBManager() as db:
        rows = db.list_subscribers(search=search or None)
    return render_template("subscribers.html", subscribers=rows, search=search)


@app.route("/newsletter/stats")
def newsletter_stats():
    with DBManager() as db:
        campaigns = db.list_campaign_stats()

    def _rate(count: int, base: int) -> Optional[float]:
        return round(100 * count / base, 1) if base else None

    for c in campaigns:
        events = c["events"]
        delivered = events.get("delivered", 0)
        bounced = events.get("hardBounce", 0) + events.get("softBounce", 0)
        c["delivered"] = delivered
        c["bounced"] = bounced
        c["unsubscribed"] = events.get("unsubscribed", 0)
        c["open_rate"] = _rate(events.get("opened", 0), delivered)
        c["click_rate"] = _rate(events.get("click", 0), delivered)
        c["bounce_rate"] = _rate(bounced, delivered)

    totals = {
        "campaigns": len(campaigns),
        "delivered": sum(c["delivered"] for c in campaigns),
        "avg_open_rate": round(sum(c["open_rate"] or 0 for c in campaigns) / len(campaigns), 1) if campaigns else None,
        "avg_click_rate": round(sum(c["click_rate"] or 0 for c in campaigns) / len(campaigns), 1) if campaigns else None,
    }
    return render_template("stats.html", campaigns=campaigns, totals=totals)


@app.route("/newsletter/tracking")
def newsletter_tracking():
    """Nível 1 do drill-down: lista de campanhas já enviadas."""
    with DBManager() as db:
        campaigns = db.list_campaign_stats()
    return render_template("tracking_campaigns.html", campaigns=campaigns)


@app.route("/newsletter/tracking/<int:campaign_id>")
def newsletter_tracking_recipients(campaign_id: int):
    """Nível 2: destinatários dessa campanha, com status mais recente."""
    with DBManager() as db:
        recipients = db.list_campaign_recipients(campaign_id)
        campaign = db.get_campaign_summary(campaign_id)
    return render_template(
        "tracking_recipients.html", campaign_id=campaign_id, campaign=campaign, recipients=recipients
    )


@app.route("/newsletter/tracking/<int:campaign_id>/<email>")
def newsletter_tracking_events(campaign_id: int, email: str):
    """Nível 3: log completo de eventos desse destinatário nessa campanha."""
    with DBManager() as db:
        events = db.list_recipient_events(campaign_id, email)
    return render_template(
        "tracking_events.html", campaign_id=campaign_id, email=email, events=events
    )


@app.route("/queue")
def queue():
    with DBManager() as db:
        drafts = db.list_pending_drafts()
        sent_drafts = db.list_sent_drafts()
    for draft in drafts + sent_drafts:
        # offer_ids é None nos rascunhos avulsos (compose manual) — não
        # vêm de uma seleção automática de ofertas.
        draft["offer_ids"] = json.loads(draft["offer_ids"]) if draft["offer_ids"] else []
    return render_template("queue.html", drafts=drafts, sent_drafts=sent_drafts)


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

        # Rascunho avulso (compose manual) não tem target_time_utc — não
        # existe "horário sorteado" pra ele, aprovar já manda na hora.
        target_time = datetime.fromisoformat(draft["target_time_utc"]) if draft["target_time_utc"] else None
        now = datetime.now(timezone.utc)

        try:
            if target_time is not None and now < target_time:
                brevo_client.schedule_campaign(draft["brevo_campaign_id"], draft["target_time_utc"])
                db.update_draft_status(draft_id, "approved")
                logger.info("Draft %d agendado no Brevo para %s", draft_id, draft["target_time_utc"])
            else:
                brevo_client.send_campaign_now(draft["brevo_campaign_id"])
                db.update_draft_status(draft_id, "sent")
                logger.info("Draft %d aprovado — enviado imediatamente", draft_id)
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


@app.route("/queue/<int:draft_id>/test", methods=["POST"])
def send_test_draft(draft_id: int):
    """Manda uma cópia de teste (Brevo sendTest) só pra NEWSLETTER_TEST_EMAIL
    — funciona tanto pro rascunho automático diário quanto pro avulso
    (compose manual), os dois têm brevo_campaign_id assim que existem."""
    with DBManager() as db:
        draft = db.get_email_draft(draft_id)
    if draft is None:
        return "Rascunho não encontrado.", 404
    if not draft["brevo_campaign_id"]:
        return "Este rascunho ainda não tem campanha no Brevo.", 400

    try:
        brevo_client.send_test_email(draft["brevo_campaign_id"], [config.NEWSLETTER_TEST_EMAIL])
        flash(f"Teste enviado para {config.NEWSLETTER_TEST_EMAIL}.")
    except Exception:
        logger.exception("Falha ao mandar teste do draft %d", draft_id)
        flash("Falha ao mandar o teste — veja os logs.")

    return redirect(url_for("queue"))


@app.route("/queue/<int:draft_id>")
def draft_details(draft_id: int):
    with DBManager() as db:
        draft = db.get_email_draft(draft_id)
    if draft is None:
        return "Rascunho não encontrado.", 404
    draft["offer_ids"] = json.loads(draft["offer_ids"]) if draft["offer_ids"] else []
    return render_template("draft_details.html", draft=draft)


@app.route("/queue/<int:draft_id>/replicate", methods=["POST"])
def replicate_draft(draft_id: int):
    """Cria um rascunho novo (pending_approval) com o mesmo assunto/HTML —
    útil pra reenviar uma campanha aprovada/enviada em outra data sem
    reescrever do zero. Sempre cria uma campanha nova no Brevo, já que a
    original já foi decidida (agendada/enviada/cancelada)."""
    with DBManager() as db:
        draft = db.get_email_draft(draft_id)
    if draft is None:
        return "Rascunho não encontrado.", 404

    subject = f"Cópia de {draft['subject']}" if draft["subject"] else "Cópia de rascunho"
    try:
        campaign_id = brevo_client.create_campaign_draft(subject, draft["html_content"])
    except Exception:
        logger.exception("Falha ao replicar draft %d no Brevo", draft_id)
        flash("Falha ao falar com o Brevo — veja os logs.")
        return redirect(url_for("queue"))

    with DBManager() as db:
        db.create_adhoc_email_draft(subject, draft["html_content"], campaign_id)

    flash("Cópia criada — revise e aprove na fila.")
    return redirect(url_for("queue"))


@app.route("/newsletter/compose", methods=["GET", "POST"])
def compose_email():
    """Compose manual — upload/cola um HTML pronto, cria como rascunho no
    Brevo e entra na mesma fila de aprovação dos automáticos (com o botão
    de teste disponível antes de aprovar de verdade)."""
    if request.method == "GET":
        subject, html_content = "", ""
        from_draft_id = request.args.get("from_draft_id", type=int)
        if from_draft_id is not None:
            with DBManager() as db:
                source = db.get_email_draft(from_draft_id)
            if source is not None:
                subject = f"{source['subject']} (editado)" if source["subject"] else ""
                html_content = source["html_content"]
        return render_template("compose.html", error=None, subject=subject, html_content=html_content)

    subject = (request.form.get("subject") or "").strip()
    html_content = request.form.get("html_content") or ""

    uploaded_file = request.files.get("html_file")
    if uploaded_file is not None and uploaded_file.filename:
        html_content = uploaded_file.read().decode("utf-8", errors="replace")

    if not subject or not html_content.strip():
        return render_template(
            "compose.html",
            error="Preencha o assunto e o conteúdo HTML (ou envie um arquivo).",
            subject=subject,
            html_content=html_content,
        ), 400

    try:
        campaign_id = brevo_client.create_campaign_draft(subject, html_content)
    except Exception:
        logger.exception("Falha ao criar campanha rascunho no Brevo (compose manual)")
        return render_template(
            "compose.html",
            error="Falha ao falar com o Brevo — veja os logs.",
            subject=subject,
            html_content=html_content,
        ), 502

    with DBManager() as db:
        db.create_adhoc_email_draft(subject, html_content, campaign_id)

    flash("Rascunho criado — dá pra mandar um teste antes de aprovar, na fila de aprovação.")
    return redirect(url_for("queue"))


@app.route("/schedule")
def schedule():
    with DBManager() as db:
        rows = db.list_scheduled_sends()
        for row in rows:
            draft = db.get_draft_by_scheduled_send(row["id"])
            if draft is not None:
                draft["offer_count"] = len(json.loads(draft["offer_ids"])) if draft["offer_ids"] else 0
            row["draft"] = draft
        offers_available = db.list_offers_by_score(since_hours=config.NEWSLETTER_LOOKBACK_HOURS) if any(
            row["draft"] is None for row in rows
        ) else []
    return render_template(
        "schedule.html",
        rows=rows,
        today=datetime.now(UK_TZ).date().isoformat(),
        offers_available=len(offers_available),
    )


@app.route("/schedule/<int:scheduled_send_id>/generate-draft-now", methods=["POST"])
def generate_draft_now(scheduled_send_id: int):
    """Força a geração do rascunho antes do draft_generation_time_utc —
    útil pra revisar/aprovar com mais folga em vez de esperar a hora
    automática (mesma lógica de newsletter_scheduler.process_due_drafts,
    só que sob demanda pra um horário específico)."""
    with DBManager() as db:
        row = db.get_scheduled_send(scheduled_send_id)
        if row is None:
            return "Horário não encontrado.", 404
        if db.has_draft_for_scheduled_send(scheduled_send_id):
            flash("Esse horário já tem um rascunho.")
            return redirect(url_for("schedule"))

        send_date = date.fromisoformat(row["send_date"])
        content = newsletter.build_newsletter(db, send_date)
        if content is None:
            flash("Sem ofertas recentes o suficiente pra montar um rascunho agora.")
            return redirect(url_for("schedule"))

        try:
            campaign_id = brevo_client.create_campaign_draft(content.subject, content.html)
        except Exception:
            logger.exception("Falha ao criar campanha rascunho no Brevo (geração manual)")
            flash("Falha ao falar com o Brevo — veja os logs.")
            return redirect(url_for("schedule"))

        db.create_email_draft(scheduled_send_id, content.html, content.offer_ids, campaign_id)
        db.update_scheduled_send(scheduled_send_id, status="draft_created")

    flash("Rascunho gerado — já dá pra revisar na fila de aprovação.")
    return redirect(url_for("schedule"))


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
    # Bind exclusivo em loopback — nunca 0.0.0.0. O Tailscale Funnel é quem
    # decide se/como isso vira alcançável de fora, não o próprio Flask.
    app.run(host="127.0.0.1", port=config.APPROVAL_PANEL_PORT, debug=False)
