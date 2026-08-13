from fitness_mcp import server, store


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    store.upsert("steps", [
        {"id": "a", "start": "2024-07-01T09:00:00+05:30", "value": 8000},
        {"id": "b", "start": "2024-07-02T09:00:00+05:30", "value": 10000},
    ], "id")
    store.upsert("workouts", [
        {"start": "2024-07-05T06:00:00+05:30", "activity_type": "Running", "duration_min": 30.0},
        {"start": "2024-07-06T06:00:00+05:30", "activity_type": "Cycling", "duration_min": 45.0},
    ], "start")


def test_coverage_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    assert "no data" in server.list_data_coverage()["message"]


def test_daily_and_stats(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    rows = server.get_daily_metrics("2024-07-01", "2024-07-31")
    assert [r["steps"] for r in rows] == [8000, 10000]

    stats = server.get_metric_stats("steps", "2024-07-01", "2024-07-31")
    assert stats["count"] == 2
    assert stats["min"] == 8000
    assert stats["max"] == 10000
    assert stats["avg"] == 9000.0
    assert stats["sum"] == 18000


def test_workouts_filter(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    runs = server.get_workouts("2024-07-01", "2024-07-31", activity_type="running")
    assert len(runs) == 1 and runs[0]["activity_type"] == "Running"
    assert len(server.get_workouts("2024-07-01", "2024-07-31")) == 2


def test_metric_stats_no_data(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    stats = server.get_metric_stats("calories", "2024-07-01", "2024-07-31")
    assert stats["count"] == 0 and "no data" in stats["message"]


def test_get_sleep(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    store.upsert("sleep", [
        {"start": "2024-07-03T23:00:00+05:30", "end": "2024-07-04T07:00:00+05:30", "duration_min": 480.0},
        {"start": "2024-07-04T23:00:00+05:30", "end": "2024-07-05T07:00:00+05:30", "duration_min": 480.0},
    ], "start")

    sessions = server.get_sleep("2024-07-03", "2024-07-03")
    assert len(sessions) == 1
    assert sessions[0]["start"] == "2024-07-03T23:00:00+05:30"

    all_sessions = server.get_sleep("2024-07-03", "2024-07-31")
    assert len(all_sessions) == 2
