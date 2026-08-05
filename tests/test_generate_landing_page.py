import config
from scripts.generate_landing_page import (
    HIGHLIGHT_SCORE_THRESHOLD,
    SITE_URL,
    copy_offer_images,
    render,
    render_privacy,
    render_robots_txt,
    render_sitemap_xml,
    render_terms,
    render_thank_you,
)


def _offer(**overrides):
    offer = dict(
        item_id="1",
        title="Fone Bluetooth Teste",
        url="https://example.com/1",
        affiliate_url="https://example.com/1?ref=aff",
        price=19.99,
        original_price=39.99,
        discount_percent=50.0,
        category="audio_wearables",
        image_url=None,
        score=50,
    )
    offer.update(overrides)
    return offer


def test_render_includes_all_three_channels(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHANNEL_INVITE_LINK", "https://t.me/ombrotechfinds")
    monkeypatch.setattr(config, "INSTAGRAM_PROFILE_URL", "https://www.instagram.com/ombrotechfinds")

    html = render([_offer()])

    assert "https://t.me/ombrotechfinds" in html
    assert "https://www.instagram.com/ombrotechfinds" in html
    assert 'id="subscribe"' in html


def test_render_highlights_top_pick_above_threshold():
    html = render([_offer(score=HIGHLIGHT_SCORE_THRESHOLD)])
    assert "Top pick" in html


def test_render_does_not_highlight_below_threshold():
    html = render([_offer(score=HIGHLIGHT_SCORE_THRESHOLD - 1)])
    assert "Top pick" not in html


def test_render_shows_original_price_only_when_higher():
    html = render([_offer(price=10.0, original_price=5.0)])
    # original_price menor que price não deve aparecer riscado
    assert "£5.00" not in html


def test_render_empty_state_when_no_offers():
    html = render([])
    assert "No offers published yet." in html


def test_render_privacy_and_thank_you_do_not_raise():
    assert "<html" in render_privacy()
    assert "<html" in render_thank_you()


def test_render_terms_does_not_raise_and_links_privacy():
    html = render_terms()
    assert "<html" in html
    assert 'href="privacy.html"' in html


def test_render_has_no_inline_script_tag():
    # script-src no netlify.toml não tem 'unsafe-inline' — landing.js
    # externo é o único <script> permitido; um <script> inline voltaria
    # a quebrar em produção sem que os testes percebessem.
    html = render([_offer()])
    assert '<script src="landing.js"' in html
    assert "<script>" not in html


def test_render_includes_seo_meta_tags():
    html = render([_offer()])
    assert 'rel="canonical"' in html
    assert 'property="og:title"' in html
    assert 'name="twitter:card"' in html
    assert "application/ld+json" in html


def test_render_robots_txt_references_sitemap():
    robots = render_robots_txt()
    assert "Allow: /" in robots
    assert f"Sitemap: {SITE_URL}/sitemap.xml" in robots


def test_render_uses_relative_offer_images_path_when_cached():
    html = render([_offer(image_url="https://ae01.alicdn.com/img.jpg", local_image_path="1.webp")])
    assert 'src="offer-images/1.webp"' in html
    assert "ae01.alicdn.com" not in html


def test_render_falls_back_to_original_image_url_without_cache():
    html = render([_offer(image_url="https://ae01.alicdn.com/img.jpg")])
    assert "ae01.alicdn.com" in html


def test_copy_offer_images_copies_existing_cached_files(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(config, "OFFER_IMAGE_CACHE_DIR", cache_dir)
    (cache_dir / "1.webp").write_bytes(b"fake-bytes")

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    copied = copy_offer_images([_offer(local_image_path="1.webp")], dist_dir)

    assert copied == 1
    assert (dist_dir / "offer-images" / "1.webp").read_bytes() == b"fake-bytes"


def test_copy_offer_images_skips_offers_without_local_path(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    copied = copy_offer_images([_offer()], dist_dir)

    assert copied == 0
    assert not (dist_dir / "offer-images").exists()


def test_copy_offer_images_skips_missing_cache_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OFFER_IMAGE_CACHE_DIR", tmp_path / "empty-cache")
    (tmp_path / "empty-cache").mkdir()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    copied = copy_offer_images([_offer(local_image_path="missing.webp")], dist_dir)

    assert copied == 0


def test_render_sitemap_xml_is_well_formed_and_excludes_noindex_pages():
    import xml.etree.ElementTree as ET

    sitemap = render_sitemap_xml()
    root = ET.fromstring(sitemap)  # levanta exceção se o XML for inválido
    locs = [el.text for el in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]

    assert f"{SITE_URL}/" in locs
    # privacy/thank-you são noindex — não deveriam aparecer no sitemap
    assert not any("privacy" in loc or "thank-you" in loc for loc in locs)
