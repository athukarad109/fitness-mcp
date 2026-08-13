import json
import os
import threading
from pathlib import Path

from . import config

_write_lock = threading.Lock()

KINDS = {
    "steps": "steps.json",
    "distance": "distance.json",
    "active_calories": "active_calories.json",
    "total_calories": "total_calories.json",
    "active_minutes": "active_minutes.json",
    "heart_rate": "heart_rate.json",
    "sleep": "sleep.json",
    "workouts": "workouts.json",
    "body_metrics": "body_metrics.json",
}


def _path(kind: str) -> Path:
    return config.data_dir() / KINDS[kind]


def _load(kind: str) -> dict:
    p = _path(kind)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def upsert(kind: str, records: list[dict], key: str) -> int:
    with _write_lock:
        data = _load(kind)
        for rec in records:
            data[str(rec[key])] = rec
        _atomic_write(_path(kind), data)
        return len(records)


def query_range(kind: str, key: str, start: str, end: str) -> list[dict]:
    data = _load(kind)
    out = [r for r in data.values() if r.get(key) is not None and start <= str(r[key])[:10] <= end]
    return sorted(out, key=lambda r: str(r[key]))


def coverage(kind: str, key: str) -> dict | None:
    data = _load(kind)
    dates = sorted(str(r[key])[:10] for r in data.values() if r.get(key) is not None)
    if not dates:
        return None
    return {"count": len(dates), "start": dates[0], "end": dates[-1]}
