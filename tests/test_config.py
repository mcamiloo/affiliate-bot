import config


def test_paths_are_absolute_and_under_base_dir():
    assert config.BASE_DIR.is_absolute()
    assert config.DB_PATH.parent == config.DATABASE_DIR
    assert config.LOG_FILE.parent == config.LOGS_DIR
    assert config.DATABASE_DIR.exists()
    assert config.LOGS_DIR.exists()


def test_min_discount_percent_has_sane_default():
    assert isinstance(config.MIN_DISCOUNT_PERCENT, int)
    assert 0 < config.MIN_DISCOUNT_PERCENT <= 100


def test_niche_keywords_cover_all_groups():
    assert isinstance(config.NICHE_KEYWORDS, list)
    assert len(config.NICHE_KEYWORDS) > 0
    # todas em minúsculo (comparação de filtro é case-insensitive)
    assert all(keyword == keyword.lower() for keyword in config.NICHE_KEYWORDS)
    # sem duplicatas
    assert len(config.NICHE_KEYWORDS) == len(set(config.NICHE_KEYWORDS))
    # amostras de cada grupo do nicho devem estar presentes
    for sample in ["ps5", "smart tv", "headphones", "webcam", "gaming mouse"]:
        assert sample in config.NICHE_KEYWORDS


def test_retry_backoff_settings_are_numeric_and_positive():
    assert isinstance(config.MAX_RETRIES, int) and config.MAX_RETRIES > 0
    assert config.BACKOFF_BASE_SECONDS > 0
    assert config.BACKOFF_MAX_SECONDS >= config.BACKOFF_BASE_SECONDS


def test_env_int_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("SOME_INT_VAR", "not-a-number")
    try:
        config._env_int("SOME_INT_VAR", 10)
    except ValueError as exc:
        assert "SOME_INT_VAR" in str(exc)
    else:
        raise AssertionError("esperava ValueError para valor inválido")
