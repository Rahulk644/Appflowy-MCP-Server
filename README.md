<p align="center">
  <img src="assets/social-preview.png" alt="AppFlowy MCP Server" width="840">
</p>

# AppFlowy MCP Server

<div align="center">

[![CI](https://github.com/Rahulk644/appflowy-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Rahulk644/appflowy-mcp-server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)](https://modelcontextprotocol.io)

</div>

An open-source **[Model Context Protocol](https://modelcontextprotocol.io) server for [AppFlowy Cloud](https://appflowy.com)** — so AI agents can **read, build, and finish work** in your AppFlowy workspace.

Not just *view* a Kanban board: create databases and pages, move cards, edit and delete rows, and edit document blocks (including advanced ones like callouts and toggles) — all over a single endpoint that's **scoped to exactly the workspaces you choose** and gated by **Google OAuth or a token**.

> ℹ️ Independent community project — not affiliated with or endorsed by AppFlowy. It talks to the public AppFlowy Cloud API with an account you control.

## ✨ Highlights

- **Full CRUD, not read-only.** Create pages/databases/fields/rows, and — via a collaborative-editing (CRDT) layer — **edit, move, and delete *any* existing row or document block**, including ones made by hand in the UI.
- **Advanced blocks the REST API can't make.** Callouts, toggles, quotes, code, columns, and more, placed programmatically.
- **Scoped by design.** `ALLOWED_WORKSPACE_IDS` makes every tool refuse anything outside your allow-list — even if the account can see more.
- **Three ways to connect.** Google **OAuth sign-in**, a Bearer **header** token, or a token-in-**URL link** for UIs that can't set headers. Works with Claude, Cursor, Antigravity, and any MCP client.
- **Agent-ready.** Ships an AppFlowy "knowledge pack" as MCP server instructions (see [KNOWLEDGE.md](KNOWLEDGE.md)) so agents build clean, well-formed structures.
- **Batteries included.** stdio / Streamable-HTTP / SSE transports, Docker, tests, and CI.

## 🧰 Tools

**Read** — `get_workspaces`, `get_workspace_folder`, `list_databases`, `get_database_fields`, `get_database_row_ids`, `get_database_row_details`, `get_page`, `list_updated_rows`

**Create & structure** (plain JSON, no CRDT) — `create_page`, `create_database` (grid/board/calendar), `create_database_view`, `add_database_field`, `create_database_row`, `upsert_database_row`, `append_blocks`, `create_space`, `move_page`, `duplicate_page`, `rename_page`, `trash_page`, `restore_page`

**Edit & delete — any row or block** (collab/CRDT layer) — `update_row_cells` (e.g. move a Board card by setting its Status), `delete_row`, `add_block` (incl. advanced: callout / toggle / quote / code…), `edit_block_text`, `delete_block`

**Schema editing** (collab/CRDT) — `update_database_field`, `delete_database_field`, `add_select_option`, `delete_select_option`

Row bodies accept **Markdown**, rendered into real blocks (headings, lists, interactive checkboxes, tables, code, math). Field-type ids, the page block-tree schema, and the full block palette are documented in [KNOWLEDGE.md](KNOWLEDGE.md).

## 🏗️ How it works

```
  MCP client                      this server                    AppFlowy Cloud
 (Claude, Cursor,   ── OAuth / ──►  (you host it)   ── bot ──►   (your workspace)
  Antigravity …)      token                           account
                                   ├─ REST API .......... reads, create page/db/field/row, append blocks, markdown docs
                                   └─ collab/CRDT (pycrdt)  edit/move/delete any row or block, advanced blocks
```

The server logs into AppFlowy Cloud with a **dedicated bot account** and exposes MCP tools. Most operations use the JSON REST API; surgical edits/deletes and advanced blocks go through AppFlowy's collaborative (Yjs/CRDT) layer via a merging update, so they're safe alongside live editing.

## 🚀 Quick start

### Local (stdio) — most private, nothing exposed
```bash
cp .env.example .env      # fill in APPFLOWY_EMAIL / APPFLOWY_PASSWORD
pip install -r requirements.txt
python server.py
```

### Docker / VPS — for remote & unattended agents
```bash
cp .env.example .env      # fill in credentials + MCP_SECRET_TOKEN (and OAuth, optional)
docker compose up -d --build
```
`docker-compose.yaml` includes optional Traefik labels. **Keep the port off the open internet** — front it with an identity gate (e.g. Cloudflare Tunnel + Access) and/or the built-in auth. A guided `deploy_vps.sh` is included for a first deploy.

## ⚙️ Configuration (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `APPFLOWY_EMAIL` / `APPFLOWY_PASSWORD` | ✅ | Dedicated bot account login. |
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
{ "mcpServers": { "appflowy": { "command": "python", "args": ["/absolute/path/to/server.py"] } } }
```

## 🔐 Security

AppFlowy Cloud auth is full-account (there are **no scoped API keys**), so:
- Use a **dedicated bot account** invited only to the workspace(s) you expose.
- Set **`ALLOWED_WORKSPACE_IDS`** — enforced on every tool.
- Gate the endpoint with **OAuth** (email allow-list) or **`MCP_SECRET_TOKEN`**, and keep the port off the open internet.

Full details and vulnerability reporting: [SECURITY.md](SECURITY.md).

## 🧪 Development

```bash
pip install -r requirements.txt
ruff format . && ruff check .
pytest -q
```
CI runs lint, format-check, and tests on every push/PR.

## 🩺 Troubleshooting

**`ValueError: Cannot decode update: while reading, an unexpected value was found`** — a **pycrdt 0.14.1 regression** fails to decode some AppFlowy *database* collabs, which breaks every collab-layer structural op (`delete_row`, field/option edits) on the affected database while row cell-writes keep working. `requirements.txt` pins **`pycrdt==0.13.0`** to avoid it — don't unpin past `0.13` until it's fixed upstream.

**A write looks like it didn't apply** — `get_database_row_details` reads a materialized view that can lag the live collab by minutes; the write is usually fine. `update_row_cells` confirms its own write against the collab (with retry) before returning, so its success result is trustworthy.

## 🧭 How this compares

[`LucasXu0/appflowy_mcp`](https://github.com/LucasXu0/appflowy_mcp) covers pages/folders/trash/favorites. This server adds **database write-back, full row/block edit & delete via the collab layer, workspace scoping, and OAuth** — aimed at agents that *finish* work on a board, not just read it.

## 🗺️ Roadmap

- Pagination + filtering on large database reads
- Reorder fields; manage filters, sorts, and Board grouping
- Richer inline formatting on collab edits

## 🤝 Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## 📄 License

[MIT](LICENSE).
