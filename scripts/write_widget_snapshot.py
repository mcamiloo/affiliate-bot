"""Materializa um JSON com o mesmo status que a Home do painel Flask mostra,
pra o widget nativo (macos-widget/) ler.

A extensão do widget roda em App Sandbox (exigência do WidgetKit no
macOS) e não pode abrir o SQLite, ler logs/.env, nem chamar
launchctl/pgrep diretamente — só tem permissão (via temporary-exception
entitlement) pra ler este único arquivo. Rodar isso é responsabilidade de
um launchd agent (com.miguelcamilo.affiliatebot.widgetsnapshot) em
intervalo curto; o widget também força um reload após pedir um ciclo
manual (ver RunCycleIntent.swift), mas a foto pode ficar até esse
intervalo desatualizada em relação ao estado real.

Mesma lógica de scripts/health_check.py e scripts/approval_panel.py
(job_is_loaded/last_successful_cycle, _service_running, _whatsapp_app_running,
count_offers_since, list_recent_offers) — sem importar approval_panel.py
aqui porque esse módulo tem efeitos colaterais pesados de import (cria o
Flask app, exige APPROVAL_PANEL_SECRET_KEY).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from database.db_manager import DBManager
from scripts.health_check import job_is_loaded, last_successful_cycle
from utils.headlines import pick_offer_headline

NEWSLETTER_LABEL = "com.miguelcamilo.affiliatebot.newsletter"


def _service_running(label: str) -> bool:
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] == label:
            return parts[0] != "-"
    return False


def _whatsapp_app_running() -> bool:
    return subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True).returncode == 0


def _iso_utc(local_naive: datetime) -> str:
    """Timestamps do log são naive no horário local da máquina (default do
    logging) — converte pra UTC com 'Z' porque é o único formato que o
    JSONDecoder(.iso8601) do Swift aceita sem ambiguidade."""
    aware_local = local_naive.astimezone()  # naive -> presume horário local da máquina
    return aware_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_snapshot() -> dict[str, Any]:
    with DBManager() as db:
        offers_today = db.count_offers_since(24)
        offers_week = db.count_offers_since(24 * 7)
        latest_offers = [o for o in db.list_recent_offers(limit=10) if not o["hidden"]][:3]

    for offer in latest_offers:
        offer["headline"] = pick_offer_headline(offer["category"], offer["item_id"])

    last_cycle = last_successful_cycle()
    last_cycle_at, last_cycle_count = last_cycle if last_cycle else (None, None)

    return {
        "main_bot_running": job_is_loaded(),
        "last_cycle_at": _iso_utc(last_cycle_at) if last_cycle_at else None,
        "last_cycle_count": last_cycle_count,
        "newsletter_running": _service_running(NEWSLETTER_LABEL),
        "whatsapp_enabled": config.WHATSAPP_ENABLED,
        "whatsapp_app_running": _whatsapp_app_running(),
        "offers_today": offers_today,
        "offers_week": offers_week,
        "latest_offers": [
            {
                "item_id": o["item_id"],
                "title": o["title"],
                "price": o["price"],
                "original_price": o["original_price"],
                "discount_percent": o["discount_percent"],
                "category": o["category"],
                "headline": o["headline"],
            }
            for o in latest_offers
        ],
    }


def main() -> None:
    snapshot = build_snapshot()
    tmp_path = config.WIDGET_SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(snapshot))
    tmp_path.replace(config.WIDGET_SNAPSHOT_PATH)


if __name__ == "__main__":
    main()
