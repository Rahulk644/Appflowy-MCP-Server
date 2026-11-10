"""Disposable local stack only. Run through scripts/selfhost.py, never on user data."""

import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APPFLOWY_SELFHOST_TEST") != "true",
        reason="Disposable self-hosted checks are opt-in",
    ),
]


async def test_disposable_workspace_lifecycle(monkeypatch, tmp_path):
    from appflowy_mcp import api as a
    from appflowy_mcp import models as m
    from appflowy_mcp import server as b
    from appflowy_mcp import workflows as w

    base = os.environ.get("APPFLOWY_SELFHOST_URL", "http://127.0.0.1:18080")
    assert urlsplit(base).hostname in {"localhost", "127.0.0.1"}, (
        "This suite only targets a disposable local stack"
    )
    credentials = {"email": "mcp-bot@example.com", "password": "Disposable-test-2026!"}
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        await client.post(base + "/gotrue/signup", json=credentials)
        response = await client.post(
            base + "/gotrue/token?grant_type=password", json=credentials
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        verification = await client.get(base + "/api/user/verify/" + token)
        verification.raise_for_status()
        assert verification.json()["code"] == 0
        response = await client.get(
            base + "/api/workspace", headers={"Authorization": "Bearer " + token}
        )
        response.raise_for_status()
        ws = response.json()["data"][0]["workspace_id"]
    monkeypatch.delenv("APPFLOWY_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("APPFLOWY_EMAIL", credentials["email"])
    monkeypatch.setenv("APPFLOWY_PASSWORD", credentials["password"])
    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", ws)
    monkeypatch.delenv("APPFLOWY_READ_ONLY", raising=False)
    monkeypatch.setattr(a, "BASE_URL", base)
    await a._close_async_client()
    checks, created = [], []
    completed = False
    search_token = "mcpsearch" + uuid4().hex
    search_startup_retries = 0

    def passed(name):
        checks.append({"name": name, "classification": "live_validated", "ok": True})

    try:
        for key, value in (
            ("_access_token", None),
            ("_refresh_token", None),
            ("_token_expires_at", 0),
        ):
            monkeypatch.setattr(a, key, value)
        await a._login_async()
        assert a._access_token and a._refresh_token

        async def reject_password_fallback():
            pytest.fail("The refresh grant must succeed without password re-login")

        # A successful password fallback must not masquerade as refresh evidence.
        with monkeypatch.context() as refresh_check:
            refresh_check.setattr(a, "_login_async", reject_password_fallback)
            await a._refresh_async()
            assert a._access_token and a._refresh_token
            assert any(item["workspace_id"] == ws for item in await b.get_workspaces())
        passed("password_login_and_token_refresh")
        from live_compatibility import CompatibilityConfig, run_compatibility_checks

        refresh_report = await run_compatibility_checks(
            CompatibilityConfig(
                deployment_type="disposable-self-hosted",
                version="0.20.5",
                build="",
                workspace_id=ws,
                database_id="",
                document_id="",
                parent_view_id="",
                validate_token_refresh=True,
            )
        )
        assert refresh_report["summary"] == {"passed": 3, "failed": 0, "skipped": 0}
        assert refresh_report["checks"][1]["properties"]["refresh_succeeded"] is True
        passed("operator_refresh_exact_token_readback")
        folder = await b.get_workspace_folder(ws, 2)
        parent = next(
            item["view_id"] for item in folder["children"] if item.get("is_space")
        )
        passed("workspace_and_folder")
        result = await w.appflowy_create_pages(
            m.CreateInput(
                workspace_id=ws,
                pages=[
                    m.PageSpec(
                        parent_view_id=parent,
                        name="MCP integration document",
                        markdown="# Contract test\n\nBefore **editing**",
                    )
                ],
            )
        )
        assert result["ok"], result
        document = result["items"][0]["result"]["view_id"]
        created.append(document)
        before = await b.get_page_markdown_async(ws, document)
        assert "Before **editing**" in before
        passed("document_create_and_markdown")
        await w.appflowy_update(
            m.UpdateInput(
                workspace_id=ws,
                command="append_comment",
                id=document,
                content="Document comment",
            )
        )
        comments = await w.appflowy_fetch(
            m.FetchInput(workspace_id=ws, kind="comments", id=document)
        )
        parent_comment = next(
            c["comment_id"]
            for c in comments["comments"]
            if c["content"] == "Document comment"
        )
        await w.appflowy_update(
            m.UpdateInput(
                workspace_id=ws,
                command="append_comment",
                id=document,
                content="Document reply",
                reply_comment_id=parent_comment,
            )
        )
        comments = await w.appflowy_fetch(
            m.FetchInput(workspace_id=ws, kind="comments", id=document, limit=1)
        )
        assert comments["has_more"] and len(comments["comments"]) == 1
        tail = await w.appflowy_fetch(
            m.FetchInput(
                workspace_id=ws,
                kind="comments",
                id=document,
                offset=comments["next_offset"],
            )
        )
        assert {c["content"] for c in comments["comments"] + tail["comments"]} == {
            "Document comment",
            "Document reply",
        }
        passed("document_comments_and_replies")
        await a._api_call(
            "POST",
            f"/api/workspace/{ws}/page-view/{document}/publish",
            json={"comments_enabled": True},
        )
        try:
            await b.append_comment(ws, document, "published", "Published comment")
            comments = await b.list_comments(ws, document, "published")
            parent_comment = next(
                c["comment_id"]
                for c in comments["comments"]
                if c["content"] == "Published comment"
            )
            await b.append_comment(
                ws,
                document,
                "published",
                "Published reply",
                reply_comment_id=parent_comment,
            )
            comments = await b.list_comments(ws, document, "published", limit=1)
            assert comments["has_more"]
            tail = await b.list_comments(
                ws, document, "published", offset=comments["next_offset"]
            )
            assert {c["content"] for c in comments["comments"] + tail["comments"]} == {
                "Published comment",
                "Published reply",
            }
            passed("published_comments_and_replies")
        finally:
            await a._api_call(
                "POST", f"/api/workspace/{ws}/page-view/{document}/unpublish"
            )
        await w.appflowy_blocks(
            m.BlocksInput(
                workspace_id=ws,
                page_id=document,
                command="replace_text",
                find="Before",
                replace="After",
            )
        )
        after = await b.get_page_markdown_async(ws, document)
        assert "After **editing**" in after
        passed("collab_document_edit_persistence")
        await w.appflowy_update(
            m.UpdateInput(
                workspace_id=ws,
                command="replace",
                id=document,
                markdown=f"# Replacement\n\nVerified {search_token}",
                expected_markdown=after,
            )
        )
        assert "Replacement" in await b.get_page_markdown_async(ws, document)
        passed("guarded_document_replacement")
        child = await b.create_page(
            ws,
            document,
            "MCP paged document",
            markdown="# Paged content\n\n" + "Chunk text. " * 4500,
        )
        subtree = await w.appflowy_fetch(
            m.FetchInput(
                workspace_id=ws,
                kind="workspace_folder",
                id=document,
                depth=1,
            )
        )
        assert subtree["data"]["view_id"] == document
        assert any(item["view_id"] == child for item in subtree["data"]["children"])
        passed("scoped_folder_read")
        first = await w.appflowy_export(
            m.ExportInput(workspace_id=ws, view_id=document, depth=1, limit=1)
        )
        assert first["entries"][0]["id"] == document
        assert first["next_offset"] == 1
        second = await w.appflowy_export(
            m.ExportInput(
                workspace_id=ws,
                view_id=document,
                depth=1,
                limit=1,
                offset=first["next_offset"],
            )
        )
        assert second["entries"] == []
        assert second["warnings"][0]["type"] == "document_requires_paging"
        assert second["next_offset"] is None
        passed("export_tree_page_cursor")
        request = second["warnings"][0]["continuation"]["request"]
        complete = await b.get_page_markdown_async(ws, child)
        chunks, content_hash = [], None
        while True:
            chunk = await w.appflowy_fetch(m.FetchInput(**request))
            assert chunk["id"] == child
            assert content_hash is None or chunk["content_hash"] == content_hash
            content_hash = chunk["content_hash"]
            chunks.append(chunk["data"]["markdown"])
            if not chunk["has_more"]:
                break
            assert chunk["next_offset"] > request["offset"]
            request["offset"] = chunk["next_offset"]
        assert len(chunks) > 1 and "".join(chunks) == complete
        passed("large_document_chunk_reassembly")
        payload = b"Disposable MCP upload verification\n"
        uploaded = await w.appflowy_import(
            m.ImportInput(
                workspace_id=ws,
                parent_view_id=document,
                files=[
                    m.FileEntry(
                        name="verification.txt",
                        content_type="text/plain",
                        content_base64=base64.b64encode(payload).decode(),
                    )
                ],
            )
        )
        assert uploaded["ok"], uploaded
        file = uploaded["files"][0]
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            downloaded = await client.get(
                file["url"], headers=await a.get_auth_headers_async()
            )
            downloaded.raise_for_status()
            assert downloaded.content == payload
            removed = await client.delete(
                file["url"], headers=await a.get_auth_headers_async()
            )
            removed.raise_for_status()
        passed("file_upload_download_and_cleanup")
        result = await w.appflowy_create_pages(
            m.CreateInput(
                workspace_id=ws,
                pages=[
                    m.PageSpec(
                        parent_view_id=parent,
                        kind="database",
                        name="MCP integration database",
                    )
                ],
            )
        )
        assert result["ok"], result
        database = result["items"][0]["result"]
        created.append(database["view_id"])
        db = database["database_id"]
        fields = await b.get_database_fields(ws, db)
        title = next(field for field in fields if field.get("is_primary"))["id"]
        done = next(field for field in fields if field.get("field_type_id") == 5)["id"]
        passed("database_creation_returns_both_ids")
        result = await w.appflowy_rows(
            m.RowsInput(
                workspace_id=ws,
                database_id=db,
                command="create",
                rows=[
                    m.RowSpec(
                        cells={title: "MCP integration row", done: True},
                        document="# Row notes\n\nBody content",
                    )
                ],
            )
        )
        assert result["ok"], result
        row_id = result["items"][0]["result"]["row_id"]
        row = await b._collab_doc(ws, row_id, 4)
        assert (
            row.get("data", type=b.Map)["data"]["cells"][title]["data"]
            == "MCP integration row"
        )
        passed("typed_row_create_and_readback")
        assert "Body content" in await b.get_page_markdown_async(ws, row_id)
        passed("row_document_markdown_readback")
        first_comment = await b.append_comment(ws, row_id, "row", "Card comment")
        reply = await b.append_comment(
            ws,
            row_id,
            "row",
            "Card reply",
            reply_comment_id=first_comment["comment_id"],
            database_view_id=database["view_id"],
        )
        comments = await b.list_comments(ws, row_id, "row", limit=1)
        assert comments["has_more"]
        tail = await b.list_comments(ws, row_id, "row", offset=comments["next_offset"])
        assert {c["comment_id"] for c in comments["comments"] + tail["comments"]} == {
            first_comment["comment_id"],
            reply["comment_id"],
        }
        assert (await b._collab_doc(ws, row_id, 4)).get("data", type=b.Map)["data"][
            "cells"
        ][title]["data"] == "MCP integration row"
        passed("row_comments_and_replies")
        result = await w.appflowy_rows(
            m.RowsInput(
                workspace_id=ws,
                database_id=db,
                command="update_cells",
                rows=[
                    m.RowSpec(
                        row_id=row_id, cells={title: "MCP updated row", done: False}
                    )
                ],
            )
        )
        assert result["ok"], result
        row = await b._collab_doc(ws, row_id, 4)
        assert row.get("data", type=b.Map)["data"]["cells"][done]["data"] == "No"
        assert {c["comment_id"] for c in b._row_comments(row)} == {
            first_comment["comment_id"],
            reply["comment_id"],
        }
        passed("typed_row_update_persistence")
        result = await w.appflowy_rows(
            m.RowsInput(workspace_id=ws, database_id=db, command="list", limit=1)
        )
        assert len(result["items"]) <= 1
        passed("bounded_row_listing")
        response = await a._api_call_async(
            "GET", f"/api/workspace/v1/{ws}/collab/{db}", params={"collab_type": 1}
        )
        snapshot = b._collab_doc_state(response.json())
        fixture_output = os.environ.get("APPFLOWY_FIXTURE_OUTPUT")
        if fixture_output:
            Path(fixture_output).write_bytes(snapshot)
        b._decode_collab(snapshot, 1)
        passed("database_collab_decode")
        added = await b.add_database_field(ws, db, "MCP Formula", 19)
        formula_id = (
            added.get("field_id", added.get("id")) if isinstance(added, dict) else added
        )
        await w.appflowy_database(
            m.DatabaseInput(
                workspace_id=ws,
                command="formula",
                database_id=db,
                field_id=formula_id,
                expression="1 + 2",
            )
        )
        _, current = await b._open_database(ws, db)
        assert (
            current["fields"][formula_id]["type_option"]["19"]["expression"] == "1 + 2"
        )
        passed("formula_expression_persistence")
        added = await b.add_database_field(ws, db, "MCP Date", 2)
        date_id = (
            added.get("field_id", added.get("id")) if isinstance(added, dict) else added
        )
        timeline = await b.create_database_view(
            ws, database["view_id"], "timeline", "MCP Timeline"
        )
        timeline_id = (
            timeline.get("view_id", timeline.get("id"))
            if isinstance(timeline, dict)
            else timeline
        )
        await w.appflowy_database(
            m.DatabaseInput(
                workspace_id=ws,
                command="timeline",
                database_id=db,
                view_id=timeline_id,
                settings={"field_id": date_id, "layout_ty": 4, "show_table": True},
            )
        )
        _, current = await b._open_database(ws, db)
        assert (
            current["views"][timeline_id]["layout_settings"]["8"]["field_id"] == date_id
        )
        passed("timeline_settings_persistence")
        with pytest.raises(ValueError, match="dependencies.*layout_settings"):
            await b.delete_database_field(ws, db, date_id)
        _, current = await b._open_database(ws, db)
        assert date_id in current["fields"]
        passed("field_deletion_rejects_timeline_dependency")
        spare = await b.add_database_field(ws, db, "MCP spare field", 0)
        spare_id = (
            spare.get("field_id", spare.get("id")) if isinstance(spare, dict) else spare
        )
        await b.delete_database_field(ws, db, spare_id)
        _, current = await b._open_database(ws, db)
        assert spare_id not in current["fields"]
        assert all(
            order["id"] != spare_id
            for view in current["views"].values()
            for order in view["field_orders"]
        )
        passed("unreferenced_field_delete_persistence")
        result = await w.appflowy_rows(
            m.RowsInput(
                workspace_id=ws, database_id=db, command="delete", row_ids=[row_id]
            )
        )
        assert result["ok"], result
        passed("row_delete_authoritative_cleanup")
        exported = await w.appflowy_export(
            m.ExportInput(workspace_id=ws, view_id=document)
        )
        assert "Replacement" in exported["entries"][0]["markdown"]
        passed("markdown_export")
        imported = await w.appflowy_import(
            m.ImportInput(
                workspace_id=ws,
                parent_view_id=document,
                entries=[
                    m.Entry(path="Imported/Notes.md", markdown="# Imported content")
                ],
            )
        )
        assert imported["ok"], imported
        assert "Imported content" in await b.get_page_markdown_async(
            ws, imported["entries"][0]["id"]
        )
        passed("markdown_tree_import_persistence")
        space = await w.appflowy_create_pages(
            m.CreateInput(
                workspace_id=ws,
                pages=[
                    m.PageSpec(
                        kind="space",
                        name="MCP private test space",
                        permission=m.SpacePermission(visibility="private"),
                    )
                ],
            )
        )
        assert space["ok"], space
        space_id = space["items"][0]["result"]["view_id"]
        created.append(space_id)
        permission = await w.appflowy_database(
            m.DatabaseInput(
                workspace_id=ws, command="space_permissions", view_id=space_id
            )
        )
        assert permission["permission"]["visibility"] == "private"
        passed("structured_space_permissions")
        await w.appflowy_update(
            m.UpdateInput(
                workspace_id=ws,
                id=space_id,
                command="space_permissions",
                permission=m.SpacePermission(
                    visibility="custom", member_default_access_level=None
                ),
            )
        )
        permission = await w.appflowy_database(
            m.DatabaseInput(
                workspace_id=ws, command="space_permissions", view_id=space_id
            )
        )
        assert permission["permission"]["visibility"] == "custom"
        assert permission["permission"]["member_default_access_level"] is None
        passed("custom_space_permissions_persistence")
        # Keyword indexing is asynchronous; only successful hits establish persistence.
        import asyncio

        for _ in range(120):
            try:
                search = await w.appflowy_search(
                    m.SearchInput(workspace_id=ws, query=search_token, limit=1)
                )
            except RuntimeError as exc:
                # HTTP health can precede the pinned stack's search admission.
                # Retry only its explicit temporary-unavailable application code.
                if not str(exc).startswith("AppFlowy API code 1054:"):
                    raise
                search_startup_retries += 1
            else:
                if search["items"]:
                    assert len(search["items"]) == 1
                    assert search["items"][0]["object_id"] == document
                    assert "has_more" in search
                    passed("keyword_search_pagination")
                    break
            await asyncio.sleep(1)
        else:
            pytest.fail("Keyword indexing did not return the disposable documents")
        completed = True
    except Exception as exc:
        checks.append(
            {
                "name": "lifecycle",
                "classification": "failed",
                "ok": False,
                "error_type": type(exc).__name__,
            }
        )
        raise
    finally:
        cleanup_failures = 0
        for view_id in reversed(created):
            try:
                await b.trash_page(ws, view_id)
            except (ValueError, RuntimeError) as exc:
                cleanup_failures += 1
                checks.append(
                    {
                        "name": "disposable_cleanup",
                        "classification": "failed",
                        "ok": False,
                        "error_type": type(exc).__name__,
                    }
                )
        await a._close_async_client()
        report = {
            "schema": "appflowy-mcp.integration-report.v1",
            "deployment": {
                "type": "disposable-self-hosted",
                "version": "0.20.5",
                "source_commit": "0796497ebe36d569734fb8eb559f28264d86605c",
            },
            "checks": checks,
            "passed": sum(item["ok"] for item in checks),
            "failed": sum(not item["ok"] for item in checks),
            "ok": completed and not cleanup_failures,
            "credentials_recorded": False,
            "search_startup_retries": search_startup_retries,
        }
        destination = Path(
            os.environ.get(
                "APPFLOWY_INTEGRATION_REPORT", str(tmp_path / "integration.json")
            )
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n")
        if completed and cleanup_failures:
            pytest.fail("Disposable resource cleanup did not complete")
