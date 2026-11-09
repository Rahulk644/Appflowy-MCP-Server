# Changelog

## Unreleased

- Upgrade workflow actions to verified release commits using Node 24, verify
  distribution upload/download on Linux and Windows, and enable weekly action updates.
- Wait through the disposable stack's explicit temporary search-unavailable state
  before asserting an indexed hit; keep unexpected errors and exhausted waits failing.
- Attach gated wheel/source artifacts to GitHub Releases, verify identical assets
  on retry and refuse replacements. Reuse matching versioned images and recover
  only the latest stable alias without rebuilding immutable tags.
- Use one declared package version for builds, CLI, doctor and MCP, and generate
  registry metadata from it. Keep dependencies in pyproject and validate release
  tags/image versions in CI, including older-tag registry recovery.
- Register legacy handlers through an explicit profile table and share behavior
  annotations with compact workflows; keep profile manifests unchanged.
- Give AppFlowy HTTP/session state a single owner in `api.py`; retain direct Python
  helper aliases and close the shared client on both transport shutdown paths.
- Isolate local Markdown/block conversion and collaboration decoding from the
  network backend; retain the existing tools, entry points and async behavior.
- Refuse field deletion while local filters, sorts, groups, formulas, calculations
  or view layouts reference it. Keep rejection read-only, clean direct form-field
  settings on successful deletion, and delegate Relation deletion to AppFlowy.
- Reject command-specific fields that would otherwise be ignored, including row
  document text on cell-only updates, Markdown on database creation, conflicting
  block representations and mismatched fetch IDs. Validate whole batches before writes.
- Fix DateTime cell writes to persist timestamp, range and time flags as separate
  collaboration attributes; preserve unrelated cell metadata and confirm all
  changed attributes on readback.
- Validate visible Number, DateTime/range, select and multi-select create/update,
  Board grouping, an evaluated Formula and a configured Timeline in disposable CI.
- Start search/worker services after Cloud migrations are ready; search checks use
  a unique document token and allow for asynchronous indexing.
- Expire abandoned OAuth state/codes; prune expired token records and bound public
  registration/transient caches.
- Rotate refresh tokens with fixed login deadlines, hashed replay records, and
  durable revocation of the affected login family. Other logins remain independent.
- Enable standards-compliant public/Basic/post-client token revocation and advertise
  supported client authentication methods.
- Refuse uncommitted token issuance/rotation when persistent storage fails; keep
  client registration and credential changes consistent on retry.
- Validate the official MCP SDK login, PKCE, refresh, replay, reauthentication and
  revocation flow over HTTP with a mocked Google identity exchange.
- Existing OAuth token stores require one new sign-in for the upgraded token format;
  client registrations are retained.

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
