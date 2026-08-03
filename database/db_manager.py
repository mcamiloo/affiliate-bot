"""Camada de acesso ao SQLite.

Responsável por persistir as ofertas já publicadas para que o bot nunca
publique o mesmo anúncio duas vezes, mesmo depois de reiniciar (o processo
roda via launchd e pode ser reiniciado a qualquer momento).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posted_offers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           TEXT NOT NULL UNIQUE,
    title             TEXT NOT NULL,
    url               TEXT NOT NULL,
    affiliate_url     TEXT NOT NULL,
    price             REAL NOT NULL,
    original_price    REAL,
    discount_percent  REAL,
    category          TEXT,
    image_url         TEXT,
    hidden            INTEGER NOT NULL DEFAULT 0,
    posted_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_posted_offers_item_id ON posted_offers (item_id);

-- Espelho local dos contatos do Brevo (fonte de verdade é o Brevo — esta
-- tabela é sincronizada por pull, nunca escrita diretamente por quem
-- recebe o cadastro). Serve como registro de auditoria de consentimento
-- (UK GDPR/PECR exige poder provar quando e como o consentimento foi
-- dado, e o Brevo pode não reter esse histórico indefinidamente).
CREATE TABLE IF NOT EXISTS subscribers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT NOT NULL UNIQUE,
    brevo_contact_id  INTEGER,
    consented_at      TEXT,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unsubscribed')),
    synced_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Um horário-alvo sorteado por dia, dentro da janela UK configurada.
CREATE TABLE IF NOT EXISTS scheduled_sends (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    send_date                  TEXT NOT NULL UNIQUE,
    target_time_utc            TEXT NOT NULL,
    draft_generation_time_utc  TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'pending' CHECK (
                                    status IN ('pending', 'draft_created', 'sent', 'cancelled')
                                ),
    created_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Rascunho gerado ~1h antes do horário-alvo, aguardando aprovação manual
-- no painel local antes de ir pro Brevo de fato. scheduled_send_id é
-- opcional porque um rascunho também pode vir do compose manual
-- (/newsletter/compose) sem estar atrelado a um envio agendado do dia.
CREATE TABLE IF NOT EXISTS email_drafts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_send_id   INTEGER REFERENCES scheduled_sends (id),
    subject             TEXT,
    html_content        TEXT NOT NULL,
    offer_ids           TEXT,
    brevo_campaign_id   INTEGER,
    status              TEXT NOT NULL DEFAULT 'pending_approval' CHECK (
                            status IN ('pending_approval', 'approved', 'sent', 'rejected')
                        ),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_email_drafts_status ON email_drafts (status);

-- Login do painel de aprovação (scripts/approval_panel.py). Um único
-- usuário — este não é um sistema multi-usuário, só a forma de exigir
-- login em vez de deixar o painel aberto pra quem quer que alcance a
-- URL pública (Tailscale Funnel + proxy da Netlify em /sistema).
CREATE TABLE IF NOT EXISTS admin_users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT NOT NULL UNIQUE,
    password_hash         TEXT NOT NULL,
    must_change_password  INTEGER NOT NULL DEFAULT 1,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Eventos por destinatário reportados pelo webhook de marketing do Brevo
-- (POST /api/brevo-webhook — ver approval_panel.py) — um evento por
-- linha, um POST por evento (o Brevo não manda em lote). Sem limite de
-- 6 meses como a API de consulta do Brevo, porque fica guardado aqui.
CREATE TABLE IF NOT EXISTS email_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   INTEGER,
    email         TEXT NOT NULL,
    event         TEXT NOT NULL,
    occurred_at   TEXT NOT NULL,
    received_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_email_events_campaign ON email_events (campaign_id);
CREATE INDEX IF NOT EXISTS idx_email_events_email ON email_events (email);
"""

# CREATE TABLE IF NOT EXISTS não adiciona colunas a uma tabela já existente
# (bancos criados antes do campo image_url) — migração idempotente à parte.
_MIGRATIONS: list[str] = [
    "ALTER TABLE posted_offers ADD COLUMN image_url TEXT;",
    "ALTER TABLE posted_offers ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;",
]


def compute_score(price: float, discount_percent: Optional[float], category: Optional[str]) -> float:
    """Mesma fórmula da view offer_scores, mas em Python.

    Necessária porque o orchestrator precisa rankear ofertas candidatas
    *antes* de publicar — nesse momento elas ainda não têm linha em
    posted_offers, então a view (que consulta a tabela) não serve.
    """
    weights = config.SCORE_WEIGHTS
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"config.SCORE_WEIGHTS deve somar 1.0, soma atual: {total_weight}")

    if config.IMPULSE_PRICE_MIN <= price <= config.IMPULSE_PRICE_MAX:
        price_score = 100
    elif price < config.IMPULSE_PRICE_MIN:
        price_score = 60
    else:
        price_score = 30

    discount_score = min(discount_percent or 0, 100)
    category_score = config.CATEGORY_VISUAL_APPEAL.get(category, config.DEFAULT_VISUAL_APPEAL)

    score = (
        price_score * weights["price"]
        + discount_score * weights["discount"]
        + category_score * weights["category"]
    )
    return round(score, 1)


def _score_view_sql() -> str:
    """Monta a view offer_scores a partir dos pesos/faixas de config.py.

    Recriada (DROP + CREATE) toda vez que o schema é inicializado, pra
    refletir mudanças em config.py sem precisar de migração manual — é só
    uma fórmula, não dado persistido.
    """
    weights = config.SCORE_WEIGHTS
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"config.SCORE_WEIGHTS deve somar 1.0, soma atual: {total_weight}")

    def _sql_escape(value: str) -> str:
        return value.replace("'", "''")

    category_cases = "\n".join(
        f"                WHEN category = '{_sql_escape(category)}' THEN {appeal}"
        for category, appeal in config.CATEGORY_VISUAL_APPEAL.items()
    )

    return f"""
    DROP VIEW IF EXISTS offer_scores;
    CREATE VIEW offer_scores AS
    SELECT
        *,
        ROUND(
            CASE
                WHEN price BETWEEN {config.IMPULSE_PRICE_MIN} AND {config.IMPULSE_PRICE_MAX} THEN 100
                WHEN price < {config.IMPULSE_PRICE_MIN} THEN 60
                ELSE 30
            END * {weights['price']}
            + MIN(COALESCE(discount_percent, 0), 100) * {weights['discount']}
            + (
                CASE
{category_cases}
                ELSE {config.DEFAULT_VISUAL_APPEAL}
                END
            ) * {weights['category']}
        , 1) AS score
    FROM posted_offers
    WHERE hidden = 0;
    """


class DBManager:
    """Gerencia a conexão SQLite e as operações sobre ofertas publicadas."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else config.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL: permite leitura concorrente enquanto o processo grava, útil
        # para um serviço 24/7 que pode ter múltiplos acessos (ex.: um script
        # de inspeção manual rodando ao mesmo tempo).
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
        self._run_migrations()
        with self._conn:
            self._conn.executescript(_score_view_sql())

    def _run_migrations(self) -> None:
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(posted_offers);")}
        for statement in _MIGRATIONS:
            column = statement.split("ADD COLUMN")[1].split()[0]
            if column not in existing:
                self._conn.execute(statement)
        self._migrate_email_drafts_adhoc()

    def _migrate_email_drafts_adhoc(self) -> None:
        """Bancos criados antes do compose manual têm email_drafts com
        scheduled_send_id NOT NULL e sem coluna subject. SQLite não
        suporta remover NOT NULL via ALTER, então reconstrói a tabela
        quando detecta o formato antigo (idempotente — não faz nada se já
        migrado)."""
        info = list(self._conn.execute("PRAGMA table_info(email_drafts);"))
        scheduled_send_col = next(row for row in info if row["name"] == "scheduled_send_id")
        has_subject = any(row["name"] == "subject" for row in info)
        if not scheduled_send_col["notnull"] and has_subject:
            return

        # PRAGMA foreign_keys só tem efeito fora de uma transação ativa.
        self._conn.execute("PRAGMA foreign_keys = OFF;")
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE email_drafts_new (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_send_id   INTEGER REFERENCES scheduled_sends (id),
                    subject             TEXT,
                    html_content        TEXT NOT NULL,
                    offer_ids           TEXT,
                    brevo_campaign_id   INTEGER,
                    status              TEXT NOT NULL DEFAULT 'pending_approval' CHECK (
                                            status IN ('pending_approval', 'approved', 'sent', 'rejected')
                                        ),
                    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                    decided_at          TEXT
                );
                INSERT INTO email_drafts_new (
                    id, scheduled_send_id, html_content, offer_ids,
                    brevo_campaign_id, status, created_at, decided_at
                )
                SELECT
                    id, scheduled_send_id, html_content, offer_ids,
                    brevo_campaign_id, status, created_at, decided_at
                FROM email_drafts;
                DROP TABLE email_drafts;
                ALTER TABLE email_drafts_new RENAME TO email_drafts;
                CREATE INDEX IF NOT EXISTS idx_email_drafts_status ON email_drafts (status);
                """
            )
        self._conn.execute("PRAGMA foreign_keys = ON;")

    def is_duplicate(self, item_id: str) -> bool:
        """Retorna True se a oferta com esse item_id já foi publicada."""
        cursor = self._conn.execute(
            "SELECT 1 FROM posted_offers WHERE item_id = ? LIMIT 1;", (item_id,)
        )
        return cursor.fetchone() is not None

    def save_offer(
        self,
        item_id: str,
        title: str,
        url: str,
        affiliate_url: str,
        price: float,
        original_price: Optional[float] = None,
        discount_percent: Optional[float] = None,
        category: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> bool:
        """Persiste uma oferta publicada.

        Retorna True se a oferta foi inserida, False se já existia
        (item_id duplicado) — nesse caso nada é sobrescrito.
        """
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO posted_offers (
                        item_id, title, url, affiliate_url,
                        price, original_price, discount_percent, category, image_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        item_id,
                        title,
                        url,
                        affiliate_url,
                        price,
                        original_price,
                        discount_percent,
                        category,
                        image_url,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_offer(self, item_id: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM posted_offers WHERE item_id = ?;", (item_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def list_recent_offers(self, limit: int = 100) -> list[dict[str, Any]]:
        """Ofertas publicadas mais recentes primeiro, incluindo as ocultas —
        usado pelo painel (a landing page/newsletter usam list_offers_by_score,
        que já filtra hidden)."""
        cursor = self._conn.execute(
            "SELECT * FROM posted_offers ORDER BY posted_at DESC LIMIT ?;", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def hide_offer(self, item_id: str) -> None:
        """Some da landing page/newsletter (via offer_scores) sem apagar a
        linha — mantém o dedupe (is_duplicate) reconhecendo o item_id."""
        with self._conn:
            self._conn.execute(
                "UPDATE posted_offers SET hidden = 1 WHERE item_id = ?;", (item_id,)
            )

    def count_offers_since(self, hours: int) -> int:
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM posted_offers WHERE posted_at >= datetime('now', ?);",
            (f"-{hours} hours",),
        )
        return cursor.fetchone()[0]

    def count_offers(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM posted_offers;")
        return cursor.fetchone()[0]

    def get_offer_score(self, item_id: str) -> Optional[float]:
        cursor = self._conn.execute(
            "SELECT score FROM offer_scores WHERE item_id = ?;", (item_id,)
        )
        row = cursor.fetchone()
        return row["score"] if row is not None else None

    def list_offers_by_score(
        self, limit: int = 60, since_hours: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Ofertas ordenadas por score (desc) e, a critério de desempate,
        pelas mais recentes primeiro — usado pela landing page e pela
        newsletter (esta última passa since_hours pra só considerar
        ofertas recentes, não o catálogo inteiro).
        """
        if since_hours is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM offer_scores
                WHERE posted_at >= datetime('now', ?)
                ORDER BY score DESC, posted_at DESC LIMIT ?;
                """,
                (f"-{since_hours} hours", limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM offer_scores ORDER BY score DESC, posted_at DESC LIMIT ?;",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]

    # --- subscribers (espelho do Brevo) ---------------------------------

    def upsert_subscriber(
        self,
        email: str,
        brevo_contact_id: Optional[int],
        status: str,
        consented_at: Optional[str] = None,
    ) -> None:
        """Insere ou atualiza um assinante a partir de um pull do Brevo."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO subscribers (email, brevo_contact_id, status, consented_at, synced_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(email) DO UPDATE SET
                    brevo_contact_id = excluded.brevo_contact_id,
                    status = excluded.status,
                    consented_at = COALESCE(subscribers.consented_at, excluded.consented_at),
                    synced_at = excluded.synced_at;
                """,
                (email, brevo_contact_id, status, consented_at),
            )

    def list_active_subscribers(self) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM subscribers WHERE status = 'active' ORDER BY email;"
        )
        return [dict(row) for row in cursor.fetchall()]

    def count_active_subscribers(self) -> int:
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM subscribers WHERE status = 'active';"
        )
        return cursor.fetchone()[0]

    def list_subscribers(self, search: Optional[str] = None) -> list[dict[str, Any]]:
        """Todos os assinantes (ativos e descadastrados) — usado pela
        página /subscribers do painel, diferente de list_active_subscribers
        (que só serve pro envio de fato)."""
        if search:
            cursor = self._conn.execute(
                "SELECT * FROM subscribers WHERE email LIKE ? ORDER BY email;",
                (f"%{search}%",),
            )
        else:
            cursor = self._conn.execute("SELECT * FROM subscribers ORDER BY email;")
        return [dict(row) for row in cursor.fetchall()]

    def mark_subscriber_unsubscribed(self, email: str) -> None:
        """Reflete na hora o clique no link de descadastro próprio (ver
        utils/unsubscribe.py) — não espera o próximo sync periódico a
        partir do Brevo, que é quem também precisa ser avisado (ver
        brevo_client.unsubscribe_contact, chamado à parte)."""
        with self._conn:
            self._conn.execute(
                "UPDATE subscribers SET status = 'unsubscribed', synced_at = datetime('now') WHERE email = ?;",
                (email,),
            )

    # --- scheduled_sends --------------------------------------------------

    def get_scheduled_send_by_date(self, send_date: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM scheduled_sends WHERE send_date = ?;", (send_date,)
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def create_scheduled_send(
        self, send_date: str, target_time_utc: str, draft_generation_time_utc: str
    ) -> int:
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO scheduled_sends (send_date, target_time_utc, draft_generation_time_utc)
                VALUES (?, ?, ?);
                """,
                (send_date, target_time_utc, draft_generation_time_utc),
            )
            return cursor.lastrowid

    def list_scheduled_sends(self, limit: int = 30) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM scheduled_sends ORDER BY send_date DESC LIMIT ?;", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_scheduled_send(self, scheduled_send_id: int) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM scheduled_sends WHERE id = ?;", (scheduled_send_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def update_scheduled_send(
        self,
        scheduled_send_id: int,
        target_time_utc: Optional[str] = None,
        draft_generation_time_utc: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        fields, values = [], []
        if target_time_utc is not None:
            fields.append("target_time_utc = ?")
            values.append(target_time_utc)
        if draft_generation_time_utc is not None:
            fields.append("draft_generation_time_utc = ?")
            values.append(draft_generation_time_utc)
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if not fields:
            return
        values.append(scheduled_send_id)
        with self._conn:
            self._conn.execute(
                f"UPDATE scheduled_sends SET {', '.join(fields)} WHERE id = ?;", values
            )

    def delete_scheduled_send(self, scheduled_send_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM email_drafts WHERE scheduled_send_id = ?;", (scheduled_send_id,)
            )
            self._conn.execute(
                "DELETE FROM scheduled_sends WHERE id = ?;", (scheduled_send_id,)
            )

    # --- email_drafts -------------------------------------------------------

    def create_email_draft(
        self,
        scheduled_send_id: int,
        html_content: str,
        offer_ids: list[str],
        brevo_campaign_id: Optional[int],
    ) -> int:
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO email_drafts (scheduled_send_id, html_content, offer_ids, brevo_campaign_id)
                VALUES (?, ?, ?, ?);
                """,
                (scheduled_send_id, html_content, json.dumps(offer_ids), brevo_campaign_id),
            )
            return cursor.lastrowid

    def create_adhoc_email_draft(
        self, subject: str, html_content: str, brevo_campaign_id: Optional[int]
    ) -> int:
        """Rascunho criado manualmente via /newsletter/compose — sem
        scheduled_send_id, porque não está atrelado a um envio agendado
        do dia. Entra na mesma fila de aprovação dos automáticos."""
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO email_drafts (subject, html_content, brevo_campaign_id)
                VALUES (?, ?, ?);
                """,
                (subject, html_content, brevo_campaign_id),
            )
            return cursor.lastrowid

    def list_pending_drafts(self) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT email_drafts.*, scheduled_sends.send_date, scheduled_sends.target_time_utc
            FROM email_drafts
            LEFT JOIN scheduled_sends ON scheduled_sends.id = email_drafts.scheduled_send_id
            WHERE email_drafts.status = 'pending_approval'
            ORDER BY email_drafts.created_at;
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_email_draft(self, draft_id: int) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT email_drafts.*, scheduled_sends.send_date, scheduled_sends.target_time_utc
            FROM email_drafts
            LEFT JOIN scheduled_sends ON scheduled_sends.id = email_drafts.scheduled_send_id
            WHERE email_drafts.id = ?;
            """,
            (draft_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def has_draft_for_scheduled_send(self, scheduled_send_id: int) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM email_drafts WHERE scheduled_send_id = ? LIMIT 1;",
            (scheduled_send_id,),
        )
        return cursor.fetchone() is not None

    def get_draft_by_scheduled_send(self, scheduled_send_id: int) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM email_drafts WHERE scheduled_send_id = ? LIMIT 1;",
            (scheduled_send_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def update_draft_status(self, draft_id: int, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE email_drafts SET status = ?, decided_at = datetime('now') WHERE id = ?;",
                (status, draft_id),
            )

    # --- email_events (webhook de marketing do Brevo) -------------------

    def record_email_event(
        self, campaign_id: Optional[int], email: str, event: str, occurred_at: str
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO email_events (campaign_id, email, event, occurred_at) VALUES (?, ?, ?, ?);",
                (campaign_id, email, event, occurred_at),
            )

    def campaign_event_counts(self, campaign_id: int) -> dict[str, int]:
        """Contagem de destinatários únicos por tipo de evento — uma
        pessoa que abre o mesmo email duas vezes só conta uma vez."""
        cursor = self._conn.execute(
            "SELECT event, COUNT(DISTINCT email) AS n FROM email_events WHERE campaign_id = ? GROUP BY event;",
            (campaign_id,),
        )
        return {row["event"]: row["n"] for row in cursor.fetchall()}

    def list_campaign_stats(self, limit: int = 30) -> list[dict[str, Any]]:
        """Um resumo por rascunho já enviado ao Brevo (tem brevo_campaign_id),
        mais recente primeiro — alimenta a página de estatísticas do painel."""
        cursor = self._conn.execute(
            """
            SELECT email_drafts.id, email_drafts.subject, email_drafts.brevo_campaign_id,
                   email_drafts.decided_at, scheduled_sends.send_date
            FROM email_drafts
            LEFT JOIN scheduled_sends ON scheduled_sends.id = email_drafts.scheduled_send_id
            WHERE email_drafts.brevo_campaign_id IS NOT NULL
            ORDER BY email_drafts.decided_at DESC
            LIMIT ?;
            """,
            (limit,),
        )
        drafts = [dict(row) for row in cursor.fetchall()]
        for draft in drafts:
            draft["events"] = self.campaign_event_counts(draft["brevo_campaign_id"])
        return drafts

    def last_event_per_email(self, emails: list[str]) -> dict[str, dict[str, Any]]:
        """Evento mais recente por email — usado pra mostrar 'visto pela
        última vez' na lista de assinantes sem uma query por linha."""
        if not emails:
            return {}
        placeholders = ",".join("?" for _ in emails)
        cursor = self._conn.execute(
            f"""
            SELECT email, event, occurred_at FROM email_events
            WHERE id IN (
                SELECT MAX(id) FROM email_events WHERE email IN ({placeholders}) GROUP BY email
            );
            """,
            emails,
        )
        return {row["email"]: {"event": row["event"], "occurred_at": row["occurred_at"]} for row in cursor.fetchall()}

    # --- admin_users (login do painel) --------------------------------

    def get_admin_user(self, username: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM admin_users WHERE username = ?;", (username,)
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def create_admin_user_if_absent(
        self, username: str, password_hash: str, must_change_password: bool = True
    ) -> None:
        """Não faz nada se já existir algum admin — seed único de bootstrap,
        pra não sobrescrever uma senha já trocada em execuções seguintes."""
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO admin_users (username, password_hash, must_change_password) "
                "VALUES (?, ?, ?);",
                (username, password_hash, int(must_change_password)),
            )

    def update_admin_password(self, user_id: int, password_hash: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE admin_users SET password_hash = ?, must_change_password = 0, "
                "updated_at = datetime('now') WHERE id = ?;",
                (password_hash, user_id),
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DBManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
