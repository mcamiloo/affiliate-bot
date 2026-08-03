import os
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from database.db_manager import DBManager
from scripts import write_widget_snapshot as wws


@pytest.fixture
def fixed_local_tz():
    """Fixa o TZ do processo pra -03:00 (mesmo fuso do resto do projeto,
    ver Europe/London só é usado pra newsletter) — _iso_utc depende do
    fuso local da máquina via datetime.astimezone() sem argumentos."""
    original = os.environ.get("TZ")
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()
    yield
    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


def test_iso_utc_converts_naive_local_to_utc_with_z_suffix(fixed_local_tz):
    naive = datetime(2026, 8, 3, 10, 0, 0)  # 10:00 em -03:00
    assert wws._iso_utc(naive) == "2026-08-03T13:00:00Z"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    manager = DBManager(db_path=tmp_path / "test.db")
    yield manager
    manager.close()


def test_build_snapshot_shape(db, monkeypatch):
    db.save_offer(
        item_id="ITEM1",
        title="Oferta 1",
        url="https://x.com/1",
        affiliate_url="https://x.com/1?ref=1",
        price=9.99,
        original_price=19.99,
        discount_percent=50.0,
        category="setup_gamer",
    )

    monkeypatch.setattr(wws, "job_is_loaded", lambda: True)
    monkeypatch.setattr(wws, "last_successful_cycle", lambda: None)
    monkeypatch.setattr(wws, "_service_running", lambda label: False)
    monkeypatch.setattr(wws, "_whatsapp_app_running", lambda: False)

    snapshot = wws.build_snapshot()

    assert snapshot["main_bot_running"] is True
    assert snapshot["newsletter_running"] is False
    assert snapshot["last_cycle_at"] is None
    assert snapshot["last_cycle_count"] is None
    assert snapshot["offers_today"] == 1
    assert len(snapshot["latest_offers"]) == 1
    offer = snapshot["latest_offers"][0]
    assert offer["item_id"] == "ITEM1"
    assert "headline" in offer


def test_build_snapshot_excludes_hidden_offers(db, monkeypatch):
    db.save_offer(
        item_id="HIDDEN1",
        title="Escondida",
        url="https://x.com/2",
        affiliate_url="https://x.com/2?ref=1",
        price=9.99,
    )
    db.hide_offer("HIDDEN1")

    monkeypatch.setattr(wws, "job_is_loaded", lambda: True)
    monkeypatch.setattr(wws, "last_successful_cycle", lambda: None)
    monkeypatch.setattr(wws, "_service_running", lambda label: False)
    monkeypatch.setattr(wws, "_whatsapp_app_running", lambda: False)

    snapshot = wws.build_snapshot()

    assert snapshot["latest_offers"] == []


def test_build_snapshot_includes_last_cycle_when_present(db, monkeypatch, fixed_local_tz):
    monkeypatch.setattr(wws, "job_is_loaded", lambda: True)
    monkeypatch.setattr(wws, "last_successful_cycle", lambda: (datetime(2026, 8, 3, 10, 0, 0), 3))
    monkeypatch.setattr(wws, "_service_running", lambda label: True)
    monkeypatch.setattr(wws, "_whatsapp_app_running", lambda: False)

    snapshot = wws.build_snapshot()

    assert snapshot["last_cycle_at"] == "2026-08-03T13:00:00Z"
    assert snapshot["last_cycle_count"] == 3


def test_main_writes_snapshot_atomically(db, monkeypatch, tmp_path):
    import config

    snapshot_path = tmp_path / "widget_snapshot.json"
    monkeypatch.setattr(config, "WIDGET_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(wws, "job_is_loaded", lambda: True)
    monkeypatch.setattr(wws, "last_successful_cycle", lambda: None)
    monkeypatch.setattr(wws, "_service_running", lambda label: False)
    monkeypatch.setattr(wws, "_whatsapp_app_running", lambda: False)

    wws.main()

    assert snapshot_path.exists()
    assert not snapshot_path.with_suffix(".json.tmp").exists()
    import json

    data = json.loads(snapshot_path.read_text())
    assert data["main_bot_running"] is True
