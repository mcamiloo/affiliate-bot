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
import shutil
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

SITE_TITLE = "Tech & Gaming Deals"
SITE_DESCRIPTION = "Auto-curated — real AliExpress discounts."
# Domínio de produção — usado pra canonical/OG/sitemap. Só isso muda se o
# site algum dia trocar de domínio (não vem do .env porque não é um
# segredo nem varia por ambiente — é o mesmo Netlify site sempre).
SITE_URL = "https://ombrotechwear.co.uk"


def fetch_offers(limit: int) -> list[dict]:
    # DBManager abre em modo leitura/escrita normal (não mode=ro) porque
    # também é responsável por criar/atualizar a view offer_scores — mas
    # só executa SELECTs aqui, não interfere com o bot gravando via WAL.
    with DBManager() as db:
        return db.list_offers_by_score(limit=limit)


def count_total_offers() -> int:
    """Total histórico (não só as exibidas) — vira o número de destaque
    da faixa de estatísticas do hero, pra dar sensação de volume real."""
    with DBManager() as db:
        return db.count_offers()


def render(offers: list[dict]) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("landing.html.j2")
    return template.render(
        site_title=SITE_TITLE,
        site_description=SITE_DESCRIPTION,
        offers=offers,
        highlight_threshold=HIGHLIGHT_SCORE_THRESHOLD,
        generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
        telegram_invite_link=config.TELEGRAM_CHANNEL_INVITE_LINK,
        instagram_profile_url=config.INSTAGRAM_PROFILE_URL,
        offers_total=count_total_offers(),
        current_year=datetime.now().year,
        # site_title é a tagline ("Tech & Gaming Deals"), não a marca de
        # verdade — o rodapé/copyright usa o mesmo nome do Telegram/
        # Instagram/remetente do email (BREVO_SENDER_NAME).
        brand_name=config.BREVO_SENDER_NAME,
        site_url=SITE_URL,
    )


def render_privacy() -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("privacy.html.j2")
    return template.render(
        site_title=SITE_TITLE,
        controller_name=config.BREVO_SENDER_NAME,
        controller_email=config.BREVO_SENDER_EMAIL,
        address_line1=config.NEWSLETTER_ADDRESS_LINE1,
        address_city=config.NEWSLETTER_ADDRESS_CITY,
        address_postal_code=config.NEWSLETTER_ADDRESS_POSTAL_CODE,
        address_country=config.NEWSLETTER_ADDRESS_COUNTRY,
        updated_at=datetime.now().strftime("%d %B %Y"),
        site_url=SITE_URL,
    )


def render_terms() -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("terms.html.j2")
    return template.render(
        site_title=SITE_TITLE,
        controller_name=config.BREVO_SENDER_NAME,
        controller_email=config.BREVO_SENDER_EMAIL,
        updated_at=datetime.now().strftime("%d %B %Y"),
        site_url=SITE_URL,
    )


def render_thank_you() -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("thank_you.html.j2")
    return template.render(site_title=SITE_TITLE)


def render_robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )


def render_sitemap_xml() -> str:
    # Só páginas com valor pra busca orgânica — privacy/thank-you já são
    # noindex (ver <meta name="robots"> nos templates delas), listar no
    # sitemap junto seria um sinal contraditório pros buscadores.
    urls = [
        (f"{SITE_URL}/", "hourly", "1.0"),
        (f"{SITE_URL}/terms.html", "yearly", "0.2"),
    ]
    entries = "\n".join(
        f"  <url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        for loc, freq, prio in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
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

    privacy_out = args.out.parent / "privacy.html"
    privacy_out.write_text(render_privacy(), encoding="utf-8")

    terms_out = args.out.parent / "terms.html"
    terms_out.write_text(render_terms(), encoding="utf-8")

    thank_you_out = args.out.parent / "thank-you.html"
    thank_you_out.write_text(render_thank_you(), encoding="utf-8")

    robots_out = args.out.parent / "robots.txt"
    robots_out.write_text(render_robots_txt(), encoding="utf-8")

    sitemap_out = args.out.parent / "sitemap.xml"
    sitemap_out.write_text(render_sitemap_xml(), encoding="utf-8")

    # landing.js é JS estático puro (sem Jinja) — só copia, não renderiza.
    # Externo de propósito pra permitir um CSP sem 'unsafe-inline' em
    # script-src (ver netlify.toml).
    landing_js_out = args.out.parent / "landing.js"
    shutil.copyfile(TEMPLATES_DIR / "landing.js", landing_js_out)

    with_image = sum(1 for o in offers if o["image_url"])
    print(f"✅ {len(offers)} oferta(s) renderizada(s) ({with_image} com imagem) -> {args.out}")
    print(f"✅ Página de privacidade -> {privacy_out}")
    print(f"✅ Página de termos -> {terms_out}")
    print(f"✅ Página de agradecimento -> {thank_you_out}")
    print(f"✅ robots.txt -> {robots_out}")
    print(f"✅ sitemap.xml -> {sitemap_out}")
    print(f"✅ landing.js -> {landing_js_out}")


if __name__ == "__main__":
    main()
