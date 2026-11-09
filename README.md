<p align="center">
  <img src="assets/social-preview.png" alt="AppFlowy MCP Server" width="840">
</p>

# AppFlowy MCP Server

<div align="center">

[![CI](https://github.com/Rahulk644/appflowy-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Rahulk644/appflowy-mcp-server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)](https://modelcontextprotocol.io)

</div>

An open-source **[Model Context Protocol](https://modelcontextprotocol.io) server for [AppFlowy Cloud](https://appflowy.com)** — so AI agents can **read, build, and finish work** in your AppFlowy workspace.

Not just *view* a Kanban board: create databases and pages, move cards, edit and delete rows, and edit document blocks (including advanced ones like callouts and toggles) — all over a single endpoint that's **scoped to exactly the workspaces you choose** and gated by **Google OAuth or a token**.

> ℹ️ Independent community project — not affiliated with or endorsed by AppFlowy. It talks to the public AppFlowy Cloud API with an account you control.

## ✨ Highlights

- **Full CRUD, not read-only.** Create pages/databases/fields/rows, and — via a collaborative-editing (CRDT) layer — **edit and delete existing rows or document blocks**, including ones made by hand in the UI.
- **Advanced blocks the REST API can't make.** Callouts, toggles, quotes, code, columns, and more, placed programmatically.
- **Scoped by design.** `ALLOWED_WORKSPACE_IDS` makes every tool refuse anything outside your allow-list — even if the account can see more.
- **Three ways to connect.** Google **OAuth sign-in**, a Bearer **header** token, or a token-in-**URL link** for UIs that can't set headers. Uses standard MCP stdio or HTTP; client recipes are in [examples](examples/README.md).
- **Agent-ready.** Ships an AppFlowy "knowledge pack" as MCP server instructions **and a fetchable `appflowy://guide` resource** (see [KNOWLEDGE.md](KNOWLEDGE.md)) so agents build clean, well-formed structures.
- **Batteries included.** stdio / Streamable-HTTP / SSE transports, Docker, tests, and CI.

## 🧰 Tools

The default **compact** profile exposes **11 async tools**, or **12** when
AppFlowy AI is explicitly enabled. All names start with `appflowy_`. Parameters
are structured JSON inside `request`; cell values never require a JSON string.

| Tool | Workflows |
|---|---|
| `appflowy_search` | Keyword search with server pagination |
| `appflowy_fetch` | Workspaces, folder trees, page metadata/Markdown, database fields |
| `appflowy_create_pages` | Batch documents, spaces, databases and database views |
| `appflowy_update` | Rename, move, duplicate, trash/restore, append/prepend/replace, space permissions |
| `appflowy_delete` | Page trash and row/block/field deletion |
| `appflowy_database` | Fields, select options, grouping, Formula expressions, Timeline settings |
| `appflowy_rows` | Bounded reads and typed batch create/upsert/update/delete |
| `appflowy_blocks` | Markdown/advanced blocks, inline edits, deletion and text replacement |
| `appflowy_import` | Markdown tree entries and bounded base64 file uploads |
| `appflowy_export` | Bounded Markdown page/tree export |
| `appflowy_api` | Additional REST routes within the selected workspace |
| `appflowy_ai` *(opt-in)* | AppFlowy chat with explicit page or workspace context |

Example tool arguments:

```json
{"request": {"command": "update_cells", "workspace_id": "WORKSPACE_ID", "database_id": "DATABASE_ID", "rows": [{"row_id": "ROW_ID", "cells": {"Name": "Updated task", "Done": true}}]}}
```

`APPFLOWY_TOOL_PROFILE=legacy` exposes the original 34 names instead. Profiles are
exclusive; aliases do not inflate the compact manifest. `APPFLOWY_READ_ONLY=true`
exposes five read-only tools and enforces the policy below tool routing.
See the [migration table](MIGRATION.md), [agent guide](KNOWLEDGE.md), and
[measured manifest sizes](benchmarks/current.json). Byte measurements do not
establish LLM selection accuracy or a fixed token/latency saving.

## 📦 What you can build

AppFlowy's editor and API offer a large palette of blocks, views, and inline styles.
Here's what this MCP creates **today** — the rest is on the roadmap below.

**Legend:** ✅ full · 🟡 partial · 🗺️ roadmap · ⛔ not an MCP capability

| Category | Supported now | Partial / roadmap |
|---|---|---|
| **Text blocks** | Text, Heading 1–3, bulleted / numbered / to-do lists, quote, code, callout, toggle, divider | 🟡 simple table (GFM in Markdown) · 🗺️ link-to-page, breadcrumb |
| **Media** | Image by URL | 🟡 Bounded binary uploads by payload; rich media workflows, galleries, bookmarks and embeds remain partial |
| **Database** | Grid / Board / Calendar and additional layouts, Board grouping, select options, Formula definitions and Timeline settings | 🟡 Additional layouts depend on backend permissions/version; inline & linked views remain roadmap |
| **Advanced** | Callouts (`> [!NOTE]`), block & inline equations (`$$` / `$…$`), toggle-headings (via `appflowy_blocks`) | 🗺️ columns, table of contents, Mermaid |
| **Inline style** | Bold / italic / strike / code / link, **page @mention** (`[](mention:id)`), color (page bodies), emoji | 🗺️ underline, background color, person-mention (not in AppFlowy), date & reminder |
| **AI blocks** | — | ⛔ AI note / transcript / summarize / ask — these run AppFlowy's own AI, not insertable content |

Recipes and current limits live in [KNOWLEDGE.md](KNOWLEDGE.md).

## 🏗️ How it works

```
  MCP client                      this server                    AppFlowy Cloud
 (Claude, Cursor,   ── OAuth / ──►  (you host it)   ── bot ──►   (your workspace)
  Antigravity …)      token                           account
                                   ├─ REST API .......... reads, create page/db/field/row, append blocks, markdown docs
                                   └─ collab/CRDT (pycrdt)  edit/move/delete any row or block, advanced blocks
```

The server logs into AppFlowy Cloud with a **dedicated bot account** and exposes MCP tools. Most operations use the JSON REST API; surgical edits/deletes and advanced blocks go through AppFlowy's collaborative (Yjs/CRDT) layer via a merging update, so concurrent updates merge. Replacement still requires a fresh read; it is not a server-side atomic compare-and-swap.

## 🚀 Quick start

### Local (stdio)

Install directly from GitHub with `uvx` (no clone or virtualenv setup):

```bash
uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server appflowy-mcp
```

Set `APPFLOWY_EMAIL` / `APPFLOWY_PASSWORD` in the environment or a `.env` file in
the directory you run it from. Set `ALLOWED_WORKSPACE_IDS` to limit access.
Use `--env-file /absolute/path/to/.env` to select another configuration file;
existing environment variables take precedence.

For a checked-out repository:

```bash
cp .env.example .env      # fill in APPFLOWY_EMAIL / APPFLOWY_PASSWORD
uv run appflowy-mcp
```

`python server.py` and `uvicorn server:app` remain supported for existing deployments.
An installed package also supports `python -m appflowy_mcp`, `--help`, and `--version`.

Check configuration without printing credentials:

```bash
appflowy-mcp doctor --env-file /absolute/path/to/.env
appflowy-mcp doctor --check --json --env-file /absolute/path/to/.env
```

`doctor` checks configuration locally; `--check` also verifies workspace access.

### Installed HTTP server

```bash
appflowy-mcp --transport streamable-http --env-file /absolute/path/to/.env
```

This binds to `127.0.0.1:8000`; use `--host` / `--port` to change it. The MCP
endpoint remains `/mcp/`, with legacy SSE at `/sse/`.

### Docker / VPS — for remote & unattended agents
```bash
cp .env.example .env      # fill in credentials + MCP_SECRET_TOKEN (and OAuth, optional)
docker compose up -d --build
```
`docker-compose.yaml` includes optional Traefik labels. **Keep the port off the open internet** — front it with an identity gate (e.g. Cloudflare Tunnel + Access) and/or the built-in auth. A guided `deploy_vps.sh` is included for a first deploy.

The image starts HTTP by default. For a local stdio client, override the command:

```bash
docker run --rm -i --env-file .env appflowy-mcp appflowy-mcp
```

Build the local image first with `docker build -t appflowy-mcp .`.
PyPI and prebuilt GHCR installation instructions are in [RELEASING.md](RELEASING.md);
they become usable after the first release has been published.

## ⚙️ Configuration (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `APPFLOWY_EMAIL` / `APPFLOWY_PASSWORD` | alternative | Dedicated bot account login. |
| `APPFLOWY_ACCESS_TOKEN` | alternative | AppFlowy access token instead of email/password. |
| `APPFLOWY_TOOL_PROFILE` | – | `compact` (default) or `legacy`. |
| `APPFLOWY_READ_ONLY` | – | `true` disables writes and exposes five read-only tools. |
| `APPFLOWY_ENABLE_AI` | – | `true` opts into experimental AI tools on a configured deployment. |
| `APPFLOWY_BASE_URL` | – | Defaults to `https://beta.appflowy.cloud`. |
| `ALLOWED_WORKSPACE_IDS` | strongly recommended | Comma-separated workspace ids the server may touch. |
| `MCP_SECRET_TOKEN` | for network use | Shared token; `openssl rand -hex 32`. |
| `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` | when proxied | Your public host (DNS-rebinding protection). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | for OAuth | Enables Google sign-in (see below). |
| `ALLOWED_EMAILS` | for OAuth | Comma-separated emails allowed to sign in. |
| `OAUTH_ISSUER` | for OAuth | Public base URL, e.g. `https://mcp.example.com`. |

## 🔌 Connecting a client

**Google OAuth** *(recommended for remote/shared use — no token in the link)*
1. Create a Google OAuth **Web** client; set the redirect URI to `https://YOUR_HOST/auth/google/callback`.
2. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAILS`, `OAUTH_ISSUER` and restart.
3. In your MCP client, add a custom connector with **just the URL** `https://YOUR_HOST/mcp/` — it will trigger a Google sign-in.

**Bearer header** *(technical clients / CLIs)*
```json
{ "mcpServers": { "appflowy": {
  "url": "https://mcp.example.com/mcp/",
  "headers": { "Authorization": "Bearer YOUR_MCP_SECRET_TOKEN" }
}}}
```
For stdio-only clients, bridge with `npx mcp-remote https://mcp.example.com/mcp/ --header "Authorization: Bearer YOUR_MCP_SECRET_TOKEN"`.

**Link (token in URL)** *(for UIs that can't set a header)*
```
https://mcp.example.com/mcp/?token=YOUR_MCP_SECRET_TOKEN
```
Convenient, but the token rides in the URL/logs — treat the whole link like a password.

**Local (stdio)**
```json
{ "mcpServers": { "appflowy": {
  "command": "uvx",
  "args": [
    "--from", "git+https://github.com/Rahulk644/Appflowy-MCP-Server",
    "appflowy-mcp", "--env-file", "/absolute/path/to/.env"
  ]
}}}
```

## 🔐 Security

AppFlowy Cloud auth is full-account (there are **no scoped API keys**), so:
- Use a **dedicated bot account** invited only to the workspace(s) you expose.
- Set **`ALLOWED_WORKSPACE_IDS`** — enforced on every tool.
- Gate the endpoint with **OAuth** (email allow-list) or **`MCP_SECRET_TOKEN`**, and keep the port off the open internet.

Full details and vulnerability reporting: [SECURITY.md](SECURITY.md).

## 🧪 Development

```bash
pip install -e '.[dev]'
ruff format . && ruff check .
pytest -q
python -m build
python -m twine check dist/*
python scripts/check_package.py
```
CI runs lint, format-check, tests, clean package installation checks on Linux
(Python 3.11 / 3.12) and Windows (3.12), and Docker MCP checks on every push/PR.
Package and Docker smoke checks use dummy configuration, exercise stdio and
Streamable HTTP, and do not log into AppFlowy. Live checks remain opt-in.

### Live compatibility validation

`live_compatibility.py` is an opt-in operator harness. Ordinary CI is refused;
the manual protected Cloud job requires both explicit CI and disposable-workspace
opt-ins. The disposable local suite needs no private Cloud credentials.
See [COMPATIBILITY.md](COMPATIBILITY.md) for setup and evidence.

Read-only checks:

```bash
APPFLOWY_EMAIL=bot@example.com \
APPFLOWY_PASSWORD=... \
APPFLOWY_BASE_URL=https://appflowy.example.com \
APPFLOWY_COMPAT_DEPLOYMENT_TYPE=self-hosted-docker \
APPFLOWY_COMPAT_VERSION=0.18.5 \
APPFLOWY_COMPAT_BUILD=86feb976d320e3ced95b7acaff57009f4935fcbe \
APPFLOWY_COMPAT_WORKSPACE_ID=... \
python live_compatibility.py --output compatibility-report.json
```

Optional disposable mutation checks are disabled unless explicitly requested:

```bash
APPFLOWY_COMPAT_PARENT_VIEW_ID=... \
APPFLOWY_COMPAT_DATABASE_ID=... \
APPFLOWY_COMPAT_ROW_FIELD_ID=... \
python live_compatibility.py --run-reversible
```

Reversible mode creates a disposable page, verifies a collab document edit, trashes
the page, and—when a database plus writable text field are available—creates a
disposable row, verifies a collab cell edit, and hard-deletes that temporary row.
`APPFLOWY_COMPAT_ROW_FIELD_ID` is optional when the harness can identify a primary or
RichText field from the database schema.

The report records sanitized response shapes. Successful live routes are classified
as `live_validated`; failed or skipped routes keep their evidence basis separately
and are not marked validated. Reports must not include passwords, tokens, userinfo,
private URL paths, or raw server response bodies.

## 🩺 Troubleshooting

**SDK installation errors** — v2 requires Python **3.11+** and the official
`mcp>=2.3,<3` SDK. Reinstall the project's dependencies together; this server now
uses `MCPServer` and supports both modern and legacy protocol connections.

**`KeyError: 'data'` on a database row or Board/Grid page** — fixed. AppFlowy Cloud
moved the collab response shape (envelope or not, `encode_collab`/`encoded_collab`/top
level, `doc_state` as byte array or base64) and began enforcing `CollabType` (a database
row is type **4**, not 5). Update to the latest `main`. If a *new* shape appears, the
error now names the actual keys instead of raising a bare `KeyError`.

**`ValueError: Cannot decode update: while reading, an unexpected value was found`** — a **pycrdt 0.14.1 regression** fails to decode some AppFlowy *database* collabs, which breaks every collab-layer structural op (`delete_row`, field/option edits) on the affected database while row cell-writes keep working. `requirements.txt` pins **`pycrdt==0.13.0`** to avoid it — don't unpin past `0.13` until it's fixed upstream.

**A write looks like it didn't apply** — `get_database_row_details` reads a materialized view that can lag the live collab by minutes; the write is usually fine. `update_row_cells` confirms its own write against the collab (with retry) before returning, so its success result is trustworthy.

## 🧭 Compatibility and alternatives

Current self-hosted 0.20.5 API and browser validation, dependency fixture results,
and remaining gaps are recorded in [COMPATIBILITY.md](COMPATIBILITY.md).
Cloud validation is an explicit opt-in job with a dedicated test workspace;
self-hosted results are not a claim of SaaS certification.

See [DISCOVERY.md](DISCOVERY.md) for a current comparison with weironz, CAREEMER,
Cosmin-DB Toolkit and other community servers. AppFlowy also publishes native
plugins; availability and licensing depend on the deployment.

## 🗺️ Remaining work

- Obtain a representative historical failing pycrdt snapshot before loosening the supported pin.
- Validate AI answer generation on an AI-enabled deployment. The AI tool stays
  outside the default manifest until an operator enables it.
- Broaden view-specific controls, large multipart uploads and rich media workflows.
- Publish to PyPI when requested; current distribution uses GitHub source and GHCR.

## 🤝 Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## 📄 License

[MIT](LICENSE).
