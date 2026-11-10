from unittest.mock import AsyncMock

import pytest

from appflowy_mcp import server


def _synthetic_row_doc(data0="old"):
    from pycrdt import Doc, Map

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["data"] = Map(
            {"cells": Map({"F1": Map({"data": data0, "field_type": 0})})}
        )
    return doc


@pytest.mark.asyncio
async def test_document_comments_read_and_append(monkeypatch, mock_appflowy_api):
    import json

    import httpx

    def handler(req):
        assert req.headers["Authorization"] == "Bearer x"
        if req.method == "GET":
            assert req.url.path.endswith("/document/doc/inline-comment")
            assert dict(req.url.params) == {"limit": "2", "offset": "4"}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "comments": [{"comment_id": "parent", "content": "Review"}],
                        "has_more": True,
                        "next_offset": 6,
                    }
                },
            )
        assert req.url.path.endswith("/inline-comment/v2")
        assert req.headers["device-id"]
        assert json.loads(req.content) == {
            "content": "Done",
            "reply_comment_id": "parent",
            "block_id": "block",
            "mentioned_user_uuids": [],
        }
        return httpx.Response(200, json={"data": {"comment_id": "new"}})

    mock_appflowy_api(handler)
    page = await server.list_comments(
        "ws-allowed", "doc", "document", limit=2, offset=4
    )
    assert page["next_offset"] == 6 and page["has_more"]
    assert await server.append_comment(
        "ws-allowed", "doc", "document", "Done", "parent", "block"
    ) == {"comment_id": "new"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [404, 405, 403, 500, "timeout", "application"])
async def test_document_comment_fallback_only_for_missing_route(
    monkeypatch, failure, mock_appflowy_api
):
    import httpx

    calls = []

    def handler(req):
        calls.append(req.url.path)
        if len(calls) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("timeout", request=req)
            if failure == "application":
                return httpx.Response(200, json={"code": 1012, "message": "failed"})
            return httpx.Response(failure)
        return httpx.Response(200, json={"code": 0})

    mock_appflowy_api(handler)
    if failure in (404, 405):
        assert await server.append_comment("ws-allowed", "doc", "document", "Hi") == {
            "comment_id": None
        }
        assert calls[1] == calls[0].removesuffix("/v2")
    else:
        with pytest.raises(RuntimeError):
            await server.append_comment("ws-allowed", "doc", "document", "Hi")
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_published_comments_check_workspace_and_paginate(
    monkeypatch, mock_appflowy_api
):
    import json

    import httpx

    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if "/page-view/" in req.url.path:
            return httpx.Response(200, json={"data": {"view_id": "page"}})
        assert calls[-2] == ("GET", "/api/workspace/ws-allowed/page-view/page")
        assert req.url.path == "/api/workspace/published-info/page/comment"
        if req.method == "POST":
            assert json.loads(req.content) == {
                "content": "Reply",
                "reply_comment_id": "c1",
            }
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(
            200,
            json={
                "data": {
                    "comments": [
                        {"comment_id": "c1"},
                        {"comment_id": "c2"},
                        {"comment_id": "c3"},
                    ]
                }
            },
        )

    mock_appflowy_api(handler)
    page = await server.list_comments(
        "ws-allowed", "page", "published", limit=1, offset=1
    )
    assert page == {
        "comments": [{"comment_id": "c2"}],
        "has_more": True,
        "next_offset": 2,
    }
    assert await server.append_comment(
        "ws-allowed", "page", "published", "Reply", "c1"
    ) == {"comment_id": None}


@pytest.mark.asyncio
async def test_comment_guards_and_published_workspace_denial(
    monkeypatch, mock_appflowy_api
):
    import httpx

    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(403)

    mock_appflowy_api(handler)
    for target in ("row", "document", "published"):
        with pytest.raises(ValueError, match="not permitted"):
            await server.list_comments("other", "id", target)
        with pytest.raises(ValueError, match="not permitted"):
            await server.append_comment("other", "id", target, "Hi")
    for kwargs in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        with pytest.raises(ValueError):
            await server.list_comments("ws-allowed", "id", "row", **kwargs)
    for target, content, kwargs in (
        ("invalid", "Hi", {}),
        ("row", "  ", {}),
        ("row", "Hi", {"block_id": "block"}),
        ("document", "Hi", {"database_view_id": "view"}),
    ):
        with pytest.raises(ValueError):
            await server.append_comment("ws-allowed", "id", target, content, **kwargs)
    with pytest.raises(ValueError):
        await server.list_comments("ws-allowed", "../other", "published")
    assert not calls
    for operation in (server.list_comments, server.append_comment):
        args = () if operation is server.list_comments else ("Hi",)
        with pytest.raises(RuntimeError, match="403"):
            await operation("ws-allowed", "page", "published", *args)
    assert calls == ["/api/workspace/ws-allowed/page-view/page"] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_thread", [False, True])
async def test_row_comments_merge_read_and_reply(
    monkeypatch, existing_thread, mock_appflowy_api
):
    import json

    import httpx
    from pycrdt import Map

    doc = _synthetic_row_doc()
    root = doc.get("data", type=Map)
    author = "00000000-0000-4000-8000-000000000001"
    other = "00000000-0000-4000-8000-000000000002"
    if existing_thread:
        with doc.transaction():
            root["comment"] = Map(
                {
                    "parent": Map(
                        {
                            "id": "parent",
                            "content": "Question",
                            "author_id": other,
                            "created_at": 1,
                            "parent_comment_id": "",
                            "reactions": "bad-json",
                        }
                    )
                }
            )
    writes = []

    def handler(req):
        if req.url.path == "/api/user/profile":
            return httpx.Response(200, json={"data": {"uuid": author}})
        if "/page-view/" in req.url.path:
            return httpx.Response(200, json={"data": {}})
        if req.url.path.endswith("/notification"):
            payload = json.loads(req.content)
            assert payload["reply_participant_uuids"] == [other]
            return httpx.Response(500)
        if req.method == "GET":
            assert req.url.params["collab_type"] == "4"
            return httpx.Response(200, json={"doc_state": list(doc.get_update())})
        assert req.url.path.endswith("/row1/web-update")
        payload = json.loads(req.content)
        assert payload["collab_type"] == 4
        with doc.transaction():
            root["data"]["cells"]["F1"]["data"] = "concurrent edit"
        writes.append(payload)
        doc.apply_update(bytes(payload["doc_state"]))
        return httpx.Response(200, json={"code": 0})

    mock_appflowy_api(handler)
    before = doc.get_state()
    page = await server.list_comments("ws-allowed", "row1", "row")
    assert len(page["comments"]) == int(existing_thread)
    assert doc.get_state() == before
    result = await server.append_comment(
        "ws-allowed",
        "row1",
        "row",
        "New comment",
        reply_comment_id="parent" if existing_thread else "",
        database_view_id="board",
    )
    assert len(writes) == 1
    assert ("warning" in result) == existing_thread
    stored = root["comment"][result["comment_id"]].to_py()
    assert stored["author_id"] == author and stored["content"] == "New comment"
    assert stored["parent_comment_id"] == ("parent" if existing_thread else "")
    assert stored["attachments"] == "[]" and stored["reactions"] == "{}"
    assert not stored["is_resolved"] and stored["created_at"] > 0
    assert root["data"]["cells"]["F1"]["data"] == "concurrent edit"
    page = await server.list_comments("ws-allowed", "row1", "row", limit=1)
    assert page["has_more"] == existing_thread
    if existing_thread:
        assert page["comments"][0]["reactions"] == {}
        page = await server.list_comments(
            "ws-allowed", "row1", "row", offset=page["next_offset"]
        )
    assert page["comments"][0]["comment_id"] == result["comment_id"]
    assert page["comments"][0]["attachments"] == []


@pytest.mark.asyncio
async def test_row_comment_missing_parent_and_unconfirmed_write(
    monkeypatch, mock_appflowy_api
):
    import httpx

    doc = _synthetic_row_doc()
    monkeypatch.setattr(server, "_collab_doc", AsyncMock(return_value=doc))
    with pytest.raises(ValueError, match="not found"):
        await server.append_comment("ws-allowed", "row1", "row", "Reply", "missing")
    mock_appflowy_api(
        lambda req: httpx.Response(200, json={"data": {"uuid": "author"}})
    )
    reads = iter(
        [doc, _synthetic_row_doc(), _synthetic_row_doc(), _synthetic_row_doc()]
    )
    monkeypatch.setattr(
        server, "_collab_doc", AsyncMock(side_effect=lambda *_: next(reads))
    )
    writes = []
    monkeypatch.setattr(
        server,
        "_collab_web_update",
        AsyncMock(side_effect=lambda *args: writes.append(args)),
    )
    monkeypatch.setattr(server.asyncio, "sleep", AsyncMock())
    with pytest.raises(RuntimeError, match="Check list_comments for comment_id="):
        await server.append_comment("ws-allowed", "row1", "row", "Hello")
    assert len(writes) == 1


@pytest.mark.asyncio
async def test_comment_tools_annotations():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert tools["list_comments"].annotations.read_only_hint
    assert not tools["append_comment"].annotations.idempotent_hint
    assert not tools["append_comment"].annotations.destructive_hint


@pytest.mark.asyncio
async def test_compact_comments_and_read_only(monkeypatch, mock_appflowy_api):
    import httpx

    from appflowy_mcp import models, workflows

    calls = []

    def handler(req):
        calls.append(req.method)
        return httpx.Response(
            200,
            json={
                "data": {
                    "comments": [],
                    "has_more": True,
                    "next_offset": 12,
                }
            },
        )

    mock_appflowy_api(handler)
    result = await workflows.appflowy_fetch(
        models.FetchInput(
            kind="comments",
            id="doc",
            limit=2,
            offset=10,
        )
    )
    assert result["next_offset"] == 12
    assert calls == ["GET"]
    monkeypatch.setenv("APPFLOWY_READ_ONLY", "true")
    with pytest.raises(PermissionError):
        await workflows.appflowy_update(
            models.UpdateInput(
                command="append_comment",
                id="doc",
                content="Hello",
            )
        )
    assert calls == ["GET"]
    with pytest.raises(ValueError):
        models.UpdateInput(command="rename", id="doc", content="ignored")
    with pytest.raises(ValueError):
        models.FetchInput(kind="page", id="doc", target_type="row")


@pytest.mark.asyncio
async def test_compact_comment_bounds_preserve_cursor(monkeypatch):
    from appflowy_mcp import models, workflows

    monkeypatch.setattr(
        server,
        "list_comments",
        AsyncMock(
            return_value={
                "comments": [
                    {"comment_id": "first", "content": "x" * 6000},
                    {"comment_id": "second", "content": "y" * 6000},
                ],
                "has_more": False,
                "next_offset": None,
            }
        ),
    )
    monkeypatch.setattr(workflows, "MAX_RESULT_CHARS", 1000)
    result = await workflows.appflowy_fetch(
        models.FetchInput(
            kind="comments",
            id="doc",
            offset=10,
        )
    )
    assert result["has_more"] and result["next_offset"] == 11
    assert result["comments"][0]["comment_id"] == "first"
    assert result["comments"][0]["content_omitted"]
