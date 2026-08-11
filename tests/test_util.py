from datetime import datetime
from fitness_mcp import util


def test_to_number():
    assert util.to_number("8000") == 8000
    assert util.to_number("7500.5") == 7500.5
    assert util.to_number("") is None
    assert util.to_number("abc") is None
    assert util.to_number(42) == 42


def test_duration_and_local_date():
    assert util.duration_minutes("2024-07-01T23:00:00+05:30", "2024-07-02T07:00:00+05:30") == 480.0
    assert util.local_date("2024-07-01T23:30:00+05:30") == "2024-07-01"
    assert util.parse_dt("bad") is None


def test_first():
    assert util.first({"a": "", "b": "x"}, ["a", "b"]) == "x"
    assert util.first({}, ["a"]) is None
