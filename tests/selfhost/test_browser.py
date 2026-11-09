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
    from playwright.async_api import async_playwright

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
    monkeypatch.setattr(b, "BASE_URL", base)
    await b._close_async_client()
    created = []
    try:
        folder = await b.get_workspace_folder(ws, 1)
        parent = next(
            item["view_id"] for item in folder["children"] if item.get("is_space")
        )
        document = await b.create_page(
            ws,
            parent,
            "MCP browser document",
            markdown="# Browser proof headline\n\nRendered **rich text**",
        )
        created.append(document)
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
        result = await w.appflowy_rows(
            m.RowsInput(
                workspace_id=ws,
                database_id=database["database_id"],
                command="create",
                rows=[m.RowSpec(cells={title: "MCP browser visible row"})],
            )
        )
        assert result["ok"], result
        row_id = result["items"][0]["result"]["row_id"]
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
                context = await browser.new_context()
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
                await page.goto(
                    f"{base}/app/{ws}/{database['view_id']}",
                    wait_until="domcontentloaded",
                )
                try:
                    await page.get_by_text(
                        "MCP browser visible row", exact=True
                    ).first.wait_for(timeout=45_000)
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
                    await page.screenshot(path=str(directory / "grid.png"))
                    raise
            finally:
                await browser.close()
    finally:
        for page_id in reversed(created):
            await b.trash_page(ws, page_id)
        await b._close_async_client()
