"""Verify that AppFlowy Web renders content written through the MCP workflows."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APPFLOWY_BROWSER_TEST") != "true",
        reason="Disposable browser checks are opt-in",
    ),
]


async def test_web_renders_mcp_document_and_row(monkeypatch):
    from playwright.async_api import async_playwright, expect

    from appflowy_mcp import api as a
    from appflowy_mcp import models as m
    from appflowy_mcp import server as b
    from appflowy_mcp import workflows as w

    base = os.environ.get("APPFLOWY_SELFHOST_URL", "http://127.0.0.1:18080")
    assert urlsplit(base).hostname in {"localhost", "127.0.0.1"}
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        await client.post(
            base + "/gotrue/signup",
            json={"email": "mcp-bot@example.com", "password": "Disposable-test-2026!"},
        )
        response = await client.post(
            base + "/gotrue/token?grant_type=password",
            json={"email": "mcp-bot@example.com", "password": "Disposable-test-2026!"},
        )
        response.raise_for_status()
        auth = response.json()
        verification = await client.get(
            base + "/api/user/verify/" + auth["access_token"]
        )
        assert verification.json()["code"] == 0
        response = await client.get(
            base + "/api/workspace",
            headers={"Authorization": "Bearer " + auth["access_token"]},
        )
        ws = response.json()["data"][0]["workspace_id"]
    monkeypatch.setenv("APPFLOWY_ACCESS_TOKEN", auth["access_token"])
    monkeypatch.setenv("ALLOWED_WORKSPACE_IDS", ws)
    monkeypatch.delenv("APPFLOWY_READ_ONLY", raising=False)
    monkeypatch.setattr(a, "BASE_URL", base)
    await a._close_async_client()
    created, image = [], None
    try:
        folder = await b.get_workspace_folder(ws, 1)
        parent = next(
            item["view_id"] for item in folder["children"] if item.get("is_space")
        )
        document = await b.create_page(
            ws,
            parent,
            "MCP browser document",
            markdown="# Browser proof headline\n\nRendered **rich text**\n\n| Feature | State |\n| --- | --- |\n| Native table | **Visible** |",
        )
        created.append(document)
        uploaded = await w.appflowy_import(
            m.ImportInput(
                workspace_id=ws,
                parent_view_id=document,
                files=[
                    m.FileEntry(
                        name="browser-proof.png",
                        content_base64="iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGOoCLgERAwQCgArfgZp46x16AAAAABJRU5ErkJggg==",
                        append_image=True,
                    )
                ],
            )
        )
        assert uploaded["ok"], uploaded
        image = uploaded["files"][0]
        result = await w.appflowy_create_pages(
            m.CreateInput(
                workspace_id=ws,
                pages=[
                    m.PageSpec(
                        parent_view_id=parent,
                        kind="database",
                        name="MCP browser database",
                    )
                ],
            )
        )
        assert result["ok"], result
        database = result["items"][0]["result"]
        created.append(database["view_id"])
        fields = await b.get_database_fields(ws, database["database_id"])
        title = next(field["id"] for field in fields if field.get("is_primary"))
        db = database["database_id"]

        async def add_field(name, kind):
            result = await b.add_database_field(ws, db, name, kind)
            return (
                result.get("field_id", result.get("id"))
                if isinstance(result, dict)
                else result
            )

        number = await add_field("MCP Amount", 1)
        date = await add_field("MCP Due", 2)
        select = await add_field("MCP Status", 3)
        multi = await add_field("MCP Tags", 4)
        formula = await add_field("MCP Formula", 19)
        await b.add_select_option(ws, db, select, "MCP Doing", "Purple")
        await b.add_select_option(ws, db, select, "MCP Done", "Green")
        await b.add_select_option(ws, db, multi, "MCP Blue", "Blue")
        await b.add_select_option(ws, db, multi, "MCP Green", "Green")
        await w.appflowy_database(
            m.DatabaseInput(
                workspace_id=ws,
                command="formula",
                database_id=db,
                field_id=formula,
                expression="1 + 2",
            )
        )
        result = await w.appflowy_rows(
            m.RowsInput(
                workspace_id=ws,
                database_id=database["database_id"],
                command="create",
                rows=[
                    m.RowSpec(
                        cells={
                            title: "MCP browser visible row",
                            number: 42.5,
                            date: "2026-11-09T12:00:00Z",
                            select: "MCP Doing",
                            multi: ["MCP Blue", "MCP Green"],
                        }
                    )
                ],
            )
        )
        assert result["ok"], result
        row_id = result["items"][0]["result"]["row_id"]
        row = (await b._collab_doc(ws, row_id, 4)).get("data", type=b.Map)["data"]
        assert row["cells"][number]["data"] == "42.5"
        assert row["cells"][date]["data"] == "1794225600"
        assert row["cells"][date]["include_time"] is True
        _, schema = await b._open_database(ws, db)
        options = w.field_options(schema["fields"][multi].to_py())
        assert set(row["cells"][multi]["data"].split(",")) == {
            option["id"] for option in options
        }
        board = await b.create_database_view(
            ws, database["view_id"], "board", "MCP Board"
        )
        board_id = (
            board.get("view_id", board.get("id")) if isinstance(board, dict) else board
        )
        await b.set_group_by(ws, db, board_id, select)
        with pytest.raises(ValueError, match="dependencies.*groups"):
            await b.delete_database_field(ws, db, select)
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
                settings={"field_id": date, "layout_ty": 4, "show_table": True},
            )
        )
        _, persisted = await b._open_database(ws, database["database_id"])
        assert any(
            order["id"] == row_id
            for view in persisted["views"].values()
            for order in view["row_orders"]
        ), "Created row is absent from database view ordering"
        async with async_playwright() as playwright:
            launch = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if os.environ.get("APPFLOWY_TEST_CHROMIUM"):
                launch["executable_path"] = os.environ["APPFLOWY_TEST_CHROMIUM"]
            browser = await playwright.chromium.launch(**launch)
            try:
                context = await browser.new_context(
                    locale="en-US",
                    timezone_id="UTC",
                    viewport={"width": 1920, "height": 1080},
                )
                await context.add_init_script(
                    "localStorage.setItem('token', "
                    + json.dumps(json.dumps(auth))
                    + ");"
                )
                page = await context.new_page()
                await page.goto(
                    f"{base}/app/{ws}/{document}", wait_until="domcontentloaded"
                )
                await page.get_by_text(
                    "Browser proof headline", exact=True
                ).first.wait_for(timeout=45_000)
                table = page.locator('[data-block-type="simple_table"]')
                await expect(table).to_be_visible()
                await expect(
                    table.locator('td[data-block-type="simple_table_cell"]')
                ).to_have_count(4)
                await expect(table).to_contain_text("Native table")
                await expect(table.get_by_text("Visible", exact=True)).to_be_visible()
                rendered_image = page.locator('[data-block-type="image"] img')
                await rendered_image.scroll_into_view_if_needed()
                # AppFlowy fetches protected file URLs into browser blob URLs.
                await expect(rendered_image).to_be_visible()
                await expect(rendered_image).to_have_js_property("naturalWidth", 2)
                await page.goto(
                    f"{base}/app/{ws}/{database['view_id']}",
                    wait_until="domcontentloaded",
                )
                try:
                    await page.get_by_text(
                        "MCP browser visible row", exact=True
                    ).first.wait_for(timeout=45_000)
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{number}")
                    ).to_have_text("42.5")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{select}")
                    ).to_have_text("MCP Doing")
                    tags = page.get_by_test_id(f"grid-cell-{row_id}-{multi}")
                    await expect(tags).to_contain_text("MCP Blue")
                    await expect(tags).to_contain_text("MCP Green")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{date}")
                    ).to_have_text("11/09/2026 12:00 PM")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{formula}")
                    ).to_have_text("3")
                    updated = await w.appflowy_rows(
                        m.RowsInput(
                            workspace_id=ws,
                            database_id=db,
                            command="update_cells",
                            rows=[
                                m.RowSpec(
                                    row_id=row_id,
                                    cells={
                                        number: 43,
                                        select: "MCP Done",
                                        multi: ["MCP Green"],
                                        date: {
                                            "timestamp": 1794225600,
                                            "end_timestamp": 1794312000,
                                            "is_range": True,
                                            "include_time": False,
                                        },
                                    },
                                )
                            ],
                        )
                    )
                    assert updated["ok"], updated
                    row = (await b._collab_doc(ws, row_id, 4)).get("data", type=b.Map)[
                        "data"
                    ]
                    assert row["cells"][date]["end_timestamp"] == "1794312000"
                    assert row["cells"][date]["is_range"] is True
                    assert row["cells"][date]["include_time"] is False
                    await page.reload(wait_until="domcontentloaded")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{number}")
                    ).to_have_text("43")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{select}")
                    ).to_have_text("MCP Done")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{multi}")
                    ).to_have_text("MCP Green")
                    await expect(
                        page.get_by_test_id(f"grid-cell-{row_id}-{date}")
                    ).to_have_text("11/09/2026 → 11/10/2026")
                    await page.goto(
                        f"{base}/app/{ws}/{board_id}", wait_until="domcontentloaded"
                    )
                    column = page.get_by_test_id("board-column").filter(
                        has=page.get_by_text("MCP Done", exact=True)
                    )
                    await column.get_by_text(
                        "MCP browser visible row", exact=True
                    ).wait_for(timeout=45_000)
                    await page.goto(
                        f"{base}/app/{ws}/{timeline_id}", wait_until="domcontentloaded"
                    )
                    await page.get_by_test_id("timeline-toolbar").wait_for(
                        timeout=45_000
                    )
                    await page.get_by_test_id(f"timeline-row-{row_id}").wait_for()
                except Exception:
                    directory = Path(
                        os.environ.get(
                            "APPFLOWY_BROWSER_ARTIFACT_DIR", "/tmp/appflowy-browser"
                        )
                    )
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "body.txt").write_text(
                        await page.locator("body").inner_text()
                    )
                    await page.screenshot(path=str(directory / "view.png"))
                    raise
            finally:
                await browser.close()
    finally:
        if image is not None:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.delete(
                    image["url"], headers=await a.get_auth_headers_async()
                )
                response.raise_for_status()
        for page_id in reversed(created):
            await b.trash_page(ws, page_id)
        await a._close_async_client()
    output = os.environ.get("APPFLOWY_BROWSER_REPORT")
    if output:
        Path(output).write_text(
            json.dumps(
                {
                    "schema": "appflowy-mcp.browser-report.v1",
                    "deployment": {"cloud": "0.20.5", "web": "0.20.11"},
                    "checks": [
                        "document_rich_text",
                        "native_markdown_table",
                        "uploaded_image_loaded",
                        "number_create_update",
                        "datetime_create_range_update",
                        "select_labels_create_update",
                        "multiselect_labels_create_update",
                        "formula_evaluated_value",
                        "board_grouped_card",
                        "timeline_toolbar_and_row",
                    ],
                    "ok": True,
                    "credentials_recorded": False,
                },
                indent=2,
            )
            + "\n"
        )
