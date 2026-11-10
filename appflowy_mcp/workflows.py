"""Async workspace workflows. Routes follow pinned first-party Web contracts."""

import asyncio
import base64
import json
import math
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx
from pycrdt import Map

from . import api as a
from . import documents as d
from . import models as m
from .profiles import DESTRUCTIVE, READ

MAX_RESULT_CHARS = 50_000


def backend():
    from . import server

    return server


def identifier(value: str, name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError(f"{name} must be a resource ID, without path separators")
    return value


def workspace(request: m.Input) -> str:
    return identifier(a._default_workspace_id(request.workspace_id), "workspace_id")


def required(request, name: str) -> str:
    return identifier(getattr(request, name), name)


def bounded(value: Any) -> dict:
    result = value if isinstance(value, dict) else {"data": value}
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) <= MAX_RESULT_CHARS:
        return result
    preview = {
        "truncated": True,
        "preview": "",
        "hint": "Reduce limit or fetch one resource",
    }
    low, high = 0, min(len(encoded), MAX_RESULT_CHARS)
    while low < high:
        middle = (low + high + 1) // 2
        preview["preview"] = encoded[:middle]
        if len(json.dumps(preview, ensure_ascii=False)) <= MAX_RESULT_CHARS:
            low = middle
        else:
            high = middle - 1
    preview["preview"] = encoded[:low]
    return preview


def page(items: list, request: m.ReadInput) -> dict:
    data = items[request.offset : request.offset + request.limit]
    return _fit_page(data, request, len(items))


def _fit_page(data: list, request: m.ReadInput, total_count: int) -> dict:
    """Keep complete items and a usable cursor when a client page hits its budget."""

    def candidate(count):
        end = request.offset + count
        return _format_result(
            {
                "items": data[:count],
                "offset": request.offset,
                "next_offset": end if end < total_count else None,
                "has_more": end < total_count,
                "total_count": total_count,
            },
            request.response_format,
        )

    result = candidate(len(data))
    if len(json.dumps(result, ensure_ascii=False, default=str)) <= MAX_RESULT_CHARS:
        return result
    low, high = 0, len(data) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if (
            len(json.dumps(candidate(middle), ensure_ascii=False, default=str))
            <= MAX_RESULT_CHARS
        ):
            low = middle
        else:
            high = middle - 1
    if low:
        return candidate(low)
    item = data[0]
    identity = {
        key: str(item[key])[:256]
        for key in ("id", "row_id", "object_id", "name", "title")
        if isinstance(item, dict) and key in item
    }
    data = [
        {
            **identity,
            "content_omitted": True,
            "message": "Item exceeds the response budget; use a narrower fetch or AppFlowy for full content",
        }
    ]
    return candidate(1)


def _format_result(value: dict, response_format: str) -> dict:
    if response_format == "markdown":
        items = value.get("items", value.get("comments"))
        if isinstance(items, list):
            lines = []
            for item in items:
                if isinstance(item, dict):
                    label = item.get(
                        "name",
                        item.get(
                            "title",
                            item.get(
                                "id",
                                item.get("object_id", item.get("comment_id", "Item")),
                            ),
                        ),
                    )
                    details = {
                        key: entry
                        for key, entry in item.items()
                        if key not in {"name", "title"}
                    }
                    lines.append(
                        f"- **{label}**: {json.dumps(details, ensure_ascii=False, default=str)}"
                    )
                else:
                    lines.append(f"- {item}")
            markdown = "\n".join(lines) if lines else "No results."
        else:
            markdown = "\n".join(
                f"- **{key}**: {entry}" for key, entry in value.items()
            )
        return {
            "markdown": markdown,
            "has_more": value.get("has_more", False),
            "next_offset": value.get("next_offset"),
        }
    return value


def render(value: dict, response_format: str) -> dict:
    return bounded(_format_result(value, response_format))


async def api(method: str, path: str, **kwargs):
    response = await a._api_call_async(method, path, **kwargs)
    if not response.content:
        return None
    value = response.json()
    return value.get("data", value) if isinstance(value, dict) else value


async def batch(items, operation) -> dict:
    results = []
    for index, item in enumerate(items):
        try:
            value = await operation(item)
            complete = not (isinstance(value, dict) and value.get("partial"))
            results.append({"index": index, "ok": complete, "result": value})
        except (ValueError, RuntimeError) as exc:
            results.append({"index": index, "ok": False, "error": str(exc)[:500]})
    return bounded(
        {
            "ok": all(item["ok"] for item in results),
            "items": results,
            "completed": sum(item["ok"] for item in results),
        }
    )


async def appflowy_search(request: m.SearchInput) -> dict:
    """Find pages by keyword, with server pagination and bounded previews."""
    ws = workspace(request)
    data = await api(
        "GET",
        f"/api/search/{ws}/page",
        params={
            "query": request.query,
            "limit": request.limit,
            "offset": request.offset,
            "mode": "keyword",
            "preview_size": 160,
        },
    )
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise TypeError(
            "Search response contract changed: expected items/has_more/next_offset"
        )
    return render(data, request.response_format)


def _comment_page(data: dict, request: m.FetchInput) -> dict:
    """Keep complete comments while preserving the server's untrimmed cursor."""
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("comments"), list)
        or any(
            not isinstance(c, dict) or not c.get("comment_id") for c in data["comments"]
        )
        or len(data["comments"]) > request.limit
        or not isinstance(data.get("has_more"), bool)
        or (
            data["has_more"]
            and (
                type(data.get("next_offset")) is not int
                or data["next_offset"] <= request.offset
            )
        )
        or (not data["has_more"] and data.get("next_offset") is not None)
    ):
        raise RuntimeError(
            "Comment response contract changed: expected bounded comments and a progressing cursor"
        )
    comments = data["comments"]

    def candidate(count):
        shortened = count < len(comments)
        return _format_result(
            {
                "comments": comments[:count],
                "has_more": shortened or data["has_more"],
                "next_offset": request.offset + count
                if shortened
                else data["next_offset"],
            },
            request.response_format,
        )

    result = candidate(len(comments))
    if len(json.dumps(result, ensure_ascii=False)) <= MAX_RESULT_CHARS:
        return result
    low, high = 0, len(comments) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps(candidate(middle), ensure_ascii=False)) <= MAX_RESULT_CHARS:
            low = middle
        else:
            high = middle - 1
    if low:
        return candidate(low)
    marker = {
        "comment_id": str(comments[0]["comment_id"])[:256],
        "content_omitted": True,
        "message": "Comment exceeds the response budget; read it in AppFlowy",
    }
    more = len(comments) > 1
    return _format_result(
        {
            "comments": [marker],
            "has_more": more or data["has_more"],
            "next_offset": request.offset + 1 if more else data["next_offset"],
        },
        request.response_format,
    )


async def appflowy_fetch(request: m.FetchInput) -> dict:
    """Read identity, folders, pages, database fields, or paginated comments by ID."""
    if request.id != "self":
        identifier(request.id, "id")
    if request.database_id:
        identifier(request.database_id, "database_id")
    if request.kind == "comments":
        data = await backend().list_comments(
            workspace(request),
            request.id,
            request.target_type,
            limit=request.limit,
            offset=request.offset,
        )
        return _comment_page(data, request)
    return bounded(
        await backend().appflowy_fetch(**request.model_dump(exclude={"target_type"}))
    )


async def create_space(ws: str, spec: m.PageSpec):
    permission = spec.permission or m.SpacePermission(visibility="private")
    body = {
        "name": spec.name,
        "permission": permission.model_dump(),
        "space_icon": "",
        "space_icon_color": "",
    }
    # A custom ACL must never be silently reduced to public/private.
    return await api("POST", f"/api/workspace/{ws}/spaces", json=body)


async def appflowy_create_pages(request: m.CreateInput) -> dict:
    """Create document pages, spaces, databases or views; report each batch item."""
    ws, b = workspace(request), backend()

    async def create(spec):
        if spec.kind == "space":
            return await create_space(ws, spec)
        parent = identifier(spec.parent_view_id, "parent_view_id")
        if spec.permission is not None:
            raise ValueError("permission applies only to a space")
        if spec.kind == "document":
            return {
                "view_id": await b.create_page(
                    ws, parent, spec.name, markdown=spec.markdown
                )
            }
        if spec.kind == "database":
            return await api(
                "POST",
                f"/api/workspace/{ws}/page-view",
                json={
                    "parent_view_id": parent,
                    "name": spec.name,
                    "layout": b._DB_LAYOUTS[spec.layout],
                },
            )
        return {
            "view_id": await b.create_database_view(ws, parent, spec.layout, spec.name)
        }

    return await batch(request.pages, create)


async def rewrite_document(
    ws: str, page_id: str, markdown: str, expected: str | None, prepend=False
):
    b = backend()
    doc, object_id, document = await b._open_document(ws, page_id)
    current = d._doc_to_markdown(document)
    if expected is None:
        raise ValueError(
            "expected_markdown is required: read the page before replacing its content"
        )
    if current != expected:
        raise ValueError(
            "Page changed since it was read; fetch it again before replacing"
        )
    blocks, cmap, tmap = (
        document["blocks"],
        document["meta"]["children_map"],
        document["meta"]["text_map"],
    )
    root_id = document["page_id"]
    root = blocks[root_id]
    state = doc.get_state()
    with doc.transaction():
        children = cmap[root["children"]]
        if not prepend:
            for child in list(children):
                d._delete_block_tree(blocks, cmap, tmap, child)
            while len(children):
                del children[0]
        for index, spec in enumerate(d._md_to_blocks(markdown)):
            block_id = d._insert_pd_block(blocks, cmap, tmap, spec, root_id)
            children.insert(index if prepend else len(children), block_id)
    await b._collab_web_update(ws, object_id, doc, state, 0)
    return {"id": page_id, "updated": True}


async def appflowy_update(request: m.UpdateInput) -> dict:
    """Rename, move, duplicate, trash/restore or edit pages; append comments; set space permissions."""
    ws, b, target = workspace(request), backend(), request.id
    command = request.command
    if command == "append_comment":
        result = await b.append_comment(
            ws,
            target,
            request.target_type,
            request.content,
            request.reply_comment_id,
            request.block_id,
            request.database_view_id,
        )
    elif command == "rename":
        if not request.name.strip():
            raise ValueError("name is required")
        result = await b.rename_page(ws, target, request.name)
    elif command == "move":
        result = await b.move_page(ws, target, required(request, "parent_view_id"))
    elif command == "duplicate":
        result = await b.duplicate_page(ws, target, request.name)
    elif command == "trash":
        result = await b.trash_page(ws, target)
    elif command == "restore":
        result = await b.restore_page(ws, target)
    elif command == "append":
        result = await b.append_blocks(ws, target, markdown=request.markdown)
    elif command in {"prepend", "replace"}:
        result = await rewrite_document(
            ws,
            target,
            request.markdown,
            request.expected_markdown,
            command == "prepend",
        )
    else:
        if request.permission is None:
            raise ValueError("permission is required")
        result = await api(
            "PATCH",
            f"/api/workspace/{ws}/spaces/{target}",
            json={"permission": request.permission.model_dump()},
        )
    return bounded({"id": target, "command": command, "result": result})


async def appflowy_delete(request: m.DeleteInput) -> dict:
    """Trash a page, or delete an existing row, block or field."""
    ws, b = workspace(request), backend()
    if request.kind == "page":
        result = await b.trash_page(ws, request.id)
    elif request.kind == "row":
        result = await b._delete_row_strict(
            ws, required(request, "database_id"), request.id
        )
    elif request.kind == "block":
        result = await b.delete_block(ws, required(request, "page_id"), request.id)
    else:
        result = await b.delete_database_field(
            ws, required(request, "database_id"), request.id
        )
    return bounded({"id": request.id, "kind": request.kind, "result": result})


async def configure_formula(ws, request):
    b = backend()
    doc, database = await b._open_database(ws, required(request, "database_id"))
    field = database["fields"][required(request, "field_id")]
    if int(field["ty"]) != 19:
        raise ValueError("field_id must identify a Formula field (19)")
    state = doc.get_state()
    with doc.transaction():
        if "type_option" not in field:
            field["type_option"] = Map()
        options = field["type_option"]
        if "19" not in options:
            options["19"] = Map()
        options["19"]["expression"] = request.expression
    await b._collab_web_update(ws, request.database_id, doc, state, 1)
    return {
        "field_id": request.field_id,
        "expression": request.expression,
        "evaluation": "AppFlowy client",
    }


async def configure_timeline(ws, request):
    b = backend()
    doc, database = await b._open_database(ws, required(request, "database_id"))
    view = database["views"][required(request, "view_id")]
    if int(view["layout"]) != 8:
        raise ValueError("view_id must identify a Timeline database view (layout 8)")
    allowed = {
        "field_id",
        "layout_ty",
        "show_table",
        "first_day_of_week_v2",
        "end_field_id",
        "progress_field_id",
        "dependency_field_id",
        "dependency_shift_ty",
        "dependency_direction",
        "avoid_weekends",
    }
    if not request.settings or set(request.settings) - allowed:
        raise ValueError(
            "Provide only supported Timeline settings; see appflowy://guide"
        )
    for key, value in request.settings.items():
        if key.endswith("field_id"):
            identifier(value, key)
            if value not in database["fields"]:
                raise ValueError(f"Unknown field: {key}")
            if (
                key in {"field_id", "end_field_id"}
                and int(database["fields"][value]["ty"]) != 2
            ):
                raise ValueError(f"{key} must identify a DateTime field")
        elif key in {"show_table", "avoid_weekends"} and type(value) is not bool:
            raise ValueError(f"{key} must be boolean")
        elif key in {"layout_ty", "first_day_of_week_v2"} and (
            type(value) is not int or not 0 <= value <= 6
        ):
            raise ValueError(f"{key} must be an integer from 0 to 6")
        elif key in {"dependency_shift_ty", "dependency_direction"} and (
            type(value) is not int
            or not 0 <= value <= (2 if key.endswith("shift_ty") else 1)
        ):
            raise ValueError(f"Invalid {key}")
    state = doc.get_state()
    with doc.transaction():
        if "layout_settings" not in view:
            view["layout_settings"] = Map()
        layouts = view["layout_settings"]
        if "8" not in layouts:
            layouts["8"] = Map()
        for key, value in request.settings.items():
            layouts["8"][key] = value
    await b._collab_web_update(ws, request.database_id, doc, state, 1)
    return {"view_id": request.view_id, "settings": request.settings}


async def appflowy_database(request: m.DatabaseInput) -> dict:
    """Inspect or edit schema, select options, grouping, Formula and Timeline settings."""
    ws, b, command = workspace(request), backend(), request.command
    if command == "list":
        return page(await b.list_databases(ws), request)
    if command == "space_permissions":
        return bounded(
            await api(
                "GET",
                f"/api/workspace/{ws}/spaces/{required(request, 'view_id')}/permission",
            )
        )
    db = required(request, "database_id")
    if command == "fields":
        return page(await b.get_database_fields(ws, db), request)
    if command == "formula":
        return await configure_formula(ws, request)
    if command == "timeline":
        return await configure_timeline(ws, request)
    if command == "view_settings":
        _, database = await b._open_database(ws, db)
        return bounded(database["views"][required(request, "view_id")].to_py())
    if command == "add_field":
        if not request.name.strip():
            raise ValueError("name is required")
        result = await b.add_database_field(
            ws,
            db,
            request.name,
            request.field_type,
            json.dumps(request.settings) if request.settings else "",
        )
    else:
        field = required(request, "field_id")
        if command == "update_field":
            result = await b.update_database_field(
                ws,
                db,
                field,
                request.name,
                json.dumps(request.settings) if request.settings else "",
            )
        elif command == "delete_field":
            result = await b.delete_database_field(ws, db, field)
        elif command == "add_option":
            if not request.name.strip():
                raise ValueError("name is required")
            result = await b.add_select_option(ws, db, field, request.name)
        elif command == "delete_option":
            result = await b.delete_select_option(
                ws, db, field, required(request, "option_id")
            )
        else:
            result = await b.set_group_by(ws, db, required(request, "view_id"), field)
    return bounded({"command": command, "result": result})


FIELD_TYPES = {
    name: index
    for index, name in enumerate(
        (
            "RichText",
            "Number",
            "DateTime",
            "SingleSelect",
            "MultiSelect",
            "Checkbox",
            "URL",
            "Checklist",
            "LastEditedTime",
            "CreatedTime",
            "Relation",
            "Summary",
            "Translate",
            "Time",
            "Media",
            "Person",
            "Rollup",
            "CreatedBy",
            "LastEditedBy",
            "Formula",
        )
    )
}


def field_kind(field: dict) -> int:
    value = field.get(
        "field_type_id", field.get("field_type", field.get("type", field.get("ty", 0)))
    )
    return FIELD_TYPES[value] if value in FIELD_TYPES else int(value)


def field_options(field: dict) -> list:
    options = field.get("type_option", field.get("type_options", {}))
    if isinstance(options, str):
        options = json.loads(options)
    if isinstance(options, dict):
        options = options.get(str(field_kind(field)), options)
        if isinstance(options, dict) and "content" in options:
            options = options["content"]
            if isinstance(options, str):
                options = json.loads(options)
    return options.get("options", []) if isinstance(options, dict) else []


def encode_cells(fields: list[dict], cells: dict) -> dict:
    """Resolve names once and encode authoritative CRDT cell values by field type."""
    result = {}
    for key, value in cells.items():
        matches = [
            field
            for field in fields
            if str(field.get("id", field.get("field_id"))) == key
        ]
        if not matches:
            matches = [
                field
                for field in fields
                if field.get("name", "").casefold() == key.casefold()
            ]
        if len(matches) != 1:
            raise ValueError(f"Field {key!r} is missing or ambiguous; use a field ID")
        field = matches[0]
        fid = str(field.get("id", field.get("field_id")))
        kind = field_kind(field)
        if kind in {8, 9, 11, 12, 16, 17, 18, 19}:
            raise ValueError(f"Field {key!r} is computed or server-managed")
        if kind in {0, 6}:
            if not isinstance(value, str):
                raise ValueError(f"Field {key!r} expects text")
        elif kind == 1:
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(f"Field {key!r} expects a number")
            if not math.isfinite(float(value)):
                raise ValueError("Number must be finite")
            value = str(value)
        elif kind == 5:
            if type(value) is not bool:
                raise ValueError(f"Field {key!r} expects true or false")
            value = "Yes" if value else "No"
        elif kind in {3, 4}:
            values = value if isinstance(value, list) else [value]
            if kind == 3 and len(values) > 1:
                raise ValueError("SingleSelect accepts one option")
            resolved = []
            for option in values:
                matches = [
                    item
                    for item in field_options(field)
                    if option in (item.get("id"), item.get("name"))
                ]
                if len(matches) != 1:
                    raise ValueError(f"Option {option!r} is missing or ambiguous")
                resolved.append(matches[0]["id"])
            value = ",".join(resolved)
        elif kind == 2:
            if isinstance(value, str):
                stamp = datetime.fromisoformat(value)
                if stamp.tzinfo is None:
                    raise ValueError("DateTime strings must include a UTC offset")
                value = {
                    "timestamp": int(stamp.timestamp()),
                    "include_time": True,
                    "is_range": False,
                }
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                value = {
                    "timestamp": int(value),
                    "include_time": True,
                    "is_range": False,
                }
            if not isinstance(value, dict) or "timestamp" not in value:
                raise ValueError(
                    "DateTime expects an ISO timestamp or timestamp object"
                )
            for key in ("timestamp", "end_timestamp"):
                stamp = value.get(key)
                if stamp is not None and (
                    isinstance(stamp, bool)
                    or not isinstance(stamp, (int, float))
                    or not math.isfinite(stamp)
                ):
                    raise ValueError(f"DateTime {key} must be a finite number")
            if value["timestamp"] is None:
                raise ValueError("DateTime timestamp must be a finite number")
            for key in ("include_time", "is_range"):
                if key in value and type(value[key]) is not bool:
                    raise ValueError(f"DateTime {key} must be boolean")
            unknown = value.keys() - {
                "timestamp",
                "end_timestamp",
                "include_time",
                "is_range",
            }
            if unknown:
                raise ValueError(
                    f"Unknown DateTime attributes: {', '.join(sorted(unknown))}"
                )
            is_range = value.get("is_range", False)
            end = value.get("end_timestamp")
            if is_range and (end is None or end < value["timestamp"]):
                raise ValueError(
                    "DateTime ranges need an end_timestamp at or after timestamp"
                )
            # AppFlowy stores date attributes beside data, not as JSON inside it.
            value = {
                "data": str(int(value["timestamp"])),
                "end_timestamp": str(int(end)) if is_range else "",
                "include_time": value.get("include_time", True),
                "is_range": is_range,
            }
        else:
            raise ValueError(
                f"Typed writes for field type {kind} are not available; existing cells are preserved"
            )
        result[fid] = value
    return result


async def appflowy_rows(request: m.RowsInput) -> dict:
    """Read paginated rows or batch create/upsert/update/delete using typed cells."""
    ws, b, db = workspace(request), backend(), request.database_id
    if request.command == "changed_since":
        return page(await b.list_updated_rows(ws, db, request.after), request)
    if request.command in {"list", "get"}:
        if request.command == "get":
            if not request.row_ids:
                raise ValueError("row_ids is required")
            ids = request.row_ids
        else:
            ids = await b.get_database_row_ids(ws, db)
        selected = ids[request.offset : request.offset + request.limit]
        normalized = [
            str(item.get("id", item.get("row_id", "")))
            if isinstance(item, dict)
            else str(item)
            for item in selected
        ]
        for row_id in normalized:
            identifier(row_id, "row_id")
        rows = (
            await b.get_database_row_details(
                ws, db, ",".join(normalized), request.with_doc
            )
            if normalized
            else []
        )
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not row.get("id", row.get("row_id"))
            for row in rows
        ):
            raise TypeError("Row detail response must be a list with stable row IDs")
        by_id = {str(row.get("id", row.get("row_id"))): row for row in rows}
        ordered = [
            by_id.get(
                row_id,
                {
                    "id": row_id,
                    "unavailable": True,
                    "message": "Materialized row details are not ready; do not recreate this row",
                },
            )
            for row_id in normalized
        ]
        return _fit_page(ordered, request, len(ids))
    if request.command == "delete":
        if not request.row_ids:
            raise ValueError("row_ids is required")
        return await batch(
            request.row_ids, lambda row_id: b._delete_row_strict(ws, db, row_id)
        )
    if not request.rows:
        raise ValueError("rows is required")
    fields = await b.get_database_fields(ws, db)
    encoded = [encode_cells(fields, row.cells) for row in request.rows]
    if request.command == "update_cells":
        for row in request.rows:
            identifier(row.row_id, "row_id")
    if request.command == "upsert" and any(not row.pre_hash for row in request.rows):
        raise ValueError("Each upsert needs a stable pre_hash")

    async def mutate(pair):
        row, cells = pair
        row_id = row.row_id
        if request.command in {"create", "upsert"}:
            body = {"cells": {}, "document": row.document}
            if request.command == "upsert":
                body["pre_hash"] = row.pre_hash
            operation = (
                b.create_database_row
                if request.command == "create"
                else b.upsert_database_row
            )
            created = await operation(ws, db, json.dumps(body))
            row_id = (
                created.get("row_id", created.get("id", ""))
                if isinstance(created, dict)
                else created
            )
            identifier(row_id, "created row_id")
        try:
            if cells:
                await b.update_row_cells(ws, db, row_id, json.dumps(cells))
        except (ValueError, RuntimeError) as exc:
            return {
                "row_id": row_id,
                "cells_applied": False,
                "partial": True,
                "error": str(exc)[:300],
                "retry": "update_cells with this row_id; do not create another row",
            }
        return {"row_id": row_id, "cells_applied": True}

    result = await batch(list(zip(request.rows, encoded, strict=True)), mutate)
    if any(item.get("result", {}).get("partial") for item in result.get("items", [])):
        result["ok"] = False
    return result


async def appflowy_blocks(request: m.BlocksInput) -> dict:
    """Add Markdown blocks, edit/delete a block, or replace matching text."""
    ws, b = workspace(request), backend()
    if request.command == "add":
        if request.parent_id:
            identifier(request.parent_id, "parent_id")
        if request.block_type:
            result = await b.add_block(
                ws,
                request.page_id,
                block_type=request.block_type,
                text=request.text,
                data=json.dumps(request.data),
                parent_block_id=request.parent_id,
            )
        else:
            result = await b.add_blocks(
                ws,
                request.page_id,
                markdown=request.markdown,
                parent_block_id=request.parent_id,
            )
    elif request.command == "edit":
        result = await b.edit_block_text(
            ws, request.page_id, required(request, "block_id"), request.text
        )
    elif request.command == "delete":
        result = await b.delete_block(
            ws, request.page_id, required(request, "block_id")
        )
    else:
        if not request.find:
            raise ValueError("find must not be empty")
        result = await b.replace_text(
            ws, request.page_id, request.find, request.replace, request.replace_all
        )
    return bounded({"page_id": request.page_id, "result": result})


async def appflowy_import(request: m.ImportInput) -> dict:
    """Import Markdown trees or upload small files from payloads, with per-item outcomes."""
    ws, b = workspace(request), backend()
    paths = []
    for entry in request.entries:
        raw = entry.path
        path = PurePosixPath(raw)
        if (
            raw.startswith("/")
            or "\\" in raw
            or any(part in {"", ".", ".."} for part in raw.split("/"))
            or ":" in raw
            or "\x00" in raw
        ):
            raise ValueError(
                "Import paths must be relative, without traversal or drive names"
            )
        if path.suffix.lower() != ".md":
            raise ValueError("Each entry path must end in .md")
        paths.append(str(path))
    if len(paths) != len(set(paths)):
        raise ValueError("Import paths must be unique")
    if sum(len(entry.markdown) for entry in request.entries) > 200_000:
        raise ValueError("Import payload exceeds 200000 characters")
    decoded = []
    for entry in request.files:
        value = base64.b64decode(entry.content_base64, validate=True)
        if len(value) > 1_000_000:
            raise ValueError("Each file is limited to 1000000 bytes")
        decoded.append(value)
    if sum(map(len, decoded)) > 2_000_000:
        raise ValueError("File payload exceeds 2000000 bytes; split the batch")
    created = {".": request.parent_view_id}
    results = []
    for entry in sorted(
        request.entries,
        key=lambda item: (len(PurePosixPath(item.path).parts), item.path),
    ):
        path = PurePosixPath(entry.path)
        try:
            parent = PurePosixPath(".")
            for segment in path.parts[:-1]:
                child = parent / segment
                if str(child) not in created:
                    created[str(child)] = await b.create_page(
                        ws, created[str(parent)], segment
                    )
                parent = child
            page_id = await b.create_page(
                ws, created[str(parent)], path.stem, markdown=entry.markdown
            )
            created[str(path.with_suffix(""))] = page_id
            results.append({"path": entry.path, "id": page_id, "ok": True})
        except (ValueError, RuntimeError) as exc:
            results.append({"path": entry.path, "ok": False, "error": str(exc)[:300]})
    uploads = []
    for entry, value in zip(request.files, decoded, strict=True):
        try:
            response = await a._api_call_async(
                "PUT",
                f"/api/file_storage/{ws}/v1/blob/{request.parent_view_id}",
                content=value,
                headers={"Content-Type": entry.content_type},
            )
            file_id = response.json()["data"]["file_id"]
            uploads.append(
                {
                    "ok": True,
                    "name": entry.name,
                    "file_id": file_id,
                    "url": f"{a.BASE_URL}/api/file_storage/{ws}/v1/blob/{request.parent_view_id}/{quote(file_id, safe='')}",
                }
            )
        except (ValueError, RuntimeError) as exc:
            uploads.append({"ok": False, "name": entry.name, "error": str(exc)[:300]})
    return bounded(
        {
            "ok": all(item["ok"] for item in results + uploads),
            "entries": results,
            "files": uploads,
            "created_parents": created,
        }
    )


async def appflowy_export(request: m.ExportInput) -> dict:
    """Export a page/tree as bounded Markdown entries without reading server files."""
    return bounded(
        await backend().appflowy_export(
            workspace(request),
            request.view_id,
            request.depth,
            request.limit,
            request.offset,
        )
    )


def decode_answer(text: str) -> str:
    decoder, result, cursor = json.JSONDecoder(), [], 0
    while cursor < len(text):
        remaining = text[cursor:].lstrip()
        if not remaining:
            break
        if remaining.startswith("data:"):
            remaining = remaining[5:].lstrip()
        if remaining.startswith("[DONE]"):
            break
        try:
            value, consumed = decoder.raw_decode(remaining)
        except ValueError as exc:
            raise RuntimeError(
                "AppFlowy AI stream is incomplete or has an unsupported format"
            ) from exc
        if isinstance(value, dict):
            if value.get("code", 0) != 0 or "error" in value:
                raise RuntimeError("AppFlowy AI returned an error")
            for key in ("1", "2"):
                if isinstance(value.get(key), str):
                    result.append(value[key])
        cursor = len(text) - len(remaining) + consumed
    if not result:
        raise RuntimeError("AppFlowy AI stream contained no answer text")
    return "".join(result)


async def appflowy_ai(request: m.AIInput) -> dict:
    """Use AppFlowy's AI chat. Explicit page sources or full_workspace consent is required."""
    ws, b = workspace(request), backend()
    if not ai_enabled():
        raise ValueError(
            "AppFlowy AI is opt-in: set APPFLOWY_ENABLE_AI=true on a deployment with configured AI"
        )
    if request.command == "create_chat":
        parent = required(request, "parent_view_id")
        return bounded(
            await api(
                "POST",
                f"/api/workspace/{ws}/page-view",
                json={"parent_view_id": parent, "layout": 4, "name": request.name},
            )
        )
    chat = required(request, "chat_id")
    path = f"/api/chat/{ws}/{chat}"
    if request.command == "messages":
        return bounded(
            await api(
                "GET",
                path + "/message",
                params={"limit": request.limit, "offset": request.offset},
            )
        )
    if request.command == "delete_chat":
        return bounded(
            {"chat_id": chat, "trashed": True, "result": await b.trash_page(ws, chat)}
        )
    if request.command == "ask" and not request.question.strip():
        raise ValueError("question is required")
    # Empty sources represent no selected pages, never implicit workspace-wide RAG.
    settings = {
        "rag_ids": request.page_ids
        if request.page_ids
        else ([] if request.full_workspace else [chat]),
        "full_workspace": request.full_workspace,
    }
    await api("POST", path + "/settings", json=settings)
    if request.command == "set_context":
        return {
            "chat_id": chat,
            "page_ids": request.page_ids,
            "full_workspace": request.full_workspace,
        }
    question = await api(
        "POST",
        path + "/message/question",
        json={"content": request.question, "message_type": 1},
    )
    question_id = (
        question.get("message_id", question.get("id"))
        if isinstance(question, dict)
        else None
    )
    if question_id is None:
        raise RuntimeError(
            "Question was submitted but returned no message ID; do not resubmit blindly"
        )
    client = await a._get_async_client()
    # Bound the streamed body before decoding; no historical non-streaming route.
    try:
        async with asyncio.timeout(120):
            async with client.stream(
                "POST",
                a.BASE_URL + path + "/answer/stream",
                headers=await a.get_auth_headers_async(),
                json={
                    "question_id": question_id,
                    "chat_id": chat,
                    "format": {"output_layout": 0, "output_content": 0},
                },
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_text():
                    size += len(chunk)
                    if size > 200_000:
                        raise RuntimeError("AI answer exceeded the response limit")
                    chunks.append(chunk)
        answer = decode_answer("".join(chunks))
    except (TimeoutError, httpx.HTTPError, ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "partial": True,
            "chat_id": chat,
            "question_id": question_id,
            "error": f"Answer unavailable ({type(exc).__name__})",
            "retry": "Read messages for this chat before resubmitting the question",
        }
    return {
        "ok": True,
        "chat_id": chat,
        "question_id": question_id,
        "answer": answer[:40_000],
        "truncated": len(answer) > 40_000,
    }


async def appflowy_api(request: m.APIInput) -> dict:
    """Call an additional workspace REST route; paths stay within the selected workspace."""
    ws = workspace(request)
    path = request.path
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", path):
        raise ValueError(
            "path must be a workspace-relative route without URLs, escapes or traversal"
        )
    if len(json.dumps(request.body, allow_nan=False)) > 100_000:
        raise ValueError("body is too large")
    return bounded(
        await api(
            request.method,
            f"/api/workspace/{ws}/{path}",
            params=request.params,
            **({"json": request.body} if request.body is not None else {}),
        )
    )


def ai_enabled() -> bool:
    import os

    return os.environ.get("APPFLOWY_ENABLE_AI", "false").lower() in {"true", "1", "yes"}


async def _read_database(request: m.ReadDatabaseInput) -> dict:
    """Read database schema, view settings or space permissions."""
    return await appflowy_database(m.DatabaseInput(**request.model_dump()))


async def _read_rows(request: m.ReadRowsInput) -> dict:
    """Read bounded rows or rows changed since a cursor."""
    return await appflowy_rows(m.RowsInput(**request.model_dump()))


def register(server):
    read = {"appflowy_search", "appflowy_fetch", "appflowy_export"}
    for function in (
        appflowy_search,
        appflowy_fetch,
        appflowy_create_pages,
        appflowy_update,
        appflowy_delete,
        appflowy_database,
        appflowy_rows,
        appflowy_blocks,
        appflowy_ai,
        appflowy_import,
        appflowy_export,
        appflowy_api,
    ):
        name = function.__name__
        if name == "appflowy_ai" and not ai_enabled():
            continue
        if a._read_only() and function.__name__ not in read | {
            "appflowy_database",
            "appflowy_rows",
        }:
            continue
        if a._read_only():
            function = {
                "appflowy_database": _read_database,
                "appflowy_rows": _read_rows,
            }.get(name, function)
        # A tool can create/append/import depending on its command. Advertising
        # idempotence here could cause a client to retry and duplicate writes.
        server.tool(
            name=name,
            title=name.removeprefix("appflowy_").replace("_", " ").title(),
            annotations=READ
            if name in read or a._read_only()
            else {**DESTRUCTIVE, "idempotentHint": False},
        )(function)
