# Fitness MCP Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python MCP server on Windows that imports Google Fit data from a Takeout export into local JSON files and exposes it to Claude Desktop as query tools.

**Architecture:** Four isolated components — `config` (paths), `parser` (Takeout files → normalized records), `store` (JSON read/write/upsert/query, the shared contract Phase 2 reuses), and `server` (FastMCP tools + a CLI importer). Everything runs locally over stdio; no cloud, no network, no database.

**Tech Stack:** Python 3.11+, `mcp` SDK (FastMCP), `uv` for env/deps, `pytest` for tests, standard-library `csv`/`json`/`xml.etree`/`datetime` for parsing.

## Global Constraints

- Python `>=3.11` (uses `str | None` unions and `datetime.fromisoformat` offset parsing).
- No third-party runtime deps beyond `mcp` (`>=1.2.0`); parsing uses stdlib only.
- All data lives under `%LOCALAPPDATA%\fitness-mcp\` (override via `FITNESS_MCP_DATA_DIR` env var), never in the repo.
- Storage is JSON files only — **no SQLite, no database engine**.
- All store writes are atomic (temp file + `os.replace`).
- Package uses a `src/` layout: importable as `fitness_mcp`.
- Units are fixed and documented: distance in meters (`distance_m`), duration in minutes (`duration_min`), weight in kg (`weight_kg`).
- Parsing is defensive: a missing/renamed column or a single bad file must never abort a whole import.

> **Format-verification note:** Fixtures below follow the documented Google Takeout "Fit" layout (combined `Daily activity metrics.csv`, `Activities/*.tcx`, session `*.json` with `fitnessActivity`). Google has changed this format over time. During Task 6's manual E2E, reconcile fixtures against a real export from the user and adjust `DAILY_COLUMN_MAP` / discovery globs if column names or paths differ. The defensive parsing means mismatches degrade gracefully (fields skipped) rather than crashing.

---

## File Structure

- `pyproject.toml` — project metadata, deps, pytest config.
- `src/fitness_mcp/__init__.py` — package marker.
- `src/fitness_mcp/config.py` — path resolution + remembered Takeout folder.
- `src/fitness_mcp/store.py` — JSON keyed store: upsert, range query, coverage.
- `src/fitness_mcp/parser.py` — pure Takeout parsers (daily CSV, body, TCX workouts, sleep JSON).
- `src/fitness_mcp/importer.py` — orchestrates discovery + parse + store; used by CLI and MCP refresh.
- `src/fitness_mcp/server.py` — FastMCP app + tools + `main()`.
- `src/fitness_mcp/__main__.py` — CLI entry: `import <folder>` or launch server.
- `tests/test_config.py`, `tests/test_store.py`, `tests/test_parser.py`, `tests/test_importer.py`, `tests/test_server.py`
- `tests/fixtures/` — `daily.csv`, `workout.tcx`, `sleep.json`

---

## Task 1: Project scaffold + config module

**Files:**
- Create: `pyproject.toml`, `src/fitness_mcp/__init__.py`, `src/fitness_mcp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `config.data_dir() -> pathlib.Path` (creates the dir; honors `FITNESS_MCP_DATA_DIR`)
  - `config.config_path() -> pathlib.Path`
  - `config.get_takeout_folder() -> str | None`
  - `config.set_takeout_folder(folder: str) -> None`

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
import json
from fitness_mcp import config


def test_data_dir_honors_env_and_creates(tmp_path, monkeypatch):
    target = tmp_path / "fmcp"
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(target))
    d = config.data_dir()
    assert d == target
    assert d.is_dir()


def test_takeout_folder_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    assert config.get_takeout_folder() is None
    config.set_takeout_folder(r"D:\exports\Takeout")
    assert config.get_takeout_folder() == r"D:\exports\Takeout"
    # persisted as JSON on disk
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["takeout_folder"] == r"D:\exports\Takeout"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError` / `AttributeError: config has no attribute data_dir`)

- [ ] **Step 5: Implement `src/fitness_mcp/config.py`**

```python
import json
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


def config_path() -> Path:
    return data_dir() / "config.json"


def _load() -> dict:
    cp = config_path()
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    return {}


def get_takeout_folder() -> str | None:
    return _load().get("takeout_folder")


def set_takeout_folder(folder: str) -> None:
    data = _load()
    data["takeout_folder"] = folder
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/fitness_mcp/__init__.py src/fitness_mcp/config.py tests/test_config.py
git commit -m "feat: project scaffold + config module"
```

---

## Task 2: Store module (JSON keyed store)

**Files:**
- Create: `src/fitness_mcp/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `config.data_dir()`.
- Produces:
  - `store.upsert(kind: str, records: list[dict], key: str) -> int` — writes/updates records keyed by `record[key]`; returns count processed.
  - `store.query_range(kind: str, key: str, start: str, end: str) -> list[dict]` — records whose `record[key][:10]` (a `YYYY-MM-DD`) is within `[start, end]`, sorted by key.
  - `store.coverage(kind: str, key: str) -> dict | None` — `{"count": int, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}` or `None` if empty.
  - `KINDS: dict[str, str]` — maps kind → filename.

- [ ] **Step 1: Write the failing test** — `tests/test_store.py`

```python
from fitness_mcp import store


def test_upsert_is_idempotent_and_queryable(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    rows = [{"date": "2024-07-01", "steps": 8000}, {"date": "2024-07-02", "steps": 10000}]
    assert store.upsert("daily_metrics", rows, "date") == 2
    # re-import same keys -> no duplicates
    store.upsert("daily_metrics", [{"date": "2024-07-01", "steps": 9999}], "date")

    got = store.query_range("daily_metrics", "date", "2024-07-01", "2024-07-01")
    assert got == [{"date": "2024-07-01", "steps": 9999}]

    both = store.query_range("daily_metrics", "date", "2024-07-01", "2024-07-31")
    assert [r["date"] for r in both] == ["2024-07-01", "2024-07-02"]


def test_range_matches_datetime_keys_by_date_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    store.upsert("workouts", [{"start": "2024-07-05T06:30:00.000+05:30"}], "start")
    got = store.query_range("workouts", "start", "2024-07-05", "2024-07-05")
    assert len(got) == 1


def test_coverage_reports_span_or_none(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    assert store.coverage("sleep", "start") is None
    store.upsert("daily_metrics", [{"date": "2024-07-01"}, {"date": "2024-07-03"}], "date")
    cov = store.coverage("daily_metrics", "date")
    assert cov == {"count": 2, "start": "2024-07-01", "end": "2024-07-03"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.store`)

- [ ] **Step 3: Implement `src/fitness_mcp/store.py`**

```python
import json
import os
from pathlib import Path

from . import config

KINDS = {
    "daily_metrics": "daily_metrics.json",
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

Run: `uv run --extra dev pytest tests/test_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fitness_mcp/store.py tests/test_store.py
git commit -m "feat: JSON keyed store with idempotent upsert and range queries"
```

---

## Task 3: Parser — daily activity metrics + body metrics

**Files:**
- Create: `src/fitness_mcp/parser.py`, `tests/fixtures/daily.csv`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: nothing (pure functions over file paths).
- Produces:
  - `parser.parse_daily_metrics(csv_path) -> list[dict]` — one record per row, keyed field `date` (`YYYY-MM-DD`), optional numeric fields `steps`, `distance_m`, `calories`, `active_minutes`, `avg_hr`, `min_hr`, `max_hr` (absent when blank/missing).
  - `parser.parse_body_metrics(csv_path) -> list[dict]` — records with `date` and optional `weight_kg` (rows with no body data omitted).

- [ ] **Step 1: Create fixture** — `tests/fixtures/daily.csv`

```csv
Date,Step count,Distance (m),Calories (kcal),Move Minutes count,Average heart rate (bpm),Min heart rate (bpm),Max heart rate (bpm),Average weight (kg)
2024-07-01,8000,6000,2200,45,72,58,150,70.5
2024-07-02,10000,7500.5,2400,60,,,,
```

- [ ] **Step 2: Write the failing test** — `tests/test_parser.py`

```python
from pathlib import Path
from fitness_mcp import parser

FIX = Path(__file__).parent / "fixtures"


def test_parse_daily_metrics_maps_and_skips_blanks():
    rows = parser.parse_daily_metrics(FIX / "daily.csv")
    by_date = {r["date"]: r for r in rows}

    d1 = by_date["2024-07-01"]
    assert d1["steps"] == 8000
    assert d1["distance_m"] == 6000
    assert d1["calories"] == 2200
    assert d1["active_minutes"] == 45
    assert d1["avg_hr"] == 72

    d2 = by_date["2024-07-02"]
    assert d2["steps"] == 10000
    assert d2["distance_m"] == 7500.5
    # blank HR columns are omitted, not zero
    assert "avg_hr" not in d2


def test_parse_body_metrics_only_rows_with_weight():
    rows = parser.parse_body_metrics(FIX / "daily.csv")
    by_date = {r["date"]: r for r in rows}
    assert by_date["2024-07-01"]["weight_kg"] == 70.5
    assert "2024-07-02" not in by_date  # no weight -> omitted
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_parser.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.parser`)

- [ ] **Step 4: Implement `src/fitness_mcp/parser.py`** (daily + body portion)

```python
import csv
from pathlib import Path

DAILY_COLUMN_MAP = {
    "steps": ["Step count"],
    "distance_m": ["Distance (m)"],
    "calories": ["Calories (kcal)"],
    "active_minutes": ["Move Minutes count"],
    "avg_hr": ["Average heart rate (bpm)"],
    "min_hr": ["Min heart rate (bpm)"],
    "max_hr": ["Max heart rate (bpm)"],
}

BODY_COLUMN_MAP = {
    "weight_kg": ["Average weight (kg)"],
}


def _to_number(raw):
    s = (raw or "").strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else round(f, 3)


def _map_row(row: dict, column_map: dict) -> dict:
    out = {}
    for field, candidates in column_map.items():
        for col in candidates:
            if col in row:
                val = _to_number(row[col])
                if val is not None:
                    out[field] = val
                break
    return out


def _read_daily_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def parse_daily_metrics(csv_path) -> list[dict]:
    records = []
    for row in _read_daily_rows(csv_path):
        date = (row.get("Date") or "").strip()
        if not date:
            continue
        rec = {"date": date}
        rec.update(_map_row(row, DAILY_COLUMN_MAP))
        records.append(rec)
    return records


def parse_body_metrics(csv_path) -> list[dict]:
    records = []
    for row in _read_daily_rows(csv_path):
        date = (row.get("Date") or "").strip()
        if not date:
            continue
        body = _map_row(row, BODY_COLUMN_MAP)
        if body:
            records.append({"date": date, **body})
    return records
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_parser.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/fitness_mcp/parser.py tests/fixtures/daily.csv tests/test_parser.py
git commit -m "feat: parse Takeout daily activity + body metrics CSV"
```

---

## Task 4: Parser — workouts (TCX) + sleep sessions (JSON)

**Files:**
- Modify: `src/fitness_mcp/parser.py` (append functions)
- Create: `tests/fixtures/workout.tcx`, `tests/fixtures/sleep.json`
- Modify: `tests/test_parser.py` (append tests)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parser.parse_workout_tcx(tcx_path) -> dict | None` — keyed field `start` (ISO datetime from `<Id>`), plus `end`, `activity_type`, `duration_min`, optional `distance_m`, `calories`. Returns `None` if no activity/lap.
  - `parser.parse_sleep_session(json_path) -> dict | None` — for session JSON with `fitnessActivity == "sleep"`: keyed field `start`, plus `end`, `duration_min`. Returns `None` for non-sleep or malformed sessions.

- [ ] **Step 1: Create fixture** — `tests/fixtures/workout.tcx`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-07-05T06:30:00.000+05:30</Id>
      <Lap StartTime="2024-07-05T06:30:00.000+05:30">
        <TotalTimeSeconds>1800</TotalTimeSeconds>
        <DistanceMeters>5000</DistanceMeters>
        <Calories>320</Calories>
        <Track>
          <Trackpoint><Time>2024-07-05T06:30:00.000+05:30</Time></Trackpoint>
          <Trackpoint><Time>2024-07-05T07:00:00.000+05:30</Time></Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
```

- [ ] **Step 2: Create fixture** — `tests/fixtures/sleep.json`

```json
{
  "fitnessActivity": "sleep",
  "startTime": "2024-07-01T23:00:00.000+05:30",
  "endTime": "2024-07-02T07:00:00.000+05:30"
}
```

- [ ] **Step 3: Write the failing tests** — append to `tests/test_parser.py`

```python
def test_parse_workout_tcx():
    rec = parser.parse_workout_tcx(FIX / "workout.tcx")
    assert rec["start"] == "2024-07-05T06:30:00.000+05:30"
    assert rec["end"] == "2024-07-05T07:00:00.000+05:30"
    assert rec["activity_type"] == "Running"
    assert rec["duration_min"] == 30.0
    assert rec["distance_m"] == 5000
    assert rec["calories"] == 320


def test_parse_sleep_session():
    rec = parser.parse_sleep_session(FIX / "sleep.json")
    assert rec["start"] == "2024-07-01T23:00:00.000+05:30"
    assert rec["end"] == "2024-07-02T07:00:00.000+05:30"
    assert rec["duration_min"] == 480.0


def test_parse_sleep_session_ignores_non_sleep(tmp_path):
    p = tmp_path / "run.json"
    p.write_text('{"fitnessActivity": "running", "startTime": "x", "endTime": "y"}')
    assert parser.parse_sleep_session(p) is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_parser.py -k "tcx or sleep" -v`
Expected: FAIL (`AttributeError: module 'fitness_mcp.parser' has no attribute 'parse_workout_tcx'`)

- [ ] **Step 5: Implement — append to `src/fitness_mcp/parser.py`**

```python
import json
import xml.etree.ElementTree as ET
from datetime import datetime

_TCX_NS = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_minutes(start, end):
    a, b = _parse_dt(start), _parse_dt(end)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 60, 1)


def parse_workout_tcx(tcx_path) -> dict | None:
    root = ET.parse(tcx_path).getroot()
    act = root.find(".//t:Activity", _TCX_NS)
    if act is None:
        return None
    laps = act.findall("t:Lap", _TCX_NS)
    if not laps:
        return None
    start = act.findtext("t:Id", None, _TCX_NS) or laps[0].get("StartTime")
    total_seconds = sum(float(l.findtext("t:TotalTimeSeconds", "0", _TCX_NS) or 0) for l in laps)
    total_distance = sum(float(l.findtext("t:DistanceMeters", "0", _TCX_NS) or 0) for l in laps)
    total_cal = sum(float(l.findtext("t:Calories", "0", _TCX_NS) or 0) for l in laps)
    times = act.findall(".//t:Trackpoint/t:Time", _TCX_NS)
    rec = {
        "start": start,
        "end": times[-1].text if times else None,
        "activity_type": act.get("Sport") or "Unknown",
        "duration_min": round(total_seconds / 60, 1),
    }
    if total_distance:
        rec["distance_m"] = int(total_distance) if total_distance.is_integer() else round(total_distance, 1)
    if total_cal:
        rec["calories"] = int(total_cal) if total_cal.is_integer() else round(total_cal, 1)
    return rec


def parse_sleep_session(json_path) -> dict | None:
    try:
        d = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if d.get("fitnessActivity") != "sleep":
        return None
    start, end = d.get("startTime"), d.get("endTime")
    if not start or not end:
        return None
    rec = {"start": start, "end": end}
    dur = _duration_minutes(start, end)
    if dur is not None:
        rec["duration_min"] = dur
    return rec
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_parser.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add src/fitness_mcp/parser.py tests/fixtures/workout.tcx tests/fixtures/sleep.json tests/test_parser.py
git commit -m "feat: parse Takeout workout TCX and sleep session JSON"
```

---

## Task 5: Importer (discovery + orchestration)

**Files:**
- Create: `src/fitness_mcp/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `parser.*`, `store.upsert`, `config.set_takeout_folder`.
- Produces:
  - `importer.import_takeout(folder: str) -> dict` — discovers Fit files under `folder`, parses, upserts, remembers the folder, and returns a summary `{"daily_metrics": int, "body_metrics": int, "workouts": int, "sleep": int, "errors": list[str]}`.

- [ ] **Step 1: Write the failing test** — `tests/test_importer.py`

```python
import shutil
from pathlib import Path
from fitness_mcp import importer, store, config

FIX = Path(__file__).parent / "fixtures"


def _build_fit_tree(root: Path):
    fit = root / "Takeout" / "Fit"
    (fit / "Daily activity metrics").mkdir(parents=True)
    (fit / "Activities").mkdir(parents=True)
    (fit / "All Sessions").mkdir(parents=True)
    shutil.copy(FIX / "daily.csv", fit / "Daily activity metrics" / "Daily activity metrics.csv")
    shutil.copy(FIX / "workout.tcx", fit / "Activities" / "2024-07-05.tcx")
    shutil.copy(FIX / "sleep.json", fit / "All Sessions" / "2024-07-01-sleep.json")
    return root


def test_import_takeout_populates_all_kinds(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path / "data"))
    src = _build_fit_tree(tmp_path / "export")

    summary = importer.import_takeout(str(src))

    assert summary["daily_metrics"] == 2
    assert summary["body_metrics"] == 1
    assert summary["workouts"] == 1
    assert summary["sleep"] == 1
    assert summary["errors"] == []

    assert len(store.query_range("daily_metrics", "date", "2024-07-01", "2024-07-31")) == 2
    assert len(store.query_range("workouts", "start", "2024-07-05", "2024-07-05")) == 1
    assert config.get_takeout_folder() == str(src)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_importer.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.importer`)

- [ ] **Step 3: Implement `src/fitness_mcp/importer.py`**

```python
from pathlib import Path

from . import config, parser, store


def _find_fit_root(root: Path) -> Path:
    for c in (root, root / "Fit", root / "Takeout" / "Fit"):
        if c.exists() and (list(c.glob("**/Daily activity metrics*.csv")) or (c / "Activities").exists()):
            return c
    return root


def import_takeout(folder: str) -> dict:
    root = Path(folder)
    fit = _find_fit_root(root)
    summary = {"daily_metrics": 0, "body_metrics": 0, "workouts": 0, "sleep": 0, "errors": []}

    daily_csvs = list(fit.glob("**/Daily activity metrics.csv"))
    if daily_csvs:
        csv_path = daily_csvs[0]
        try:
            summary["daily_metrics"] = store.upsert("daily_metrics", parser.parse_daily_metrics(csv_path), "date")
            summary["body_metrics"] = store.upsert("body_metrics", parser.parse_body_metrics(csv_path), "date")
        except Exception as e:  # noqa: BLE001 - one bad file must not abort the import
            summary["errors"].append(f"daily csv: {e}")

    for tcx in fit.glob("**/Activities/*.tcx"):
        try:
            rec = parser.parse_workout_tcx(tcx)
            if rec:
                store.upsert("workouts", [rec], "start")
                summary["workouts"] += 1
        except Exception as e:  # noqa: BLE001
            summary["errors"].append(f"{tcx.name}: {e}")

    for js in fit.glob("**/*.json"):
        try:
            rec = parser.parse_sleep_session(js)
            if rec:
                store.upsert("sleep", [rec], "start")
                summary["sleep"] += 1
        except Exception as e:  # noqa: BLE001
            summary["errors"].append(f"{js.name}: {e}")

    config.set_takeout_folder(folder)
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_importer.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/fitness_mcp/importer.py tests/test_importer.py
git commit -m "feat: Takeout discovery + import orchestration"
```

---

## Task 6: MCP server tools + CLI entry

**Files:**
- Create: `src/fitness_mcp/server.py`, `src/fitness_mcp/__main__.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `store.*`, `importer.import_takeout`, `config.get_takeout_folder`.
- Produces (module-level functions decorated as MCP tools, also directly callable in tests):
  - `list_data_coverage() -> dict`
  - `get_daily_metrics(start_date: str, end_date: str) -> list[dict]`
  - `get_sleep(start_date: str, end_date: str) -> list[dict]`
  - `get_workouts(start_date: str, end_date: str, activity_type: str = "") -> list[dict]`
  - `get_metric_stats(metric: str, start_date: str, end_date: str) -> dict`
  - `refresh_from_takeout(folder_path: str = "") -> dict`
  - `main() -> None` (runs the stdio server)

- [ ] **Step 1: Write the failing test** — `tests/test_server.py`

```python
from fitness_mcp import server, store


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    store.upsert("daily_metrics", [
        {"date": "2024-07-01", "steps": 8000},
        {"date": "2024-07-02", "steps": 10000},
    ], "date")
    store.upsert("workouts", [
        {"start": "2024-07-05T06:30:00+05:30", "activity_type": "Running", "duration_min": 30.0},
        {"start": "2024-07-06T06:30:00+05:30", "activity_type": "Cycling", "duration_min": 45.0},
    ], "start")


def test_coverage_message_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path))
    out = server.list_data_coverage()
    assert "no data imported yet" in out["message"]


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


def test_workouts_filter_by_type(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    runs = server.get_workouts("2024-07-01", "2024-07-31", activity_type="running")
    assert len(runs) == 1
    assert runs[0]["activity_type"] == "Running"
    allw = server.get_workouts("2024-07-01", "2024-07-31")
    assert len(allw) == 2


def test_metric_stats_no_data_message(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    stats = server.get_metric_stats("calories", "2024-07-01", "2024-07-31")
    assert stats["count"] == 0
    assert "no data" in stats["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_server.py -v`
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.server`)

- [ ] **Step 3: Implement `src/fitness_mcp/server.py`**

```python
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import config, importer, store

mcp = FastMCP("fitness")

_COVERAGE_KEYS = {
    "daily_metrics": "date",
    "sleep": "start",
    "workouts": "start",
    "body_metrics": "date",
}


@mcp.tool()
def list_data_coverage() -> dict:
    """Report which data types are present and the date range each covers."""
    cov = {kind: store.coverage(kind, key) for kind, key in _COVERAGE_KEYS.items()}
    if all(v is None for v in cov.values()):
        return {"message": "no data imported yet — run refresh_from_takeout", "coverage": cov}
    return {"coverage": cov}


@mcp.tool()
def get_daily_metrics(start_date: str, end_date: str) -> list[dict]:
    """Daily activity rows (steps, distance, calories, active minutes, heart rate) in [start_date, end_date]."""
    return store.query_range("daily_metrics", "date", start_date, end_date)


@mcp.tool()
def get_sleep(start_date: str, end_date: str) -> list[dict]:
    """Sleep sessions that start within [start_date, end_date]."""
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
    rows = store.query_range("daily_metrics", "date", start_date, end_date)
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


@mcp.tool()
def refresh_from_takeout(folder_path: str = "") -> dict:
    """Import (or re-import) Google Fit data from a Takeout folder. Uses the remembered folder if none given."""
    folder = folder_path or config.get_takeout_folder()
    if not folder:
        return {"error": "no folder provided and none remembered; pass folder_path"}
    if not Path(folder).exists():
        return {"error": f"folder not found: {folder}"}
    return importer.import_takeout(folder)


def main() -> None:
    mcp.run()
```

- [ ] **Step 4: Implement `src/fitness_mcp/__main__.py`**

```python
import sys

from . import importer, server


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "import":
        if len(sys.argv) < 3:
            print("usage: python -m fitness_mcp import <takeout-folder>")
            sys.exit(2)
        print(importer.import_takeout(sys.argv[2]))
    else:
        server.main()


main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_server.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Run the full suite**

Run: `uv run --extra dev pytest -v`
Expected: PASS (all tasks' tests green)

- [ ] **Step 7: Commit**

```bash
git add src/fitness_mcp/server.py src/fitness_mcp/__main__.py tests/test_server.py
git commit -m "feat: MCP tools + CLI entry point"
```

---

## Task 7: Claude Desktop wiring + real-export E2E (docs)

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-08-09-fitness-mcp-phase1-design.md` (tick off "open questions" as they're resolved against the real export)

**Interfaces:** none (integration + documentation).

- [ ] **Step 1: Verify the server launches over stdio**

Run: `uv run python -m fitness_mcp.server`
Expected: process starts and blocks waiting on stdio (no crash, no traceback). Stop with Ctrl+C.

- [ ] **Step 2: Produce a real Takeout export and import it**

1. At <https://takeout.google.com>, create an export limited to **Fit**, download, and unzip to a folder (e.g. `D:\exports\Takeout`).
2. Run: `uv run python -m fitness_mcp import "D:\exports\Takeout"`
3. Confirm the printed summary shows non-zero counts and an empty (or explained) `errors` list.
4. **If counts are zero or errors appear:** open the real export, compare its folder names and CSV header against `DAILY_COLUMN_MAP` and the discovery globs in `importer.py`; adjust the column candidates / glob paths, re-run, and update the fixtures to match. Then re-run the full suite (`uv run --extra dev pytest -v`).

- [ ] **Step 3: Register with Claude Desktop**

Add to `%APPDATA%\Claude\claude_desktop_config.json` (create the file if absent), replacing the project path with the real one:

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

Fully quit and reopen Claude Desktop. Confirm the `fitness` tools appear in the tools/connectors list.

- [ ] **Step 4: Manual end-to-end questions in Claude Desktop**

Ask, and confirm answers match the data:
- "What fitness data do you have and for what dates?" (exercises `list_data_coverage`)
- "How many steps did I average last week?" (exercises `get_metric_stats`)
- "List my workouts in July." (exercises `get_workouts`)
- "How did I sleep over the last few days?" (exercises `get_sleep`)

- [ ] **Step 5: Write `README.md`**

Document: prerequisites (Python 3.11+, `uv`), how to import a Takeout export (the CLI command), the Claude Desktop config block, the list of tools, where data is stored (`%LOCALAPPDATA%\fitness-mcp\`), and the refresh workflow ("re-run the import, or ask Claude to `refresh_from_takeout`"). Note that Phase 2 (Android + Health Connect live sync) will replace the manual Takeout step.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/specs/2026-08-09-fitness-mcp-phase1-design.md
git commit -m "docs: Claude Desktop setup, README, and verified E2E"
```

---

## Self-Review

**Spec coverage:**
- Local-only, no cloud, no Fit REST API → Tasks 1–7 (no network anywhere). ✓
- Claude Desktop + local stdio MCP → Task 6 (`main`/server), Task 7 (registration). ✓
- Python/FastMCP/uv/pytest stack → Task 1. ✓
- JSON files (no SQLite), atomic writes, keyed upsert → Task 2. ✓
- Four data types (daily/body/workouts/sleep) → Tasks 3–4, storage in Task 2. ✓
- Shared store contract for Phase 2 → Task 2 interface; noted in Task 5/README. ✓
- Six MCP tools (coverage, daily, sleep, workouts, metric_stats, refresh) + CLI → Task 6. ✓
- Import flow + Takeout discovery, skip raw per-sample streams → Task 5 (globs target daily CSV, Activities TCX, session JSON only). ✓
- Error handling: schema drift skipped (Task 3 `_map_row` tolerance), one bad file never aborts (Task 5 try/except), empty-data messages (Task 6 coverage + metric_stats), bad path (Task 6 refresh). ✓
- Timezone assumption (local `YYYY-MM-DD`, no conversion) → Task 2 range logic on date prefix; documented in README (Task 7). ✓
- Testing: parser unit (incl. defensive blank-column case), store idempotency/range, tool shapes + empty path → Tasks 2/3/4/6. ✓
- Open questions (real export layout, sleep location) → resolved in Task 7 Step 2/4. ✓

**Placeholder scan:** No TBD/TODO; every code step contains runnable code; no "handle edge cases" hand-waves. ✓

**Type consistency:** `store.upsert(kind, records, key)`, `store.query_range(kind, key, start, end)`, `store.coverage(kind, key)` used identically in Tasks 5–6. Parser record keys (`date` for daily/body, `start` for workouts/sleep) match the `key` arguments and `_COVERAGE_KEYS` in Task 6. `import_takeout` summary dict shape matches its test and the `refresh_from_takeout` return. ✓
