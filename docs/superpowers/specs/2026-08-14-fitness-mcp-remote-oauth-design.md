# Fitness MCP — Phase B Design: Remote, OAuth-Secured, Phone-Hosted MCP

**Date:** 2026-08-14
**Status:** Design approved at architecture + decomposition level; B1 to be detailed
into an implementation plan next.
**Repo branch:** `feature/fitness-mcp` (all Phase A code lives here)
**Builds on:** [2026-08-10-fitness-mcp-health-connect-design.md](2026-08-10-fitness-mcp-health-connect-design.md)

---

## 0. Cross-chat context (read this first in a new session)

**What already exists (Phase A — built, tested, review-clean on branch `feature/fitness-mcp`):**
A fully-local Windows system to chat with Google Fit / Health Connect fitness data
through Claude Desktop. A Python package `fitness_mcp` (src layout) with:
- `config` — data dir + receiver host/port
- `store` — JSON keyed store: atomic writes, idempotent upsert (thread-safe lock), range queries, coverage
- `util` — parse/number/date helpers
- `aggregate` — raw records → daily metrics (steps, distance, calories, active minutes, HR)
- `webhook_mapper` — the `health-connect-webhook` app's POST payload → normalized records (defensive)
- `receiver` — stdlib `http.server` LAN receiver: `GET /health`, `POST /webhook`, raw-payload archival to `raw/`
- `server` — FastMCP (stdio) with tools: `list_data_coverage`, `get_daily_metrics`,
  `get_sleep`, `get_workouts`, `get_metric_stats`, `get_body_metrics`
- Tests: 21 passing (`python -m uv run --extra dev pytest`). Data stored under `%LOCALAPPDATA%\fitness-mcp\`.
- Stack: Python 3.11+, `mcp` SDK (FastMCP), stdlib only otherwise, `uv`, pytest.

**Why Phase B:** The user wants to ask their assistant about fitness data **from anywhere on
their phone** (not just Claude Desktop on the PC), and to support **Claude (Desktop + mobile)
AND ChatGPT** (both support remote MCP connectors). They accept that query data will transit
the assistant vendor's cloud (inherent to remote connectors). They will host it themselves on a
spare Android phone and want a properly secured (OAuth) system.

**Key facts established during brainstorming (do not re-litigate):**
- Google Fit REST API is dead (closed to new access; shuts down end of 2026). Not usable.
- Health Connect has **no cloud API**; reading it requires a **native Android app** with permission.
  Termux/Python cannot read Health Connect. Therefore the Health Connect *reader* must be a native
  app — we reuse the existing open-source `health-connect-webhook` rather than building one.
- Remote MCP clients (Claude, ChatGPT) connect **from the vendor's cloud**, so the server needs a
  **public HTTPS URL** — localhost/LAN/VPN are unreachable by them.
- The `health-connect-webhook` app can set **only the destination URL** — no custom headers, no
  token. So its POST **cannot** be OAuth'd or even API-key'd. Solution: point it at **`localhost`**
  on the same phone, so write traffic never leaves the device (no internet write exposure at all).
- The app is **paid on the Play Store**, but it is open-source (AGPLv3) and ships a **free prebuilt
  APK on its GitHub releases** (latest v1.9.14) — sideload that instead of paying, or build from
  source. Any reader that can POST to localhost works; this app is just the proven default.
- **Ways to fetch Google Fit data (checked 2026-08-14):** the Fit **REST API is closed** to new
  access and dies end of 2026 → the **web** path and **Google Apps Script** path (Apps Script just
  calls that same REST API; all tutorials are pre-2024 and won't work for a new project) are both
  **dead**. **Google Takeout** is manual, not live. A **native Android app using Health Connect** is
  the **only** live programmatic way to read the data. **Decision:** use the free
  `health-connect-webhook` APK **for now**; building our own reader is deferred (see B-Reader).
- **B-Reader (deferred, optional future sub-project):** a minimal Kotlin app that reads Health
  Connect and POSTs **our** JSON contract to `localhost`, replacing the third-party app. Upsides:
  no third-party dependency, and we define the payload (making `webhook_mapper` an exact contract
  instead of defensive guessing). A personal sideloaded app skips Google's Health Connect Play-Store
  permissions review. Cost: real Android/Kotlin work (Health Connect client, WorkManager background
  sync, foreground service + battery exemption, boot start), built/tested on-device. Revisit after
  B1/B2 prove the rest of the system.
- Offloading auth to **Cloudflare Access "managed OAuth"** is **flaky with claude.ai web+mobile**
  (open bug reports; connects from Claude Code but fails from the app). So we **self-host OAuth 2.1**
  (DCR + PKCE) in the MCP server; Cloudflare Tunnel only provides the stable HTTPS URL. Reference
  implementations exist (e.g. `jimprosser/obsidian-web-mcp`, and a documented custom-OAuth-2.1 +
  Cloudflare-Tunnel writeup).
- Stable URL: user will **register a cheap domain and put it on Cloudflare** → named Cloudflare
  Tunnel gives `https://mcp.<domain>`.

---

## 1. Goal

Let the user ask Claude (Desktop + mobile) and ChatGPT about their fitness data from anywhere,
answered from their own data, served by an **OAuth-secured MCP server hosted on a spare Android
phone**, reusing the Phase A Python pipeline. Writes stay on-device (loopback); only a single
OAuth-guarded HTTPS read endpoint is exposed.

## 2. Non-goals (YAGNI)

- No native Android app of our own (reuse `health-connect-webhook` as the on-device reader).
- No custom database for fitness data (keep the JSON store). A small persistent auth store is
  allowed for OAuth token/client state.
- No multi-user support — single user (the owner) only.
- No internet-exposed write endpoint (writes are loopback).
- No Google Fit REST API, no Google Takeout.

## 3. Architecture

Everything runs on **one spare Android phone** that has Google Fit installed (so Health Connect on
that phone holds the data). Three long-lived processes in Termux, plus the reader app:

```
On the phone:
  Google Fit ──► Health Connect (on-device)
        │
        ▼
  [health-connect-webhook app]  ──HTTP POST──►  127.0.0.1  (LOOPBACK — never leaves the phone)
                                                     │
                                                     ▼
                                          [receiver]  ──►  [JSON store]   (Phase A code, unchanged)
                                                                 ▲
                                          [MCP server, HTTP/streamable transport]  reads store
                                                     ▲
                                          [OAuth 2.1 provider]  guards it (bearer tokens)
                                                     ▲
                                          [cloudflared]  named tunnel → https://mcp.<domain>
                                                     ▲
                    ── public HTTPS ──
                                                     ▲
              Claude Desktop • Claude mobile • ChatGPT   (custom OAuth connector)
```

- The Python MCP/OAuth server binds to `127.0.0.1`; only `cloudflared` reaches it.
- Write path = loopback (no internet exposure). Read path = one OAuth-guarded HTTPS endpoint.

**Reused unchanged from Phase A:** `config`, `store`, `util`, `aggregate`, `webhook_mapper`,
`receiver`, and all six MCP tools.

**New in Phase B:**
1. MCP server in **HTTP/streamable transport** (instead of stdio).
2. **OAuth 2.1 provider** (Dynamic Client Registration + PKCE + single-user login + token validation).
3. **cloudflared** named-tunnel configuration.
4. **Termux runtime + autostart** (Termux:Boot), wakelock, battery-optimization exemption.

## 4. Decomposition — two sub-projects, build B1 first

This is too large and too risky for one spec. Split it; **build B1 before writing any OAuth code.**

### B1 — Pipeline + remote reachability (de-risk everything except OAuth)
Deliverable: fitness data flowing on the phone and a tool reachable over the internet, unauthenticated
(or trivially gated), proving the ground is solid.
- Bring up Python 3.11+ in Termux (directly, or via `proot-distro` Ubuntu for pip compatibility).
- Install/run the Phase A package in Termux; run `receiver` (loopback) and confirm the
  `health-connect-webhook` app on the same phone posts to `http://127.0.0.1:<port>/webhook`.
- Add an **HTTP/streamable transport entrypoint** for the MCP server (bind `127.0.0.1`).
- Configure a **named Cloudflare Tunnel** (`cloudflared`) → `https://mcp.<domain>`.
- Prove a client reaches a tool end-to-end via `curl` and/or Claude Code (which tolerates authless).
- **Front-loads the two feasibility unknowns:** (a) Termux can run our stack; (b) the tunnel exposes
  a working MCP. If a client/runtime is incompatible, we learn it here, cheaply, before any auth work.

### B2 — OAuth 2.1 + multi-client + hardening (security-critical; its own spec/plan later)
- Implement the **OAuth 2.1 provider**: `/.well-known/oauth-authorization-server` metadata,
  `/register` (DCR), `/authorize` (auth code + PKCE, gated by a single owner login credential),
  `/token` (code → access/refresh tokens); the MCP endpoint validates bearer tokens.
- Persist client registrations + tokens in a small auth store (SQLite or JSON) on the phone.
- Onboard **Claude Desktop, Claude mobile, and ChatGPT** as custom OAuth connectors; document each.
- Hardening: Cloudflare WAF + rate-limiting; confirm only MCP + OAuth endpoints are exposed.
- **Termux autostart** (Termux:Boot) for receiver + MCP/OAuth server + cloudflared; wakelock; battery.

Each sub-project is independently testable and delivers something real. B1 is brainstormed/spec'd/built
first; B2 gets its own spec → plan once B1 proves the pipeline.

## 5. Data flow

`Google Fit → Health Connect (phone) → health-connect-webhook app → POST 127.0.0.1 → receiver →
JSON store → MCP server (HTTP) ← [OAuth bearer] ← cloudflared → https://mcp.<domain> ← Claude/ChatGPT`

## 6. Components & interfaces (Phase B additions)

- **HTTP MCP entrypoint** (`server` HTTP mode or a new `server_http` module): serves the existing six
  tools over streamable HTTP, bound to `127.0.0.1:<mcp_port>`. Depends on `store` + `aggregate`.
- **OAuth 2.1 provider** (B2): standard AS endpoints + a resource-server token verifier the MCP
  endpoint calls. Single owner credential from config/env. Depends on a small persistent auth store.
- **Tunnel config** (`cloudflared`): named tunnel mapping `mcp.<domain>` → `127.0.0.1:<mcp_port>`.
- **Process supervision** (B2): Termux:Boot scripts starting receiver, MCP/OAuth server, cloudflared.

## 7. Error handling & security posture

- Server binds to `127.0.0.1`; the tunnel is the only public ingress. No internet-exposed write path.
- OAuth 2.1 with PKCE; short-lived access tokens + refresh; single-user login gate; TLS terminated at
  Cloudflare. Cloudflare WAF/rate-limiting as defense-in-depth.
- The reader app posts to loopback only; a bad payload never crashes the receiver (Phase A behavior).
- Token/client secrets never placed in URLs (avoid log leakage); use OAuth/headers.

## 8. Testing

- Reuse Phase A unit/integration tests unchanged.
- B1: an integration check that the HTTP MCP entrypoint serves `list_data_coverage`/tools locally
  (e.g. against a seeded store) and over the tunnel via `curl`; a manual end-to-end from a client.
- B2: OAuth flow tests (DCR, PKCE auth-code exchange, token validation, rejection of missing/expired
  tokens); manual connector onboarding from Claude Desktop, Claude mobile, and ChatGPT.

## 9. Top risks / feasibility unknowns (verify early in B1)

1. **Termux can run the stack** — Python 3.11+, the `mcp` package (pydantic-core is Rust; aarch64
   wheels usually exist, else `proot-distro` Ubuntu), and `cloudflared`, staying alive in background.
2. **Self-hosted OAuth-DCR compatibility** — the flow must work from **Claude mobile** and **ChatGPT**
   against a self-hosted server, not just Claude Code (there are known claude.ai app quirks). Prove the
   OAuth path against each real client early in B2.
3. **The server phone actually has the data** — Google Fit must be logged in on that phone and syncing
   to its Health Connect, so the reader app has something to read.
4. **Battery/uptime** — a phone running three services + a tunnel 24/7 needs wakelock and
   battery-optimization exemptions; confirm it survives sleep/reboot.

## 10. Open questions (resolve during B1/B2 planning)

1. Run Python natively in Termux vs `proot-distro` Ubuntu (pip/wheel compatibility for `mcp`).
2. Exact HTTP transport: MCP **streamable HTTP** (preferred, modern) vs SSE — pick per current
   `mcp` SDK + client support.
3. Auth-state storage: small **SQLite** vs JSON for OAuth client/token registry.
4. Whether to keep `receiver` as a separate process or fold loopback ingest into the same process as
   the MCP server (two-process vs one-process on the phone).
