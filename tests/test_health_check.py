from datetime import datetime

from scripts.health_check import _as_applescript_string, last_successful_cycle


def _write_log(tmp_path, lines):
    log_file = tmp_path / "affiliate_bot.log"
    log_file.write_text("\n".join(lines) + "\n")
    return log_file


def test_last_successful_cycle_returns_none_for_missing_file(tmp_path):
    assert last_successful_cycle(log_file=tmp_path / "does_not_exist.log") is None


def test_last_successful_cycle_returns_none_when_no_matching_line(tmp_path):
    log_file = _write_log(
        tmp_path,
        ["2026-08-01 20:00:00,000 INFO modules.orchestrator: 'gaming mouse': 3 oferta(s) publicada(s)"],
    )
    assert last_successful_cycle(log_file=log_file) is None


def test_last_successful_cycle_parses_timestamp_and_count(tmp_path):
    log_file = _write_log(
        tmp_path,
        [
            "2026-08-01 18:00:03,123 INFO modules.orchestrator: "
            "Ciclo completo: 5 oferta(s) publicada(s) no total"
        ],
    )
    result = last_successful_cycle(log_file=log_file)
    assert result == (datetime(2026, 8, 1, 18, 0, 3), 5)


def test_last_successful_cycle_picks_the_most_recent_match(tmp_path):
    log_file = _write_log(
        tmp_path,
        [
            "2026-08-01 15:00:00,000 INFO modules.orchestrator: Ciclo completo: 1 oferta(s) publicada(s) no total",
            "2026-08-01 18:00:00,000 INFO modules.orchestrator: Ciclo completo: 7 oferta(s) publicada(s) no total",
        ],
    )
    result = last_successful_cycle(log_file=log_file)
    assert result == (datetime(2026, 8, 1, 18, 0, 0), 7)


def test_as_applescript_string_escapes_quotes_and_backslashes():
    assert _as_applescript_string("hello") == '"hello"'
    assert _as_applescript_string('say "hi"') == '"say \\"hi\\""'
    assert _as_applescript_string("back\\slash") == '"back\\\\slash"'
