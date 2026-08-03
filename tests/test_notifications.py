from utils.notifications import _as_applescript_string


def test_as_applescript_string_escapes_quotes_and_backslashes():
    assert _as_applescript_string("hello") == '"hello"'
    assert _as_applescript_string('say "hi"') == '"say \\"hi\\""'
    assert _as_applescript_string("back\\slash") == '"back\\\\slash"'
