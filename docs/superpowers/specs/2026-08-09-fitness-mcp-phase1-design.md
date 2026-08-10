# Fitness MCP — Phase 1 Design (Local, Takeout-fed)

**Date:** 2026-08-09
**Status:** Approved design, ready for implementation planning
**Author:** Brainstormed with Claude

---

## Goal

Let the user ask Claude questions about their own Google Fit fitness data
("how did I sleep this week?", "am I trending up on steps?", "list my runs in
July") and get answers grounded in their real data — running **entirely locally**
on their Windows PC, with **no cloud service** and **no dependency on the
deprecated Google Fit REST API**.

## Why this shape (context from brainstorming)

- The Google Fit **REST API is closed to new access** (since May 2024) and
  **shuts down end of 2026**, so a live cloud integration on that API is not an
  option and would be short-lived anyway.
- The user is on **Android + the Google Fit app**, so their data is available
  both via **Google Takeout** (export) and, on-device, via **Health Connect**
  (Google Fit's supported successor).
- The user wants to ask on their machine with **strong privacy** → decided on
  **Claude Desktop + a local MCP server** on their Windows PC. Claude Desktop
  natively runs local stdio MCP servers via `claude_desktop_config.json`.
- The full system is phased:
  - **Phase 1 (this spec):** local MCP server fed by a manual Google Takeout
    export. Proves the end-to-end "chat with my fitness data" loop fast, with no
    Android build.
  - **Phase 2 (future spec):** a small Android app reads Health Connect and
    pushes to the PC over the home LAN, writing into the **same local datastore**,
    eliminating the manual Takeout step. Fully hands-off after one-time setup.

The Phase 1 storage layer is the shared contract Phase 2 reuses, so Phase 2
slots in without reworking the parser, tools, or storage schema.

## Non-goals (YAGNI)

- No cloud hosting, no public endpoint, no auth server (all local, single user).
- No Google Fit REST API usage.
- No raw per-sample data (second-by-second HR streams, etc.) in Phase 1 — only
  daily aggregates, sleep sessions, and workout sessions.
- No database engine — plain JSON files (see Storage).
- No Android app in Phase 1.

---

## Architecture

Everything runs on the Windows PC. Nothing leaves the machine.

```
Google Takeout (.zip)  ->  user unzips to a folder
        |
        v
  [parser]   reads Fit CSV/TCX  ->  normalized records
        |
        v
  [store]    JSON files on the PC   <--- (Phase 2 Android push writes here too)
        |
        v
  [server]   FastMCP tools over stdio
        |
        v
  Claude Desktop  -->  user asks; Claude calls tools; answers from the data
```

### Stack

- **Python 3.11+**
- **`mcp` SDK (FastMCP)** for the MCP server (local stdio transport)
- **Standard library** for parsing: `csv`, `json`, `xml.etree` (TCX), `zipfile`
- **`uv`** for env/dependency management (pip is an acceptable fallback)
- **`pytest`** for tests

### Components (each independently testable)

1. **`config`** — resolves paths: data directory
   (`%LOCALAPPDATA%\fitness-mcp\`), and the remembered Takeout source folder.
   Simple, no logic beyond path resolution + a small JSON config file.
2. **`parser`** — pure functions: given Takeout files, return normalized record
   lists. No I/O side effects beyond reading the given paths. Fully unit-testable
   against small fixtures.
3. **`store`** — the shared contract. Reads/writes the JSON data files, performs
   idempotent upserts, and answers range/filter queries. Isolated behind a clean
   interface so the backend could change without touching consumers.
4. **`server`** — FastMCP app exposing the read tools + a refresh tool. Thin;
   delegates to `store` and `parser`.

---

## Storage (the shared contract)

Plain JSON files in `%LOCALAPPDATA%\fitness-mcp\`:

- `daily_metrics.json`
- `sleep.json`
- `workouts.json`
- `body_metrics.json`

Each file is a **keyed map** (not a bare list) so imports **upsert** with no
duplicates:

- `daily_metrics.json` — keyed by `date` (`YYYY-MM-DD`). Value fields:
  `steps`, `distance_m`, `calories`, `active_minutes`, `resting_hr`, `avg_hr`,
  `min_hr`, `max_hr`. Missing fields are simply absent.
- `sleep.json` — keyed by session `start` (ISO datetime). Value fields:
  `start`, `end`, `duration_min`, and stage breakdown
  (`deep_min`, `light_min`, `rem_min`, `awake_min`) when present.
- `workouts.json` — keyed by session `start` (ISO datetime). Value fields:
  `start`, `end`, `activity_type`, `duration_min`, `calories`, `distance_m`.
- `body_metrics.json` — keyed by `date` (`YYYY-MM-DD`). Value fields:
  `weight_kg` and any other available body measurements.

**Write discipline:** all writes are **atomic** (write to a temp file, then
`os.replace` onto the target) so a Phase-2 sync writing while the MCP server
reads can never observe a half-written file. The store is the single writer.

**Read pattern:** load the relevant file fully into memory and filter in Python.
At personal scale (thousands of daily rows, hundreds of sessions) this is
effectively instant, and keeps the code trivial.

**Units:** distances in meters, durations in minutes, weight in kg — documented
and consistent so Claude can convert as the user prefers.

---

## MCP tools (the interface Claude calls)

Small and composable; tools serve data, Claude does the reasoning.

- `list_data_coverage()` → for each data type, the date range covered and which
  metrics are present. Lets Claude know what it can actually answer before
  guessing.
- `get_daily_metrics(start_date, end_date)` → list of daily rows in range.
- `get_sleep(start_date, end_date)` → sleep sessions overlapping the range.
- `get_workouts(start_date, end_date, activity_type?)` → workout sessions,
  optionally filtered by type.
- `get_metric_stats(metric, start_date, end_date)` → `min`/`max`/`avg`/`sum`
  and count for a named daily metric (e.g. `steps`) over the range — for trend
  questions.
- `refresh_from_takeout(folder_path?)` → (re)import from the given Takeout folder
  (or the remembered one from config); returns a summary of what was imported.

The same import is also available as a CLI: `python -m fitness_mcp import <path>`.

**Empty-data behavior:** if no data has been imported yet, read tools return a
clear message ("no data imported yet — run refresh_from_takeout") so Claude tells
the user plainly rather than inventing an answer.

---

## Import flow & Google Takeout specifics

1. User creates a Google Takeout export limited to **Fit**, downloads and unzips
   it to a folder.
2. User points the importer at that folder once — path remembered in config.
3. Importer parses and upserts into the JSON store. Re-running with a fresh
   export updates existing records and adds new ones.

Phase 1 parses:

- **Daily activity metrics** CSVs (steps, distance, calories, active minutes,
  heart rate min/max/avg) → `daily_metrics.json`.
- **Activities / Sessions** files (TCX/JSON) → `workouts.json`, and sleep
  sessions → `sleep.json`.
- Body measurements where present → `body_metrics.json`.

Phase 1 **skips** the large raw per-sample JSON streams (`All Data/derived_*`) —
unnecessary for the intended questions and slow to parse.

> **Assumption to verify during implementation:** exact Takeout Fit folder/file
> layout and column names. The parser must be written defensively (see Error
> handling) because Google's export format has changed over time. First
> implementation step should inspect a real sample export from the user.

---

## Error handling

- **Schema drift** (Google renames/moves a column or file): the parser logs the
  issue, skips the unknown/missing field or file, and continues — a single bad
  column never aborts the whole import. The refresh summary reports what was and
  wasn't imported.
- **Empty / missing data files**: read tools return the friendly "no data yet"
  message described above.
- **Timezones**: dates are stored as the local `YYYY-MM-DD` labels Google
  provides; session datetimes stored as given. The local-time assumption is
  documented; no timezone conversion in Phase 1.
- **Malformed Takeout path**: `refresh_from_takeout` validates the folder exists
  and looks like a Fit export before parsing, and returns a clear error otherwise.

---

## Testing

- **Parser unit tests** against small fixture files (a few-row daily CSV, a
  sample TCX workout, a sleep session) — including a fixture with an unexpected
  extra/renamed column to prove defensive parsing.
- **Store tests**: upsert idempotency (import twice → no duplicates), range
  queries, atomic write behavior.
- **Tool tests**: call each MCP tool against a seeded store and assert the shape
  and filtering of results, plus the empty-data path.
- **Manual end-to-end**: register the server in `claude_desktop_config.json`,
  import a real Takeout export, and ask Claude several real questions.

---

## Claude Desktop integration

Add an entry to `%APPDATA%\Claude\claude_desktop_config.json`:

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

(Exact `command`/`args` finalized during implementation depending on the chosen
env setup.) Restart Claude Desktop; the `fitness` tools become available.

---

## Phase 2 preview (not built here)

A small Android app reads Health Connect and pushes normalized records to a
local receiver on the PC over the home LAN, writing into the **same JSON store**
via the same `store` interface. This removes the manual Takeout step entirely.
Designing Phase 1's `store` as an isolated, well-defined component is what makes
this drop-in.

---

## Open questions / to confirm at implementation time

1. Exact Google Takeout Fit export layout (inspect a real sample first).
2. Whether sleep data appears in the daily CSVs, the sessions files, or both for
   this user's export.
3. Final Python env/runner choice (`uv` vs pip) and the resulting
   `claude_desktop_config.json` command line.
