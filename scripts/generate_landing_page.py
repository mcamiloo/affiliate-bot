"""Gera uma landing page estática (HTML autocontido) a partir das ofertas
já publicadas no Telegram, pra servir de segunda vitrine / destino de
tráfego pago.

Não faz parte do loop do bot — roda manualmente quando quiser atualizar
a página, e o resultado (dist/index.html) é o que se sobe pra um host
estático (Cloudflare Pages, Netlify, etc.).

Uso:
    python scripts/generate_landing_page.py [--limit 60] [--out dist/index.html]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinja2 import Environment, FileSystemLoader

import config
from database.db_manager import DBManager

TEMPLATES_DIR = config.BASE_DIR / "templates"
DEFAULT_OUT = config.BASE_DIR / "dist" / "index.html"
DEFAULT_LIMIT = 60

# A partir desse score (0-100) o card ganha destaque visual na página —
# mesma escala definida por config.SCORE_WEIGHTS.
HIGHLIGHT_SCORE_THRESHOLD = 75

SITE_TITLE = "Ofertas Tech & Gaming"
SITE_DESCRIPTION = "Selecionadas automaticamente — descontos reais na AliExpress."


def fetch_offers(limit: int) -> list[dict]:
    # DBManager abre em modo leitura/escrita normal (não mode=ro) porque
    # também é responsável por criar/atualizar a view offer_scores — mas
    # só executa SELECTs aqui, não interfere com o bot gravando via WAL.
    with DBManager() as db:
        return db.list_offers_by_score(limit=limit)


def render(offers: list[dict]) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("landing.html.j2")
    return template.render(
        site_title=SITE_TITLE,
        site_description=SITE_DESCRIPTION,
        offers=offers,
        highlight_threshold=HIGHLIGHT_SCORE_THRESHOLD,
        generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Quantidade máxima de ofertas na página.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Caminho do HTML gerado.")
    args = parser.parse_args()

    if not config.DB_PATH.exists():
        raise SystemExit(f"Banco não encontrado em {config.DB_PATH}")

    offers = fetch_offers(args.limit)
    html = render(offers)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    with_image = sum(1 for o in offers if o["image_url"])
    print(f"✅ {len(offers)} oferta(s) renderizada(s) ({with_image} com imagem) -> {args.out}")


if __name__ == "__main__":
    main()
