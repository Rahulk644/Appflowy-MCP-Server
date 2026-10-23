<p align="center">
  <img src="assets/social-preview.png" alt="AppFlowy MCP Server" width="840">
</p>

# AppFlowy MCP Server

[![CI](https://github.com/Rahulk644/Appflowy-MCP-Server/actions/workflows/ci.yml/badge.svg)](https://github.com/Rahulk644/Appflowy-MCP-Server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

Connect MCP clients to AppFlowy documents, databases and rows. The server provides
Markdown editing, typed batch row operations, search, import/export and database
schema changes through AppFlowy's REST and collaboration APIs.

Independent community project; not affiliated with or endorsed by AppFlowy.
The tested self-hosted baseline is Cloud **0.20.5** with Web **0.20.11**.
See [compatibility and limitations](COMPATIBILITY.md) before choosing a deployment.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/), or Docker. The commands
below use the published **2.0.0** release. `main` can contain unreleased fixes;
see [CHANGELOG.md](CHANGELOG.md).

Create a private `.env` file with a dedicated AppFlowy bot account:

```dotenv
APPFLOWY_EMAIL=bot@example.com
APPFLOWY_PASSWORD=replace-with-the-bot-password
ALLOWED_WORKSPACE_IDS=replace-with-workspace-id
# APPFLOWY_BASE_URL=https://your-self-hosted-appflowy.example.com
```

An `APPFLOWY_ACCESS_TOKEN` can replace email/password. It takes precedence and
must be replaced when it expires. [.env.example](.env.example) lists all settings.

### Local MCP client (stdio)

Run without cloning or creating a virtual environment:

```bash
uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.0.0 \
  appflowy-mcp --env-file /absolute/path/to/.env
```

Example Claude Desktop/Cursor-style configuration:

```json
{
  "mcpServers": {
    "appflowy": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.0.0",
        "appflowy-mcp", "--env-file", "/absolute/path/to/.env"
      ]
    }
  }
}
```

[Client recipes](examples/README.md) also cover Claude Code, Codex and Docker.
Check configuration and workspace access with the same launcher:

```bash
uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.0.0 \
  appflowy-mcp doctor --check --env-file /absolute/path/to/.env
```

`doctor` without `--check` stays offline; `--json` produces a sanitized report.

### Docker

The public image supports Linux amd64 and arm64. For stdio:

```bash
docker run --rm -i --env-file .env \
  ghcr.io/rahulk644/appflowy-mcp-server:2.0.0 appflowy-mcp
```

For HTTP, add `MCP_SECRET_TOKEN` to `.env` and run:

```bash
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 \
  ghcr.io/rahulk644/appflowy-mcp-server:2.0.0
```

The MCP endpoint is `/mcp/`; legacy SSE is `/sse/`. The image is listed in the
[official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Rahulk644%2Fappflowy-mcp-server/versions/2.0.0).
**PyPI publication is deferred.** [RELEASING.md](RELEASING.md) covers publishing.

For a source-built service, configure `.env` and run `docker compose up -d --build`.
The Compose file does not publish a port; connect it to your HTTPS reverse proxy.
Traefik labels require an existing proxy and shared Docker network. The optional
`deploy_vps.sh` starts the service; it does not provision public routing or TLS.

## Tools

The compact profile exposes **11 async tools**, or **12** with experimental AI
enabled. Parameters are typed JSON inside `request`.

| Tool | Purpose |
|---|---|
| `appflowy_search` | Keyword search with server pagination |
| `appflowy_fetch` | Workspaces, folders, page metadata/Markdown and database fields |
| `appflowy_create_pages` | Batch documents, spaces, databases and database views |
| `appflowy_update` | Rename, move, duplicate, trash/restore, Markdown edits and space permissions |
| `appflowy_delete` | Page trash; row, block and field deletion |
| `appflowy_database` | Fields, options, grouping, Formula expressions and Timeline settings |
| `appflowy_rows` | Bounded reads and typed batch create/upsert/update/delete |
| `appflowy_blocks` | Markdown/advanced blocks, inline edits and text replacement |
| `appflowy_import` | Markdown trees and small base64 file payloads |
| `appflowy_export` | Bounded Markdown page/tree export |
| `appflowy_api` | Additional workspace-relative REST routes |
| `appflowy_ai` (opt-in) | Experimental AppFlowy chat with explicit context |

```json
{"request":{"workspace_id":"WORKSPACE_ID","database_id":"DATABASE_ID","command":"update_cells","rows":[{"row_id":"ROW_ID","cells":{"Name":"Updated task","Done":true}}]}}
```

`APPFLOWY_TOOL_PROFILE=legacy` exposes the original 34 tool names instead.
`APPFLOWY_READ_ONLY=true` exposes five read-only tools in compact mode and rejects
API mutations. Profiles are exclusive. Read the [migration table](MIGRATION.md)
and [agent guide](KNOWLEDGE.md), also available as `appflowy://guide`.
[Manifest measurements](benchmarks/README.md) measure bytes, not LLM accuracy.

## Configuration and HTTP access

| Setting | Behavior |
|---|---|
| `APPFLOWY_EMAIL` / `APPFLOWY_PASSWORD` | Dedicated account login with automatic token refresh |
| `APPFLOWY_ACCESS_TOKEN` | Alternative AppFlowy access token; no automatic renewal |
| `APPFLOWY_BASE_URL` | AppFlowy origin; defaults to `https://beta.appflowy.cloud` |
| `ALLOWED_WORKSPACE_IDS` | Comma-separated server-wide workspace allow-list |
| `APPFLOWY_TOOL_PROFILE` | `compact` (default) or `legacy` |
| `APPFLOWY_READ_ONLY` | Disable writes; compact read-only schemas |
| `APPFLOWY_ENABLE_AI` | Opt into experimental AI on a configured deployment |
| `MCP_SECRET_TOKEN` | HTTP shared secret, sent as `Authorization: Bearer ...` |
| `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` | Explicit public host/origin when proxied; include custom ports |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional Google OAuth credentials |
| `ALLOWED_EMAILS` / `OAUTH_ISSUER` | OAuth email allow-list and public HTTPS origin |
| `OAUTH_STORE_PATH` | Private JSON token store on a persistent volume |

For an installed command, `appflowy-mcp --transport streamable-http` listens on
`127.0.0.1:8000`; `--host` and `--port` change the bind address. Source checkouts
also support `python server.py` and `uvicorn server:app`.

For Google OAuth, register a Google Web client with redirect URI
`https://YOUR_HOST/auth/google/callback`, configure the OAuth settings above, and
connect the MCP client to `https://YOUR_HOST/mcp/`. For shared-secret clients:

```json
{"mcpServers":{"appflowy":{"url":"https://mcp.example.com/mcp/","headers":{"Authorization":"Bearer YOUR_MCP_SECRET_TOKEN"}}}}
```

The `?token=...` URL form is supported for clients without header support; URLs
can leak through proxies, logs and browser history. Prefer headers or OAuth.

All HTTP users act through the same AppFlowy account and server-wide workspace
policy. OAuth identifies clients; it does not grant each client a separate
AppFlowy role or page-subtree scope. Protect remote HTTP with authentication and
HTTPS. See [SECURITY.md](SECURITY.md).

Token refresh is also a separate opt-in mode. It runs only the initial authenticated
workspace request, the GoTrue refresh grant, and a second authenticated workspace
request. It verifies that refresh did not silently fall back to password login:

```bash
python live_compatibility.py --validate-token-refresh \
  --output compatibility-report.token-refresh.json
```

The report records only sanitized response shapes and boolean refresh properties;
access and refresh token values are never written to disk.

Reversible mode creates a disposable page, verifies a collab document edit, trashes
the page, and—when a database plus writable text field are available—creates a
disposable row, verifies a collab cell edit, and hard-deletes that temporary row.
`APPFLOWY_COMPAT_ROW_FIELD_ID` is optional when the harness can identify a primary or
RichText field from the database schema.

## Limits and development

- Formula/Timeline support covers schema persistence; calculated results and the
  complete view UI still need deployment-specific validation.
- Row details can lag live collaboration state. Cell writes confirm against the
  row collab; do not recreate a row solely because a REST read is stale.
- Document replacement checks a fetched snapshot and then sends a merging update;
  it is not an atomic server-side compare-and-swap.
- Tables fall back to text. Rich media, columns, PDF/ZIP conversion and large-file
  multipart workflows are incomplete. Small uploads do not insert media blocks.
- Current SaaS and AI answer generation are not certified by self-hosted CI.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and checks,
[ARCHITECTURE.md](ARCHITECTURE.md) for implementation boundaries,
[COMPATIBILITY.md](COMPATIBILITY.md) for evidence, and [ROADMAP.md](ROADMAP.md)
for prioritized remaining work. Licensed under [MIT](LICENSE).
