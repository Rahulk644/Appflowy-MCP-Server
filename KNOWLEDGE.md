# AppFlowy Agent Knowledge Pack

A reference for AI agents (and humans) using this MCP to build clean, well-organized
AppFlowy structures. A condensed version ships as the MCP server `instructions`.

## Workspace model
`workspace → Spaces → pages`. A **page** is either a **Document** or a **Database**
rendered as a Grid / Board / Calendar / List / Gallery view. A **Board**'s columns
are a **SingleSelect** field; each **card is a row**.

> **Gotcha:** a `view_id` from `get_workspace_folder` is **not** a `database_id`.
> Call **`list_databases`** to map a view to its `database_id` before using
> row/field tools.

## What you can do today (Tier 1 — clean JSON, no setup needed from the user)
| Need | Tool |
|------|------|
| Find databases / map view→db | `list_databases` |
| New document page | `create_page` (optional `page_data` block tree) |
| New database (grid/board/calendar) | `create_database` |
| Extra view over a database | `create_database_view` |
| Add a column | `add_database_field` |
| Add / update a card (row) | `create_database_row` / `upsert_database_row` |
| Append to a doc (end only) | `append_blocks` |
| New Space | `create_space` |
| Reorganize | `move_page`, `duplicate_page`, `trash_page` |
| Inspect | `get_workspaces`, `get_workspace_folder`, `get_page`, `get_database_fields`, `get_database_row_ids`, `get_database_row_details`, `list_updated_rows` |

## Rich content
**Card/row bodies → Markdown** (the `document` field converts server-side to real
blocks): headings `#/##/###`, `-`/`1.` lists, **`- [ ]` interactive checkboxes**,
`>` quote, ` ```lang ` code, GFM tables, `---` divider, links, images, `$math$`.

**Standalone page bodies → `page_data` JSON block tree:**
```json
{"type":"page","children":[
  {"type":"heading","data":{"level":1,"delta":[{"insert":"Title"}]}},
  {"type":"paragraph","data":{"delta":[{"insert":"a "},{"insert":"word","attributes":{"bold":true}}]}},
  {"type":"todo_list","data":{"delta":[{"insert":"task"}],"checked":false}},
  {"type":"divider"}
]}
```
Block types: `paragraph, heading (data.level 1–6), bulleted_list, numbered_list,
todo_list (data.checked), quote, divider, image (data.url)`.
Delta attributes: `bold, italic, underline, strikethrough, code, color, href`.

Field types (`add_database_field`): `0 RichText · 1 Number · 2 DateTime ·
3 SingleSelect · 4 MultiSelect · 5 Checkbox · 6 URL · 7 Checklist ·
8 LastEditedTime · 9 CreatedTime`.

## Tier 2 — collab layer (`pycrdt` + `web-update`)
Full edit/delete on **any** row or document block, including UI-created ones:
- **`update_row_cells`** — change cells on an existing row (e.g. move a Kanban card
  by setting its Status cell to the target option id).
- **`delete_row`** — hard-delete a row (removes it from every view's `row_orders`
  and deletes the row collab).
- **`add_block`** — add any block to a document, incl. **advanced** types the
  create/markdown paths can't make (callout, toggle_list, quote, code, heading);
  pass block-specific `data` (e.g. `{"icon":"💡"}`, `{"level":2}`, `{"language":"rust"}`).
- **`edit_block_text`** / **`delete_block`** — edit or remove a specific block.

Remaining nuances: edited/added block text is plain (inline bold/links not applied);
multi-column layout and @mentions need specific block/data shapes (attempt via
`add_block`). Genuinely not in AppFlowy: web-bookmark/link-preview card,
Google-Drive/iframe embed, "Feed" view.

## Task-card template (the "My Work" board)
- `Description` = concise title · `Status` = To Do / Doing / Done.
- Put context in the row's **Markdown document**:
  `## Source` (link) · `## Decisions` · `## Action items` (`- [ ]` …) · `## Open questions`.
- **Own your cards:** create/update via `upsert_database_row` with a deterministic
  `pre_hash` (e.g. `fathom-{recording_id}-{slug}`) so re-runs update in place and
  never duplicate.

## Organizing principle
One card = one work-item (action items live as a checklist inside its doc, not as
separate cards). Meeting context → a Meetings database row + linked from the card.
Keep the board to actionable tasks; archive Done regularly.
