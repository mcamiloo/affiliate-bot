import httpx
import pytest

import config
from utils import image_cache


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OFFER_IMAGE_CACHE_DIR", tmp_path)
    return tmp_path


def test_cache_offer_image_saves_file_and_returns_filename(monkeypatch, cache_dir):
    def fake_get(url, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=b"fake-image-bytes", headers={"content-type": "image/webp"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(image_cache.httpx, "get", fake_get)

    filename = image_cache.cache_offer_image("ITEM1", "https://ae-pic.example.com/x.jpg")

    assert filename == "ITEM1.webp"
    assert (cache_dir / "ITEM1.webp").read_bytes() == b"fake-image-bytes"


def test_cache_offer_image_returns_none_for_missing_url():
    assert image_cache.cache_offer_image("ITEM1", None) is None


def test_cache_offer_image_returns_none_on_http_error(monkeypatch, cache_dir):
    def fake_get(url, timeout=None, follow_redirects=None):
        return httpx.Response(403, content=b"blocked", request=httpx.Request("GET", url))

    monkeypatch.setattr(image_cache.httpx, "get", fake_get)

    assert image_cache.cache_offer_image("ITEM1", "https://ae-pic.example.com/x.jpg") is None
    assert list(cache_dir.iterdir()) == []


def test_cache_offer_image_returns_none_on_network_error(monkeypatch, cache_dir):
    def fake_get(url, timeout=None, follow_redirects=None):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(image_cache.httpx, "get", fake_get)

    assert image_cache.cache_offer_image("ITEM1", "https://ae-pic.example.com/x.jpg") is None


def test_cache_offer_image_returns_none_for_unexpected_content_type(monkeypatch, cache_dir):
    def fake_get(url, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=b"<html>not an image</html>", headers={"content-type": "text/html"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(image_cache.httpx, "get", fake_get)

    assert image_cache.cache_offer_image("ITEM1", "https://ae-pic.example.com/x.jpg") is None
    assert list(cache_dir.iterdir()) == []


def test_cache_offer_image_detects_jpeg_extension(monkeypatch, cache_dir):
    def fake_get(url, timeout=None, follow_redirects=None):
        return httpx.Response(200, content=b"jpeg-bytes", headers={"content-type": "image/jpeg; charset=binary"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(image_cache.httpx, "get", fake_get)

    filename = image_cache.cache_offer_image("ITEM2", "https://ae-pic.example.com/x.jpg")

    assert filename == "ITEM2.jpg"
