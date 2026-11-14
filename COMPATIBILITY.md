# Compatibility and validation

## Validated baseline

On 2026-11-14, the disposable integration suite ran against the official
[AppFlowy-SelfHost-Commercial](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/tree/e39869a2bae964e951832e577407e35a548b48c8)
compose stack at commit `e39869a2bae964e951832e577407e35a548b48c8`:
Cloud **0.21.4**, Web **0.20.12**, local GoTrue, Postgres, Redis, MinIO and keyword search.
Cloud image digest:
`sha256:ad9fc55d4595221d8251f69e441232556192d5d298b62ed3a644f98a455ed927`.
Web image digest:
`sha256:f439f4495b7ce8cf5e3f1157bb88ef312c3b09c3ce37d2bdb91bfbd64958d841`.
The source contracts were also checked against AppFlowy-Web commit
`c88afa5e17c862f2fc60d968dd675afab57e5f75` (Web 0.20.12).
The v2.2.0 runtime passed all 31 live checks and ten browser categories without
runtime changes. Previous 0.20.5 / 0.20.11 reports remain in
[compatibility-reports](compatibility-reports/); success on either baseline is
specific to those versions.

| Area | Evidence | Limits |
|---|---|---|
| Password login, refresh, workspace/folder | Live disposable stack | External identity providers not exercised |
| Markdown document create/read/edit/replace | Live readback and visible browser content | Replacement precondition checks a fetched snapshot, not a server atomic compare-and-swap |
| Native simple tables | Markdown/collab round trips and visible Web table cells | Export normalizes a header row; widths, colors, alignment, merged cells and arbitrary nested layouts are not preserved |
| Typed row create/update/delete and row body | Authoritative collab readback; visible Grid text, Number, DateTime/range, SingleSelect and MultiSelect labels after create/update; Board card in its selected group | Materialized REST row details can lag; not every field type has a typed encoder |
| Keyword search and bounded results | Live search hit | Requires deployed search service; semantic search not claimed |
| Markdown tree import/export | Live persistence; scoped subtree, tree continuation and large-document chunk reassembly checks | Complete text entries or explicit chunk-fetch warnings; no atomic archive or ZIP/Notion/PDF converter |
| File payload upload/download/delete and optional image insertion | Live byte comparison, image-block readback, browser image loading and cleanup | Small files; no multipart/20 MB payloads or arbitrary media orchestration. A separate public origin is covered by offline request-routing tests |
| Formula expression and Timeline settings | Collab write/readback; Grid evaluates `1 + 2` to `3`; configured Timeline toolbar and row render | Complex formula references/functions, date-only equality, Timeline dragging and every layout setting are not covered |
| Structured private/custom space ACL | Live write/readback as owner | Separate member/guest checks blocked by the unlicensed commercial stack's one-seat limit (`LicenseLimitHit`, 1120) |
| MCP 2 server and input errors | Protocol contract tests plus clean-install stdio/HTTP | Desktop product UIs not individually certified |
| Google OAuth routing and persistence | Official MCP SDK HTTP login/PKCE/refresh/replay/revocation contract and provider tests | No real Google sign-in performed in CI |
| Comments | REST/CRDT contracts and disposable read/append/reply/pagination checks for documents, rows and published pages; row cells survive comment writes | Highlighted-text anchors, attachments, reactions and person-mention notifications are not live-validated; older document endpoints return no ID, so read back before retrying |
| AI chat | Current Web contract and decoder tests | Answer generation needs an AI-enabled deployment; opt-in and experimental |
| AppFlowy SaaS | Protected opt-in harness | No current Cloud account/workspace configured for this release |

The committed JSON report in [compatibility-reports](compatibility-reports/) records
individual live and browser checks. Browser assertions target the specific row and
field, verify typed updates and date ranges, and distinguish Grid, Board and Timeline.
CI artifacts carry each run's live/browser reports and browser failure diagnostics;
failures are not labeled validated.
The search probe waits within a fixed retry budget for indexing and the baseline's
explicit temporary-unavailable code (1054). Other API errors fail immediately; an
eventual matching document hit is still required. Reports include startup retries.

The Web Formula fix for date-only calendar-day comparisons
([AppFlowy-Web #720](https://github.com/AppFlowy-IO/AppFlowy-Web/pull/720)) merged
after 0.20.12. It is not part of this tested image. Do not treat a server write
succeeding as proof that every client Formula comparison evaluates correctly.

## Reproduce disposable checks

Requires Docker Compose and enough memory for the first-party stack (a fresh pull
is substantial). Ports are bound to loopback and tests use a dummy account.

```bash
pip install -e '.[dev,browser]'
python -m playwright install --with-deps chromium
python scripts/selfhost.py up
APPFLOWY_BROWSER_TEST=true python scripts/selfhost.py test
python scripts/selfhost.py down
```

`down` removes only the `appflowy-mcp-compat` project's containers and volumes.
Do not point these tests at an existing production stack using that project name.
Use `APPFLOWY_TEST_CHROMIUM=/path/to/chromium` for an existing browser binary.
The WebSocket base ends in `/ws/v2`; `/ws` prevents live row rendering.

After changing the pinned deployment, remove the earlier disposable project with
its `down` command and use a fresh `--directory` for `up`, `test` and `down`.
The runner refuses to reuse a checkout from a different pin. These directories
are test state, not production upgrade or migration instructions.

The compatibility workflow runs on PRs, weekly, and as a release gate. Its baseline
is pinned for reproducibility; update the commit and record new evidence when
AppFlowy releases change. A passing baseline does not prove every later release.

## Decoder policy

Production remains pinned to **pycrdt 0.13.0**. The committed 0.20.5 fixture and a
job-local 0.21.4 snapshot pass decode and incremental structural-mutation
convergence on both 0.13.0 and 0.14.1. Neither reproduces the historical 0.14.1
decoding failure. CI captures its current snapshot in the runner's temporary
directory, checks the supported pin and isolated candidates, and uploads only
sanitized outcomes. No current raw snapshot is committed or uploaded.
CI tests 0.13.0 as required and 0.14.1/latest as non-blocking candidates.

Decode errors raise `CollabDecodeError` with the supported pin and stop before any
write. The server never substitutes an empty document or silently retries a
structural edit with guessed state. Obtain a sanitized representative failing
snapshot before loosening the pin or proposing an upstream binary-format patch.

## AppFlowy's official MCP

The [README comparison](README.md#this-server-or-appflowys-official-mcp) uses these
first-party sources, checked on 2026-11-14:

- [AI app plugins and setup](https://github.com/AppFlowy-IO/appflowy-ai-plugins/blob/318a8c81cab86418fa3e71cc8e03b7cb874378a6/README.md): AppFlowy sign-in, workspace-scoped connections, permission scopes, approvals and self-hosted license requirements.
- [Published tool catalog](https://github.com/AppFlowy-IO/appflowy-ai-plugins/blob/318a8c81cab86418fa3e71cc8e03b7cb874378a6/catalog/tools.json): 45 tool definitions in catalog version 25, including forms/sharing, reminders, saved filters, Chart/Dashboard controls and comment resolution/deletion. A catalog snapshot does not establish which tools a live connection receives.
- [Web MCP guide](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/c88afa5e17c862f2fc60d968dd675afab57e5f75/doc/MCP.md): separate MCP service, OAuth setup and the Settings connection-management flow.
- [Commercial deployment release notes](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/blob/e39869a2bae964e951832e577407e35a548b48c8/README.md#release-notes): managed AI app policies, workspace authoring and service rollout requirements.

The cited plugin README marks its AppFlowy Cloud MCP endpoint as not live yet.
Check the current official rollout status before using those Cloud setup commands.
This is a source/catalog comparison; the official MCP service has not been
authenticated or benchmarked here. This community server's current SaaS workspace
paths also remain unvalidated. Neither source review nor self-hosted CI certifies
current SaaS behavior or relative model accuracy, latency or cost.

## Operator token-refresh check

With a dedicated account configured through `APPFLOWY_EMAIL` / `APPFLOWY_PASSWORD`,
run:

```bash
python live_compatibility.py --validate-token-refresh --output refresh-report.json
```

This separate mode makes an initial workspace request, explicitly refreshes the
GoTrue grant, then reads with that exact returned access token. It does not call
the normal authentication fallback for readback, even if the expiry buffer makes
a short-lived token stale locally. Password fallback is a failed refresh check.
The report contains response shapes and safe boolean diagnostics, never tokens.
Unset `APPFLOWY_ACCESS_TOKEN`; a static token cannot exercise the refresh grant.
The refresh and reversible modes are mutually exclusive. Existing CI opt-in and
disposable-workspace guards still apply.

## Opt-in Cloud job

Configure the `appflowy-cloud-test` GitHub Actions environment with a dedicated,
disposable workspace. Set repository variable `ENABLE_CLOUD_COMPATIBILITY=true`;
set `APPFLOWY_TEST_BASE_URL`, `APPFLOWY_TEST_WORKSPACE_ID`, and optional
`APPFLOWY_TEST_PARENT_VIEW_ID` / `APPFLOWY_TEST_DATABASE_ID` variables. Put
`APPFLOWY_TEST_EMAIL` / `APPFLOWY_TEST_PASSWORD` or `APPFLOWY_TEST_ACCESS_TOKEN` in
environment secrets. Run **AppFlowy compatibility** manually; mutations require
the separate workflow input. No PR job receives these credentials.

The standalone harness refuses ordinary CI. This protected job explicitly sets
both `APPFLOWY_COMPAT_ALLOW_CI=true` and
`APPFLOWY_COMPAT_DISPOSABLE_WORKSPACE=true`. Credentials and raw bodies are omitted
from its report. Cloud checks remain unvalidated until that job actually succeeds.
