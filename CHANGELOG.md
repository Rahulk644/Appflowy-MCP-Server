# Changelog

All notable changes are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/), and versions aim to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Collab/CRDT layer** (via `pycrdt`): `update_row_cells`, `delete_row`,
  `add_block`, `edit_block_text`, `delete_block` — edit, move, and delete *any*
  existing row or document block (including UI-created ones), and place advanced
  blocks (callout, toggle, quote, code, …) that the REST API alone can't create.
- `add_block` / `edit_block_text` / `delete_block` accept a **database row id** for
  `page_id`, auto-resolving to the row's body document (`uuid5(row_id, "document_id")`),
  so agents can add checklist sub-tasks to a Kanban card by its row id.
- **Field/schema editing** (collab/CRDT — AppFlowy exposes no REST for it):
  `update_database_field` renames a column (or writes its raw `type_option`), and
  `delete_database_field` removes a column from the schema and every view's column
  order. The primary/title field is guarded against deletion.
- **Select-option management** (collab/CRDT): `add_select_option` (returns the new
  option id to use as a cell value; idempotent by name; strict color validation so a
  bad color can't wipe the option set) and `delete_select_option` (by option id or
  label) for SingleSelect/MultiSelect columns.
- **Structure tools**: `create_page`, `create_database` (grid/board/calendar),
  `create_database_view`, `add_database_field`, `append_blocks`, `create_space`,
  `move_page`, `duplicate_page`, `trash_page`, `restore_page`, `rename_page`
  (page/database/space), `list_databases`, `get_page`.
- **Google-federated OAuth** sign-in with an email allow-list — MCP discovery,
  dynamic client registration, and PKCE (enabled via `GOOGLE_CLIENT_ID` /
  `OAUTH_ISSUER`). Clients can connect with just the server URL.
- Optional **persistent OAuth token store** (`OAUTH_STORE_PATH`): issued tokens +
  registered clients survive restarts, so a redeploy no longer forces re-sign-in.
  Atomic `0600` file on a mounted volume; `docker-compose` ships an `oauth-data` volume.
- **Streamable HTTP** transport (alongside stdio and legacy SSE), an agent
  **knowledge pack** (server instructions + `KNOWLEDGE.md`), and a server icon.

### Changed
- Endpoint auth now accepts a Bearer header, a `?token=` link, or OAuth.
- Agent knowledge pack (`KNOWLEDGE.md` + shipped `instructions`) rewritten as a full
  operator's guide: tool-by-task catalog, how-to recipes, best practices, a pitfalls /
  "what to avoid" section (read-after-write lag, sub-tasks-in-body, …), and a data-model
  reference.

### Security
- Workspace scoping (`ALLOWED_WORKSPACE_IDS`) enforced on every tool, plus
  DNS-rebinding protection for the HTTP transports.

### Fixed
- `create_page` / `create_database` returned a dict but were annotated `-> str`,
  raising an output-validation error *after* the page was created; they now return
  the `view_id` string.

## [0.1.0]

- Initial release: workspace/folder/database reads plus row create + upsert over
  the AppFlowy Cloud REST API.
