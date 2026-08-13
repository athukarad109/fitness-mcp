import json
from pathlib import Path
from fitness_mcp import webhook_mapper

FIX = Path(__file__).parent / "fixtures"


def test_map_payload():
    payload = json.loads((FIX / "payload.json").read_text())
    out = webhook_mapper.map_payload(payload)

    assert {r["id"] for r in out["steps"]} == {"s1", "s2"}
    assert out["steps"][0]["value"] in (3000, 5000)
    assert out["distance"][0]["value"] == 2500.5

    assert len(out["heart_rate"]) == 2
    assert out["heart_rate"][0]["bpm"] == 60
    assert out["heart_rate"][0]["id"] == out["heart_rate"][0]["time"]

    assert out["sleep"][0]["duration_min"] == 480.0
    assert out["sleep"][0]["id"] == out["sleep"][0]["start"]

    w = out["workouts"][0]
    assert w["activity_type"] == "Running"
    assert w["duration_min"] == 30.0
    assert w["distance_m"] == 5000
    assert w["calories"] == 320

    assert out["body_metrics"][0] == {"date": "2024-07-01", "weight_kg": 70.5}

    # unknown section ignored, no crash
    assert "unknown_future_section" not in out


def test_map_payload_missing_id_uses_composite_key():
    payload = {"steps": [{"start_time": "2024-07-01T09:00:00+05:30",
                           "end_time": "2024-07-01T10:00:00+05:30", "count": 100}]}
    out = webhook_mapper.map_payload(payload)
    assert out["steps"][0]["id"] == "2024-07-01T09:00:00+05:30|2024-07-01T10:00:00+05:30"


def test_map_payload_empty():
    assert webhook_mapper.map_payload({"timestamp": "x", "app_version": "1"}) == {}
