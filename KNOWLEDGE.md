# AppFlowy Agent Guide

A practical guide for AI agents (and humans) operating this MCP: what's available,
how to do the common things well, and the pitfalls that bite if you don't know them.
A condensed version ships as the MCP server `instructions` (delivered to every client
on connect); this file is the full reference.

## 1. Mental model
`workspace → Spaces → pages`. A **page** is either a **Document** or a **Database**
rendered as a Grid / Board / Calendar / List / Gallery view. On a **Board**, the
columns are a **SingleSelect** field and **each card is a row**.

A row holds content in two distinct places:
- **cells** — the database columns (title, Status, dates, …).
- a **body document** — the page that opens when you click the card (headings,
  paragraphs, interactive checklists, …). This is a *separate* collab object.

> **Gotcha #1 — `view_id` ≠ `database_id`.** The id from `get_workspace_folder` is a
> *view*. Call **`list_databases`** to map it to the `database_id` before any
> row/field tool.

## 2. The two layers
- **Tier 1 — REST, clean JSON (no user setup).** Create and structure things: pages,
  databases, fields, rows; append blocks; reorganize. The server builds the
  underlying collab for you.
- **Tier 2 — collab / CRDT.** Edit, move, or delete *any* existing row or document
  block (including ones made by hand in the UI), and place advanced blocks. This is
  how you change things after they exist. Writes go through a *merging* update, so
  they're safe alongside live editing.

## 3. Tools by task
| Task | Tool(s) |
|---|---|
| List workspaces / folder tree | `get_workspaces`, `get_workspace_folder` |
| Map a view → its database | `list_databases` |
| Read a database's columns | `get_database_fields` |
| Read rows | `get_database_row_ids`, `get_database_row_details` (`with_doc=true` for bodies) |
| See what changed | `list_updated_rows` |
| New doc / database / view / field | `create_page`, `create_database`, `create_database_view`, `add_database_field` |
| **Rename / delete a column** | `update_database_field`, `delete_database_field` |
| **Add / remove a select option** | `add_select_option`, `delete_select_option` |
| **Group a Board by a field** | `set_group_by` |
| Add / upsert a row (card) | `create_database_row`, `upsert_database_row` |
| Append to a doc (end only) | `append_blocks` |
| Reorganize | `create_space`, `move_page`, `duplicate_page`, `trash_page`, `restore_page` |
| **Rename a page / database / space** | `rename_page` |
| **Change a row's cells / move a card** | `update_row_cells` |
| **Delete a row** | `delete_row` |
| **Edit a card/doc body** | `add_block`, `edit_block_text`, `delete_block` |

## 4. Recipes
**Add a row** — `create_database_row` (or `upsert_database_row`) with `cells`
(field id or name → value) and an optional `document` (Markdown body).

**Move a Board card / change a select cell** — `update_row_cells(row_id, {"<Status field
id>": "<option id>"})`. Field id and option ids come from `get_database_fields`. (Or
`upsert_database_row` with the row's `pre_hash` and the new value.)

**Add a sub-task / checkbox to a card** *(the one people get wrong)* —
`add_block(page_id=<the card's ROW id>, block_type="todo_list", text="…",
data='{"checked":false}')`. `add_block` / `edit_block_text` / `delete_block` accept a
**row id** and auto-resolve it to the card's **body document**, so the checkbox lands
in the card body — never in a column. Mark it done by rewriting its `data` to
`{"checked":true}`.

**Give a card a rich body** — pass a Markdown `document` on create/upsert: `#`/`##`
headings, `-`/`1.` lists, `- [ ]` interactive checkboxes, `>` quote, ```lang fences,
GFM tables, `---`, links, `$math$`. It renders into real blocks.

**Build a board from scratch** — `create_database(layout="board")` → `add_database_field`
for a SingleSelect status column → `add_select_option` for each column (e.g. To Do /
Doing / Done) → `create_database_row` per card, setting the status cell to an option id.
Switch which field the columns represent with `set_group_by(view_id, field_id)` (the
`view_id` is the Board view from `list_databases`).

**Read a whole database** — `list_databases` (view → `database_id`) → `get_database_fields`
(field ids + select-option ids) → `get_database_row_ids` → `get_database_row_details`
(`with_doc=true` to include row bodies).

**Rename or delete a column** — `update_database_field(database_id, field_id, name="…")`
renames it; `delete_database_field(database_id, field_id)` removes it from the schema and
every view (the primary/title column is protected).

**Add or remove a select option** — `add_select_option(database_id, field_id, name,
color="Purple")` returns the new **option id**; pass that id (not the label) to
`update_row_cells` to tag a card. It's idempotent by name. `delete_select_option(
database_id, field_id, option)` removes an option by id or label. (Don't hand-edit select
options through `update_database_field`'s `type_option` — they live as a JSON string at
`type_option["<ty>"]["content"]` and a wrong shape wipes the option set.)

**Rename a page/board/space (not a card)** — `rename_page(view_id, name)` retitles a page,
database, or space. A **card is a row**, not a page — retitle it by setting its primary
cell with `update_row_cells`, not `rename_page`.

**See what exists / changed** — `get_database_row_ids` then `get_database_row_details`
(`with_doc=true` to read bodies), or `list_updated_rows` for a change feed.

## 5. Best practices (DO)
- **Update in place, don't duplicate.** For anything you might write more than once
  (imports, syncs, re-runs), `upsert_database_row` with a stable `pre_hash` — any
  deterministic string keyed off the source record — so the same row updates instead of
  cloning.
- **Right place for content.** Cells = title / status / metadata. A row's body document =
  long content + checklists. Never put a per-row checklist in a shared column (it shows on
  every row).
- **Resolve ids first.** `list_databases` to turn a folder view into a `database_id`, then
  `get_database_fields` for field ids and select-option ids before writing cells.
- **Markdown for bodies.** Prefer a Markdown `document` over hand-building a block tree;
  it's simpler and renders to the same blocks.

## 6. Pitfalls — what to AVOID
- **Don't trust an immediate re-read.** `get_database_row_details` reads AppFlowy's
  `/row/detail`, a **materialized view that lags the collab by minutes**. A write can
  be perfectly correct while an immediate re-read still shows the old value. Verify via
  a collab-backed path (or wait) — never conclude "the write failed" from a fresh
  re-read alone. (`update_row_cells` already confirms its own write against the collab
  before returning, so *its* success result is trustworthy.) *(This one cost real
  debugging time.)*
- **Don't put per-row content in a shared column.** A RichText column value shows on
  *every* row; per-row checklists and notes belong in the row **body** document.
- **Don't full-overwrite a live document.** Never `PUT` a whole collab; use the
  merging web-update path (the edit tools already do). A full overwrite clobbers
  concurrent edits.
- **Don't duplicate on re-runs.** Re-importing or re-syncing? `upsert_database_row` with
  a stable `pre_hash` instead of creating new rows each time.
- **Don't guess a `database_id`** from a folder `view_id` — call `list_databases`.

## 7. Data model (internals, for advanced work)
- **Collab types:** `0` Document, `1` Database, `5` DatabaseRow.
- **A row's body document is a separate collab** at `uuid5(row_id, "document_id")`
  (AppFlowy derives all row-scoped ids as `uuid5(row_uuid, name)`). The block tools
  resolve this for you when you pass a row id.
- **Row cell** = a map `{field_type, data, created_at, last_modified}`. `data` is a
  plain string for text/URL/number, an **option id** for SingleSelect, `"Yes"/"No"`
  for Checkbox.
- **Database collab** (`type 1`): `data.database.fields` maps field id → field
  `{id, name, ty, is_primary, type_option}`; `data.database.views` maps view id → view,
  whose `field_orders` is the column order (array of `{id}`). `delete_database_field`
  edits both. `type_option` is keyed by field-type string; for a select column
  `type_option["3"]["content"]` is a **JSON string** `{"options":[{id,name,color}],
  "disable_color"}` — option id is a `nanoid(4)`, color is a name (below).
- **Document block** = `{id, ty, parent, children, data (a JSON string), external_id
  (→ text), external_type:"text"}`; block text lives in the doc's `text_map`, child
  order in its `children_map`.

## 8. Reference
**Field types** (`add_database_field`): `0` RichText · `1` Number · `2` DateTime ·
`3` SingleSelect · `4` MultiSelect · `5` Checkbox · `6` URL · `7` Checklist ·
`8` LastEditedTime · `9` CreatedTime.

**Select-option colors** (`add_select_option`): Purple · Pink · LightPink · Orange ·
Yellow · Lime · Green · Aqua · Blue · Cream · Mint · Sky · Lilac · Pearl · Sunset ·
Coral · Sapphire · Moss · Sand · Charcoal. Any other value is rejected (a bad color
makes AppFlowy drop every option).

**Create a page from Markdown** — `create_page(ws, parent, name, markdown="# Title\n- item\n- [ ] task")` (and `append_blocks(ws, view_id, markdown=...)`) render standard Markdown into blocks — the same converter used for row bodies. For blocks Markdown can't express, pass a `page_data` block tree:

**Standalone page body** (`create_page` `page_data`) — a block tree:
```json
{"type":"page","children":[
  {"type":"heading","data":{"level":1,"delta":[{"insert":"Title"}]}},
  {"type":"paragraph","data":{"delta":[{"insert":"a "},{"insert":"word","attributes":{"bold":true}}]}},
  {"type":"todo_list","data":{"delta":[{"insert":"task"}],"checked":false}},
  {"type":"divider"}
]}
```
Block types: `paragraph, heading (data.level 1–6), bulleted_list, numbered_list,
todo_list (data.checked), quote, divider, image (data.url)`. Delta attributes:
`bold, italic, underline, strikethrough, code, color, href`. Advanced blocks
(callout, toggle_list, code) are placed via `add_block` with the matching `data`.

**Nuances:** collab-edited/added text is plain (inline bold / links / color not
applied yet). See **§9 Coverage** for the full AppFlowy-vs-MCP support matrix.

## 9. Coverage: AppFlowy vs. this MCP
What AppFlowy's editor/API can do, and what this MCP can create today. Reach for a
supported path first, and check the roadmap before assuming a gap is permanent.

**Legend:** ✅ full · 🟡 partial · 🗺️ roadmap · ⛔ not an MCP capability (runs AppFlowy AI).

**Basic blocks**
| AppFlowy option | MCP | How |
|---|---|---|
| Text / paragraph | ✅ | Markdown body, `page_data`, or `add_block` |
| Heading 1–3 | ✅ | `#`/`##`/`###`, or `add_block heading` (`data.level`) |
| Bulleted / Numbered / To-do list | ✅ | `- `/`1. `/`- [ ]`, or `add_block` |
| Quote | ✅ | `> `, or `add_block quote` |
| Code | ✅ | ` ```lang ` fence, or `add_block code` (`data.language`) |
| Callout | ✅ | `add_block callout` (`data.icon`) — not from Markdown |
| Toggle list | ✅ | `add_block toggle_list` — not from Markdown |
| Divider | ✅ | `---`, or `add_block divider` |
| Simple table | 🟡 | GFM table in a Markdown body; no table-edit tool |
| Link to page / Breadcrumb | 🗺️ | needs a `sub_page`/mention block |

**Media**
| AppFlowy option | MCP | How |
|---|---|---|
| Image (external URL) | ✅ | `![](url)` or `add_block image` (`data.url`) |
| File / PDF / Video / Audio / Photo gallery | 🗺️ | need file upload |
| Web bookmark / Google Drive embed | 🗺️ | `link_preview` / embed block |

**Database**
| AppFlowy option | MCP | How |
|---|---|---|
| Full-page Grid / Board / Calendar | ✅ | `create_database` |
| Extra Grid / Board / Calendar views | ✅ | `create_database_view` |
| Board grouping | ✅ | `set_group_by` |
| Select options (single / multi) | ✅ | `add_select_option` / `delete_select_option` |
| List / Gallery / Chart / Feed views | 🗺️ | layout map has grid/board/calendar only |
| Inline database (in a doc) / Linked view | 🗺️ | block referencing a data source |

**Advanced blocks**
| AppFlowy option | MCP | How |
|---|---|---|
| Inline equation `$…$` | ✅ | Markdown body |
| Block equation `$$` | 🟡 | `add_block math_equation` (`data.formula`) — verify before relying |
| Columns (2–5) | 🗺️ | needs nested `column` children |
| Toggle heading / Table of contents | 🗺️ | |
| Mermaid diagram | 🗺️ | renders as a code block, not a diagram |

**Inline formatting**
| AppFlowy option | MCP | How |
|---|---|---|
| Bold / italic / underline / strike / code / link | ✅ page bodies · 🟡 in-place edits | `page_data` delta or Markdown; `add_block`/`edit_block_text` write plain text |
| Text color | ✅ | `page_data` delta `color` attr |
| Background color | 🗺️ | |
| @mention a person / page | 🗺️ | inline mention delta — foundation for agents-as-members |
| Emoji | ✅ | Unicode |
| Date & reminder | 🗺️ | |

**AI blocks** — AI Meeting Note, Transcript, Summarize, Ask AI, Continue writing: ⛔
these trigger AppFlowy's own AI service; not content this (or any) MCP inserts.

**Advanced-block `data` shapes** for `add_block(page_id, block_type, text, data)` — it
accepts any block type; the useful non-basic ones (text is inserted PLAIN):
- **callout** — `data='{"icon":"💡"}'`
- **code** — `data='{"language":"python"}'`
- **heading** — `data='{"level":2}'`
- **toggle_list** — add children via `parent_block_id`
- **math_equation** — `data='{"formula":"E=mc^2"}'` (verify before relying on it)
