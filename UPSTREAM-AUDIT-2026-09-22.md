# AppFlowy upstream audit — 2026-09-22

This audit compares the current local MCP server with AppFlowy's public client code,
release notes, and a resolved upstream issue. It does **not** certify compatibility
with a deployed Cloud instance: no AppFlowy credentials are available locally, and
the production backend source is private.

## Source of truth changed

- [AppFlowy-Cloud](https://github.com/AppFlowy-IO/AppFlowy-Cloud/blob/main/README.md)
  is archived. Its README says it is no longer used for current SaaS or self-hosted
  deployments. Endpoints found in its Rust source are historical evidence only.
- [AppFlowy-SelfHost-Commercial](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/blob/main/README.md)
  publishes the deployment files and release notes for the production backend.
  The backend itself is closed source.
- [AppFlowy-Web](https://github.com/AppFlowy-IO/AppFlowy-Web/tree/main/src/application/services/js-services/http)
  is actively maintained and shows which API calls the current first-party Web
  client makes. It is useful contract evidence, but does not prove an endpoint
  works on every SaaS or self-hosted version.
- The [desktop 0.14.5 release](https://github.com/AppFlowy-IO/AppFlowy/releases/tag/0.14.5)
  was published on 2026-09-22 and requires Cloud **0.18.10 or later** for
  self-hosted workspaces. The commercial self-host README still calls **0.18.9**
  latest. Check the actual deployed server version before any compatibility claim.
- AppFlowy's own [MCP server feature request](https://github.com/AppFlowy-IO/AppFlowy/issues/8043)
  is still open. In a separate [API-access issue](https://github.com/AppFlowy-IO/AppFlowy/issues/8776),
  an AppFlowy maintainer said in June 2026 that MCP was not yet supported.
  AppFlowy's marketing mentions MCP, but these sources do not establish an
  official replacement for this server.

## Impact on this server and v2 design

| Area | Current evidence | Local implication |
|---|---|---|
| Core pages and collaboration | Current Web still calls `/api/workspace/{id}/page-view`, `/api/workspace/v1/{id}/collab/{object}`, and `/web-update`; updates include `client-version` and `device-id` headers. [Page API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/page-api.ts), [collab API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/collab-api.ts) | Paths and JSON update body remain plausible. Header requirements and CRDT compatibility need a live probe. |
| Row documents | Current Web can pass `database_id`, `row_id`, and `row_document_id` when fetching a row document. Self-host notes mention row-document permission and initialization fixes in 0.18.8–0.18.9. [Collab API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/collab-api.ts), [release notes](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/blob/main/README.md#release-notes) | Local row-body reads derive the document ID and omit source parameters. This may fail on some versions or permission models; test read/edit on a row created in the current Web client. |
| Database IDs and errors | A [resolved upstream issue](https://github.com/AppFlowy-IO/AppFlowy/issues/9024) showed that passing a `view_id` as a `database_id` produces HTTP 200 with application `code: 1012`. The reporter confirmed it was ID confusion, not a server persistence bug. Current Web explicitly distinguishes view and database IDs. | Local guide already distinguishes the IDs. The local HTTP layer ignored nonzero application codes, so a failed write could look successful. This audit includes a fix and regression tests. |
| Database features | 0.18.9 adds Formula fields and history preview/recovery; earlier 0.18.x releases add forms, Timeline settings, row repair, and structured space permissions. [Release notes](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/blob/main/README.md#release-notes) | Local field-type descriptions cover only older types, and the `grid/board/calendar` creation choice does not express newer views. These are coverage gaps, not evidence that old fields or views broke. |
| Spaces | Current Web uses structured `/spaces` permissions and falls back to legacy `/space` only when representable. [Page API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/page-api.ts) | Local `create_space` exposes only public/private via legacy `/space`. It cannot create Custom permission spaces. Legacy route still appears supported by the first-party client. |
| Search | Current Web uses `GET /api/search/{workspace_id}/page` with `query`, `limit`, `offset`, `mode=keyword`, `preview_size`, and `score`; response has `items`, `next_offset`, and `has_more`. [Search API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/misc-api.ts) | v2 `appflowy_search` should use this paginated contract, with response-size bounds. |
| AI chat | Current Web uses question POST, answer SSE stream, and chat settings with `rag_ids`. Empty `rag_ids` can mean workspace-wide search, so Web substitutes the chat ID when the user intentionally selects no sources. [Chat client](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/components/chat/request/chat-request.ts) | v2 must define empty-source and full-workspace behavior explicitly. The old non-streaming answer route is known from archived backend source but unverified on current Cloud. |
| Markdown import | Current Web says there is no single-file Markdown endpoint and parses Markdown client-side before sending a collab update. Its server import API now supports Notion, Confluence, workspace ZIP, and database CSV. [Import service](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/components/app/import/import-service.ts), [import API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/import-api.ts) | Client-side Markdown import remains a sound design. The v2 claim that server import accepts Notion only is stale. |
| Export | Current Web calls server endpoints for workspace ZIP backup and view PDF export. [Export API](https://github.com/AppFlowy-IO/AppFlowy-Web/blob/main/src/application/services/js-services/http/export-api.ts) | The v2 claim that no REST export endpoint exists is false. Markdown tree export can still be composed locally; distinguish it from the existing ZIP/PDF exports. |

## Immediate order of work

1. Validate the target deployment: server version, auth method, and a read-only
   workspace/page/database fetch. The default `https://beta.appflowy.cloud` is
   inherited from the old setup; confirm it is the intended account endpoint.
2. On a disposable workspace, probe page creation, a row write with a confirmed
   `database_id`, document and row-document reads, and one collab update. Check
   both HTTP status and application `code`, then re-read to confirm persistence.
3. Revise v2 around the current search, permissions, import/export, and AI contracts.
   Keep historical endpoints marked unverified until a live test confirms them.
4. Only then split implementation work. The current server still exposes 34
   synchronous tools; the 12-verb async redesign is not implemented.

Local checks: 34 registered MCP tools; unit tests use mocked HTTP, so they cannot
prove live Cloud compatibility. No AppFlowy credentials were present for this audit.
