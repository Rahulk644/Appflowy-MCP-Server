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
- **Structure tools**: `create_page`, `create_database` (grid/board/calendar),
  `create_database_view`, `add_database_field`, `append_blocks`, `create_space`,
  `move_page`, `duplicate_page`, `trash_page`, `list_databases`, `get_page`.
- **Google-federated OAuth** sign-in with an email allow-list — MCP discovery,
  dynamic client registration, and PKCE (enabled via `GOOGLE_CLIENT_ID` /
  `OAUTH_ISSUER`). Clients can connect with just the server URL.
- **Streamable HTTP** transport (alongside stdio and legacy SSE), an agent
  **knowledge pack** (server instructions + `KNOWLEDGE.md`), and a server icon.

### Changed
- Endpoint auth now accepts a Bearer header, a `?token=` link, or OAuth.

### Security
- Workspace scoping (`ALLOWED_WORKSPACE_IDS`) enforced on every tool, plus
  DNS-rebinding protection for the HTTP transports.

## [0.1.0]

- Initial release: workspace/folder/database reads plus row create + upsert over
  the AppFlowy Cloud REST API.
