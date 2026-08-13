import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, store, webhook_mapper

_MAX_BODY_BYTES = 25 * 1024 * 1024

# store kind -> field used as the upsert (dedup) key
_UPSERT_KEY = {
    "steps": "id",
    "distance": "id",
    "active_calories": "id",
    "total_calories": "id",
    "active_minutes": "id",
    "heart_rate": "id",
    "sleep": "start",
    "workouts": "start",
    "body_metrics": "date",
}


def _save_raw(raw_bytes: bytes) -> None:
    fname = f"{time.strftime('%Y%m%dT%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.json"
    (config.raw_dir() / fname).write_bytes(raw_bytes)


def ingest(payload: dict) -> dict:
    mapped = webhook_mapper.map_payload(payload)
    stored = {}
    for kind, records in mapped.items():
        stored[kind] = store.upsert(kind, records, _UPSERT_KEY[kind])
    return stored


class _Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > _MAX_BODY_BYTES:
            self._json(413, {"error": "payload too large"})
            return
        raw = self.rfile.read(length)
        _save_raw(raw)
        try:
            payload = json.loads(raw)
        except ValueError:
            self._json(400, {"error": "invalid json"})
            return
        try:
            stored = ingest(payload)
        except Exception as e:  # noqa: BLE001 - never crash the receiver on one bad payload
            print(f"ingest failed: {e}")
            self._json(500, {"error": "internal error"})
            return
        self._json(200, {"status": "ok", "stored": stored})

    def log_message(self, *args):  # silence default stderr logging
        pass


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> None:
    host, port = config.receiver_host(), config.receiver_port()
    srv = make_server(host, port)
    print(f"fitness receiver listening on http://{host}:{port}  (POST /webhook, GET /health)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
