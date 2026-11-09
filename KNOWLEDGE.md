# AppFlowy Agent Guide

This is the reference for the **compact v2 profile**. All tool parameters go inside
`request`. The original 34 names require `APPFLOWY_TOOL_PROFILE=legacy`; see
MIGRATION.md. Read this resource on demand rather than repeating it in each prompt.

## 1. Identity and IDs

Call `appflowy_fetch` with `{"request":{"id":"self"}}` to see permitted workspaces.
Supply `workspace_id` unless exactly one workspace is allow-listed.
`workspace → spaces → pages`. A page can contain a document or a database view.
A **view_id is not a database_id**. Resolve IDs with
`appflowy_database(command=list)` before field/row operations. Database creation
returns both the container `view_id` and `database_id`; additional views may have
different IDs. A Board card is a **row**. Its cells and body document are separate.

## 2. Tool recipes

Examples below show the `request` object; wrap it as `{"request": ...}` when calling.

| Task | Tool | Request fields |
|---|---|---|
| Find pages | `appflowy_search` | `workspace_id, query, limit, offset` |
| Folder tree | `appflowy_fetch` | `workspace_id, kind:workspace_folder, depth, limit` |
| Read document/card body | `appflowy_fetch` | `workspace_id, id, response_format:markdown` |
| Structured page metadata | `appflowy_fetch` | `workspace_id, id, kind:page` |
| Create document | `appflowy_create_pages` | `workspace_id, pages:[{parent_view_id,name,markdown}]` |
| Create database | `appflowy_create_pages` | `workspace_id, pages:[{kind:database,parent_view_id,name,layout:grid}]` |
| Extra database view | `appflowy_create_pages` | `workspace_id, pages:[{kind:database_view,parent_view_id:EXISTING_DATABASE_VIEW,name,layout:board}]` |
| Rename / move / trash / restore | `appflowy_update` | `workspace_id, command, id`, plus `name` or `parent_view_id` |
| Duplicate page | `appflowy_update` | `command:duplicate, id, name:SUFFIX` |
| Append Markdown | `appflowy_update` | `workspace_id, command:append, id, markdown` |
| Prepend / replace Markdown | `appflowy_update` | `workspace_id, command, id, markdown, expected_markdown` |
| Schema / select options / grouping | `appflowy_database` | `workspace_id, command, database_id`, plus field/view IDs |
| Read rows | `appflowy_rows` | `workspace_id, database_id, command:list, limit, offset, with_doc` |
| Get specified rows | `appflowy_rows` | `command:get, database_id, row_ids:[...], with_doc` |
| Create/upsert rows | `appflowy_rows` | `command:create` or `upsert`, `database_id, rows:[{cells,document,pre_hash}]` |
| Update existing cells | `appflowy_rows` | `command:update_cells, database_id, rows:[{row_id,cells}]` |
| Delete rows | `appflowy_rows` | `command:delete, database_id, row_ids:[...]` |
| Changes | `appflowy_rows` | `command:changed_since, database_id, after, limit, offset` |
| Add body blocks | `appflowy_blocks` | `command:add, page_id, markdown`; optional `parent_id` |
| Advanced body block | `appflowy_blocks` | `command:add, page_id, block_type, text, data` |
| Edit/delete body block | `appflowy_blocks` | `command:edit` or `delete`, `page_id, block_id`, plus `text` |
| Find/replace | `appflowy_blocks` | `command:replace_text, page_id, find, replace, replace_all` |
| Import Markdown tree | `appflowy_import` | `parent_view_id, entries:[{path,markdown}]` |
| Small file upload | `appflowy_import` | `parent_view_id, files:[{name,content_type,content_base64}]` |
| Export page/tree | `appflowy_export` | `view_id, depth, limit` |
| Additional REST route | `appflowy_api` | `workspace_id, method, path, params, body` |

All workspace operations enforce `ALLOWED_WORKSPACE_IDS`. `appflowy_api.path` is a
plain relative route below `/api/workspace/{workspace_id}/`, without URLs,
escapes, traversal or query text. Put query arguments in `params`.

## 3. Typed cells and safe retries

`cells` is an object keyed by exact field ID or an unambiguous field name. Resolve
field types and select options using `appflowy_database(command=fields)`.
Text/URL require strings, Number accepts finite numeric values/strings, Checkbox
requires a JSON boolean, and select fields accept existing option names or IDs
(MultiSelect also accepts a list). DateTime accepts a Unix timestamp, a timestamp
object, or an ISO timestamp with a UTC offset. Unsupported and computed field
writes are rejected before row creation; unrelated existing cells are preserved.

```json
{"request":{"workspace_id":"WORKSPACE_ID","database_id":"DATABASE_ID","command":"update_cells","rows":[{"row_id":"ROW_ID","cells":{"Name":"Release","Done":true,"Status":"Complete"}}]}}
```

Use a stable `pre_hash` for repeatable upserts. Do not retry a partially completed
create as a new create. Batch results have per-item `ok`; if row creation succeeds
but cells fail, the result retains `row_id` and recommends `update_cells`.
Network timeouts can mean a write reached AppFlowy. Read first before retrying.

Cell writes confirm against the authoritative row collab. REST row details are a
materialized view and may lag. Do not repeatedly recreate a row because a REST
read is stale. Row body text/checklists belong in `document` or body blocks, not
in a shared database column. Pass the row ID as `page_id` to body block tools.

## 4. Document edits

Prefer Markdown: headings, paragraphs, nested lists, `- [ ]` checklists, quotes,
code fences, dividers, links, external images, bold/italic/strike/code, math and
`> [!NOTE]` callouts. `[](mention:VIEW_ID)` inserts a page mention.

`replace` and `prepend` require `expected_markdown` equal to a fresh read of the
page. A mismatch refuses the write. This checks the fetched snapshot; simultaneous
edits after that read can still merge through CRDT. Prefer small edits when
collaborators are actively editing. The server sends incremental collab updates,
not whole-document overwrites. Decoding failures stop before any write.

For advanced blocks use `block_type` and structured `data`, for example:

```json
{"request":{"workspace_id":"WORKSPACE_ID","page_id":"PAGE_OR_ROW_ID","command":"add","block_type":"callout","text":"**Release notes**","data":{"icon":"💡"}}}
```

Useful data: heading `{"level":2}`, code `{"language":"python"}`, todo_list
`{"checked":false}`, toggle_list `{"level":2}`. Code/math text stays literal;
other block text supports inline Markdown. Legacy raw block trees remain available
in the legacy profile. Simple tables/rich media are partial; columns, table of
contents, Mermaid rendering and reminders are not polished workflows here.

## 5. Modern database and space settings

`appflowy_database` supports `list`, `fields`, `add_field`, `update_field`,
`delete_field`, `add_option`, `delete_option`, `group_by`, `formula`, `timeline`,
`view_settings`, and `space_permissions`. Field/option IDs must exist; primary
fields are protected from deletion. `settings` supplies raw type options for
add/update_field, while add_option uses `name` and delete_option uses `option_id`.

Field IDs: 0 RichText, 1 Number, 2 DateTime, 3 SingleSelect, 4 MultiSelect,
5 Checkbox, 6 URL, 7 Checklist, 8 LastEditedTime, 9 CreatedTime, 10 Relation,
11 Summary, 12 Translate, 13 Time, 14 Media, 15 Person, 16 Rollup,
17 CreatedBy, 18 LastEditedBy, **19 Formula**. Schema support does not imply a typed
write encoder for every type.

For Formula create a field with `field_type:19`, then use `command:formula`,
`field_id`, `database_id`, `expression`. Expression is stored under type option
`19`; AppFlowy evaluates it. Evaluation is not performed by this server.

Timeline uses folder layout **10** but database-view layout **8**.
`command:timeline` accepts `database_id`, `view_id`, and `settings` with:
`field_id`, `end_field_id`, `progress_field_id`, `dependency_field_id`,
`layout_ty`, `show_table`, `first_day_of_week_v2`, `dependency_shift_ty`,
`dependency_direction`, `avoid_weekends`. Date fields must be DateTime fields.
Read current values using `view_settings` before editing; unrelated keys survive.
Formula evaluation and the full Timeline UI require deployment-specific validation.

Spaces default to **private**. Creation uses `kind:space` and a structured
`permission`; edits use `appflowy_update(command=space_permissions,id,permission)`.
Read via `appflowy_database(command=space_permissions,view_id)`.
Permissions include `visibility` (public/private/custom), owner level 50,
member/everyone-else levels (10/20/30/50 or null), invite/sidebar policies,
invite-link toggle and security flags. No-member-access and everyone-else grants
require custom visibility. Custom ACL failures never downgrade to public.
AppFlowy settings and the backend still decide effective access.

## 6. Bounds, import/export and partial outcomes

Read limits are 1–100; offsets are bounded. Search uses the server's cursor;
other listings may paginate client-side because AppFlowy lacks server paging.
`has_more` / `next_offset` report continuation. Response bodies are bounded to
50,000 characters with explicit truncation. Smaller pages preserve more structure.
Batch creation supports 20 pages or rows. Input Markdown is at most 100,000 chars
per entry. Inspect every per-item result, including on overall failure.

Import entries must have relative `.md` paths, without traversal or drive names.
Missing parent documents are created. Total Markdown per import is 200,000 chars,
50 entries. Files are base64 payloads: at most 1,000,000 decoded bytes each,
2,000,000 total, 10 files. File URLs require AppFlowy authorization; upload alone
does not insert a rich media block. No tool reads paths from the server filesystem.
Export traverses a bounded page subtree and reports skipped/unrenderable items.

## 7. Optional AI and profiles

`appflowy_ai` exists only with `APPFLOWY_ENABLE_AI=true` and a configured AppFlowy
AI deployment. It is experimental: answer generation has not been live-validated.
Commands: create_chat, ask, messages, delete_chat (trash), set_context. Supply
explicit `page_ids`; workspace-wide context requires `full_workspace:true`.
No selected pages defaults to no selected page sources. Ask submits a question
before streaming the answer; on failure inspect message history before resubmitting.

`APPFLOWY_READ_ONLY=true` exposes five tools in compact mode, with write commands
removed and an independent API mutation guard. Legacy mode exposes only its read
subset when that flag is set. OAuth/HTTP secrets and AppFlowy credentials are
separate; authenticate each layer as configured by the operator.

## 8. Coverage evidence

The release's compatibility report distinguishes live self-hosted/browser checks,
offline protocol tests and unvalidated Cloud/AI paths. Formula and Timeline support
covers schema persistence; it does not certify every calculated value or UI mode.
See COMPATIBILITY.md in the repository before assuming a backend version is tested.
