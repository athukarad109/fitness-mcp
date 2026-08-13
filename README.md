# Fitness MCP: Local Google Fit / Health Connect + Claude Desktop

A fully-local system to chat with your Google Fit / Health Connect fitness data through Claude Desktop. Your Android phone pushes Health Connect data over your home wifi (LAN) to a receiver on your PC, which stores it as JSON; Claude Desktop reads it via a local MCP server. No cloud, no internet exposure, no Google Fit REST API.

## Architecture

```
Android phone (health-connect-webhook app)
  ↓
  HTTP POST over LAN
  ↓
Receiver (writes JSON files to %LOCALAPPDATA%\fitness-mcp\)
  ↓
MCP server (reads JSON)
  ↓
Claude Desktop
```

## Prerequisites

- Windows
- Python 3.11+
- `uv` (installed via `pip install --user uv`)
- Claude Desktop
- An Android phone with Health Connect + the Google Fit app

**Note on `uv` invocation:** Run `uv` as `python -m uv run ...`. If that errors with "No module named uv" (the project's `.venv` python shadowing), use the full path:
```
"C:/Users/athuk/AppData/Roaming/Python/Python311/Scripts/uv.exe" run ...
```

## Install & Test

1. Clone or enter the project directory.
2. Run the test suite:
   ```
   python -m uv run --extra dev pytest -v
   ```

## Running the Receiver (Always-On)

```
python -m uv run python -m fitness_mcp.receiver
```

The receiver listens on `0.0.0.0:8765` and serves:
- `GET /health` — returns `{"status": "ok"}` for health checks
- `POST /webhook` — accepts Health Connect payloads

## Give the PC a Stable LAN IP + Firewall Rule

1. **Reserve a static or DHCP-reserved IPv4 for the PC** in your router (e.g., `192.168.1.50`). Note this IP.
2. **Add an inbound firewall rule** scoped to the local subnet only:
   ```powershell
   New-NetFirewallRule -DisplayName "Fitness MCP receiver" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet
   ```
3. **Test from the PC:** Browse to `http://127.0.0.1:8765/health` → expect `{"status": "ok"}`.
4. **Test from the phone** (same wifi): Browse to `http://<pc-lan-ip>:8765/health` → expect the same.
   - If it fails, re-check the firewall rule and confirm the receiver binds to `0.0.0.0`.

## Phone App Setup

1. Install the open-source `health-connect-webhook` app and Health Connect.
2. Grant read permission for: steps, distance, calories (active and total), active minutes, heart rate, sleep, exercise, weight.
3. Set the webhook URL to `http://<pc-lan-ip>:8765/webhook`.
4. Enable interval sync (~15 minutes) and tap "Sync Now".

Data will flow to `%LOCALAPPDATA%\fitness-mcp\` as JSON files.

## Register the MCP Server with Claude Desktop

1. Open or create `%APPDATA%\Claude\claude_desktop_config.json`.
2. Add this entry (fix the project path if needed):
   ```json
   {
     "mcpServers": {
       "fitness": {
         "command": "python",
         "args": ["-m", "uv", "run", "python", "-m", "fitness_mcp.server"],
         "cwd": "D:\\Personal project\\google fit connector"
       }
     }
   }
   ```
3. Fully quit Claude Desktop and reopen it.
4. Confirm the `fitness` tools appear in the tools panel.

## MCP Tools Available

- **`list_data_coverage`** — Show what fitness data you have and date ranges.
- **`get_daily_metrics(start_date, end_date)`** — Fetch daily step count, distance, and calories (active & total).
- **`get_sleep(start_date, end_date)`** — Fetch sleep records.
- **`get_workouts(start_date, end_date, activity_type?)`** — List workouts; optionally filter by type.
- **`get_metric_stats(metric, start_date, end_date)`** — Summary stats (min, max, average) for a metric (steps, distance, active_minutes, heart_rate, etc.).

### Example Questions to Ask Claude

- "What fitness data do you have and for what dates?"
- "How many steps did I average last week?"
- "List my workouts this month."
- "How did I sleep the last few nights?"

## Autostart the Receiver with Windows

1. Press **Win+R** and type `shell:startup` to open the Startup folder.
2. Create a shortcut with the following target:
   ```
   powershell -WindowStyle Hidden -Command "cd 'D:\Personal project\google fit connector'; python -m uv run python -m fitness_mcp.receiver"
   ```
3. Reboot and confirm `http://127.0.0.1:8765/health` responds without manually starting anything.

## Where Data Is Stored

All fitness data lives in `%LOCALAPPDATA%\fitness-mcp\`:

**Daily aggregates (JSON files):**
- `steps.json`
- `distance.json`
- `active_calories.json`
- `total_calories.json`
- `active_minutes.json`
- `heart_rate.json`
- `sleep.json`
- `workouts.json`
- `body_metrics.json`

**Raw payloads:**
- `raw/` folder archives every received Health Connect payload, timestamped. Use these for schema troubleshooting.

## Troubleshooting & Schema Reconciliation

If a data type shows no coverage after syncing:

1. Open the newest file in `%LOCALAPPDATA%\fitness-mcp\raw\` — this is the exact payload the phone sent.
2. Compare its array names and field names against the candidate lists in `src/fitness_mcp/webhook_mapper.py`.
3. If the real field names differ, update the candidate name lists in `webhook_mapper.py` and also update `tests/fixtures/payload.json` to match reality.
4. Run the tests:
   ```
   python -m uv run --extra dev pytest -v
   ```
5. Expected: PASS. Re-trigger "Sync Now" on the phone and confirm `list_data_coverage` shows non-null ranges.

## Privacy & Security

Everything is local and LAN-only. The receiver has no authentication (the app doesn't support it), so the LAN boundary + the subnet-scoped firewall rule are the security boundary. **Never expose port 8765 to the internet.**
