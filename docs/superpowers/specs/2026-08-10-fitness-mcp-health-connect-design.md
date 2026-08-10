# Fitness MCP — Design (Health Connect push, local)

**Date:** 2026-08-10
**Status:** Approved design, ready for implementation planning
**Supersedes:** the earlier Takeout-fed Phase 1 design (dropped in favor of a
zip-free, automatic Health Connect source).

---

## Goal

Let the user ask Claude questions about their own fitness data
("how did I sleep this week?", "am I trending up on steps?", "list my runs in
July") and get answers grounded in real data — running **entirely locally** on
the user's Windows PC, fed **automatically** from the phone with **no manual
export step** and **no dependency on the deprecated Google Fit REST API**.

## Why this shape (context from brainstorming)

- The Google Fit **REST API is closed to new access** (since May 2024) and
  **shuts down end of 2026**, so it is not a viable source.
- The user is on **Android + Google Fit**, which feeds **Health Connect** — the
  supported, on-device successor to Google Fit. Health Connect has **no cloud
  API**: data only leaves the phone via an app running on the device.
- The user wants strong **privacy** and **no manual steps**. Decision:
  everything local, LAN-only, no internet exposure; the phone pushes
  automatically.
- The phone side is **configuration, not code**: the open-source
  [`health-connect-webhook`](https://github.com/mcnaveen/health-connect-webhook)
  Android app (AGPLv3) reads 31 Health Connect data types and POSTs them as JSON
  to any configured URL on a background schedule (15-min interval via
  WorkManager). It has **no webhook authentication** ("use on a trusted LAN"),
  which is why the receiver is strictly LAN-only.
- The user asks via **Claude Desktop** on Windows, which natively runs local
  stdio MCP servers.

## Non-goals (YAGNI)

- No cloud hosting, no public/internet endpoint, no OAuth.
- No Google Fit REST API, no Google Takeout.
- No custom Android app (use the existing `health-connect-webhook`).
- No database engine — plain JSON files.
- No second-by-second analytics UI; Claude does the reasoning over served data.

---

## Architecture

```
Android phone
  Google Fit  ->  Health Connect  ->  [health-connect-webhook app]   (install + grant; no code)
                                           |  POST JSON every ~15 min, over home wifi (LAN)
                                           v
Windows PC  (all local, LAN only)
  [receiver]   always-on local HTTP server  --(map + upsert)-->  [store]  JSON files
                                                                    ^
  [MCP server] (launched by Claude Desktop over stdio) --(read)----+
                                                                    |
                                       [aggregate]  raw records -> daily metrics (read-time)
```

Two long-lived processes on the PC share the JSON store:

1. **The receiver** — always-on background process that accepts the phone's
   POSTs and writes to the store.
2. **The MCP server** — launched by Claude Desktop only while Claude is open;
   reads the store.

Atomic writes (temp file + `os.replace`) make the shared-file access safe.

### Stack

- **Python 3.11+**
- **`mcp` SDK (FastMCP)** for the MCP server (local stdio)
- **Standard library** `http.server` for the receiver, `json`/`datetime` for
  mapping/aggregation (no web framework needed for one endpoint)
- **`uv`** for env/deps, **`pytest`** for tests

### Components (each independently testable)

1. **`config`** — resolves the data directory
   (`%LOCALAPPDATA%\fitness-mcp\`, override via `FITNESS_MCP_DATA_DIR`) and the
   receiver bind host/port.
2. **`store`** — JSON keyed read/write with idempotent upsert and range queries.
   The shared contract used by both the receiver and the MCP server.
3. **`aggregate`** — pure functions rolling **raw** cumulative records (steps,
   distance, calories, active minutes, heart rate) into **daily** metrics for a
   date range. Read-time; keeps the tool contract identical regardless of how
   granular the incoming data is.
4. **`webhook_mapper`** — pure function: the app's POST payload → normalized
   records grouped by store kind, each with a **stable dedup key**.
5. **`receiver`** — always-on `http.server` handler: accepts POST, calls
   `webhook_mapper`, upserts via `store`; exposes a health check.
6. **`server`** — FastMCP tools reading the store (+ `aggregate`).

---

## Storage (the shared contract)

Plain JSON files in `%LOCALAPPDATA%\fitness-mcp\`, each a **keyed map** so
writes upsert with no duplicates.

**Raw cumulative records** (many per day; aggregated at read time):
- `steps.json`, `distance.json`, `active_calories.json`, `total_calories.json`,
  `active_minutes.json` — keyed by the Health Connect **record id** (fallback:
  `"{start}|{end}"`). Value fields: `start`, `end`, `value`.
- `heart_rate.json` — keyed by sample time. Value fields: `time`, `bpm`.

**Session records:**
- `sleep.json` — keyed by session `start`. Fields: `start`, `end`,
  `duration_min`, and stage breakdown (`deep_min`/`light_min`/`rem_min`/
  `awake_min`) when present.
- `workouts.json` — keyed by session `start`. Fields: `start`, `end`,
  `activity_type`, `duration_min`, optional `distance_m`, `calories`.

**Point-in-time:**
- `body_metrics.json` — keyed by `date`. Fields: `weight_kg` (latest per day),
  other body measurements when present.

**Dedup rationale:** the app syncs incrementally (records since last sync) and
may resend overlapping windows. Keying raw records by a stable id means a resend
overwrites rather than double-counts. Daily totals are computed from these raw
records at read time, so they are always correct regardless of push overlap.

**Units:** distance in meters, duration in minutes, weight in kg — fixed and
documented so Claude can convert as the user prefers.

---

## MCP tools (interface Claude calls)

Same external contract as intended all along; tools serve data, Claude reasons:

- `list_data_coverage()` → which data types are present and the date range each
  covers; a clear "no data yet" message when empty.
- `get_daily_metrics(start_date, end_date)` → daily rows (steps, distance,
  calories, active minutes, resting/avg/min/max heart rate), **aggregated from
  raw records** for each date.
- `get_sleep(start_date, end_date)` → sleep sessions.
- `get_workouts(start_date, end_date, activity_type?)` → workout sessions.
- `get_metric_stats(metric, start_date, end_date)` → min/max/avg/sum/count for a
  daily metric over the range (trend questions).

There is intentionally **no `refresh` tool** — data arrives automatically from
the phone; nothing to trigger manually.

---

## Receiver

- Binds to the LAN (host/port from config; default port e.g. `8765`).
- `POST /webhook` — parses JSON body, maps, upserts, returns `{"status":"ok",
  "stored": {...counts...}}`.
- `GET /health` — returns `{"status":"ok"}` for connectivity testing from the
  phone/browser.
- **Raw-payload capture:** while the exact app schema is being confirmed, the
  receiver writes each raw payload to `%LOCALAPPDATA%\fitness-mcp\raw\` so the
  first real payload can be inspected to finalize the mapper.
- **Security:** LAN-only. Never exposed to the internet. The Windows firewall
  rule should scope the port to the local subnet. (The app offers no webhook
  auth, so the LAN boundary *is* the security boundary — matching the privacy
  goal of keeping data off any third-party cloud.)

---

## Error handling

- **Schema drift / unknown fields:** the mapper skips arrays/fields it doesn't
  recognize and maps what it can; a single unrecognized section never fails the
  whole request. The receiver returns per-kind stored counts so gaps are visible.
- **Malformed request body:** receiver returns HTTP 400 with a short message;
  never crashes the process.
- **Empty store:** read tools return clear "no data yet" messaging.
- **Timezones:** Health Connect timestamps are ISO-8601 with offsets; parsed
  with offset awareness. Daily bucketing uses the **local date** of each record's
  start time. Assumption documented.
- **Concurrent access:** receiver writes atomically; MCP server only reads.

---

## Testing

- **`store`**: upsert idempotency (resend → no duplicate), range queries,
  coverage.
- **`aggregate`**: raw step/HR records → correct daily sums and min/max/avg;
  correct day bucketing across timezone offsets.
- **`webhook_mapper`**: a representative payload → correct records per kind with
  stable keys; unknown sections skipped without error. Fixtures start from the
  documented shape and are reconciled against a **captured real payload**.
- **`receiver`**: POST a fixture payload to a test instance → correct store
  contents and response; malformed body → 400; `GET /health` → ok.
- **`server`**: tools against a seeded store, including the empty-data paths.
- **Manual E2E**: install the app, point it at the PC, confirm automatic pushes
  land and Claude answers real questions correctly.

---

## Deployment / operations (Windows)

- **Receiver runs in the background**, started with Windows (Startup-folder
  shortcut launching it via `pythonw`/`uv`, or a Task Scheduler "at logon" task).
- **Stable LAN IP** for the PC (DHCP reservation or static IP) so the phone's
  configured URL keeps working.
- **Firewall rule** allowing inbound TCP on the receiver port from the local
  subnet only.
- **MCP server** registered in `%APPDATA%\Claude\claude_desktop_config.json`;
  Claude Desktop launches it over stdio.
- **Phone:** install `health-connect-webhook`, grant Health Connect read
  permissions for the desired types, set the webhook URL to
  `http://<pc-lan-ip>:<port>/webhook`, enable ~15-min background sync.

---

## Open questions / to confirm at implementation time

1. Exact `health-connect-webhook` POST JSON schema — confirmed by capturing a
   real payload (receiver raw-capture) before finalizing `webhook_mapper`.
2. Whether the app supplies stable Health Connect record ids (preferred dedup
   key) or only start/end times (fallback key).
3. Whether sleep stage breakdown and resting heart rate are present in this
   user's data, or only totals/samples.
