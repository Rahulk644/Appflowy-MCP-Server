# Architecture

## Request flow

An MCP client connects over stdio or authenticated HTTP. `MCPServer` handles the
protocol. Compact tools validate a typed `request`, enforce workspace selection,
and call the shared async AppFlowy backend. Reads and ordinary creates use REST;
structural edits fetch a collaboration snapshot and send an incremental CRDT diff.

```text
MCP transport → profile/tool registration → typed workflow → workspace guard
                                                       ├─ REST API
                                                       └─ collab read → local edit → merging diff
```

## Module boundaries

| Location | Responsibility |
|---|---|
| `appflowy_mcp/cli.py` | Environment loading, serve/doctor commands, transport startup |
| `appflowy_mcp/models.py` | Compact input schemas, bounds and permission objects |
| `appflowy_mcp/workflows.py` | Compact orchestration, typed cells, pagination and batch results |
| `appflowy_mcp/server.py` | Shared async backend, Markdown/CRDT conversion, legacy tools, MCP/HTTP lifecycle |
| `appflowy_mcp/google_oauth.py` | Google identity federation and token/client persistence |
| `appflowy_mcp/diagnostics.py` | Offline checks and optional sanitized connection diagnostics |
| Root `server.py` / `google_oauth.py` | Documented compatibility entry points |
| `tests/` | Offline regressions, protocol contracts and opt-in disposable integration/browser checks |
| `scripts/` | Build/install checks, manifest measurement, decoder checks and disposable stack runner |
| `live_compatibility.py` | Operator harness for an explicitly configured deployment |

The backend is still large. Extraction into API, document and database modules is
follow-up work; do not replace it with speculative plugin/factory layers. The
compatibility entry points and async-name aliases have callers and remain intentional.

## Profiles and annotations

Registration happens once at process startup. Compact and legacy tools are never
registered together. Compact mode has 11 tools; AI adds one only when enabled.
Read-only compact mode has five tools with mutation commands absent from schemas.
A separate backend guard rejects non-read API methods.

Mixed-command mutation tools use conservative behavior hints. They cannot promise
idempotence because creates, imports and appends can duplicate work. Hints guide
clients and are not authorization checks. Restart and reconnect after changing
profile configuration.

## State and concurrency

One reusable `httpx.AsyncClient` serves AppFlowy calls. An async lock serializes
login/refresh. Both stdio and HTTP close the client on shutdown; HTTP also starts
and stops the MCP session manager. The application targets one event loop per
process. CPU work such as Markdown parsing and snapshot decoding remains local.

OAuth stores are in memory unless `OAUTH_STORE_PATH` is set. File writes use a
private temporary file and atomic replacement. This is a **single-process store**,
not a shared database. Multiple workers can overwrite each other's state; use one
worker. Refresh credentials rotate inside a fixed login family. Hashed spent-token
records detect reuse and revoke that family's access and refresh grants, including
after restart. Token writes commit before credentials are returned. Transient
sign-in state/codes and expired grants are pruned on provider activity. A narrow
SDK 2.3 revocation adapter accepts public clients without a secret and Basic clients
without a form client ID; authentication still delegates to the SDK. Contract
coverage retains CORS, request-body limits and confidential-client secret checks.

## Data integrity

A folder view ID and database ID are different. A database row's body is a separate
document collab. Body tools resolve a row ID to that document. Structural edits
must capture the state vector before mutation and send only the resulting diff.
Never replace an unreadable snapshot with an empty document or upload a whole
replacement collab. The supported decoder remains pycrdt 0.13.0.

Typed row writes resolve field names/IDs and options before creating rows. Cell
writes verify authoritative readback; batch partial failures retain row IDs so
clients can finish edits without creating duplicates. Page deletion means trash;
row/block/field deletion changes collaboration structures.

Markdown replacement requires the expected fetched content. This protects against
an already-stale read but cannot prevent edits arriving after that snapshot.
Client-side list paging bounds responses; some upstream routes still return a
complete list. Response limits do not establish a bound on upstream snapshot size.

## Source and release policy

Use current AppFlowy-Web contracts plus live validation against the pinned
first-party commercial stack; archived backend routes alone are insufficient.
Exact commits, image digest, evidence and validation gaps are in
[COMPATIBILITY.md](COMPATIBILITY.md).

`pyproject.toml`, `requirements.txt`, the runtime version and `server.json` must
stay consistent. Release publishing validates versions, gates on package and
compatibility checks, then publishes GHCR and registry metadata. PyPI remains
disabled. Published tags/images are immutable release artifacts; fixes on `main`
need a new patch version before they reach installed stable clients.
