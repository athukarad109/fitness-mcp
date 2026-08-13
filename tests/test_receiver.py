import json
import http.client
import threading
from pathlib import Path
from fitness_mcp import receiver, store

FIX = Path(__file__).parent / "fixtures"


def test_ingest_populates_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    payload = json.loads((FIX / "payload.json").read_text())

    stored = receiver.ingest(payload)
    assert stored["steps"] == 2
    assert stored["sleep"] == 1
    assert stored["workouts"] == 1

    assert len(store.query_range("steps", "start", "2024-07-01", "2024-07-31")) == 2


def test_http_health_and_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    srv = receiver.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/health")
        health_resp = conn.getresponse()
        assert health_resp.status == 200
        assert json.loads(health_resp.read()) == {"status": "ok"}

        body = (FIX / "payload.json").read_text()
        conn.request("POST", "/webhook", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        assert json.loads(resp.read())["status"] == "ok"
        assert list((tmp_path / "raw").glob("*.json"))

        conn.request("POST", "/webhook", body="{not json", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
    finally:
        srv.shutdown()
        srv.server_close()
