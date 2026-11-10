<p align="center">
  <img src="assets/social-preview.jpg" alt="AppFlowy MCP Server — documents, typed database rows and Markdown workflows for AI agents" width="840">
</p>

# AppFlowy MCP Server

[![CI](https://github.com/Rahulk644/Appflowy-MCP-Server/actions/workflows/ci.yml/badge.svg)](https://github.com/Rahulk644/Appflowy-MCP-Server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

An open-source **AppFlowy MCP server** (Model Context Protocol) for connecting
**Claude, Cursor, Codex and other MCP clients** to your AppFlowy workspace. Give AI
agents tools to edit Markdown documents, update typed database rows and Board
cards, search pages, and import or export Markdown trees.

Run locally with `uvx` or Docker, or serve authenticated Streamable HTTP. The
compact profile exposes **11 async workflow tools** with typed inputs, bounded
responses and explicit results for partial batch failures.

Independent community project; not affiliated with or endorsed by AppFlowy.
The tested self-hosted baseline is Cloud **0.20.5** with Web **0.20.11**.
See [compatibility and limitations](COMPATIBILITY.md) before choosing a deployment.

[Quick start](#quick-start) · [Client setup](examples/README.md) · [Tools](#tools) ·
[Compatibility](COMPATIBILITY.md)

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/), or Docker. The commands
below use the published **2.1.0** release. `main` can contain unreleased fixes;
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
uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.1.0 \
  appflowy-mcp --env-file /absolute/path/to/.env
```

Example Claude Desktop/Cursor-style configuration:

```json
{
  "mcpServers": {
    "appflowy": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.1.0",
        "appflowy-mcp", "--env-file", "/absolute/path/to/.env"
      ]
    }
  }
}
```

[Client recipes](examples/README.md) also cover Claude Code, Codex and Docker.
Check configuration and workspace access with the same launcher:

```bash
uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.1.0 \
  appflowy-mcp doctor --check --env-file /absolute/path/to/.env
```

`doctor` without `--check` stays offline; `--json` produces a sanitized report.

### Docker

The public image supports Linux amd64 and arm64. For stdio:

```bash
docker run --rm -i --env-file .env \
  ghcr.io/rahulk644/appflowy-mcp-server:2.1.0 appflowy-mcp
```

For HTTP, add `MCP_SECRET_TOKEN` to `.env` and run:

```bash
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 \
  ghcr.io/rahulk644/appflowy-mcp-server:2.1.0
```

The MCP endpoint is `/mcp/`; legacy SSE is `/sse/`. The image is listed in the
[official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Rahulk644%2Fappflowy-mcp-server/versions/2.1.0).
**PyPI publication is deferred.** [RELEASING.md](RELEASING.md) covers publishing.

For a source-built service, configure `.env` and run `docker compose up -d --build`.
The Compose file does not publish a port; connect it to your HTTPS reverse proxy.
Traefik labels require an existing proxy and shared Docker network. The optional
`deploy_vps.sh` starts the service; it does not provision public routing or TLS.

## Built for AppFlowy workflows

- **Typed database edits:** resolve field names and select options, write Number,
  Checkbox and DateTime/range cells, and update existing Board cards in batches.
- **Markdown documents:** create and edit pages or row bodies, use guarded
  replacement, and import/export document trees with continuation cursors.
- **A compact interface:** group related operations into async workflows, with an
  exclusive legacy profile for existing integrations and a read-only profile for
  discovery.
- **Deployment choice:** published amd64/arm64 Docker images, a Git-based `uvx`
  command, local stdio and authenticated HTTP. No source checkout is required.
- **Tested self-hosted baseline:** disposable AppFlowy integration checks and browser
  assertions for typed Grid cells, Board grouping, Formula and Timeline rendering.
  Exact versions and validation limits are in [COMPATIBILITY.md](COMPATIBILITY.md).

| Task for your AI assistant | Relevant workflow |
|---|---|
| Find a project brief and append a meeting checklist | Search, fetch and Markdown update |
| Move an existing Board card to Done | Resolve the Status field, then update that row's cells |
| Build a tracker with dates and select fields | Create a database, configure fields and create typed rows |
| Read a card conversation and reply | Fetch comments by row ID, then append a reply |
| Export a project subtree as Markdown | Export complete files and follow returned continuations |

## Tools

The compact profile exposes **11 async tools**, or **12** with experimental AI
enabled. Parameters are typed JSON inside `request`.
Commands reject non-default inputs they cannot apply. For example, `update_cells`
does not accept row document text, and database creation does not accept Markdown.
Use the relevant document command instead; the validation error names unused fields.

| Tool | Purpose |
|---|---|
| `appflowy_search` | Keyword search with server pagination |
| `appflowy_fetch` | Workspaces, folders, page metadata/Markdown, database fields and comments |
| `appflowy_create_pages` | Batch documents, spaces, databases and database views |
| `appflowy_update` | Page operations, Markdown edits, comment appends and space permissions |
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

Follow returned `next_offset` values rather than adding the requested limit: a
response may contain fewer complete items to fit its budget. Markdown reads use
character offsets and a content hash; folder reads can target an `id`. Tree export
returns complete files, a tree cursor, and fetch instructions for oversized documents.
See the [continuation contract](KNOWLEDGE.md#6-bounds-importexport-and-partial-outcomes).

`APPFLOWY_TOOL_PROFILE=legacy` exposes 36 tools: the original 34 names plus two
comment tools.
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

## Frequently asked questions

### What is an AppFlowy MCP server?

An AppFlowy MCP server translates requests from an MCP client into AppFlowy
operations. This community server uses AppFlowy's REST and collaboration APIs to
read and edit documents, database schemas, rows and blocks. It is MIT licensed
and is not an official AppFlowy product.

### Can I connect Claude, Cursor or Codex?

Yes, through their MCP configuration. Use local stdio for a client-launched
process or Streamable HTTP for a running service. Copy the
[client-specific recipes](examples/README.md). Automated checks cover the MCP
protocol and packaged server; individual desktop interfaces are not certified.

### Does it work with self-hosted AppFlowy?

The disposable CI baseline is AppFlowy Cloud **0.20.5** with Web **0.20.11** from
the first-party commercial self-host stack. `APPFLOWY_BASE_URL` selects the origin.
The default origin is AppFlowy SaaS; current SaaS behavior still needs a dedicated
live validation run. See [deployment evidence](COMPATIBILITY.md).

### Can I install it without cloning the repository?

Yes. Use the [Git-based `uvx` command](#local-mcp-client-stdio) or the public
[Docker image](#docker). GitHub Releases also provide wheel/source assets. PyPI
publication is deferred; the setup commands do not depend on a PyPI publication.

### Can an assistant read and reply to AppFlowy comments?

Yes. Use `appflowy_fetch(kind="comments")` to read document, card-row or published
page comments, and `appflowy_update(command="append_comment")` to append or reply.
Comments use the bot identity. Read back after an uncertain result before retrying;
see the [comment recipes and limits](KNOWLEDGE.md#9-comments).

### Can I give an assistant read-only access?

Set `APPFLOWY_READ_ONLY=true` to expose five read-only compact tools and reject
API mutations. `ALLOWED_WORKSPACE_IDS` restricts workspaces for the whole server.
All approved HTTP clients use the configured bot account; OAuth does not give
each client a separate AppFlowy identity. See [SECURITY.md](SECURITY.md).

## Limits and development

- Disposable CI verifies typed Grid cells, Board grouping, a calculated Formula
  and a rendered Timeline. Complex formulas and all view interactions still need
  deployment-specific validation; see [COMPATIBILITY.md](COMPATIBILITY.md).
- Row details can lag live collaboration state. Cell writes confirm against the
  row collab; do not recreate a row solely because a REST read is stale.
- Field deletion refuses local schema/view dependencies and names the settings to
  reconfigure first. Delete Relation fields in AppFlowy for reciprocal-link cleanup;
  incoming references from other databases are not inspected.
- Document replacement checks a fetched snapshot and then sends a merging update;
  it is not an atomic server-side compare-and-swap.
- Tables fall back to text. Rich media, columns, PDF/ZIP conversion and large-file
  multipart workflows are incomplete. Small uploads do not insert media blocks.
- Current SaaS and AI answer generation are not certified by self-hosted CI.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and checks,
[ARCHITECTURE.md](ARCHITECTURE.md) for implementation boundaries,
[COMPATIBILITY.md](COMPATIBILITY.md) for evidence, and [ROADMAP.md](ROADMAP.md)
for prioritized remaining work. Licensed under [MIT](LICENSE).
