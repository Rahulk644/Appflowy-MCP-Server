# Migration guide

Python **3.11+** and the official **MCP 2.3+** SDK are required. The server uses
`mcp.server.mcpserver.MCPServer`; it supports legacy and 2026-07-28 protocol
connections. The SDK version and negotiated MCP protocol version are separate.

The default profile changes to 11 prefixed async tools. Enable experimental AI
with `APPFLOWY_ENABLE_AI=true` for the twelfth. Every compact call uses a typed
`request` object. Unknown arguments are rejected. Cell values and settings are
JSON objects, rather than JSON encoded inside strings.
Compact commands reject non-default fields that do not apply to the selected
operation. Remove fields named in the validation error or use the relevant command.
For example, edit a row body with document/block commands rather than `update_cells`.
Field deletion now names local schema/view dependencies that must be reconfigured
first. Relation fields must be deleted in AppFlowy to update reciprocal links.

For existing MCP clients, set `APPFLOWY_TOOL_PROFILE=legacy` to retain the original
34 tool names and schemas, plus `list_comments` and `append_comment`.
All implementations use async network I/O.
Direct Python callers must `await` functions that previously returned synchronously.
Root `server.py` and `google_oauth.py` remain compatibility imports. Profiles are
exclusive. Restart the server and reconnect the client after changing profiles.

## Original tool mapping

| Original tool | Compact equivalent inside `request` |
|---|---|
| `get_workspaces` | `appflowy_fetch`, `kind=workspaces` |
| `get_workspace_folder` | `appflowy_fetch`, `kind=workspace_folder` |
| `get_page` | `appflowy_fetch`, `kind=page`, `id=view_id` |
| `get_page_markdown` | `appflowy_fetch`, `id=page_id`, `response_format=markdown` |
| `get_database_fields` | `appflowy_database`, `command=fields` |
| `list_databases` | `appflowy_database`, `command=list` |
| `get_database_row_ids` | `appflowy_rows`, `command=list` (bounded details) |
| `get_database_row_details` | `appflowy_rows`, `command=get`, `row_ids=[...]` |
| `list_updated_rows` | `appflowy_rows`, `command=changed_since`, `after=...` |
| `create_database_row` | `appflowy_rows`, `command=create`, `rows=[...]` |
| `upsert_database_row` | `appflowy_rows`, `command=upsert`, stable `pre_hash` per row |
| `update_row_cells` | `appflowy_rows`, `command=update_cells`, `rows=[{row_id,cells}]` |
| `delete_row` | `appflowy_rows`, `command=delete`, `row_ids=[...]` |
| `create_page` | `appflowy_create_pages`, `pages=[{kind:document,...}]` |
| `create_space` | `appflowy_create_pages`, `pages=[{kind:space,permission,...}]` |
| `create_database` | `appflowy_create_pages`, `pages=[{kind:database,...}]` |
| `create_database_view` | `appflowy_create_pages`, `kind=database_view`; `parent_view_id` is an existing view of the database |
| `add_database_field` | `appflowy_database`, `command=add_field` |
| `update_database_field` | `appflowy_database`, `command=update_field` |
| `delete_database_field` | `appflowy_database`, `command=delete_field` |
| `add_select_option` | `appflowy_database`, `command=add_option` |
| `delete_select_option` | `appflowy_database`, `command=delete_option` |
| `set_group_by` | `appflowy_database`, `command=group_by` |
| `append_blocks` | `appflowy_update`, `command=append`, `markdown=...` |
| `move_page` | `appflowy_update`, `command=move` |
| `duplicate_page` | `appflowy_update`, `command=duplicate`; `name` supplies the legacy suffix |
| `trash_page` | `appflowy_update`, `command=trash`, or `appflowy_delete`, `kind=page` |
| `restore_page` | `appflowy_update`, `command=restore` |
| `rename_page` | `appflowy_update`, `command=rename` |
| `add_block` | `appflowy_blocks`, `command=add`, `block_type`, `text`, structured `data` |
| `add_blocks` | `appflowy_blocks`, `command=add`, `markdown=...` |
| `edit_block_text` | `appflowy_blocks`, `command=edit` |
| `replace_text` | `appflowy_blocks`, `command=replace_text` |
| `delete_block` | `appflowy_blocks`, `command=delete` |

Legacy raw block-tree strings and custom select-option colors remain available
through the legacy profile. The compact profile favors Markdown and typed values.
`appflowy_delete(kind=page)` moves a page to trash; it does not permanently purge it.
New spaces default to private. Explicit structured permissions replace the legacy
public/private boolean. Custom permissions never fall back to broader visibility.

## Example

```json
{"request":{"workspace_id":"WORKSPACE_ID","database_id":"DATABASE_ID","command":"update_cells","rows":[{"row_id":"ROW_ID","cells":{"Name":"Finished","Done":true}}]}}
```

Use `APPFLOWY_READ_ONLY=true` with the compact profile for five read-only tools;
mutation commands are absent from their schemas, and the underlying API also
rejects writes. A configured `APPFLOWY_ACCESS_TOKEN` takes precedence over
email/password and must be replaced by the operator when it expires.

See [COMPATIBILITY.md](COMPATIBILITY.md) for validated versions and limits.

## Upgrading from 2.0.0 to 2.0.1

OAuth sessions whose email has been removed from `ALLOWED_EMAILS` are rejected.
Tokens without a stored subject or the `appflowy` scope require a new sign-in.
Google sign-in requires a verified email. Refreshes preserve the resource binding
and honor requested scope narrowing. Shared-secret and stdio users keep their
existing connection configuration.

Mutation tool hints no longer promise safe automatic retries. Retain batch result
IDs and inspect partial failures before repeating a create/import/append.
Loopback HTTP defaults support custom ports. The deployment helper refuses to
overwrite `.env`; edit an existing configuration directly when redeploying.

## Upgrading from 2.0.1 to 2.0.2

### Rotating OAuth sessions

The OAuth token store gains a versioned format for login-family relationships and
hashed refresh replay records. Existing registrations survive; existing sessions
must sign in once again. Clients must save each newly returned refresh token.
Do not share a refresh token across independent processes: reuse of a rotated
credential revokes every access/refresh token from that login, including after a
server restart. Other logins are unaffected. Explicit revocation ends the whole
login family.

Sign-in state and codes expire after five minutes. Access tokens last at most one
hour; a login has a fixed 30-day deadline and a maximum of 1,024 rotations. State,
code and dynamic-registration caches have capacity limits. Storage failures return
HTTP 503 rather than handing out credentials that were not committed. Keep one
server worker when using the JSON store.

### Bounded continuations

Client-paged lists may return fewer items than requested. Use `next_offset`, rather
than adding `limit`. Oversized records carry `content_omitted` with a stable identity;
missing materialized row details carry `unavailable`. Neither marker is full content.

Markdown fetches accept a character `offset` and return `content_hash`, `has_more`
and `next_offset`. Concatenate chunks only when hashes agree. Folder fetches accept
an optional subtree `id`. Export adds a breadth-first attempt `offset`, returns
complete files, and supplies a separate Markdown-fetch request for oversized files.
Tree and document continuations operate on live reads; restart if content changes.

## Upgrading from 2.0.2 to 2.1.0

Compact mode keeps the same 11 tool names. Fetch gains `kind=comments` and update
gains `command=append_comment`; both use `target_type=document|row|published`.
Use a card's row ID for row comments. Bodies are bounded to 100,000 characters,
and non-default inputs unrelated to the operation remain rejected.

Legacy mode has 36 tools: the original 34 plus `list_comments` and
`append_comment`. Restart/reconnect clients to refresh their tool schemas.
Comments act through the configured bot account. Appends are non-idempotent;
if a result is uncertain or an older document endpoint returns no ID, read the
conversation before retrying. Published-page targets must already be published.

## Tables and uploaded images

GFM pipe tables now create native simple tables. Existing Markdown and file-import
calls remain valid. Add `append_image:true` to an `appflowy_import` file entry to
insert the uploaded image into the target document. The 1 MB per-file, 2 MB batch
and ten-file limits still apply. This extends the existing compact import tool.
See [the import contract](KNOWLEDGE.md#6-bounds-importexport-and-partial-outcomes)
for public origins and recovery after partial success.
