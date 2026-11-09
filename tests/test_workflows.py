import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp import Client
from pycrdt import Doc, Map

from appflowy_mcp import models as m
from appflowy_mcp import server as b
from appflowy_mcp import workflows as w


@pytest.mark.asyncio
async def test_search_preserves_server_cursor_and_scope(monkeypatch):
    call = AsyncMock(
        return_value={"items": [{"id": "p"}], "has_more": True, "next_offset": 42}
    )
    monkeypatch.setattr(w, "api", call)
    result = await w.appflowy_search(
        m.SearchInput(workspace_id="ws-allowed", query="plan", limit=2, offset=5)
    )
    assert result["next_offset"] == 42
    assert call.call_args.args[:2] == ("GET", "/api/search/ws-allowed/page")
    assert call.call_args.kwargs["params"]["offset"] == 5
    with pytest.raises(ValueError, match="not permitted"):
        await w.appflowy_search(m.SearchInput(workspace_id="other", query="plan"))
    assert call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "../other",
        "database/%2e%2e",
        "https://other",
        "/api/workspace/other",
        "db?token=x",
        "a//b",
        "a\\b",
    ],
)
async def test_passthrough_refuses_workspace_escape(monkeypatch, path):
    call = AsyncMock()
    monkeypatch.setattr(w, "api", call)
    with pytest.raises(ValueError, match="workspace-relative"):
        await w.appflowy_api(m.APIInput(workspace_id="ws-allowed", path=path))
    call.assert_not_called()


@pytest.mark.asyncio
async def test_read_only_enforced_below_tool_registration(monkeypatch):
    monkeypatch.setenv("APPFLOWY_READ_ONLY", "true")
    call = AsyncMock()
    monkeypatch.setattr(b, "_get_async_client", call)
    with pytest.raises(PermissionError, match="writes are disabled"):
        await b._api_call_async("POST", "/api/workspace/ws-allowed/page-view", json={})
    call.assert_not_called()


def test_typed_cells_refuse_ambiguity_and_computed_writes():
    fields = [
        {"id": "title", "name": "Title", "field_type": 0},
        {"id": "done", "name": "Done", "field_type": 5},
        {"id": "n", "name": "Count", "field_type": 1},
        {"id": "f", "name": "Total", "field_type": 19},
    ]
    assert w.encode_cells(fields, {"Title": "Plan", "Done": True, "Count": 12}) == {
        "title": "Plan",
        "done": "Yes",
        "n": "12",
    }
    with pytest.raises(ValueError, match="computed"):
        w.encode_cells(fields, {"Total": 3})
    with pytest.raises(ValueError, match="true or false"):
        w.encode_cells(fields, {"Done": "false"})
    with pytest.raises(ValueError, match="ambiguous"):
        w.encode_cells(
            fields + [{"id": "other", "name": "Title", "field_type": 0}],
            {"Title": "Plan"},
        )
    with pytest.raises(ValueError, match="finite"):
        w.encode_cells(fields, {"Count": float("nan")})


def test_typed_select_and_dates():
    fields = [
        {
            "id": "s",
            "name": "Status",
            "field_type": 3,
            "type_option": {
                "3": {
                    "content": json.dumps({"options": [{"id": "opt", "name": "Doing"}]})
                }
            },
        },
        {"id": "d", "name": "Date", "field_type": 2},
    ]
    assert w.encode_cells(fields, {"Status": "Doing"}) == {"s": "opt"}
    date = json.loads(w.encode_cells(fields, {"Date": "2026-11-09T00:00:00Z"})["d"])
    assert date["timestamp"] == 1794182400
    with pytest.raises(ValueError, match="missing or ambiguous"):
        w.encode_cells(fields, {"Status": "Missing"})
    with pytest.raises(ValueError, match="UTC offset"):
        w.encode_cells(fields, {"Date": "2026-11-09T00:00:00"})


@pytest.mark.asyncio
async def test_row_partial_failure_keeps_created_id(monkeypatch):
    monkeypatch.setattr(
        b,
        "get_database_fields",
        AsyncMock(return_value=[{"id": "title", "name": "Title", "field_type": 0}]),
    )
    create = AsyncMock(return_value="created-row")
    monkeypatch.setattr(b, "create_database_row", create)
    monkeypatch.setattr(
        b, "update_row_cells", AsyncMock(side_effect=RuntimeError("write failed"))
    )
    result = await w.appflowy_rows(
        m.RowsInput(
            workspace_id="ws-allowed",
            database_id="db",
            command="create",
            rows=[m.RowSpec(cells={"Title": "one"})],
        )
    )
    assert result["ok"] is False
    assert result["items"][0]["result"]["row_id"] == "created-row"
    assert "do not create" in result["items"][0]["result"]["retry"]
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_validates_cells_before_creating_any_rows(monkeypatch):
    monkeypatch.setattr(
        b,
        "get_database_fields",
        AsyncMock(return_value=[{"id": "title", "name": "Title", "field_type": 0}]),
    )
    create = AsyncMock()
    monkeypatch.setattr(b, "create_database_row", create)
    with pytest.raises(ValueError, match="missing"):
        await w.appflowy_rows(
            m.RowsInput(
                workspace_id="ws-allowed",
                database_id="db",
                command="create",
                rows=[
                    m.RowSpec(cells={"Title": "one"}),
                    m.RowSpec(cells={"Unknown": "two"}),
                ],
            )
        )
    create.assert_not_called()


@pytest.mark.asyncio
async def test_import_rejects_unsafe_paths_before_writes(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(b, "create_page", create)
    for path in ["../x.md", "/x.md", "a/../x.md", "C:/x.md", "a\\x.md", "a//x.md"]:
        with pytest.raises(ValueError):
            await w.appflowy_import(
                m.ImportInput(
                    workspace_id="ws-allowed",
                    parent_view_id="parent",
                    entries=[m.Entry(path=path)],
                )
            )
    create.assert_not_called()


@pytest.mark.asyncio
async def test_import_preserves_parent_ids_and_partial_results(monkeypatch):
    create = AsyncMock(side_effect=["folder-id", "first-id", RuntimeError("failed")])
    monkeypatch.setattr(b, "create_page", create)
    result = await w.appflowy_import(
        m.ImportInput(
            workspace_id="ws-allowed",
            parent_view_id="parent",
            entries=[
                m.Entry(path="Folder/one.md", markdown="one"),
                m.Entry(path="Folder/two.md", markdown="two"),
            ],
        )
    )
    assert result["ok"] is False
    assert result["entries"][0]["id"] == "first-id"
    assert create.await_args_list[1].args[1] == "folder-id"
    assert create.await_args_list[2].args[1] == "folder-id"


@pytest.mark.asyncio
async def test_custom_space_permissions_are_not_downgraded(monkeypatch):
    call = AsyncMock(side_effect=RuntimeError("404"))
    monkeypatch.setattr(w, "api", call)
    result = await w.appflowy_create_pages(
        m.CreateInput(
            workspace_id="ws-allowed",
            pages=[
                m.PageSpec(
                    kind="space",
                    name="Restricted",
                    permission=m.SpacePermission(
                        visibility="custom", member_default_access_level=None
                    ),
                )
            ],
        )
    )
    assert result["ok"] is False
    call.assert_awaited_once()
    assert call.call_args.kwargs["json"]["permission"]["visibility"] == "custom"


def database_doc():
    doc = Doc()
    with doc.transaction():
        doc.get("data", type=Map)["database"] = Map(
            {
                "fields": Map(
                    {
                        "formula": Map(
                            {"ty": 19, "type_option": Map({"19": Map({"format": 0})})}
                        ),
                        "date": Map({"ty": 2}),
                    }
                ),
                "views": Map(
                    {
                        "timeline": Map(
                            {
                                "layout": 8,
                                "layout_settings": Map(
                                    {"8": Map({"show_table": True})}
                                ),
                            }
                        )
                    }
                ),
            }
        )
    return doc


@pytest.mark.asyncio
async def test_formula_and_timeline_preserve_unrelated_settings(monkeypatch):
    doc = database_doc()
    database = doc.get("data", type=Map)["database"]
    monkeypatch.setattr(b, "_open_database", AsyncMock(return_value=(doc, database)))
    save = AsyncMock()
    monkeypatch.setattr(b, "_collab_web_update", save)
    await w.appflowy_database(
        m.DatabaseInput(
            workspace_id="ws-allowed",
            command="formula",
            database_id="db",
            field_id="formula",
            expression='prop("n") * 2',
        )
    )
    assert (
        database["fields"]["formula"]["type_option"]["19"]["expression"]
        == 'prop("n") * 2'
    )
    assert database["fields"]["formula"]["type_option"]["19"]["format"] == 0
    await w.appflowy_database(
        m.DatabaseInput(
            workspace_id="ws-allowed",
            command="timeline",
            database_id="db",
            view_id="timeline",
            settings={"field_id": "date", "layout_ty": 4},
        )
    )
    assert database["views"]["timeline"]["layout_settings"]["8"]["show_table"] is True
    assert save.await_count == 2


def test_decode_failure_is_actionable_and_never_returns_blank_doc():
    with pytest.raises(b.CollabDecodeError, match="no write was sent"):
        b._decode_collab(b"not-a-crdt-update", 1)


@pytest.mark.asyncio
async def test_async_requests_overlap_instead_of_blocking_loop(monkeypatch):
    active = maximum = 0

    async def handler(request):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={"code": 0, "data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(b, "_async_client", client)
        monkeypatch.setattr(b, "get_auth_headers_async", AsyncMock(return_value={}))
        await asyncio.gather(
            *(b._api_call_async("GET", "/api/workspace") for _ in range(3))
        )
    assert maximum == 3


@pytest.mark.asyncio
async def test_compact_tools_validate_on_modern_protocol(monkeypatch):
    monkeypatch.setenv("APPFLOWY_ENABLE_AI", "true")
    from mcp.server import MCPServer

    server = MCPServer("contract-test", version="2.0.0")
    w.register(server)
    async with Client(server, mode="2026-07-28") as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 12
        result = await client.call_tool(
            "appflowy_rows",
            {"request": {"command": "list", "database_id": "db", "limit": 0}},
        )
        assert result.is_error


def test_ai_answer_decoder_ignores_metadata_and_rejects_partial_stream():
    assert (
        w.decode_answer('{"0":[]}{"1":"Hello "}{"5":"searching"}{"1":"world"}')
        == "Hello world"
    )
    assert w.decode_answer('data: {"1":"Hello"}\n\ndata: [DONE]') == "Hello"
    with pytest.raises(RuntimeError, match="incomplete"):
        w.decode_answer('{"1":"unfinished')


@pytest.mark.asyncio
async def test_ai_empty_sources_never_expand_to_workspace(monkeypatch):
    monkeypatch.setenv("APPFLOWY_ENABLE_AI", "true")
    call = AsyncMock()
    monkeypatch.setattr(w, "api", call)
    await w.appflowy_ai(
        m.AIInput(workspace_id="ws-allowed", command="set_context", chat_id="chat")
    )
    assert call.call_args.kwargs["json"] == {
        "rag_ids": ["chat"],
        "full_workspace": False,
    }


@pytest.mark.asyncio
async def test_ai_failure_preserves_submitted_question_id(monkeypatch):
    monkeypatch.setenv("APPFLOWY_ENABLE_AI", "true")
    monkeypatch.setattr(w, "api", AsyncMock(side_effect=[{}, {"message_id": 123}]))
    monkeypatch.setattr(b, "get_auth_headers_async", AsyncMock(return_value={}))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        monkeypatch.setattr(b, "_async_client", client)
        result = await w.appflowy_ai(
            m.AIInput(
                workspace_id="ws-allowed",
                command="ask",
                chat_id="chat",
                question="Hello",
            )
        )
    assert result["partial"] and not result["ok"]
    assert result["question_id"] == 123
    assert "messages" in result["retry"]


@pytest.mark.asyncio
async def test_database_view_retries_only_explicit_rejected_admission(monkeypatch):
    monkeypatch.setattr(
        b,
        "get_page",
        AsyncMock(return_value={"view": {"extra": {"database_id": "db"}}}),
    )
    rejected = RuntimeError(
        "Failed to apply database update: Database dashboard admission for db changed; retry later"
    )
    post = AsyncMock(side_effect=[rejected, {"view_id": "new-view"}])
    monkeypatch.setattr(b, "_post", post)
    pause = AsyncMock()
    monkeypatch.setattr(b.asyncio, "sleep", pause)
    assert await b.create_database_view("ws-allowed", "view", "grid") == "new-view"
    assert post.await_count == 2 and pause.await_count == 1
    post.side_effect = RuntimeError("Request timed out; outcome unknown")
    post.reset_mock()
    with pytest.raises(RuntimeError, match="outcome unknown"):
        await b.create_database_view("ws-allowed", "view", "grid")
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_read_only_manifest_omits_mutation_commands(monkeypatch):
    from mcp.server import MCPServer

    monkeypatch.setenv("APPFLOWY_READ_ONLY", "true")
    server = MCPServer("read-test", version="2.0.0")
    w.register(server)
    tools = await server.list_tools()
    assert len(tools) == 5
    assert all(tool.annotations.read_only_hint for tool in tools)
    async with Client(server, mode="2026-07-28") as client:
        result = await client.call_tool(
            "appflowy_rows",
            {"request": {"command": "delete", "database_id": "db", "row_ids": ["row"]}},
        )
        assert result.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("installed", [True, False])
async def test_doctor_never_prints_credentials(monkeypatch, installed):
    from importlib.metadata import PackageNotFoundError

    from appflowy_mcp import diagnostics
    from appflowy_mcp.diagnostics import diagnose

    if not installed:
        original = diagnostics.version

        def source_version(name):
            if name == "appflowy-mcp-server":
                raise PackageNotFoundError(name)
            return original(name)

        monkeypatch.setattr(diagnostics, "version", source_version)
    monkeypatch.setenv("APPFLOWY_EMAIL", "fixture@example.com")
    monkeypatch.setenv("APPFLOWY_PASSWORD", "never-print-this-password")
    result = await diagnose()
    text = json.dumps(result)
    assert "never-print-this-password" not in text
    assert "fixture@example.com" not in text
    assert result["connection_checked"] is False
    if not installed:
        assert result["version"] == "development"
    assert any(
        item["name"] == "credentials_present" and item["ok"]
        for item in result["checks"]
    )


def test_cloud_ci_requires_both_explicit_opt_ins(monkeypatch):
    import live_compatibility

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("APPFLOWY_COMPAT_ALLOW_CI", "true")
    monkeypatch.delenv("APPFLOWY_COMPAT_DISPOSABLE_WORKSPACE", raising=False)
    with pytest.raises(SystemExit):
        live_compatibility._refuse_ci_without_explicit_opt_in()
    monkeypatch.setenv("APPFLOWY_COMPAT_DISPOSABLE_WORKSPACE", "true")
    live_compatibility._refuse_ci_without_explicit_opt_in()


@pytest.mark.asyncio
async def test_oauth_only_http_configuration_still_requires_auth(monkeypatch):
    provider = type(
        "Provider", (), {"load_access_token": AsyncMock(return_value=object())}
    )()
    monkeypatch.delenv("MCP_SECRET_TOKEN", raising=False)
    monkeypatch.setattr(b, "_oauth_provider", provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=b.app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/protected-test")).status_code == 401
        assert (
            await client.get(
                "/protected-test", headers={"Authorization": "Bearer valid-oauth"}
            )
        ).status_code != 401
    provider.load_access_token.assert_awaited_once_with("valid-oauth")
