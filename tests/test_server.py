"""Smoke tests for the security-critical logic: Bearer auth gate, workspace
guard, and that both HTTP transports boot cleanly."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server


def _database_doc_with_rows(*row_ids):
    from pycrdt import Array, Doc, Map

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["database"] = Map(
            {
                "views": Map(
                    {
                        "view-1": Map(
                            {
                                "row_orders": Array(
                                    [Map({"id": row_id}) for row_id in row_ids]
                                )
                            }
                        )
                    }
                )
            }
        )
    return doc


def test_agent_guide_resource():
    # The full guide is served as an MCP resource; the file must resolve + load.
    guide = server._agent_guide_md()
    assert "AppFlowy Agent Guide" in guide and "Coverage" in guide


def test_access_log_redacts_query_token():
    # The ?token= link method puts a working credential in the request line, which
    # uvicorn's access logger writes verbatim to stdout. Anything that can read
    # `docker logs` then has full access, so the secret must never reach the log.
    import logging

    f = server._RedactTokenFilter()

    rec = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        None,
        None,
    )
    rec.args = ("1.2.3.4:0", "POST", "/mcp/?token=supersecretvalue", "1.1", 200)
    f.filter(rec)
    assert "supersecretvalue" not in str(rec.args)
    assert "token=[REDACTED]" in str(rec.args)

    # Non-token args must pass through untouched.
    assert "/mcp/" in str(rec.args) and "POST" in str(rec.args)

    # Also scrubbed when the secret is baked into the message itself.
    rec2 = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        "GET /sse?token=abc123&x=1",
        None,
        None,
    )
    f.filter(rec2)
    assert "abc123" not in rec2.msg
    assert "x=1" in rec2.msg  # other query params are preserved


@pytest.mark.asyncio
async def test_collab_web_update_uses_reported_route(monkeypatch):
    from pycrdt import Doc

    calls = []
    doc = Doc()
    state_vector = doc.get_state()
    monkeypatch.setattr(
        server,
        "_api_call",
        _async_stub(
            lambda method, path, **kwargs: calls.append((method, path, kwargs))
        ),
    )

    (await server._collab_web_update("ws-1", "object-1", doc, state_vector, 4))

    assert calls[0][0:2] == (
        "POST",
        server._COLLAB_WEB_UPDATE_ROUTE.format(
            workspace_id="ws-1", object_id="object-1"
        ),
    )


def test_appflowy_export_single_page(monkeypatch):
    import asyncio

    async def fake_markdown(_workspace_id, _page_id):
        return "# Exported"

    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "page1"))

    assert out == {
        "entries": [{"path": "page1.md", "id": "page1", "markdown": "# Exported"}],
        "warnings": [],
        "warnings_truncated": False,
        "has_more": False,
    }


def test_appflowy_export_child_tree_with_warnings(monkeypatch):
    import asyncio

    tree = {
        "views": [
            {
                "view_id": "root",
                "name": "Root/Page",
                "children": [
                    {"view_id": "child", "name": "Child"},
                    {"view_id": "db", "name": "Database"},
                ],
            }
        ]
    }

    async def fake_folder(*_a, **_k):
        return tree

    async def fake_markdown(_workspace_id, page_id):
        if page_id == "db":
            raise RuntimeError("not a document")
        return f"# {page_id}"

    monkeypatch.setattr(server, "get_workspace_folder_async", fake_folder)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "root", depth=1))

    assert out["entries"] == [
        {"path": "Root-Page.md", "id": "root", "markdown": "# root"},
        {"path": "Root-Page/Child.md", "id": "child", "markdown": "# child"},
    ]
    assert out["warnings"][0]["id"] == "db"
    assert out["warnings"][0]["path"] == "Root-Page/Database.md"
    assert out["warnings"][0]["type"] == "document_unavailable"
    assert "not a document" not in str(out["warnings"][0])
    assert out["has_more"] is False


def test_appflowy_export_limit_sets_has_more(monkeypatch):
    import asyncio

    tree = {
        "views": [
            {
                "view_id": "root",
                "name": "Root",
                "children": [{"view_id": "child", "name": "Child"}],
            }
        ]
    }

    async def fake_folder(*_a, **_k):
        return tree

    async def fake_markdown(_workspace_id, page_id):
        return f"# {page_id}"

    monkeypatch.setattr(server, "get_workspace_folder_async", fake_folder)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "root", depth=1, limit=1))

    assert out["entries"] == [{"path": "Root.md", "id": "root", "markdown": "# root"}]
    assert out["has_more"] is True


def test_appflowy_export_warns_when_tree_cannot_locate_target(monkeypatch):
    import asyncio

    async def fake_folder(*_a, **_k):
        return {"views": []}

    async def fake_markdown(_workspace_id, page_id):
        return f"# {page_id}"

    monkeypatch.setattr(server, "get_workspace_folder_async", fake_folder)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "page1", depth=1))

    assert out["entries"] == [
        {"path": "page1.md", "id": "page1", "markdown": "# page1"}
    ]
    assert out["warnings"][0]["id"] == "page1"
    assert out["warnings"][0]["type"] == "target_not_found"


def test_appflowy_export_failed_child_consumes_limit(monkeypatch):
    import asyncio

    tree = {
        "views": [
            {
                "view_id": "root",
                "name": "Root",
                "children": [
                    {"view_id": "broken", "name": "Broken"},
                    {"view_id": "after", "name": "After"},
                ],
            }
        ]
    }

    async def fake_folder(*_a, **_k):
        return tree

    async def fake_markdown(_workspace_id, page_id):
        if page_id == "broken":
            raise RuntimeError("sensitive path /tmp/secret")
        return f"# {page_id}"

    monkeypatch.setattr(server, "get_workspace_folder_async", fake_folder)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "root", depth=1, limit=2))

    assert out["entries"] == [{"path": "Root.md", "id": "root", "markdown": "# root"}]
    assert out["warnings"] == [
        {
            "message": "page could not be exported as Markdown",
            "id": "broken",
            "path": "Root/Broken.md",
            "type": "document_unavailable",
        }
    ]
    assert out["has_more"] is True


def test_appflowy_export_does_not_queue_children_after_failed_parent(monkeypatch):
    import asyncio

    tree = {
        "views": [
            {
                "view_id": "root",
                "name": "Root",
                "children": [
                    {
                        "view_id": "broken",
                        "name": "Broken",
                        "children": [{"view_id": "grandchild", "name": "Grandchild"}],
                    }
                ],
            }
        ]
    }

    async def fake_folder(*_a, **_k):
        return tree

    async def fake_markdown(_workspace_id, page_id):
        if page_id == "broken":
            raise RuntimeError("not a document")
        if page_id == "grandchild":
            raise AssertionError("grandchild should not be exported")
        return f"# {page_id}"

    monkeypatch.setattr(server, "get_workspace_folder_async", fake_folder)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "root", depth=2))

    assert out["entries"] == [{"path": "Root.md", "id": "root", "markdown": "# root"}]
    assert [warning["id"] for warning in out["warnings"]] == ["broken"]


def test_appflowy_export_duplicate_sibling_paths_keep_child_subtrees(monkeypatch):
    import asyncio

    tree = {
        "views": [
            {
                "view_id": "root",
                "name": "Root",
                "children": [
                    {
                        "view_id": "same-1",
                        "name": "Same",
                        "children": [{"view_id": "child-1", "name": "Child"}],
                    },
                    {
                        "view_id": "same-2",
                        "name": "Same",
                        "children": [{"view_id": "child-2", "name": "Child"}],
                    },
                ],
            }
        ]
    }

    async def fake_folder(*_a, **_k):
        return tree

    async def fake_markdown(_workspace_id, page_id):
        return f"# {page_id}"

    monkeypatch.setattr(server, "get_workspace_folder_async", fake_folder)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    out = asyncio.run(server.appflowy_export("ws-allowed", "root", depth=2))

    assert [entry["path"] for entry in out["entries"]] == [
        "Root.md",
        "Root/Same.md",
        "Root/Same-2.md",
        "Root/Same/Child.md",
        "Root/Same-2/Child.md",
    ]


def test_appflowy_export_validates_bounds():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(
            server.appflowy_export(
                "ws-allowed", "page1", depth=server.APPFLOWY_EXPORT_MAX_DEPTH + 1
            )
        )
    with pytest.raises(ValueError):
        asyncio.run(
            server.appflowy_export(
                "ws-allowed", "page1", limit=server.APPFLOWY_EXPORT_MAX_LIMIT + 1
            )
        )


def test_live_compatibility_harness_read_only(monkeypatch):
    import asyncio

    import live_compatibility

    calls = []

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def json(self):
            return {"data": self._data}

    async def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/workspace":
            return FakeResponse([{"workspace_id": "ws-allowed", "name": "Workspace"}])
        if path == "/api/workspace/ws-allowed/folder":
            return FakeResponse(
                {
                    "views": [
                        {
                            "view_id": "page-1",
                            "name": "Doc",
                            "layout": 0,
                            "parent_view_id": "space-1",
                            "is_space": False,
                            "children": [],
                        }
                    ]
                }
            )
        if path == "/api/workspace/ws-allowed/database":
            return FakeResponse([{"database_id": "db-1", "name": "Database"}])
        if path == "/api/workspace/ws-allowed/database/db-1/fields":
            return FakeResponse([{"id": "field-1", "name": "Title"}])
        if path == "/api/workspace/ws-allowed/database/db-1/row":
            return FakeResponse(["row-1"])
        if path == "/api/workspace/ws-allowed/page-view/page-1":
            return FakeResponse({"view_id": "page-1", "name": "Doc"})
        raise AssertionError(f"unexpected route {method} {path}")

    async def fake_markdown(workspace_id, page_id):
        assert workspace_id == "ws-allowed"
        assert page_id == "page-1"
        return "# Doc"

    monkeypatch.setattr(server, "_api_call_async", fake_api_call)
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)

    report = asyncio.run(
        live_compatibility.run_compatibility_checks(
            live_compatibility.CompatibilityConfig(
                deployment_type="self-hosted-docker",
                version="0.18.5",
                build="revision",
                workspace_id="ws-allowed",
                database_id="",
                row_field_id="",
                document_id="",
                parent_view_id="",
            )
        )
    )

    assert report["schema"] == "appflowy-mcp.live-compatibility-report.v1"
    assert report["summary"] == {"passed": 7, "failed": 0, "skipped": 1}
    assert report["checks"][-1]["name"] == "reversible_create_read_trash"
    assert not any(call[0] == "POST" for call in calls)
    assert "revision" in str(report)
    assert "APPFLOWY_PASSWORD" not in str(report)


def test_live_compatibility_public_base_url_strips_private_parts(monkeypatch):
    import live_compatibility

    monkeypatch.setattr(
        server,
        "BASE_URL",
        "https://alice:secret@example.internal:8443/private/api?token=abc#frag",
    )

    assert live_compatibility._public_base_url() == "https://example.internal:8443"


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://[::1]/private?token=abc#frag", "http://[::1]"),
        (
            "https://alice:secret@[2001:db8::1]:8443/private?token=abc#frag",
            "https://[2001:db8::1]:8443",
        ),
    ],
)
def test_live_compatibility_public_base_url_preserves_ipv6_brackets(
    monkeypatch, base_url, expected
):
    import live_compatibility

    monkeypatch.setattr(server, "BASE_URL", base_url)

    assert live_compatibility._public_base_url() == expected


def test_live_compatibility_sanitizes_errors_without_raw_text(monkeypatch):
    import json

    import live_compatibility

    monkeypatch.setenv("APPFLOWY_EMAIL", "bot@example.com")
    monkeypatch.setenv("APPFLOWY_PASSWORD", "password-secret")
    monkeypatch.setenv(
        "APPFLOWY_BASE_URL", "https://alice:secret@example.internal/private/api"
    )

    error = live_compatibility._sanitize_error(
        RuntimeError(
            "AppFlowy API 502: unexpected AppFlowy API error. "
            "Server said: bot@example.com password-secret "
            "https://alice:secret@example.internal/private/api?token=abc "
            "private response body"
        )
    )
    encoded = json.dumps(error)

    assert error == {"type": "RuntimeError", "http_status": "502"}
    assert "bot@example.com" not in encoded
    assert "password-secret" not in encoded
    assert "alice:secret" not in encoded
    assert "token=abc" not in encoded
    assert "/private/api" not in encoded
    assert "private response body" not in encoded


def test_live_compatibility_failed_checks_are_not_live_validated():
    import asyncio

    import live_compatibility

    async def fail():
        raise RuntimeError("AppFlowy API code 1017: private server response")

    recorder = live_compatibility.CompatibilityRecorder()
    asyncio.run(
        recorder.record(
            name="failing_route",
            route="/api/workspace/{workspace_id}/page-view",
            operation=fail,
        )
    )

    check = recorder.checks[0]
    assert check["ok"] is False
    assert check["classification"] == live_compatibility.FAILED
    assert check["classification"] != live_compatibility.LIVE_VALIDATED
    assert check["evidence_basis"] == live_compatibility.CURRENT_WEB_OBSERVED
    assert check["error"] == {"type": "RuntimeError", "appflowy_code": "1017"}


def test_live_compatibility_document_discovery_ignores_folder_root():
    import live_compatibility

    folder = {
        "view_id": "workspace-root",
        "layout": 0,
        "parent_view_id": None,
        "is_space": False,
        "children": [
            {
                "view_id": "space",
                "layout": 0,
                "parent_view_id": "workspace-root",
                "is_space": True,
                "children": [
                    {
                        "view_id": "doc-page",
                        "layout": 0,
                        "parent_view_id": "space",
                        "is_space": False,
                        "children": [],
                    }
                ],
            },
        ],
    }

    assert live_compatibility._extract_document_id(folder, "") == "doc-page"


def test_live_compatibility_harness_reversible_flag(monkeypatch):
    import asyncio

    import live_compatibility

    calls = []

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def json(self):
            return {"data": self._data}

    async def fake_api_call(method, path, **kwargs):
        calls.append((method, path))
        if path == "/api/workspace":
            return FakeResponse([{"workspace_id": "ws-allowed"}])
        if path == "/api/workspace/ws-allowed/folder":
            return FakeResponse({"views": []})
        if path == "/api/workspace/ws-allowed/database":
            return FakeResponse([])
        if path == "/api/workspace/ws-allowed/page-view":
            return FakeResponse({"view_id": "created-page"})
        if path == "/api/workspace/ws-allowed/page-view/created-page":
            return FakeResponse({"view_id": "created-page"})
        if path == "/api/workspace/ws-allowed/page-view/created-page/move-to-trash":
            return FakeResponse("")
        raise AssertionError(f"unexpected route {method} {path}")

    monkeypatch.setattr(server, "_api_call_async", fake_api_call)
    monkeypatch.setattr(
        server,
        "replace_text",
        _async_stub(
            lambda workspace_id, page_id, find, replace: "replaced in 1 block(s)"
        ),
    )

    async def fake_verify_document_text(workspace_id, view_id, expected):
        return {"verified": True}

    monkeypatch.setattr(
        live_compatibility, "_verify_document_text", fake_verify_document_text
    )

    report = asyncio.run(
        live_compatibility.run_compatibility_checks(
            live_compatibility.CompatibilityConfig(
                deployment_type="self-hosted-docker",
                version="0.18.5",
                build="revision",
                workspace_id="ws-allowed",
                database_id="",
                row_field_id="",
                document_id="",
                parent_view_id="parent-page",
                run_reversible=True,
            )
        )
    )

    assert report["summary"]["failed"] == 0
    names = [check["name"] for check in report["checks"]]
    assert "reversible_page_create" in names
    assert "reversible_page_read" in names
    assert "reversible_collab_document_edit" in names
    assert "reversible_collab_document_verify" in names
    assert "reversible_page_trash" in names
    assert ("POST", "/api/workspace/ws-allowed/page-view") in calls


def test_live_compatibility_reversible_collab_and_row_checks(monkeypatch):
    import asyncio
    import json

    import live_compatibility

    calls = []

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def json(self):
            return {"data": self._data}

    async def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if path == "/api/workspace":
            return FakeResponse([{"workspace_id": "ws-allowed"}])
        if path == "/api/workspace/ws-allowed/folder":
            return FakeResponse({"views": []})
        if path == "/api/workspace/ws-allowed/database":
            return FakeResponse([{"database_id": "db-1"}])
        if path == "/api/workspace/ws-allowed/database/db-1/fields":
            return FakeResponse(
                [{"id": "field-1", "field_type": 0, "is_primary": True}]
            )
        if path == "/api/workspace/ws-allowed/database/db-1/row":
            if method == "POST":
                return FakeResponse("row-1")
            return FakeResponse([])
        if path == "/api/workspace/ws-allowed/page-view":
            return FakeResponse({"view_id": "created-page"})
        if path == "/api/workspace/ws-allowed/page-view/created-page":
            return FakeResponse({"view_id": "created-page"})
        if path == "/api/workspace/ws-allowed/page-view/created-page/move-to-trash":
            return FakeResponse("")
        raise AssertionError(f"unexpected route {method} {path}")

    def fake_replace_text(workspace_id, page_id, find, replace):
        calls.append(("COLLAB_DOCUMENT", page_id, (find, replace)))
        return "replaced in 1 block(s)"

    async def fake_markdown(workspace_id, page_id):
        return "compatibility-after-marker"

    def fake_update_row_cells(workspace_id, database_id, row_id, cells):
        calls.append(("COLLAB_ROW", row_id, json.loads(cells)))
        return row_id

    def fake_delete_row(workspace_id, database_id, row_id):
        calls.append(("DELETE_ROW", row_id, None))
        return {"row_id": row_id, "verified": True}

    async def fake_verify_document_text(workspace_id, view_id, expected):
        assert expected.startswith("compatibility-after-")
        return {"verified": True}

    monkeypatch.setattr(server, "_api_call_async", fake_api_call)
    monkeypatch.setattr(server, "replace_text", _async_stub(fake_replace_text))
    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)
    monkeypatch.setattr(server, "update_row_cells", _async_stub(fake_update_row_cells))
    monkeypatch.setattr(server, "_delete_row_strict", _async_stub(fake_delete_row))
    monkeypatch.setattr(
        live_compatibility, "_verify_document_text", fake_verify_document_text
    )

    report = asyncio.run(
        live_compatibility.run_compatibility_checks(
            live_compatibility.CompatibilityConfig(
                deployment_type="self-hosted-docker",
                version="0.18.5",
                build="revision",
                workspace_id="ws-allowed",
                database_id="db-1",
                row_field_id="",
                document_id="",
                parent_view_id="parent-page",
                run_reversible=True,
            )
        )
    )

    assert report["summary"]["failed"] == 0
    names = {check["name"] for check in report["checks"]}
    assert "reversible_collab_document_edit" in names
    assert "reversible_database_row_collab_edit" in names
    assert "reversible_database_row_delete" in names
    assert any(call[0] == "COLLAB_DOCUMENT" for call in calls)
    assert any(call[0] == "COLLAB_ROW" for call in calls)
    assert any(call[0] == "DELETE_ROW" for call in calls)

    write_routes = {
        check["route"]
        for check in report["checks"]
        if check["name"]
        in {"reversible_collab_document_edit", "reversible_database_row_collab_edit"}
    }
    assert write_routes == {
        "/api/workspace/v1/{workspace_id}/collab/{object_id}/web-update"
    }


def test_live_compatibility_row_cleanup_failure_is_reported(monkeypatch):
    import asyncio

    import live_compatibility

    recorder = live_compatibility.CompatibilityRecorder()

    monkeypatch.setattr(server, "update_row_cells", _async_stub(lambda *args: "row-1"))
    monkeypatch.setattr(
        server,
        "_delete_row_strict",
        _async_stub(
            lambda *args: (_ for _ in ()).throw(RuntimeError("AppFlowy API 403"))
        ),
    )
    monkeypatch.setattr(
        live_compatibility,
        "_api_json",
        lambda *args, **kwargs: asyncio.sleep(0, result={"row_id": "row-1"}),
    )

    asyncio.run(
        live_compatibility._run_reversible_row_check(
            recorder,
            live_compatibility.CompatibilityConfig(
                "self-hosted", "version", "build", "ws", "db", "", "parent"
            ),
            "ws",
            database_id="db",
            database_fields=[{"id": "field-1", "field_type": 0}],
            marker="marker",
        )
    )

    cleanup = next(
        check
        for check in recorder.checks
        if check["name"] == "reversible_database_row_delete"
    )
    assert cleanup["classification"] == live_compatibility.FAILED
    assert cleanup["ok"] is False
    assert cleanup["error"]["http_status"] == "403"


def test_live_compatibility_row_cleanup_runs_after_edit_failure(monkeypatch):
    import asyncio

    import live_compatibility

    recorder = live_compatibility.CompatibilityRecorder()
    cleanup_calls = []
    monkeypatch.setattr(
        server,
        "update_row_cells",
        _async_stub(lambda *args: (_ for _ in ()).throw(RuntimeError("edit failed"))),
    )
    monkeypatch.setattr(
        server,
        "_delete_row_strict",
        _async_stub(lambda *args: cleanup_calls.append(args) or {"verified": True}),
    )
    monkeypatch.setattr(
        live_compatibility,
        "_api_json",
        lambda *args, **kwargs: asyncio.sleep(0, result={"row_id": "row-1"}),
    )

    asyncio.run(
        live_compatibility._run_reversible_row_check(
            recorder,
            live_compatibility.CompatibilityConfig(
                "self-hosted", "version", "build", "ws", "db", "", "parent"
            ),
            "ws",
            database_id="db",
            database_fields=[{"id": "field-1", "field_type": 0}],
            marker="marker",
        )
    )

    assert cleanup_calls
    assert (
        next(
            check
            for check in recorder.checks
            if check["name"] == "reversible_database_row_collab_edit"
        )["classification"]
        == live_compatibility.FAILED
    )
    assert (
        next(
            check
            for check in recorder.checks
            if check["name"] == "reversible_database_row_delete"
        )["classification"]
        == live_compatibility.LIVE_VALIDATED
    )


@pytest.mark.asyncio
async def test_strict_row_cleanup_reports_rejected_collab_delete(monkeypatch):
    doc = _database_doc_with_rows("row-1")
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda *args: doc))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *args: None))

    def reject_delete(*args, **kwargs):
        raise RuntimeError("AppFlowy API 403")

    monkeypatch.setattr(server, "_api_call", _async_stub(reject_delete))

    with pytest.raises(RuntimeError, match="403"):
        (await server._delete_row_strict("ws-allowed", "db-1", "row-1"))


@pytest.mark.asyncio
async def test_strict_row_cleanup_reports_unsuccessful_view_removal(monkeypatch):
    before = _database_doc_with_rows("row-1")
    authoritative = _database_doc_with_rows("row-1")
    docs = iter((before, authoritative))
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda *args: next(docs)))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *args: None))
    delete_calls = []
    monkeypatch.setattr(
        server,
        "_api_call",
        _async_stub(lambda *args, **kwargs: delete_calls.append(args)),
    )

    with pytest.raises(RuntimeError, match="remained in database view order"):
        (await server._delete_row_strict("ws-allowed", "db-1", "row-1"))

    assert delete_calls == []


def test_live_compatibility_refuses_ci(monkeypatch):
    import live_compatibility

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("APPFLOWY_COMPAT_ALLOW_CI", "true")

    with pytest.raises(SystemExit, match="Refusing to run"):
        live_compatibility._refuse_ci_without_explicit_opt_in()


def test_live_compatibility_refuses_github_actions(monkeypatch):
    import live_compatibility

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    with pytest.raises(SystemExit, match="Refusing to run"):
        live_compatibility._refuse_ci_without_explicit_opt_in()


def test_workspace_guard_blocks_other_workspaces():
    server._require_workspace("ws-allowed")  # allowed -> no raise
    with pytest.raises(ValueError):
        server._require_workspace("ws-other")


def test_workspace_guard_unrestricted_when_unset(monkeypatch):
    monkeypatch.delenv("ALLOWED_WORKSPACE_IDS", raising=False)
    assert server._allowed_workspaces() is None
    server._require_workspace("anything")  # unrestricted -> no raise


def test_auth_middleware_and_transports_boot():
    # TestClient context manager runs lifespan -> proves the Streamable HTTP
    # session manager (and both mounts) start without error.
    with TestClient(server.app) as client:
        assert client.get("/robots.txt").status_code == 200  # always open
        assert client.get("/nope").status_code == 401  # no token
        assert (
            client.get("/nope", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )  # wrong token
        # correct token passes the auth gate (404 from routing, not 401)
        assert (
            client.get(
                "/nope", headers={"Authorization": "Bearer test-secret-123"}
            ).status_code
            == 404
        )
        # link method: token as ?token= query param
        assert client.get("/nope?token=test-secret-123").status_code == 404
        assert client.get("/nope?token=wrong").status_code == 401


def _synthetic_db_doc():
    """A database collab shaped like AppFlowy's: data.database.{fields,views}."""
    from pycrdt import Array, Doc, Map

    doc = Doc()
    data = doc.get("data", type=Map)
    with doc.transaction():
        data["database"] = Map(
            {
                "fields": Map(
                    {
                        "F1": Map({"id": "F1", "name": "Title", "is_primary": True}),
                        "F2": Map({"id": "F2", "name": "Status", "ty": 3}),
                    }
                ),
                "views": Map(
                    {
                        "V1": Map(
                            {
                                "field_orders": Array(
                                    [Map({"id": "F1"}), Map({"id": "F2"})]
                                ),
                                "field_settings": Map(
                                    {"F1": Map({"w": 1}), "F2": Map({"w": 2})}
                                ),
                            }
                        )
                    }
                ),
            }
        )
    return doc


@pytest.mark.asyncio
async def test_field_update_and_delete_mutate_collab(monkeypatch):
    # Exercise the real tools against a synthetic doc with the network stubbed out.
    from pycrdt import Map

    doc = _synthetic_db_doc()
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda ws, oid, ct: doc))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *a, **k: None))
    root = doc.get("data", type=Map)["database"]

    (await server.update_database_field("ws-allowed", "db", "F2", name="State"))
    assert root["fields"]["F2"]["name"] == "State"

    (await server.delete_database_field("ws-allowed", "db", "F2"))
    assert "F2" not in root["fields"]
    assert [o["id"] for o in list(root["views"]["V1"]["field_orders"])] == ["F1"]
    assert "F2" not in root["views"]["V1"]["field_settings"]

    with pytest.raises(ValueError):  # primary/title field is protected
        (await server.delete_database_field("ws-allowed", "db", "F1"))
    with pytest.raises(ValueError):  # unknown field id
        (await server.update_database_field("ws-allowed", "db", "NOPE", name="x"))


@pytest.mark.asyncio
async def test_select_option_add_and_delete(monkeypatch):
    # F2 is a SingleSelect (ty=3) with no options yet.
    import json

    from pycrdt import Map

    doc = _synthetic_db_doc()
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda ws, oid, ct: doc))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *a, **k: None))
    root = doc.get("data", type=Map)["database"]

    oid = await server.add_select_option(
        "ws-allowed", "db", "F2", "Blocked", color="Blue"
    )
    assert isinstance(oid, str) and len(oid) == 4
    assert (
        await server.add_select_option("ws-allowed", "db", "F2", "Blocked")
    ) == oid  # idempotent

    # Options persist as a JSON STRING under type_option["3"]["content"].
    data = json.loads(root["fields"]["F2"]["type_option"]["3"]["content"])
    assert [o["name"] for o in data["options"]] == ["Blocked"]
    assert data["options"][0]["color"] == "Blue"

    with pytest.raises(ValueError):  # bad color would wipe options in AppFlowy
        (await server.add_select_option("ws-allowed", "db", "F2", "X", color="Neon"))
    with pytest.raises(ValueError):  # F1 is not a select column
        (await server.add_select_option("ws-allowed", "db", "F1", "X"))

    assert (
        await server.delete_select_option("ws-allowed", "db", "F2", "Blocked")
    ) == oid
    data = json.loads(root["fields"]["F2"]["type_option"]["3"]["content"])
    assert data["options"] == []
    with pytest.raises(ValueError):  # no such option
        (await server.delete_select_option("ws-allowed", "db", "F2", "ghost"))


@pytest.mark.asyncio
async def test_set_group_by(monkeypatch):
    from pycrdt import Map

    doc = _synthetic_db_doc()
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda ws, oid, ct: doc))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *a, **k: None))
    root = doc.get("data", type=Map)["database"]

    oid = await server.add_select_option(
        "ws-allowed", "db", "F2", "Open"
    )  # F2 is SingleSelect
    assert (await server.set_group_by("ws-allowed", "db", "V1", "F2")) == "V1"

    gs = root["views"]["V1"]["groups"][0]
    assert gs["field_id"] == "F2" and gs["ty"] == 3
    # columns = the "no value" group (field_id) then one per option
    assert [g["id"] for g in list(gs["groups"])] == ["F2", oid]

    with pytest.raises(ValueError):  # unknown view
        (await server.set_group_by("ws-allowed", "db", "NOPE", "F2"))
    with pytest.raises(ValueError):  # unknown field
        (await server.set_group_by("ws-allowed", "db", "V1", "NOPE"))


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
async def test_update_row_cells_confirms_and_creates_new_cell(monkeypatch):
    from pycrdt import Map

    doc = _synthetic_row_doc()
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda ws, oid, ct: doc))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *a, **k: None))
    monkeypatch.setattr(server, "_field_types", _async_stub(lambda ws, db: {"F2": 3}))
    monkeypatch.setattr(server.asyncio, "sleep", _async_stub(lambda *_: None))

    out = await server.update_row_cells(
        "ws-allowed", "db", "row1", '{"F1": "new", "F2": "opt1"}'
    )
    assert out == "row1"
    cells = doc.get("data", type=Map)["data"]["cells"]
    assert cells["F1"]["data"] == "new"
    # a brand-new cell is tagged with the type from _field_types (the collab), not 0
    assert cells["F2"]["data"] == "opt1" and cells["F2"]["field_type"] == 3


@pytest.mark.asyncio
async def test_date_attributes_are_patched_and_confirmed_without_losing_metadata(
    monkeypatch,
):
    doc = _synthetic_row_doc()
    cells = doc.get("data", type=server.Map)["data"]["cells"]
    with doc.transaction():
        cells["F1"]["field_type"] = 2
        cells["F1"]["reminder_id"] = "keep-reminder"
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda *args: doc))
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *args: None))
    monkeypatch.setattr(
        server, "_field_types", _async_stub(lambda *args: {"F1": 2, "F2": 2})
    )
    patch = {
        "data": "1794225600",
        "end_timestamp": "",
        "include_time": True,
        "is_range": False,
    }
    await server.update_row_cells(
        "ws-allowed", "db", "row1", json.dumps({"F1": patch, "F2": patch})
    )
    for fid in ("F1", "F2"):
        assert all(cells[fid][key] == value for key, value in patch.items())
        assert cells[fid]["field_type"] == 2
    assert cells["F1"]["reminder_id"] == "keep-reminder"


@pytest.mark.asyncio
async def test_cell_attribute_object_cannot_modify_another_field_type(monkeypatch):
    monkeypatch.setattr(server, "_field_types", _async_stub(lambda *args: {"F1": 0}))
    update = AsyncMock()
    monkeypatch.setattr(server, "_collab_web_update", update)
    with pytest.raises(ValueError, match="only for DateTime"):
        await server.update_row_cells(
            "ws-allowed", "db", "row1", '{"F1": {"data": "10"}}'
        )
    update.assert_not_called()


@pytest.mark.asyncio
async def test_update_row_cells_raises_when_write_never_confirms(monkeypatch):
    from pycrdt import Map

    doc = _synthetic_row_doc()
    monkeypatch.setattr(server, "_collab_doc", _async_stub(lambda ws, oid, ct: doc))

    def revert(*a, **k):  # simulate a write that doesn't actually stick
        with doc.transaction():
            doc.get("data", type=Map)["data"]["cells"]["F1"]["data"] = "old"

    monkeypatch.setattr(server, "_collab_web_update", _async_stub(revert))
    monkeypatch.setattr(server.asyncio, "sleep", _async_stub(lambda *_: None))

    with pytest.raises(RuntimeError, match="did not confirm"):
        (await server.update_row_cells("ws-allowed", "db", "row1", '{"F1": "new"}'))


def _mock_http(monkeypatch, handler):
    """Point server httpx clients at a MockTransport and stub auth.

    NOTE: `server.httpx` IS the global httpx module, so patching `.Client` or
    `.AsyncClient` here is a global patch. Capture pristine classes before patching, or
    a second call in the same test would wrap the first mock instead of replacing it.
    """
    import httpx

    real_async_client = _PRISTINE_HTTPX_ASYNC_CLIENT
    monkeypatch.setattr(server, "_async_client", None)
    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda **k: real_async_client(transport=httpx.MockTransport(handler)),
    )

    async def auth_headers():
        return {"Authorization": "Bearer x"}

    monkeypatch.setattr(server, "get_auth_headers_async", auth_headers)


def _pristine_httpx_async_client():
    import httpx

    return httpx.AsyncClient


_PRISTINE_HTTPX_ASYNC_CLIENT = _pristine_httpx_async_client()


@pytest.mark.asyncio
async def test_is_database_row_discriminates_row_from_document(monkeypatch):
    # append_blocks routes on this: AppFlowy's page-view payload carries `row_data`
    # for a database row and `encoded_collab` for a document.
    import httpx

    def as_row(_request):
        return httpx.Response(200, json={"data": {"data": {"row_data": {}}}})

    _mock_http(monkeypatch, as_row)
    assert (await server._is_database_row("ws", "some-id")) is True

    def as_doc(_request):
        return httpx.Response(200, json={"data": {"data": {"encoded_collab": "..."}}})

    _mock_http(monkeypatch, as_doc)
    assert (await server._is_database_row("ws", "some-id")) is False

    # Flat shape (AppFlowy has moved this key around across releases).
    def as_row_flat(_request):
        return httpx.Response(200, json={"data": {"row_data": {}}})

    _mock_http(monkeypatch, as_row_flat)
    assert (await server._is_database_row("ws", "some-id")) is True


@pytest.mark.asyncio
async def test_is_database_row_never_raises(monkeypatch):
    # It only ever ADDS a fallback path, so an error must answer False and leave the
    # caller's existing behaviour untouched — never turn a probe into a failure.
    import httpx

    def boom(_request):
        return httpx.Response(500, text="upstream exploded")

    _mock_http(monkeypatch, boom)
    assert (await server._is_database_row("ws", "some-id")) is False


@pytest.mark.asyncio
async def test_append_blocks_reroutes_row_id_to_collab(monkeypatch):
    # The bug: AppFlowy's REST append-block accepts only a real page-view. Handed a
    # database ROW id it returns success and writes NOTHING, so folding a checklist
    # onto a Kanban card silently lost the content.
    calls = {}

    def fake_add_blocks(ws, pid, markdown="", blocks=""):
        calls["md"] = markdown
        calls["page_id"] = pid
        return "blk1"

    monkeypatch.setattr(server, "_require_workspace", lambda *_: None)
    monkeypatch.setattr(
        server, "_post", _async_stub(lambda *a, **k: "")
    )  # the silent no-op
    monkeypatch.setattr(server, "_is_database_row", _async_stub(lambda *_: True))
    monkeypatch.setattr(server, "add_blocks", _async_stub(fake_add_blocks))

    out = await server.append_blocks("ws", "row-id", markdown="- [ ] fold me")
    assert out == "blk1"  # delegated to the collab path
    assert calls["md"] == "- [ ] fold me"  # content carried across intact
    assert calls["page_id"] == "row-id"  # and aimed at the row, not the page


@pytest.mark.asyncio
async def test_append_blocks_leaves_document_path_untouched(monkeypatch):
    # Zero-regression guard: a normal page-view append must not gain an extra probe
    # or a second write just because the row fallback exists.
    seen = {"posts": 0, "probes": 0}

    def fake_post(*_a, **_k):
        seen["posts"] += 1
        return "ok-block-id"

    def fake_probe(*_a, **_k):
        seen["probes"] += 1
        return True

    monkeypatch.setattr(server, "_require_workspace", lambda *_: None)
    monkeypatch.setattr(server, "_post", _async_stub(fake_post))
    monkeypatch.setattr(server, "_is_database_row", _async_stub(fake_probe))

    assert (
        await server.append_blocks("ws", "page-id", markdown="hello")
    ) == "ok-block-id"
    assert seen["posts"] == 1  # exactly one write
    assert seen["probes"] == 0  # no extra round-trip on the happy path


@pytest.mark.asyncio
async def test_api_call_actionable_error(monkeypatch):
    # A non-2xx from AppFlowy must surface as a specific, agent-readable message
    # (not a bare traceback), with a hint about what to fix.
    import httpx

    def handler(_request):
        return httpx.Response(404, text="object not found")

    _mock_http(monkeypatch, handler)

    with pytest.raises(RuntimeError) as ei:
        (await server._api_call("GET", "/api/workspace/x/database/y/fields"))
    msg = str(ei.value)
    assert "AppFlowy API 404" in msg
    assert "database_id" in msg  # the 404 hint steers toward list_databases
    assert "object not found" in msg  # includes the server's own words


@pytest.mark.asyncio
async def test_api_call_rejects_application_error_inside_http_200(monkeypatch):
    import httpx

    def handler(_request):
        return httpx.Response(
            200,
            json={
                "code": 1012,
                "message": "permission target was not found",
            },
        )

    _mock_http(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="AppFlowy API code 1012") as ei:
        (await server._api_call("POST", "/api/workspace/w/database/v/row", json={}))
    assert "database_id" in str(ei.value)
    assert "permission target was not found" in str(ei.value)


@pytest.mark.asyncio
async def test_api_call_accepts_success_envelope_and_empty_response(monkeypatch):
    import httpx

    def handler(request):
        if request.url.path.endswith("/row"):
            return httpx.Response(200, json={"code": 0, "data": "row-1"})
        return httpx.Response(204)

    _mock_http(monkeypatch, handler)
    assert (await server._post("/api/workspace/w/database/d/row", {})) == "row-1"
    assert (
        await server._api_call("POST", "/api/workspace/w/collab/d/web-update")
    ).status_code == 204


def test_api_call_works_inside_running_event_loop(monkeypatch):
    import asyncio

    import httpx

    def handler(_request):
        return httpx.Response(204)

    _mock_http(monkeypatch, handler)

    async def run_inside_loop():
        return await server._api_call("POST", "/api/workspace/w/collab/d/web-update")

    assert asyncio.run(run_inside_loop()).status_code == 204


def test_async_auth_headers_serializes_concurrent_login(monkeypatch):
    import asyncio

    monkeypatch.setattr(server, "_access_token", None)
    monkeypatch.setattr(server, "_refresh_token", None)
    monkeypatch.setattr(server, "_token_expires_at", 0)
    calls = {"login": 0}

    async def fake_login():
        calls["login"] += 1
        await asyncio.sleep(0)
        server._access_token = "token"
        server._refresh_token = "refresh"
        server._token_expires_at = server.time.time() + 3600

    monkeypatch.setattr(server, "_login_async", fake_login)

    async def concurrent_headers():
        return await asyncio.gather(
            *(server.get_auth_headers_async() for _ in range(5))
        )

    headers = asyncio.run(concurrent_headers())

    assert calls["login"] == 1
    assert {header["Authorization"] for header in headers} == {"Bearer token"}


def test_async_api_call_reuses_shared_client(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setattr(server, "_async_client", None)
    created = {"count": 0}

    def handler(_request):
        return httpx.Response(204)

    real_async_client = _PRISTINE_HTTPX_ASYNC_CLIENT

    def fake_async_client(**_kwargs):
        created["count"] += 1
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(server.httpx, "AsyncClient", fake_async_client)

    async def auth_headers():
        return {"Authorization": "Bearer x"}

    monkeypatch.setattr(server, "get_auth_headers_async", auth_headers)

    async def call_twice():
        first = await server._api_call_async(
            "POST", "/api/workspace/w/collab/d/web-update"
        )
        second = await server._api_call_async(
            "POST", "/api/workspace/w/collab/d/web-update"
        )
        await server._close_async_client()
        return first.status_code, second.status_code

    assert asyncio.run(call_twice()) == (204, 204)
    assert created["count"] == 1


def test_stdio_runner_closes_async_client(monkeypatch):
    import asyncio

    calls = []

    async def fake_run_stdio_async():
        calls.append("run")

    async def fake_close_async_client():
        calls.append("close")

    monkeypatch.setattr(server.mcp, "run_stdio_async", fake_run_stdio_async)
    monkeypatch.setattr(server, "_close_async_client", fake_close_async_client)

    asyncio.run(server._run_stdio_with_lifecycle())

    assert calls == ["run", "close"]


def test_stdio_runner_closes_async_client_after_error(monkeypatch):
    import asyncio

    calls = []

    async def fake_run_stdio_async():
        calls.append("run")
        raise RuntimeError("boom")

    async def fake_close_async_client():
        calls.append("close")

    monkeypatch.setattr(server.mcp, "run_stdio_async", fake_run_stdio_async)
    monkeypatch.setattr(server, "_close_async_client", fake_close_async_client)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(server._run_stdio_with_lifecycle())

    assert calls == ["run", "close"]


def test_appflowy_fetch_self_filters_allowed_workspaces(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", "ws-allowed")

    def handler(request):
        assert request.url.path == "/api/workspace"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"workspace_id": "ws-allowed", "name": "Allowed"},
                    {"workspace_id": "ws-other", "name": "Other"},
                ]
            },
        )

    _mock_http(monkeypatch, handler)
    out = asyncio.run(server.appflowy_fetch(id="self"))

    assert out["kind"] == "workspaces"
    assert [w["workspace_id"] for w in out["data"]] == ["ws-allowed"]
    assert out["has_more"] is False
    assert out["total_count"] == 1


def test_appflowy_fetch_folder_infers_single_allowed_workspace(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", "ws-allowed")

    def handler(request):
        assert request.url.path == "/api/workspace/ws-allowed/folder"
        assert request.url.params["depth"] == "2"
        return httpx.Response(200, json={"data": {"views": [{"id": "page1"}]}})

    _mock_http(monkeypatch, handler)
    out = asyncio.run(server.appflowy_fetch(kind="workspace_folder", depth=2))

    assert out["kind"] == "workspace_folder"
    assert out["workspace_id"] == "ws-allowed"
    assert out["data"] == {"views": [{"id": "page1"}]}
    assert out["truncated"] is False
    assert out["nodes_visited"] == 2


def test_appflowy_fetch_page_json_and_markdown(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", "ws-allowed")

    def handler(request):
        assert request.url.path == "/api/workspace/ws-allowed/page-view/page1"
        return httpx.Response(200, json={"data": {"id": "page1", "name": "Page"}})

    _mock_http(monkeypatch, handler)
    json_out = asyncio.run(server.appflowy_fetch(id="page1", workspace_id="ws-allowed"))
    assert json_out["kind"] == "page"
    assert json_out["data"] == {"id": "page1", "name": "Page"}

    async def fake_markdown(workspace_id, page_id):
        assert (workspace_id, page_id) == ("ws-allowed", "page1")
        return "# Page"

    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)
    md = asyncio.run(
        server.appflowy_fetch(
            id="page1", workspace_id="ws-allowed", response_format="markdown"
        )
    )
    assert md["kind"] == "page"
    assert md["data"] == {"format": "markdown", "markdown": "# Page"}
    assert md["truncated"] is False
    assert md["total_chars"] == 6


def test_appflowy_fetch_database_fields(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", "ws-allowed")

    def handler(request):
        assert request.url.path == "/api/workspace/ws-allowed/database/db1/fields"
        return httpx.Response(200, json={"data": [{"id": "f1", "name": "Title"}]})

    _mock_http(monkeypatch, handler)
    out = asyncio.run(
        server.appflowy_fetch(
            kind="database_fields", workspace_id="ws-allowed", id="db1"
        )
    )

    assert out["kind"] == "database_fields"
    assert out["workspace_id"] == "ws-allowed"
    assert out["database_id"] == "db1"
    assert out["data"] == [{"id": "f1", "name": "Title"}]
    assert out["has_more"] is False


def test_appflowy_fetch_validates_input_bounds():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(server.appflowy_fetch(kind="invalid"))
    with pytest.raises(ValueError):
        asyncio.run(server.appflowy_fetch(kind="workspace_folder", depth=99))
    with pytest.raises(ValueError):
        asyncio.run(server.appflowy_fetch(limit=0))
    with pytest.raises(ValueError):
        asyncio.run(server.appflowy_fetch(max_folder_nodes=9999))


def test_appflowy_fetch_list_bounds_and_markdown_truncation(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", "ws-allowed")

    def handler(request):
        if request.url.path == "/api/workspace":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"workspace_id": "ws-allowed", "name": "One"},
                        {"workspace_id": "ws-allowed", "name": "Two"},
                        {"workspace_id": "ws-allowed", "name": "Three"},
                    ]
                },
            )
        raise AssertionError(request.url)

    _mock_http(monkeypatch, handler)
    out = asyncio.run(server.appflowy_fetch(id="self", limit=2, offset=1))

    assert [w["name"] for w in out["data"]] == ["Two", "Three"]
    assert out["total_count"] == 3
    assert out["has_more"] is False

    async def fake_markdown(_workspace_id, _page_id):
        return "abcdef"

    monkeypatch.setattr(server, "get_page_markdown_async", fake_markdown)
    md = asyncio.run(
        server.appflowy_fetch(
            id="page1",
            workspace_id="ws-allowed",
            response_format="markdown",
            max_markdown_chars=3,
        )
    )

    assert md["data"]["markdown"] == "abc"
    assert md["truncated"] is True
    assert md["total_chars"] == 6


@pytest.mark.asyncio
async def test_oauth_store_persists_across_instances(tmp_path):
    import time
    from types import SimpleNamespace

    from mcp.server.auth.provider import AuthorizationCode

    from google_oauth import GoogleOAuthProvider

    path = str(tmp_path / "oauth.json")
    p = GoogleOAuthProvider(
        "https://mcp.example.com", "cid", "sec", ["a@b.com"], store_path=path
    )
    code = AuthorizationCode(
        code="code",
        client_id="c1",
        scopes=["appflowy"],
        expires_at=time.time() + 300,
        code_challenge="challenge",
        redirect_uri="http://localhost/callback",
        redirect_uri_provided_explicitly=True,
        subject="a@b.com",
        resource=p.issuer,
    )
    p.codes[code.code] = code
    result = await p.exchange_authorization_code(SimpleNamespace(client_id="c1"), code)
    restarted = GoogleOAuthProvider(
        "https://mcp.example.com", "cid", "sec", ["a@b.com"], store_path=path
    )
    token = await restarted.load_access_token(result.access_token)
    assert token and token.client_id == "c1"


@pytest.mark.asyncio
async def test_replace_text(monkeypatch):
    from pycrdt import Array, Doc, Map, Text

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["document"] = Map(
            {
                "blocks": Map(),
                "meta": Map({"children_map": Map(), "text_map": Map()}),
                "page_id": "page",
            }
        )
        d = root["document"]
        blocks = d["blocks"]
        tmap = d["meta"]["text_map"]
        cmap = d["meta"]["children_map"]
        blocks["page"] = Map({"ty": "page", "children": "pc"})
        cmap["pc"] = Array(["p1", "p2"])
        tmap["t1"] = Text("hello world")
        blocks["p1"] = Map({"ty": "paragraph", "children": "c1", "external_id": "t1"})
        cmap["c1"] = Array([])
        tmap["t2"] = Text("goodbye world")
        blocks["p2"] = Map({"ty": "paragraph", "children": "c2", "external_id": "t2"})
        cmap["c2"] = Array([])

    monkeypatch.setattr(
        server,
        "_open_document",
        _async_stub(lambda ws, pid: (doc, pid, root["document"])),
    )
    monkeypatch.setattr(server, "_collab_web_update", _async_stub(lambda *a, **k: None))

    (await server.replace_text("ws-allowed", "page", "hello", "hi"))
    assert str(tmap["t1"]) == "hi world"
    with pytest.raises(ValueError):  # "world" is in two blocks
        (await server.replace_text("ws-allowed", "page", "world", "earth"))
    (
        await server.replace_text(
            "ws-allowed", "page", "world", "earth", replace_all=True
        )
    )
    assert str(tmap["t1"]) == "hi earth"
    assert str(tmap["t2"]) == "goodbye earth"
    with pytest.raises(ValueError):  # not found
        (await server.replace_text("ws-allowed", "page", "zzz", "x"))


@pytest.mark.asyncio
async def test_is_database_row_document_with_empty_row_data(monkeypatch):
    # A real document's page-view payload carries `row_data` too (as {}), next to its
    # encoded_collab. Taking that for a row made append_blocks write everything twice.
    import httpx

    def as_doc(_request):
        return httpx.Response(
            200, json={"data": {"data": {"encoded_collab": [1, 2], "row_data": {}}}}
        )

    _mock_http(monkeypatch, as_doc)
    assert (await server._is_database_row("ws", "some-id")) is False

    def as_row(_request):
        return httpx.Response(
            200, json={"data": {"data": {"row_data": {"id": "r1", "cells": {}}}}}
        )

    _mock_http(monkeypatch, as_row)
    assert (await server._is_database_row("ws", "some-id")) is True


@pytest.mark.asyncio
async def test_append_blocks_nested_goes_through_collab(monkeypatch):
    # AppFlowy's REST append-block reverses nested blocks (a table's rows and cells)
    # and reorders the blocks around them, so nested content takes the collab path.
    calls = {}

    def fake_add_blocks(ws, pid, markdown="", blocks=""):
        calls["blocks"] = blocks
        return "b1,b2"

    def no_post(*_a, **_k):
        raise AssertionError("REST append must not be used for nested blocks")

    monkeypatch.setattr(server, "_require_workspace", lambda *_: None)
    monkeypatch.setattr(server, "_post", _async_stub(no_post))
    monkeypatch.setattr(server, "add_blocks", _async_stub(fake_add_blocks))

    md = "Before\n\n- Parent\n  - Child\n"
    assert (await server.append_blocks("ws", "page-id", markdown=md)) == "b1,b2"
    import json

    assert [b["type"] for b in json.loads(calls["blocks"])] == [
        "paragraph",
        "bulleted_list",
    ]


def _async_stub(fn):
    async def invoke(*args, **kwargs):
        import inspect

        result = fn(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return invoke
