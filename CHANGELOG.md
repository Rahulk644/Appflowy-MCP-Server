# Changelog

## Unreleased

- Validate the v2.2.0 runtime against pinned AppFlowy Cloud 0.21.4 / Web 0.20.12
  and use that deployment in disposable CI. Share deployment metadata between the
  runner and reports; retain the previous baseline's evidence.
- Check a job-local 0.21.4 database snapshot on supported and candidate decoders;
  publish only sanitized results and keep the supported pycrdt pin. Document the
  official MCP's different access model and published capabilities, and correct
  stale table/image limitations.

## 2.2.0 — 2026-11-10

- Convert GFM tables to native AppFlowy simple tables and render table cells back
  to Markdown, preserving inline formatting and line breaks.
- Add optional uploaded-image insertion through the existing bounded import tool
  and `APPFLOWY_PUBLIC_URL` for browser-facing file links. Preserve uploaded file
  identities when image insertion cannot be confirmed; keep existing payload limits.
- Add an operator-only GoTrue refresh check with exact-token readback, short-expiry
  coverage and sanitized diagnostics, adapting contribution #15 to the shared API
  owner. Keep refresh and reversible modes separate and close the client on exit.
- Count pytest assertion failures in disposable compatibility reports, so a failed
  lifecycle cannot report zero failures.

## 2.1.0 — 2026-11-10

- Add comment reads, replies and appends for documents, database rows and published
  pages through the existing compact fetch/update tools. Legacy mode adds two
  comment tools. Preserve author attribution and incremental row-collab edits.
- Bound comment payloads and resource IDs, retain complete comment pages and
  usable cursors, and verify all three comment targets on the disposable stack.
- Fall back to the legacy document endpoint only for definitive unsupported-route
  responses; never replay ambiguous comment writes after errors or timeouts.
- Refresh repository positioning around AppFlowy workflows, typed rows and Markdown.
  Add client/setup answers and evidence links, align package/registry identity, and
  replace the stale tool-count graphic with a light social preview.

## 2.0.2 — 2026-11-09

### Fixed

- Rotate OAuth refresh tokens within a durable login family. Detect replay across
  restarts, revoke only the affected login, expire abandoned state/codes and bound
  public caches. Storage failures return 503 before credentials are issued.
- Support public, Basic and post-client OAuth revocation with the official MCP SDK.
  Existing client registrations survive; upgraded OAuth sessions require a new sign-in.
- Store DateTime timestamps and range/time flags in the collaboration attributes
  AppFlowy renders, preserving unrelated metadata and verifying all changed attributes.
- Reject meaningful command inputs that would otherwise be ignored. Validate whole
  batches before writes. Refuse field deletion while local schema/view references
  remain; delegate Relation deletion to AppFlowy for reciprocal cleanup.
- Preserve complete list records and continuation cursors within response bounds.
  Retain stable identities for oversized records and temporarily unavailable rows.
- Scope folder/export reads to the requested subtree. Export complete files with
  breadth-first continuation, stop document reads at the output budget, and supply
  chunk-fetch instructions for oversized documents. Markdown chunks include a
  character cursor and revision hash.

### Maintenance and validation

- Separate API/session ownership, local document/CRDT conversion and explicit
  profile registration without changing supported entry points or tool counts.
- Use one package version for builds and runtime surfaces, with generated registry
  metadata and one dependency declaration in `pyproject.toml`.
- Attach gated wheel/source artifacts to GitHub Releases. Refuse replacements,
  reuse matching immutable images on retry, and recover the latest stable alias.
  PyPI remains disabled.
- Upgrade pinned workflow actions to Node 24 releases, verify artifact round trips
  on Linux/Windows, and enable weekly dependency-update proposals.
- Expand disposable browser coverage for typed cell updates, Board grouping,
  evaluated Formula and rendered Timeline. Wait for migration/index readiness
  while still requiring an actual search hit and failing unexpected API errors.
- Add official MCP OAuth lifecycle contracts and synthetic workspace benchmarks.
  Document remaining full-list/snapshot costs without claiming production latency.

See [MIGRATION.md](MIGRATION.md) before upgrading OAuth clients or continuation loops.

## 2.0.1 — 2026-11-09

### Fixed

- Mixed-command mutation tools no longer advertise safe automatic retries for
  creates, imports and appends.
- OAuth callbacks require a verified allowed Google email. Persisted tokens are
  rechecked against the allow-list; refreshes preserve resource binding and honor
  requested scopes. HTTP access requires the `appflowy` scope.
- OAuth persistence creates private temporary files before writing credentials,
  loads state atomically and omits credential-bearing exception details from logs.
- Doctor skips network checks for invalid local configuration and reports missing
  permitted workspaces. DateTime objects reject invalid timestamps/flags.
- Loopback HTTP defaults accept custom ports. The deployment helper refuses to
  overwrite an existing `.env` and no longer implies that it provisions routing.

### Maintenance

- Remove the discovery/comparison page, obsolete design/audit proposals, unused
  heading-edit code and duplicate async implementations.
- Keep tests under `tests/`, share deterministic test configuration and correct
  stale synchronous test stubs. Cancel superseded PR workflow runs.
- Align user/maintainer docs with current behavior; add architecture, durable agent
  context and a prioritized roadmap with completion criteria.

OAuth sessions without a stored subject, removed allow-list members and tokens
without the AppFlowy scope must sign in again after upgrading.

## 2.0.0 — 2026-11-09

- Require Python 3.11+ and the official MCP 2.3+ `MCPServer`; move AppFlowy network
  calls to native async I/O with modern and legacy protocol support.
- Expose 11 compact workflow tools, 12 with opt-in experimental AI, plus exclusive
  legacy 34-tool and compact five-tool read-only profiles.
- Add typed batches, paginated keyword search, guarded Markdown updates,
  import/export, small file payload uploads, doctor and access-token login.
- Add Formula/Timeline schema settings, structured space permissions and
  fail-closed decoding while retaining pycrdt 0.13.0.
- Package the CLI/wheel, publish public amd64/arm64 GHCR images and official MCP
  Registry metadata. PyPI remains disabled.
- Validate the commercial 0.20.5 disposable stack and visible Web document/Grid
  content. Add decoder candidates and protected opt-in SaaS checks.

See [MIGRATION.md](MIGRATION.md) for the v1-to-v2 interface mapping and
[COMPATIBILITY.md](COMPATIBILITY.md) for evidence and limits.

## 0.1.0

Initial workspace/folder/database reads and row create/upsert. Subsequent pre-2.0
work added Markdown, CRDT block/row/schema edits, OAuth, workspace restrictions and
HTTP transports. Detailed historical commits remain available in Git history.
