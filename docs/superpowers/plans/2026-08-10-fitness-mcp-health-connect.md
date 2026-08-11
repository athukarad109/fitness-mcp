# Fitness MCP (Health Connect push) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully-local Windows system where the `health-connect-webhook` Android app auto-pushes fitness data over the home LAN to a receiver that stores it as JSON, and Claude Desktop reads it through a local MCP server.

**Architecture:** Two long-lived PC processes share JSON files: an always-on HTTP **receiver** (writes) and a stdio **MCP server** (reads). Pure helper modules — `util`, `aggregate` (raw records → daily metrics), `webhook_mapper` (app payload → normalized records) — sit between them. No cloud, no internet exposure, no Google Fit API, no Takeout.

**Tech Stack:** Python 3.11+, `mcp` SDK (FastMCP), stdlib `http.server` for the receiver, stdlib `json`/`datetime` for mapping/aggregation, `uv` for env/deps, `pytest` for tests.

## Global Constraints

- Python `>=3.11` (`str | None` unions, `datetime.fromisoformat` offset parsing).
- No third-party runtime deps beyond `mcp` (`>=1.2.0`); receiver/mapper/aggregate use stdlib only.
- All data lives under `%LOCALAPPDATA%\fitness-mcp\` (override via `FITNESS_MCP_DATA_DIR`), never in the repo.
- Storage is JSON files only — no SQLite/database.
- All store writes are atomic (temp file + `os.replace`). The MCP server only reads; the receiver is the only writer.
- Receiver is **LAN-only**, never exposed to the internet (the app offers no webhook auth).
- Package uses a `src/` layout, importable as `fitness_mcp`.
- Units fixed and documented: distance meters (`distance_m`), duration minutes (`duration_min`), weight kg (`weight_kg`).
- Defensive mapping: unknown payload sections/fields are skipped, never fatal.
- Dedup: raw cumulative records are keyed by a stable id (Health Connect record id, else `"{start}|{end}"`) so re-synced overlapping data overwrites instead of double-counting.

> **Schema-verification note:** The `webhook_mapper` fixtures below use the app's documented shape (top-level `timestamp`/`app_version` + snake_case arrays per data type). The exact inner field names are confirmed in Task 7 by capturing a real payload (the receiver writes every payload to `%LOCALAPPDATA%\fitness-mcp\raw\`). The mapper tries multiple candidate field names per value so mismatches degrade gracefully; Task 7 adjusts candidates/fixtures if the real payload differs.

---

## File Structure

- `pyproject.toml` — project metadata, deps, pytest config.
- `src/fitness_mcp/__init__.py` — package marker.
- `src/fitness_mcp/config.py` — data dir + receiver host/port.
- `src/fitness_mcp/util.py` — shared parse/number/date helpers.
- `src/fitness_mcp/store.py` — JSON keyed store: upsert, range query, coverage.
- `src/fitness_mcp/aggregate.py` — raw cumulative records → daily metrics.
- `src/fitness_mcp/webhook_mapper.py` — app POST payload → normalized records per kind.
- `src/fitness_mcp/server.py` — FastMCP tools + `main()`.
- `src/fitness_mcp/receiver.py` — always-on HTTP receiver + `ingest()` + `main()`.
- `tests/test_store.py`, `tests/test_util.py`, `tests/test_aggregate.py`, `tests/test_mapper.py`, `tests/test_server.py`, `tests/test_receiver.py`
- `tests/fixtures/payload.json` — representative app payload.
- `README.md`

---

## Task 1: Scaffold + config

**Files:**
- Create: `pyproject.toml`, `src/fitness_mcp/__init__.py`, `src/fitness_mcp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `config.data_dir() -> pathlib.Path` (creates dir; honors `FITNESS_MCP_DATA_DIR`)
  - `config.raw_dir() -> pathlib.Path` (creates `raw/` under data dir)
  - `config.receiver_host() -> str` (default `"0.0.0.0"`, override `FITNESS_MCP_HOST`)
  - `config.receiver_port() -> int` (default `8765`, override `FITNESS_MCP_PORT`)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "fitness-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["mcp>=1.2.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/fitness_mcp"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `src/fitness_mcp/__init__.py`** (empty file)

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`

```python
from fitness_mcp import config


def test_data_and_raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path / "d"))
    assert config.data_dir() == tmp_path / "d"
    assert config.data_dir().is_dir()
    assert config.raw_dir() == tmp_path / "d" / "raw"
    assert config.raw_dir().is_dir()


def test_host_port_defaults_and_override(monkeypatch):
    monkeypatch.delenv("FITNESS_MCP_HOST", raising=False)
    monkeypatch.delenv("FITNESS_MCP_PORT", raising=False)
    assert config.receiver_host() == "0.0.0.0"
    assert config.receiver_port() == 8765
    monkeypatch.setenv("FITNESS_MCP_PORT", "9000")
    assert config.receiver_port() == 9000
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError` / missing attributes)

- [ ] **Step 5: Implement `src/fitness_mcp/config.py`**

```python
import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("FITNESS_MCP_DATA_DIR")
    if override:
        p = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(base) / "fitness-mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def raw_dir() -> Path:
    p = data_dir() / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def receiver_host() -> str:
    return os.environ.get("FITNESS_MCP_HOST", "0.0.0.0")


def receiver_port() -> int:
    return int(os.environ.get("FITNESS_MCP_PORT", "8765"))
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m uv run --extra dev pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/fitness_mcp/__init__.py src/fitness_mcp/config.py tests/test_config.py
git commit -m "feat: scaffold + config (data dir, raw dir, receiver host/port)"
```

---

## Task 2: Store (JSON keyed store)

**Files:**
- Create: `src/fitness_mcp/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `config.data_dir()`.
- Produces:
  - `store.upsert(kind: str, records: list[dict], key: str) -> int` — writes/updates records keyed by `record[key]`; returns count processed.
  - `store.query_range(kind: str, key: str, start: str, end: str) -> list[dict]` — records whose `record[key][:10]` (`YYYY-MM-DD`) is within `[start, end]`, sorted by that key.
  - `store.coverage(kind: str, key: str) -> dict | None` — `{"count", "start", "end"}` or `None` when empty.
  - `KINDS: dict[str, str]` — kind → filename.

- [ ] **Step 1: Write the failing test** — `tests/test_store.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.store`)

- [ ] **Step 3: Implement `src/fitness_mcp/store.py`**

```python
import json
import os
from pathlib import Path

from . import config

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
    data = _load(kind)
    for rec in records:
        data[str(rec[key])] = rec
    _atomic_write(_path(kind), data)
    return len(records)


def query_range(kind: str, key: str, start: str, end: str) -> list[dict]:
    data = _load(kind)
    out = [r for r in data.values() if start <= str(r[key])[:10] <= end]
    return sorted(out, key=lambda r: str(r[key]))


def coverage(kind: str, key: str) -> dict | None:
    data = _load(kind)
    if not data:
        return None
    dates = sorted(str(r[key])[:10] for r in data.values())
    return {"count": len(data), "start": dates[0], "end": dates[-1]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m uv run --extra dev pytest tests/test_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fitness_mcp/store.py tests/test_store.py
git commit -m "feat: JSON keyed store with idempotent upsert and range queries"
```

---

## Task 3: Util + aggregate (raw → daily)

**Files:**
- Create: `src/fitness_mcp/util.py`, `src/fitness_mcp/aggregate.py`
- Test: `tests/test_util.py`, `tests/test_aggregate.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `util.to_number(raw) -> int | float | None`
  - `util.parse_dt(s) -> datetime | None`
  - `util.duration_minutes(start, end) -> float | None`
  - `util.local_date(iso) -> str | None` (`YYYY-MM-DD` of the timestamp's own offset)
  - `util.first(d: dict, keys: list[str])` — first present, non-empty value
  - `aggregate.build_daily(raw_by_kind: dict[str, list[dict]], start: str, end: str) -> list[dict]` — daily rows with `date`, summed `steps`/`distance_m`/`calories`/`active_calories`/`active_minutes`, and `avg_hr`/`min_hr`/`max_hr`.

- [ ] **Step 1: Write the failing test** — `tests/test_util.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_util.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.util`)

- [ ] **Step 3: Implement `src/fitness_mcp/util.py`**

```python
from datetime import datetime


def to_number(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return raw
    s = (str(raw) if raw is not None else "").strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else round(f, 3)


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_minutes(start, end):
    a, b = parse_dt(start), parse_dt(end)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 60, 1)


def local_date(iso):
    dt = parse_dt(iso)
    return dt.date().isoformat() if dt else None


def first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None
```

- [ ] **Step 4: Write the failing test** — `tests/test_aggregate.py`

```python
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
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_aggregate.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.aggregate`)

- [ ] **Step 6: Implement `src/fitness_mcp/aggregate.py`**

```python
from collections import defaultdict

from . import util

# store kind -> daily output field for summed cumulative metrics
SUM_FIELDS = {
    "steps": "steps",
    "distance": "distance_m",
    "active_calories": "active_calories",
    "total_calories": "calories",
    "active_minutes": "active_minutes",
}


def _clean(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return round(v, 3) if isinstance(v, float) else v


def build_daily(raw_by_kind: dict, start: str, end: str) -> list[dict]:
    days: dict[str, dict] = defaultdict(dict)

    for kind, field in SUM_FIELDS.items():
        for rec in raw_by_kind.get(kind, []):
            d = util.local_date(rec.get("start"))
            if d is None or not (start <= d <= end):
                continue
            val = rec.get("value")
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                days[d][field] = days[d].get(field, 0) + val

    hr_by_day = defaultdict(list)
    for rec in raw_by_kind.get("heart_rate", []):
        d = util.local_date(rec.get("time"))
        if d is None or not (start <= d <= end):
            continue
        bpm = rec.get("bpm")
        if isinstance(bpm, (int, float)) and not isinstance(bpm, bool):
            hr_by_day[d].append(bpm)
    for d, vals in hr_by_day.items():
        days[d]["avg_hr"] = round(sum(vals) / len(vals), 1)
        days[d]["min_hr"] = min(vals)
        days[d]["max_hr"] = max(vals)

    rows = []
    for d in sorted(days):
        row = {"date": d}
        row.update({k: _clean(v) for k, v in days[d].items()})
        rows.append(row)
    return rows
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m uv run --extra dev pytest tests/test_util.py tests/test_aggregate.py -v`
Expected: PASS (5 passed)

- [ ] **Step 8: Commit**

```bash
git add src/fitness_mcp/util.py src/fitness_mcp/aggregate.py tests/test_util.py tests/test_aggregate.py
git commit -m "feat: shared util helpers + raw-to-daily aggregation"
```

---

## Task 4: Webhook mapper

**Files:**
- Create: `src/fitness_mcp/webhook_mapper.py`, `tests/fixtures/payload.json`
- Test: `tests/test_mapper.py`

**Interfaces:**
- Consumes: `util.first`, `util.to_number`, `util.duration_minutes`.
- Produces:
  - `webhook_mapper.map_payload(payload: dict) -> dict[str, list[dict]]` — keys are store kinds; raw/heart_rate records carry a stable `id`; sessions carry `start`; body carries `date`.

- [ ] **Step 1: Create fixture** — `tests/fixtures/payload.json`

```json
{
  "timestamp": "2024-07-02T00:00:00+05:30",
  "app_version": "1.0.0",
  "steps": [
    {"id": "s1", "start_time": "2024-07-01T09:00:00+05:30", "end_time": "2024-07-01T10:00:00+05:30", "count": 3000},
    {"id": "s2", "start_time": "2024-07-01T18:00:00+05:30", "end_time": "2024-07-01T19:00:00+05:30", "count": 5000}
  ],
  "distance": [
    {"id": "d1", "start_time": "2024-07-01T09:00:00+05:30", "end_time": "2024-07-01T10:00:00+05:30", "distance": 2500.5}
  ],
  "heart_rate": [
    {"time": "2024-07-01T09:00:00+05:30", "bpm": 60},
    {"time": "2024-07-01T09:05:00+05:30", "bpm": 80}
  ],
  "sleep_sessions": [
    {"start_time": "2024-07-01T23:00:00+05:30", "end_time": "2024-07-02T07:00:00+05:30"}
  ],
  "exercise_sessions": [
    {"start_time": "2024-07-01T06:00:00+05:30", "end_time": "2024-07-01T06:30:00+05:30", "exercise_type": "Running", "distance": 5000, "energy": 320}
  ],
  "weight": [
    {"time": "2024-07-01T07:00:00+05:30", "weight_kg": 70.5}
  ],
  "unknown_future_section": [{"foo": "bar"}]
}
```

- [ ] **Step 2: Write the failing test** — `tests/test_mapper.py`

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_mapper.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.webhook_mapper`)

- [ ] **Step 4: Implement `src/fitness_mcp/webhook_mapper.py`**

```python
from . import util

_START = ["start_time", "startTime", "start"]
_END = ["end_time", "endTime", "end"]
_ID = ["id", "record_id", "metadata_id", "uid"]
_TIME = ["time", "timestamp"] + _START

# store kind -> (candidate top-level array names, candidate value field names)
_CUMULATIVE = {
    "steps": (["steps", "step_count", "steps_records"], ["count", "steps", "value"]),
    "distance": (["distance", "distance_records"], ["distance", "meters", "value", "length"]),
    "active_calories": (["active_calories_burned", "active_calories"], ["energy", "calories", "kilocalories", "value"]),
    "total_calories": (["total_calories_burned", "total_calories"], ["energy", "calories", "kilocalories", "value"]),
    "active_minutes": (["active_minutes", "move_minutes", "exercise_minutes"], ["minutes", "duration", "count", "value"]),
}


def _array(payload: dict, names: list[str]) -> list:
    for n in names:
        v = payload.get(n)
        if isinstance(v, list):
            return v
    return []


def map_payload(payload: dict) -> dict:
    out: dict[str, list[dict]] = {}

    for kind, (names, value_keys) in _CUMULATIVE.items():
        recs = []
        for r in _array(payload, names):
            start = util.first(r, _START)
            val = util.to_number(util.first(r, value_keys))
            if start is None or val is None:
                continue
            end = util.first(r, _END)
            rid = util.first(r, _ID) or f"{start}|{end}"
            recs.append({"id": str(rid), "start": start, "end": end, "value": val})
        if recs:
            out[kind] = recs

    hr = []
    for r in _array(payload, ["heart_rate", "heart_rate_records", "heartrate"]):
        samples = r["samples"] if isinstance(r.get("samples"), list) else [r]
        for s in samples:
            t = util.first(s, _TIME)
            bpm = util.to_number(util.first(s, ["bpm", "beats_per_minute", "beatsPerMinute", "value"]))
            if t is None or bpm is None:
                continue
            hr.append({"id": str(t), "time": t, "bpm": bpm})
    if hr:
        out["heart_rate"] = hr

    sleep = []
    for r in _array(payload, ["sleep_sessions", "sleep", "sleep_records"]):
        start, end = util.first(r, _START), util.first(r, _END)
        if not start or not end:
            continue
        rec = {"id": str(start), "start": start, "end": end}
        dur = util.duration_minutes(start, end)
        if dur is not None:
            rec["duration_min"] = dur
        sleep.append(rec)
    if sleep:
        out["sleep"] = sleep

    workouts = []
    for r in _array(payload, ["exercise_sessions", "workouts", "exercise", "sessions"]):
        start, end = util.first(r, _START), util.first(r, _END)
        if not start or not end:
            continue
        rec = {"id": str(start), "start": start, "end": end,
               "activity_type": str(util.first(r, ["exercise_type", "type", "activity_type", "title"]) or "Unknown")}
        dur = util.duration_minutes(start, end)
        if dur is not None:
            rec["duration_min"] = dur
        dist = util.to_number(util.first(r, ["distance", "distance_m", "meters"]))
        if dist is not None:
            rec["distance_m"] = dist
        cal = util.to_number(util.first(r, ["energy", "calories", "kilocalories"]))
        if cal is not None:
            rec["calories"] = cal
        workouts.append(rec)
    if workouts:
        out["workouts"] = workouts

    body = {}
    for r in _array(payload, ["weight", "weight_records", "body"]):
        t = util.first(r, _TIME)
        w = util.to_number(util.first(r, ["weight_kg", "weight", "kilograms", "value"]))
        if t is None or w is None:
            continue
        d = str(t)[:10]
        body[d] = {"date": d, "weight_kg": w}
    if body:
        out["body_metrics"] = list(body.values())

    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m uv run --extra dev pytest tests/test_mapper.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/fitness_mcp/webhook_mapper.py tests/fixtures/payload.json tests/test_mapper.py
git commit -m "feat: map health-connect-webhook payload to normalized records"
```

---

## Task 5: MCP server tools

**Files:**
- Create: `src/fitness_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `store.query_range`, `store.coverage`, `aggregate.build_daily`.
- Produces (module-level functions, also MCP tools, directly callable in tests):
  - `list_data_coverage() -> dict`
  - `get_daily_metrics(start_date, end_date) -> list[dict]`
  - `get_sleep(start_date, end_date) -> list[dict]`
  - `get_workouts(start_date, end_date, activity_type="") -> list[dict]`
  - `get_metric_stats(metric, start_date, end_date) -> dict`
  - `main() -> None`

- [ ] **Step 1: Write the failing test** — `tests/test_server.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_server.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.server`)

- [ ] **Step 3: Implement `src/fitness_mcp/server.py`**

```python
from mcp.server.fastmcp import FastMCP

from . import aggregate, store

mcp = FastMCP("fitness")

# raw kind -> the record field carrying its timestamp (for range queries)
_RAW_DATE_FIELD = {
    "steps": "start",
    "distance": "start",
    "active_calories": "start",
    "total_calories": "start",
    "active_minutes": "start",
    "heart_rate": "time",
}

_COVERAGE = {
    "steps": "start",
    "heart_rate": "time",
    "sleep": "start",
    "workouts": "start",
    "body_metrics": "date",
}


def _daily(start_date: str, end_date: str) -> list[dict]:
    raw = {k: store.query_range(k, f, start_date, end_date) for k, f in _RAW_DATE_FIELD.items()}
    return aggregate.build_daily(raw, start_date, end_date)


@mcp.tool()
def list_data_coverage() -> dict:
    """Report which data types are present and the date range each covers."""
    cov = {k: store.coverage(k, f) for k, f in _COVERAGE.items()}
    if all(v is None for v in cov.values()):
        return {"message": "no data yet — the phone app hasn't pushed anything", "coverage": cov}
    return {"coverage": cov}


@mcp.tool()
def get_daily_metrics(start_date: str, end_date: str) -> list[dict]:
    """Daily activity rows (steps, distance, calories, active minutes, heart rate) in [start_date, end_date]."""
    return _daily(start_date, end_date)


@mcp.tool()
def get_sleep(start_date: str, end_date: str) -> list[dict]:
    """Sleep sessions starting within [start_date, end_date]."""
    return store.query_range("sleep", "start", start_date, end_date)


@mcp.tool()
def get_workouts(start_date: str, end_date: str, activity_type: str = "") -> list[dict]:
    """Workout sessions in [start_date, end_date], optionally filtered by activity_type (case-insensitive)."""
    rows = store.query_range("workouts", "start", start_date, end_date)
    if activity_type:
        want = activity_type.lower()
        rows = [r for r in rows if str(r.get("activity_type", "")).lower() == want]
    return rows


@mcp.tool()
def get_metric_stats(metric: str, start_date: str, end_date: str) -> dict:
    """min/max/avg/sum/count for a daily metric (e.g. 'steps') over [start_date, end_date]."""
    rows = _daily(start_date, end_date)
    vals = [r[metric] for r in rows if isinstance(r.get(metric), (int, float))]
    if not vals:
        return {"metric": metric, "count": 0, "message": "no data for this metric in range"}
    return {
        "metric": metric,
        "count": len(vals),
        "min": min(vals),
        "max": max(vals),
        "avg": round(sum(vals) / len(vals), 2),
        "sum": round(sum(vals), 2),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run --extra dev pytest tests/test_server.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fitness_mcp/server.py tests/test_server.py
git commit -m "feat: MCP tools reading store + daily aggregation"
```

---

## Task 6: Receiver (always-on HTTP server)

**Files:**
- Create: `src/fitness_mcp/receiver.py`
- Test: `tests/test_receiver.py`

**Interfaces:**
- Consumes: `webhook_mapper.map_payload`, `store.upsert`, `config.*`.
- Produces:
  - `receiver.ingest(payload: dict) -> dict` — maps + upserts; returns per-kind stored counts.
  - `receiver.make_server(host, port) -> http.server.ThreadingHTTPServer`
  - `receiver.main() -> None`

- [ ] **Step 1: Write the failing test** — `tests/test_receiver.py`

```python
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
    # raw payload archived for schema inspection
    assert list((tmp_path / "raw").glob("*.json"))


def test_http_health_and_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    srv = receiver.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/health")
        assert conn.getresponse().status == 200

        body = (FIX / "payload.json").read_text()
        conn.request("POST", "/webhook", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        assert json.loads(resp.read())["status"] == "ok"

        conn.request("POST", "/webhook", body="{not json", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_receiver.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.receiver`)

- [ ] **Step 3: Implement `src/fitness_mcp/receiver.py`**

```python
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, store, webhook_mapper

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
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except ValueError:
            self._json(400, {"error": "invalid json"})
            return
        _save_raw(raw)
        try:
            stored = ingest(payload)
        except Exception as e:  # noqa: BLE001 - never crash the receiver on one bad payload
            self._json(500, {"error": str(e)})
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run --extra dev pytest tests/test_receiver.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m uv run --extra dev pytest -v`
Expected: PASS (all tests green)

- [ ] **Step 6: Commit**

```bash
git add src/fitness_mcp/receiver.py tests/test_receiver.py
git commit -m "feat: always-on LAN webhook receiver"
```

---

## Task 7: Deploy, reconcile real payload, wire Claude Desktop, README

**Files:**
- Create: `README.md`
- Possibly modify: `src/fitness_mcp/webhook_mapper.py`, `tests/fixtures/payload.json` (only if the real payload differs)

**Interfaces:** none (integration, reconciliation, documentation).

- [ ] **Step 1: Give the PC a stable LAN IP + firewall rule**

- Reserve a static/DHCP-reserved IPv4 for the PC in the router (note it, e.g. `192.168.1.50`).
- Add an inbound firewall rule for the receiver port scoped to the local subnet:

```powershell
New-NetFirewallRule -DisplayName "Fitness MCP receiver" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet
```

- [ ] **Step 2: Start the receiver and self-test**

Run: `python -m uv run python -m fitness_mcp.receiver`
Then from the same PC: browse to `http://127.0.0.1:8765/health` → expect `{"status": "ok"}`.
From the phone's browser (same wifi): `http://<pc-lan-ip>:8765/health` → expect the same. If it fails, re-check the firewall rule and that host is `0.0.0.0`.

- [ ] **Step 3: Configure the phone app**

- Install `health-connect-webhook` and Health Connect; grant read permission for steps, distance, calories, active minutes, heart rate, sleep, exercise, weight.
- Set webhook URL to `http://<pc-lan-ip>:8765/webhook`.
- Enable interval sync (15 min) and tap "Sync Now".

- [ ] **Step 4: Reconcile the real payload with the mapper**

- Open the newest file in `%LOCALAPPDATA%\fitness-mcp\raw\` — this is the real payload.
- Compare its array names and record field names against `_CUMULATIVE`, the heart-rate/sleep/exercise/weight candidate lists, and `payload.json`.
- If anything differs: update the candidate name lists in `webhook_mapper.py` and update `tests/fixtures/payload.json` to match reality, then:

Run: `python -m uv run --extra dev pytest -v`
Expected: PASS. Re-trigger "Sync Now" and confirm `list_data_coverage` (next step) shows non-null ranges.

- [ ] **Step 5: Register the MCP server with Claude Desktop**

Add to `%APPDATA%\Claude\claude_desktop_config.json` (create if absent), fixing the path:

```json
{
  "mcpServers": {
    "fitness": {
      "command": "uv",
      "args": ["run", "python", "-m", "fitness_mcp.server"],
      "cwd": "D:\\Personal project\\google fit connector"
    }
  }
}
```

Fully quit and reopen Claude Desktop; confirm the `fitness` tools appear.

- [ ] **Step 6: Manual end-to-end in Claude Desktop**

Ask and verify against the data:
- "What fitness data do you have and for what dates?" (`list_data_coverage`)
- "How many steps did I average last week?" (`get_metric_stats`)
- "List my workouts this month." (`get_workouts`)
- "How did I sleep the last few nights?" (`get_sleep`)

- [ ] **Step 7: Make the receiver start with Windows**

Create a startup shortcut (Win+R → `shell:startup`) whose target launches the receiver headless:

```
Target: powershell -WindowStyle Hidden -Command "cd 'D:\Personal project\google fit connector'; uv run python -m fitness_mcp.receiver"
```

(Or an equivalent Task Scheduler "At log on" task.) Reboot and confirm `http://127.0.0.1:8765/health` responds without manually starting anything.

- [ ] **Step 8: Write `README.md`**

Document: prerequisites (Python 3.11+, `uv`, Claude Desktop); the architecture diagram; how to run the receiver and register the MCP server; the phone-app setup (URL, permissions, sync interval); the LAN IP + firewall requirement; where data is stored (`%LOCALAPPDATA%\fitness-mcp\`, including `raw/`); the list of MCP tools; and a troubleshooting note pointing to `raw/` for payload-schema issues.

- [ ] **Step 9: Commit**

```bash
git add README.md src/fitness_mcp/webhook_mapper.py tests/fixtures/payload.json
git commit -m "docs: deployment, real-payload reconciliation, Claude Desktop, README"
```

---

## Self-Review

**Spec coverage:**
- Local-only, LAN-only, no cloud/internet/Fit API → all tasks; receiver binds LAN, firewall scoped to subnet (Task 7). ✓
- Health Connect source via `health-connect-webhook`, no custom app → Task 3/4 (mapper), Task 7 (config). ✓
- Automatic pushes, no manual step → receiver (Task 6) + interval sync (Task 7). ✓
- Claude Desktop + local stdio MCP → Task 5 (`main`), Task 7 registration. ✓
- Python/FastMCP/http.server/uv/pytest → Task 1. ✓
- JSON store, atomic writes, keyed dedup upsert → Task 2. ✓
- Raw records + read-time daily aggregation → Task 3 (`aggregate.build_daily`), Task 5 (`_daily`). ✓
- All data types (steps/distance/active+total calories/active minutes/heart rate/sleep/workouts/weight) → mapper Task 4, store kinds Task 2. ✓
- Five MCP tools (coverage, daily, sleep, workouts, metric_stats), no refresh tool → Task 5. ✓
- Raw-payload capture for schema confirmation → receiver `_save_raw` (Task 6), reconciled Task 7 Step 4. ✓
- Error handling: unknown sections skipped (mapper `_array`/`first`), malformed body → 400, ingest failure → 500 not crash (Task 6), empty-data messages (Task 5). ✓
- Timezones: offset-aware parse, local-date bucketing (`util.local_date`, Task 3); documented in README (Task 7). ✓
- Ops: stable IP, firewall, startup, Claude config → Task 7. ✓
- Open questions (exact schema, id availability, sleep stages) → Task 7 Step 4. ✓

**Placeholder scan:** No TBD/TODO; every code step has runnable code; no "handle edge cases" hand-waves. ✓

**Type consistency:** `store.upsert(kind, records, key)`, `store.query_range(kind, key, start, end)`, `store.coverage(kind, key)` used identically across Tasks 2/5/6. `aggregate.build_daily(raw_by_kind, start, end)` signature matches its test and Task 5 `_daily`. Mapper output kinds match `store.KINDS` (Task 2), `_RAW_DATE_FIELD`/`_COVERAGE` (Task 5), and `_UPSERT_KEY` (Task 6). Raw records carry `id`+`start`/`time`; sessions carry `start`; body carries `date` — consistent between mapper (Task 4), aggregate date fields (Task 3), and query/upsert keys (Tasks 5/6). ✓
