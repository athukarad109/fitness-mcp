# Fitness MCP — B1: Pipeline + Tunnel (remote reachability) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans for the CODE task (Task 1). Tasks 2–5 are on-device runbook steps performed by the user on the Android phone (Termux) — they cannot be run by a subagent or unit-tested; follow them interactively. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Prove — cheaply, before any OAuth — that our Phase A Python pipeline runs on the phone in Termux, ingests Health Connect data via loopback, serves the MCP tools over HTTP, and is reachable from the internet through a Cloudflare Tunnel at `https://mcp.qvnode17.online/mcp`.

**Architecture:** Add an HTTP/streamable-transport entrypoint to our existing FastMCP server (the only code change; testable on the PC). Everything else is device setup on one Android phone: Python in a Termux `proot-distro` Ubuntu, the reader app POSTing to `localhost`, the MCP server bound to `127.0.0.1`, and `cloudflared` exposing it. B1 is authless on purpose — reachability is proven with Claude Code / MCP Inspector (which tolerate authless); real clients + OAuth come in B2.

**Tech Stack:** Python 3.11+, `mcp` 1.29.x (FastMCP, streamable-http), stdlib `http.server` (receiver), `uv`/`pytest` on PC; on phone: Termux + `proot-distro` Ubuntu, `pip`/`venv`, `cloudflared`; `health-connect-webhook` APK as the reader.

**Spec:** [docs/superpowers/specs/2026-08-14-fitness-mcp-remote-oauth-design.md](../specs/2026-08-14-fitness-mcp-remote-oauth-design.md)

## Global Constraints

- Python `>=3.11`; runtime deps limited to `mcp` (`>=1.2.0`, installed 1.29.0) + stdlib. Reuse all Phase A modules unchanged.
- The MCP HTTP server binds to **`127.0.0.1`** only — the Cloudflare Tunnel is the sole public ingress. Never bind the MCP server to `0.0.0.0`/public.
- The write path is **loopback only**: the reader app POSTs to `127.0.0.1` on the phone; nothing about writes is exposed to the internet.
- B1 has **no authentication** by design; prove reachability with Claude Code / MCP Inspector, NOT the claude.ai app (which may refuse authless). OAuth is B2.
- Stable public hostname: **`mcp.qvnode17.online`** (domain registered; must be added to the user's Cloudflare account with nameservers pointed at Cloudflare before Task 5).
- **Git:** the user performs all `git add`/`commit`/`push` themselves. Commit steps below are the user's to run; do not commit on their behalf.

---

## File Structure

- `src/fitness_mcp/config.py` — MODIFY: add `mcp_host()` / `mcp_port()`.
- `src/fitness_mcp/server_http.py` — CREATE: streamable-http entrypoint reusing the existing `mcp` instance + tools from `server.py`.
- `tests/test_server_http.py` — CREATE: unit tests for config wiring + app construction.

Only Task 1 touches the repo. Tasks 2–5 create no repo files (they configure the phone), though Task 5 writes a `cloudflared` config on the phone.

---

## Task 1: HTTP/streamable transport entrypoint (CODE — do this on the PC)

**Files:**
- Modify: `src/fitness_mcp/config.py`
- Create: `src/fitness_mcp/server_http.py`
- Test: `tests/test_server_http.py`

**Interfaces:**
- Consumes: `server.mcp` (the existing `FastMCP("fitness")` instance with all six tools), `config.*`.
- Produces:
  - `config.mcp_host() -> str` (default `"127.0.0.1"`, override `FITNESS_MCP_MCP_HOST`)
  - `config.mcp_port() -> int` (default `8000`, override `FITNESS_MCP_MCP_PORT`)
  - `server_http.configure(host: str, port: int) -> FastMCP` — sets `mcp.settings.host/port`, returns the instance
  - `server_http.build_app()` — returns the streamable-http ASGI app (`mcp.streamable_http_app()`)
  - `server_http.main() -> None` — configures from config and runs `transport="streamable-http"`

- [ ] **Step 1: Write the failing test** — `tests/test_server_http.py`

```python
from fitness_mcp import config, server_http


def test_mcp_host_port_defaults_and_override(monkeypatch):
    monkeypatch.delenv("FITNESS_MCP_MCP_HOST", raising=False)
    monkeypatch.delenv("FITNESS_MCP_MCP_PORT", raising=False)
    assert config.mcp_host() == "127.0.0.1"
    assert config.mcp_port() == 8000
    monkeypatch.setenv("FITNESS_MCP_MCP_PORT", "8010")
    assert config.mcp_port() == 8010


def test_configure_sets_settings_and_builds_app():
    inst = server_http.configure("127.0.0.1", 8123)
    assert inst.settings.host == "127.0.0.1"
    assert inst.settings.port == 8123
    app = server_http.build_app()
    assert callable(app)  # an ASGI application
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m uv run --extra dev pytest tests/test_server_http.py -v`
(If `python -m uv` errors with "No module named uv", use `"C:/Users/athuk/AppData/Roaming/Python/Python311/Scripts/uv.exe" run --extra dev pytest tests/test_server_http.py -v`.)
Expected: FAIL (`ModuleNotFoundError: fitness_mcp.server_http` / missing `config.mcp_host`).

- [ ] **Step 3: Add config accessors** — append to `src/fitness_mcp/config.py`

```python
def mcp_host() -> str:
    return os.environ.get("FITNESS_MCP_MCP_HOST", "127.0.0.1")


def mcp_port() -> int:
    return int(os.environ.get("FITNESS_MCP_MCP_PORT", "8000"))
```

- [ ] **Step 4: Create `src/fitness_mcp/server_http.py`**

```python
from . import config
from .server import mcp


def configure(host: str, port: int):
    """Point the shared FastMCP instance at the given bind host/port."""
    mcp.settings.host = host
    mcp.settings.port = port
    return mcp


def build_app():
    """Return the streamable-http ASGI app for the fitness MCP server."""
    return mcp.streamable_http_app()


def main() -> None:
    host, port = config.mcp_host(), config.mcp_port()
    configure(host, port)
    print(f"fitness MCP (streamable-http) listening on http://{host}:{port}/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m uv run --extra dev pytest tests/test_server_http.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Run the full suite (nothing regressed)**

Run: `python -m uv run --extra dev pytest -v`
Expected: PASS (all Phase A tests + the 2 new).

- [ ] **Step 7: Smoke-test the HTTP server locally on the PC (manual)**

In one terminal: `python -m uv run python -m fitness_mcp.server_http`
Expected: prints "listening on http://127.0.0.1:8000/mcp" and blocks.
In another terminal: `curl -s -i http://127.0.0.1:8000/mcp`
Expected: an HTTP response (a 400/405/406 JSON-RPC-style error is fine — it proves the server is up and routing `/mcp`; a streamable-http endpoint rejects a bare GET). "Connection refused" means it's not listening — recheck. Stop the server with Ctrl+C.

- [ ] **Step 8: Commit (user runs this)**

```bash
git add src/fitness_mcp/config.py src/fitness_mcp/server_http.py tests/test_server_http.py
git commit -m "feat: streamable-http entrypoint for the MCP server"
```

---

## Task 2: Python stack running in Termux (ON-DEVICE — the feasibility gate)

**Goal:** Prove the phone can run our Python + `mcp`. Use `proot-distro` Ubuntu so `pip` pulls prebuilt aarch64 wheels for `pydantic-core` (avoids a fragile Rust build under bare Termux).

- [ ] **Step 1: Install Termux + proot Ubuntu.** Install Termux from **F-Droid or GitHub releases** (the Play Store build is outdated). Then in Termux:

```bash
pkg update && pkg upgrade -y
pkg install -y proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
```

- [ ] **Step 2: Inside Ubuntu, install Python + tooling.**

```bash
apt update && apt install -y python3 python3-venv python3-pip git
python3 --version   # expect >= 3.11 (Ubuntu 24.04 ships 3.12)
```

- [ ] **Step 3: Get the project onto the phone.** Either `git clone` your repo, or copy the folder in. Then:

```bash
cd <project-dir>
python3 -m venv .venv
. .venv/bin/activate
pip install -e .          # installs mcp>=1.2.0 and its deps from aarch64 wheels
pip install pytest
```

- [ ] **Step 4: Run the test suite on the phone (the gate).**

```bash
PYTHONPATH=src pytest -q
```

Expected: the full suite passes (same tests as the PC). **This is the go/no-go for the whole approach** — if `mcp`/`pydantic-core` won't install or the suite fails here, STOP and report what failed before doing anything else. (Fallback if wheels are unavailable: `apt install -y build-essential rust cargo` and retry `pip install -e .`, or try `pip install uv` and `uv run pytest`.)

- [ ] **Step 5: Note the paths.** Record the project dir and the venv activation command — Tasks 3–5 assume you're inside `proot-distro login ubuntu` with `.venv` activated.

---

## Task 3: Loopback ingest — reader app → receiver → store (ON-DEVICE)

**Goal:** Real Health Connect data lands in the JSON store on the phone, with writes never leaving the device.

- [ ] **Step 1: Start the receiver** (inside Ubuntu, venv active), bound to localhost:

```bash
FITNESS_MCP_HOST=127.0.0.1 PYTHONPATH=src python3 -m fitness_mcp.receiver
```

Expected: "fitness receiver listening on http://127.0.0.1:8765 …". Leave it running (use a second Termux session / `tmux` for the next steps).

- [ ] **Step 2: Point the reader app at loopback.** In the `health-connect-webhook` app: grant Health Connect read permissions for steps, distance, calories, active minutes, heart rate, sleep, exercise, weight; set the webhook URL to **`http://127.0.0.1:8765/webhook`**; enable interval sync; tap **Sync Now**. (Termux/proot share Android's network namespace, so an Android app can reach a `127.0.0.1:8765` listener inside Termux.)

- [ ] **Step 3: Verify data landed.** In the Ubuntu shell:

```bash
ls -la "$HOME/.local/share/fitness-mcp" 2>/dev/null || ls -la "${FITNESS_MCP_DATA_DIR:-$HOME/fitness-mcp}"
cat <data-dir>/raw/*.json | head -c 400   # a real captured payload
```

Expected: a `raw/` archive file exists and one or more kind files (e.g. `steps.json`) are non-empty. If empty: re-check the app's URL, that the receiver is running, and that Health Connect actually has data on THIS phone (Google Fit logged in and syncing to Health Connect here). Set `FITNESS_MCP_DATA_DIR` explicitly if you want a known path.

- [ ] **Step 4: Reconcile the mapper against the real payload.** Open the newest `raw/*.json` and compare its array/field names to the candidate lists in `src/fitness_mcp/webhook_mapper.py`. If `list_data_coverage` later shows gaps, adjust candidates + `tests/fixtures/payload.json`, re-run `PYTHONPATH=src pytest -q`, and re-sync. (User commits any change.)

---

## Task 4: Serve the MCP over HTTP on the phone, verify locally (ON-DEVICE)

**Goal:** The MCP tools are served over HTTP on `127.0.0.1:8000` reading the store populated in Task 3.

- [ ] **Step 1: Start the HTTP MCP server** (Ubuntu, venv active), same data dir as the receiver:

```bash
PYTHONPATH=src python3 -m fitness_mcp.server_http
```

Expected: "fitness MCP (streamable-http) listening on http://127.0.0.1:8000/mcp". Leave running.

- [ ] **Step 2: Confirm it's listening.**

```bash
curl -s -i http://127.0.0.1:8000/mcp | head -n 20
```

Expected: an HTTP response (a JSON-RPC/406/405-style error to a bare GET is fine — it proves the endpoint is live). "Connection refused" ⇒ not listening; recheck.

- [ ] **Step 3: Real protocol check with the MCP Inspector** (optional but recommended). From any machine that can reach the phone (or on-device if you install Node), run the MCP Inspector against `http://127.0.0.1:8000/mcp` (transport: streamable-http) and confirm it lists the six tools and that `list_data_coverage` returns your real coverage. If you can't run Inspector here, defer the true protocol check to Task 5 Step 5 (Claude Code over the tunnel).

---

## Task 5: Cloudflare Tunnel — public reachability at mcp.qvnode17.online (ON-DEVICE)

**Goal:** `https://mcp.qvnode17.online/mcp` reaches the phone's MCP server, proving end-to-end remote reachability. **B1 is done when a client connects over this URL and lists the tools.**

- [ ] **Step 1: Put the domain on Cloudflare (dashboard, one-time).** In the Cloudflare dashboard, add site `qvnode17.online`, then at your registrar change the nameservers to the two Cloudflare gives you. Wait until the zone shows **Active**.

- [ ] **Step 2: Install cloudflared** (Ubuntu proot):

```bash
apt install -y curl
ARCH=$(dpkg --print-architecture)   # expect arm64
curl -L -o cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
apt install -y ./cloudflared.deb
cloudflared --version
```

- [ ] **Step 3: Authenticate + create the tunnel.**

```bash
cloudflared tunnel login          # opens a URL; authorize the qvnode17.online zone
cloudflared tunnel create fitness # note the Tunnel ID + the credentials json path it prints
```

- [ ] **Step 4: Configure ingress + DNS.** Create `~/.cloudflared/config.yml`:

```yaml
tunnel: fitness
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json
ingress:
  - hostname: mcp.qvnode17.online
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Then route DNS and run:

```bash
cloudflared tunnel route dns fitness mcp.qvnode17.online
cloudflared tunnel run fitness
```

Expected: cloudflared connects and shows registered connections. Keep the receiver (Task 3) and MCP server (Task 4) running alongside it.

- [ ] **Step 5: Prove remote reachability (B1 success criterion).** From your PC:

```bash
curl -s -i https://mcp.qvnode17.online/mcp | head -n 20
```

Expected: an HTTPS response from the phone (again, a JSON-RPC/4xx to a bare GET is fine — TLS + routing work). Then connect a real MCP client authless:

```bash
claude mcp add --transport http fitness-remote https://mcp.qvnode17.online/mcp
```

In Claude Code, confirm the `fitness-remote` server connects and that asking it "what fitness data do you have and for what dates?" invokes `list_data_coverage` and returns your real data. **When that works end-to-end, B1 is proven** and we proceed to design B2 (OAuth + claude.ai/mobile/ChatGPT onboarding + autostart/hardening).

- [ ] **Step 6: Record results.** Note: did Termux run the stack (Task 2)? did loopback ingest work (Task 3)? did the tunnel + Claude Code round-trip work (Task 5)? Any failure here reshapes B2 — capture it before moving on.

---

## Self-Review

**Spec coverage (B1 scope of `2026-08-14-...-remote-oauth-design.md` §4 "B1"):**
- Python in Termux → Task 2 (proot Ubuntu, suite as the gate). ✓
- Reader app → loopback → receiver → store on phone → Task 3. ✓
- MCP server in HTTP/streamable transport, bound to 127.0.0.1 → Task 1 (code) + Task 4 (run). ✓
- Named Cloudflare Tunnel → `mcp.qvnode17.online` → Task 5. ✓
- Prove a client reaches a tool end-to-end (authless, via Claude Code) → Task 5 Step 5. ✓
- Front-loads the two feasibility unknowns (Termux runs stack; tunnel exposes working MCP) → Task 2 gate + Task 5. ✓
- Reuse Phase A modules unchanged; only add HTTP entrypoint → Task 1 only touches config + new server_http. ✓
- No OAuth in B1; loopback writes; 127.0.0.1 bind → Global Constraints + Tasks 1/3/4. ✓

**Placeholder scan:** No TBD/TODO. The one code task carries real code + tests; runbook tasks carry exact commands and explicit expected outputs. `<project-dir>`, `<data-dir>`, `<TUNNEL-ID>` are genuine user-specific values (not placeholders for logic), each with the command that reveals them.

**Type consistency:** `config.mcp_host()/mcp_port()` used by `server_http.main()`; `server_http.configure(host, port)` sets `mcp.settings.host/port` (verified against installed mcp 1.29.0: `run(transport="streamable-http")`, `streamable_http_app()`, `settings.host/port` all exist). Receiver env `FITNESS_MCP_HOST`/data dir match Phase A `config`. Ports consistent: receiver 8765 (Task 3), MCP 8000 (Tasks 1/4/5 ingress).
