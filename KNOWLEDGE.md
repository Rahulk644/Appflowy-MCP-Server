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
| Add / upsert a row (card) | `create_database_row`, `upsert_database_row` |
| Append to a doc (end only) | `append_blocks` |
| Reorganize | `create_space`, `move_page`, `duplicate_page`, `trash_page` |
| **Change a row's cells / move a card** | `update_row_cells` |
| **Delete a row** | `delete_row` |
| **Edit a card/doc body** | `add_block`, `edit_block_text`, `delete_block` |

## 4. Recipes
**Add a task card** — `create_database_row` (or `upsert_database_row`) with `cells`
(field id or name → value) and an optional `document` (Markdown body).

**Move a card / change its status** — `update_row_cells(row_id, {"<Status field id>":
"<option id>"})`. Field id and option ids come from `get_database_fields`. (Or
`upsert_database_row` with the card's `pre_hash` and the new Status.)

**Add a sub-task / checkbox to a card** *(the one people get wrong)* —
`add_block(page_id=<the card's ROW id>, block_type="todo_list", text="…",
data='{"checked":false}')`. `add_block` / `edit_block_text` / `delete_block` accept a
**row id** and auto-resolve it to the card's **body document**, so the checkbox lands
in the card body — never in a column. Mark it done by rewriting its `data` to
`{"checked":true}`.

**Give a card a rich body** — pass a Markdown `document` on create/upsert: `#`/`##`
headings, `-`/`1.` lists, `- [ ]` interactive checkboxes, `>` quote, ```lang fences,
GFM tables, `---`, links, `$math$`. It renders into real blocks.

**Log a meeting (full record)** — one row in a Meetings/Log database with cells (name,
date, attendees, link) plus a Markdown `document`: purpose · key takeaways · topics ·
next steps · action items · recording link.

**Fold a follow-up into an existing task** — if a new action item continues an
existing task, add it as a `todo_list` checkbox in that card's body (recipe above)
rather than creating a new card.

**See what exists / changed** — `get_database_row_ids` then `get_database_row_details`
(`with_doc=true` to read bodies), or `list_updated_rows` for a change feed.

## 5. Best practices (DO)
- **Own your cards.** Create/update via `upsert_database_row` with a deterministic
  `pre_hash` (e.g. `fathom-{recording_id}-{slug}`) so re-runs update in place and
  never duplicate.
- **Continuations fold in.** A meeting's follow-ups are usually the next step of an
  existing task — add a checkbox to that card's body; don't spawn a card. One card =
  one stream of work.
- **Right place for content.** Cells = title / status / metadata. Body document =
  context + checklist. Never put a per-card checklist in a shared column.
- **Full record vs personal board.** A meeting log holds the whole record for
  everyone; a personal "My Work" board should hold only that person's action items.
- **Read the org context first.** If a "Company Context" doc exists, read it before
  creating or triaging work.
- **Markdown for bodies.** Prefer a Markdown `document` over hand-building a block
  tree; it's simpler and renders to the same blocks.

## 6. Pitfalls — what to AVOID
- **Don't trust an immediate re-read.** `get_database_row_details` reads AppFlowy's
  `/row/detail`, a **materialized view that lags the collab by minutes**. A write can
  be perfectly correct while an immediate re-read still shows the old value. Verify via
  a collab-backed path (or wait) — never conclude "the write failed" from a fresh
  re-read alone. *(This one cost real debugging time.)*
- **Don't put sub-tasks in a property column.** A RichText column value shows on
  *every* card; per-card checklists belong in the card **body**.
- **Don't full-overwrite a live document.** Never `PUT` a whole collab; use the
  merging web-update path (the edit tools already do). A full overwrite clobbers
  concurrent edits.
- **Don't duplicate.** Don't create a new card for a follow-up that continues an
  existing task; fold it in.
- **Don't guess a `database_id`** from a folder `view_id` — call `list_databases`.
- **Deletes may need a human.** The host environment may require a person to approve
  deleting board rows. If a delete is refused, surface it — don't retry in a loop.

## 7. Data model (internals, for advanced work)
- **Collab types:** `0` Document, `1` Database, `5` DatabaseRow.
- **A row's body document is a separate collab** at `uuid5(row_id, "document_id")`
  (AppFlowy derives all row-scoped ids as `uuid5(row_uuid, name)`). The block tools
  resolve this for you when you pass a row id.
- **Row cell** = a map `{field_type, data, created_at, last_modified}`. `data` is a
  plain string for text/URL/number, an **option id** for SingleSelect, `"Yes"/"No"`
  for Checkbox.
- **Document block** = `{id, ty, parent, children, data (a JSON string), external_id
  (→ text), external_type:"text"}`; block text lives in the doc's `text_map`, child
  order in its `children_map`.

## 8. Reference
**Field types** (`add_database_field`): `0` RichText · `1` Number · `2` DateTime ·
`3` SingleSelect · `4` MultiSelect · `5` Checkbox · `6` URL · `7` Checklist ·
`8` LastEditedTime · `9` CreatedTime.

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

**Not in AppFlowy** (don't attempt): web-bookmark / link-preview card,
Google-Drive/iframe embed, a "Feed" view.

**Nuances:** collab-edited/added text is plain (inline bold/links not applied);
multi-column layout and @mentions need specific block/data shapes.
