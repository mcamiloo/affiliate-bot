from utils.offer_title import clean_offer_title


def test_strips_leading_sku_tag_with_mismatched_brackets():
    title = "(A60I] PCIe Graphics Card Extension Cable"
    assert clean_offer_title(title) == "PCIe Graphics Card Extension Cable"


def test_strips_leading_sku_tag_with_matched_brackets():
    title = "[A60I] PCIe Graphics Card Extension Cable"
    assert clean_offer_title(title) == "PCIe Graphics Card Extension Cable"


def test_strips_glued_lowercase_prefix():
    title = "skBluetooth Speaker Bag LED Lights"
    assert clean_offer_title(title) == "Bluetooth Speaker Bag LED Lights"


def test_strips_leading_filler_word():
    title = "update. WiFi Tuya Smart Switch US Version"
    assert clean_offer_title(title) == "WiFi Tuya Smart Switch US Version"


def test_does_not_mangle_brand_names_starting_lowercase():
    assert clean_offer_title("iPhone 15 Pro Max Case") == "iPhone 15 Pro Max Case"
    assert clean_offer_title("eBike Battery 48V 20Ah") == "eBike Battery 48V 20Ah"


def test_does_not_strip_single_letter_lowercase_prefix():
    # a regra exige 2-3 letras — 1 letra minúscula colada é quase sempre
    # marca de verdade (iPhone, eBay), não ruído de scraper.
    assert clean_offer_title("iRobot Vacuum Cleaner").startswith("iRobot")


def test_leaves_normal_titles_untouched():
    title = "AULA SC580X Tri-mode Wireless Gaming Mouse 12000DPI"
    assert clean_offer_title(title) == title


def test_collapses_extra_whitespace():
    assert clean_offer_title("Gaming   Mouse    RGB") == "Gaming Mouse RGB"


def test_does_not_truncate_long_titles():
    # Títulos da AliExpress são normalmente bem longos (mediana real
    # ~124 caracteres) — truncar por tamanho reescreveria a maioria das
    # ofertas em vez de só limpar ruído. Isso fica pro CSS de exibição.
    title = "Realistic Long Product Title " * 5
    assert clean_offer_title(title.strip()) == title.strip()


def test_falls_back_to_original_when_cleanup_removes_everything():
    # Título que é só a tag de SKU não deve virar string vazia — melhor
    # mostrar o original bruto do que nada.
    assert clean_offer_title("(AB]") == "(AB]"
