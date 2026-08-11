from fitness_mcp import store


def test_upsert_idempotent_and_range(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    recs = [{"id": "a", "start": "2024-07-01T10:00:00+05:30", "value": 100},
            {"id": "b", "start": "2024-07-02T10:00:00+05:30", "value": 200}]
    assert store.upsert("steps", recs, "id") == 2
    # resend "a" with new value -> overwrite, no duplicate
    store.upsert("steps", [{"id": "a", "start": "2024-07-01T10:00:00+05:30", "value": 150}], "id")

    day1 = store.query_range("steps", "start", "2024-07-01", "2024-07-01")
    assert [r["value"] for r in day1] == [150]
    both = store.query_range("steps", "start", "2024-07-01", "2024-07-31")
    assert len(both) == 2


def test_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    assert store.coverage("sleep", "start") is None
    store.upsert("workouts", [
        {"start": "2024-07-05T06:00:00+05:30"},
        {"start": "2024-07-09T06:00:00+05:30"},
    ], "start")
    assert store.coverage("workouts", "start") == {"count": 2, "start": "2024-07-05", "end": "2024-07-09"}
