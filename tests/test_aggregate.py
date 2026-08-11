from fitness_mcp import aggregate


def test_build_daily_sums_and_hr_stats():
    raw = {
        "steps": [
            {"start": "2024-07-01T09:00:00+05:30", "value": 3000},
            {"start": "2024-07-01T18:00:00+05:30", "value": 5000},
            {"start": "2024-07-02T10:00:00+05:30", "value": 10000},
        ],
        "distance": [{"start": "2024-07-01T09:00:00+05:30", "value": 2500.5}],
        "heart_rate": [
            {"time": "2024-07-01T09:00:00+05:30", "bpm": 60},
            {"time": "2024-07-01T09:05:00+05:30", "bpm": 80},
        ],
    }
    rows = aggregate.build_daily(raw, "2024-07-01", "2024-07-31")
    by_date = {r["date"]: r for r in rows}

    assert by_date["2024-07-01"]["steps"] == 8000
    assert by_date["2024-07-01"]["distance_m"] == 2500.5
    assert by_date["2024-07-01"]["avg_hr"] == 70.0
    assert by_date["2024-07-01"]["min_hr"] == 60
    assert by_date["2024-07-01"]["max_hr"] == 80
    assert by_date["2024-07-02"]["steps"] == 10000


def test_build_daily_respects_range():
    raw = {"steps": [{"start": "2024-06-30T09:00:00+05:30", "value": 999}]}
    assert aggregate.build_daily(raw, "2024-07-01", "2024-07-31") == []
