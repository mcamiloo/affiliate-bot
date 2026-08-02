"""Camada de acesso ao SQLite.

Responsável por persistir as ofertas já publicadas para que o bot nunca
publique o mesmo anúncio duas vezes, mesmo depois de reiniciar (o processo
roda via launchd e pode ser reiniciado a qualquer momento).
"""

from __future__ import annotations

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
    posted_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_posted_offers_item_id ON posted_offers (item_id);
"""

# CREATE TABLE IF NOT EXISTS não adiciona colunas a uma tabela já existente
# (bancos criados antes do campo image_url) — migração idempotente à parte.
_MIGRATIONS: list[str] = [
    "ALTER TABLE posted_offers ADD COLUMN image_url TEXT;",
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
    FROM posted_offers;
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

    def count_offers(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM posted_offers;")
        return cursor.fetchone()[0]

    def get_offer_score(self, item_id: str) -> Optional[float]:
        cursor = self._conn.execute(
            "SELECT score FROM offer_scores WHERE item_id = ?;", (item_id,)
        )
        row = cursor.fetchone()
        return row["score"] if row is not None else None

    def list_offers_by_score(self, limit: int = 60) -> list[dict[str, Any]]:
        """Ofertas ordenadas por score (desc) e, a critério de desempate,
        pelas mais recentes primeiro — usado pela landing page.
        """
        cursor = self._conn.execute(
            "SELECT * FROM offer_scores ORDER BY score DESC, posted_at DESC LIMIT ?;",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DBManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
