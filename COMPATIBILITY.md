# Compatibility and validation

## Validated baseline

On 2026-11-10, the disposable integration suite ran against the official
[AppFlowy-SelfHost-Commercial](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/tree/0796497ebe36d569734fb8eb559f28264d86605c)
compose stack at commit `0796497ebe36d569734fb8eb559f28264d86605c`:
Cloud **0.20.5**, Web **0.20.11**, local GoTrue, Postgres, Redis, MinIO and keyword search.
Cloud image digest:
`sha256:4c45a647ae892783afdc8af175c9f2e75d54085a47e62aea1a347a562e0345f3`.
The source contracts were also checked against AppFlowy-Web commit
`d940e0e767b0bb8df594bb15a9390b958ff89ee4`.

| Area | Evidence | Limits |
|---|---|---|
| Password login, refresh, workspace/folder | Live disposable stack | External identity providers not exercised |
| Markdown document create/read/edit/replace | Live readback and visible browser content | Replacement precondition checks a fetched snapshot, not a server atomic compare-and-swap |
| Typed row create/update/delete and row body | Authoritative collab readback; visible Grid text, Number, DateTime/range, SingleSelect and MultiSelect labels after create/update; Board card in its selected group | Materialized REST row details can lag; not every field type has a typed encoder |
| Keyword search and bounded results | Live search hit | Requires deployed search service; semantic search not claimed |
| Markdown tree import/export | Live persistence; scoped subtree, tree continuation and large-document chunk reassembly checks | Complete text entries or explicit chunk-fetch warnings; no atomic archive or ZIP/Notion/PDF converter |
| File payload upload/download/delete | Live byte comparison and cleanup | Small files; no multipart or rich media orchestration |
| Formula expression and Timeline settings | Collab write/readback; Grid evaluates `1 + 2` to `3`; configured Timeline toolbar and row render | Complex formula references/functions, Timeline dragging and every layout setting are not covered |
| Structured private/custom space ACL | Live write/readback as owner | Separate member/guest checks blocked by the unlicensed commercial stack's one-seat limit (`LicenseLimitHit`, 1120) |
| MCP 2 server and input errors | Protocol contract tests plus clean-install stdio/HTTP | Desktop product UIs not individually certified |
| Google OAuth routing and persistence | Official MCP SDK HTTP login/PKCE/refresh/replay/revocation contract and provider tests | No real Google sign-in performed in CI |
| Comments | REST/CRDT contracts and disposable read/append/reply/pagination checks for documents, rows and published pages; row cells survive comment writes | Highlighted-text anchors, attachments, reactions and multi-user notifications are not live-validated; older document endpoints return no ID, so read back before retrying |
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

The compatibility workflow runs on PRs, weekly, and as a release gate. Its baseline
is pinned for reproducibility; update the commit and record new evidence when
AppFlowy releases change. A passing baseline does not prove every later release.

## Decoder policy

Production remains pinned to **pycrdt 0.13.0**. The captured disposable database
fixture passes decode and incremental structural-mutation convergence on both
0.13.0 and 0.14.1. It does **not** reproduce the historical 0.14.1 decoding failure.
CI tests 0.13.0 as required and 0.14.1/latest as non-blocking candidates.

Decode errors raise `CollabDecodeError` with the supported pin and stop before any
write. The server never substitutes an empty document or silently retries a
structural edit with guessed state. Obtain a sanitized representative failing
snapshot before loosening the pin or proposing an upstream binary-format patch.

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
