"""Large responses must preserve identities, progress and complete exported files."""

import hashlib
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from appflowy_mcp import api as a
from appflowy_mcp import models as m
from appflowy_mcp import server as b
from appflowy_mcp import workflows as w


def test_generic_preview_accounts_for_its_json_escaping_and_envelope():
    result = w.bounded({"text": '\n"\\😀' * 50_000})
    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False)) <= w.MAX_RESULT_CHARS
    assert json.loads(json.dumps(result)) == result


def test_size_limited_client_pages_reassemble_without_gaps_or_partial_records():
    items = [{"id": f"item-{i}", "text": "x" * 2000} for i in range(50)]
    received, offset = [], 0
    while True:
        result = w.page(items, m.ReadInput(offset=offset, limit=50))
        assert "preview" not in result
        assert len(json.dumps(result, ensure_ascii=False)) <= w.MAX_RESULT_CHARS
        received.extend(result["items"])
        if not result["has_more"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert received == items


@pytest.mark.parametrize("response_format", ["json", "markdown"])
def test_one_oversized_item_keeps_its_identity_and_advances(response_format):
    result = w.page(
        [{"id": "row-1", "cells": {"Notes": "x" * 100_000}}, {"id": "row-2"}],
        m.ReadInput(response_format=response_format),
    )
    assert result["next_offset"] == 1
    assert result["has_more"] is True
    assert "preview" not in result
    if response_format == "json":
        assert result["items"][0]["id"] == "row-1"
        assert result["items"][0]["content_omitted"] is True
        assert "cells" not in result["items"][0]
    else:
        assert "row-1" in result["markdown"]
        assert "content_omitted" in result["markdown"]


@pytest.mark.asyncio
async def test_get_rows_fetches_only_selected_ids_and_handles_lag_or_reordering(
    monkeypatch,
):
    details = AsyncMock(return_value=[{"id": "row-3"}, {"row_id": "row-1"}])
    monkeypatch.setattr(b, "get_database_row_details", details)
    result = await w.appflowy_rows(
        m.RowsInput(
            workspace_id="ws-allowed",
            database_id="db",
            command="get",
            row_ids=["row-0", "row-1", "row-2", "row-3"],
            offset=1,
            limit=3,
        )
    )
    assert details.call_args.args[2] == "row-1,row-2,row-3"
    assert [item.get("id", item.get("row_id")) for item in result["items"]] == [
        "row-1",
        "row-2",
        "row-3",
    ]
    assert result["items"][1]["unavailable"] is True
    assert "do not recreate" in result["items"][1]["message"]
    assert result["next_offset"] is None


@pytest.mark.asyncio
async def test_markdown_chunks_reassemble_and_identify_the_content_revision(
    monkeypatch,
):
    markdown = "# Heading\n\n" + '\x01\n"😀' * 20_000
    read = AsyncMock(return_value=markdown)
    monkeypatch.setattr(b, "get_page_markdown_async", read)
    parts, offset = [], 0
    while True:
        result = await w.appflowy_fetch(
            m.FetchInput(
                workspace_id="ws-allowed",
                id="page",
                response_format="markdown",
                offset=offset,
            )
        )
        assert "preview" not in result
        assert result["content_hash"] == hashlib.sha256(markdown.encode()).hexdigest()
        assert len(json.dumps(result, ensure_ascii=False)) <= w.MAX_RESULT_CHARS
        parts.append(result["data"]["markdown"])
        if not result["has_more"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert "".join(parts) == markdown
    read.return_value = "Changed after the previous snapshot"
    changed = await w.appflowy_fetch(
        m.FetchInput(workspace_id="ws-allowed", id="page", response_format="markdown")
    )
    assert changed["content_hash"] != result["content_hash"]
    with pytest.raises(ValidationError, match="offset"):
        m.FetchInput(id="page", offset=1)


@pytest.mark.asyncio
async def test_folder_fetch_targets_the_selected_subtree(monkeypatch):
    call = AsyncMock(
        return_value=httpx.Response(
            200, json={"data": {"view_id": "target", "children": []}}
        )
    )
    monkeypatch.setattr(a, "_api_call", call)
    result = await w.appflowy_fetch(
        m.FetchInput(
            workspace_id="ws-allowed", kind="workspace_folder", id="target", depth=2
        )
    )
    assert call.call_args.args == ("GET", "/api/workspace/ws-allowed/view/target")
    assert call.call_args.kwargs["params"] == {"depth": 2}
    assert result["data"]["view_id"] == "target"


def mock_export(monkeypatch, children, markdown):
    folder = AsyncMock(
        return_value={"view_id": "root", "name": "Root", "children": children}
    )
    read = AsyncMock(
        side_effect=markdown if callable(markdown) else None,
        return_value=markdown if not callable(markdown) else None,
    )
    monkeypatch.setattr(b, "get_folder_view_async", folder)
    monkeypatch.setattr(b, "get_page_markdown_async", read)
    return folder, read


@pytest.mark.asyncio
async def test_tree_cursor_preserves_duplicate_paths_without_reading_skipped_bodies(
    monkeypatch,
):
    children = [
        {
            "view_id": f"same-{i}",
            "name": "Same",
            "children": [{"view_id": f"child-{i}", "name": "Child"}],
        }
        for i in (1, 2)
    ]
    _, read = mock_export(monkeypatch, children, "Complete file")
    offset, paths = 0, []
    while True:
        result = await b.appflowy_export(
            "ws-allowed", "root", depth=2, limit=1, offset=offset
        )
        paths.extend(item["path"] for item in result["entries"])
        if not result["has_more"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert paths == [
        "Root.md",
        "Root/Same.md",
        "Root/Same-2.md",
        "Root/Same/Child.md",
        "Root/Same-2/Child.md",
    ]
    assert read.await_count == 5


@pytest.mark.asyncio
async def test_export_budget_stops_reads_and_returns_a_usable_cursor(monkeypatch):
    children = [{"view_id": f"page-{i}", "name": f"Page {i}"} for i in range(1000)]
    _, read = mock_export(monkeypatch, children, "x" * 25_000)
    result = await w.appflowy_export(
        m.ExportInput(workspace_id="ws-allowed", view_id="root", depth=1, limit=50)
    )
    assert len(result["entries"]) == 1
    assert len(result["entries"][0]["markdown"]) == 25_000
    assert result["next_offset"] == 1
    assert read.await_count == 2
    assert "preview" not in result


@pytest.mark.asyncio
async def test_large_export_document_returns_a_fetch_request_not_a_partial_file(
    monkeypatch,
):
    _, read = mock_export(
        monkeypatch, [{"view_id": "child", "name": "Child"}], "x" * 100_000
    )
    result = await b.appflowy_export("ws-allowed", "root", depth=1, limit=50)
    assert result["entries"] == []
    assert result["next_offset"] == 1
    assert read.await_count == 1
    continuation = result["warnings"][0]["continuation"]
    assert continuation["tool"] == "appflowy_fetch"
    fetched = await w.appflowy_fetch(m.FetchInput(**continuation["request"]))
    assert fetched["has_more"] is True
    assert fetched["data"]["markdown"] == "x" * fetched["next_offset"]


@pytest.mark.asyncio
async def test_warning_limit_keeps_a_cursor_instead_of_losing_unavailable_pages(
    monkeypatch,
):
    children = [{"view_id": f"page-{i}", "name": f"Page {i}"} for i in range(30)]

    async def markdown(workspace_id, view_id):
        if view_id == "root":
            return "Root content"
        raise RuntimeError("Not a document")

    mock_export(monkeypatch, children, markdown)
    first = await b.appflowy_export("ws-allowed", "root", depth=1, limit=100)
    assert first["warnings_truncated"] is True
    assert first["has_more"] is True
    second = await b.appflowy_export(
        "ws-allowed", "root", depth=1, limit=100, offset=first["next_offset"]
    )
    assert second["has_more"] is False
    assert [item["id"] for item in first["warnings"] + second["warnings"]] == [
        item["view_id"] for item in children
    ]
