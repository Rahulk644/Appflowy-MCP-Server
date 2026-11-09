"""Invalid mixed commands must fail before they can write partial user intent."""

from unittest.mock import AsyncMock

import pytest
from mcp import Client
from mcp.server import MCPServer
from pydantic import ValidationError

from appflowy_mcp import models as m
from appflowy_mcp import server as b
from appflowy_mcp import workflows as w


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (m.FetchInput, {"database_id": "db"}, "database_id"),
        (m.FetchInput, {"kind": "page", "id": "page", "depth": 3}, "depth"),
        (
            m.FetchInput,
            {"kind": "database_fields", "database_id": "one", "id": "two"},
            "different databases",
        ),
        (
            m.AIInput,
            {
                "command": "create_chat",
                "parent_view_id": "parent",
                "question": "Do not lose this",
            },
            "question",
        ),
        (
            m.AIInput,
            {"command": "messages", "chat_id": "chat", "full_workspace": True},
            "full_workspace",
        ),
        (
            m.PageSpec,
            {"name": "Table", "kind": "database", "markdown": "Important content"},
            "markdown",
        ),
        (
            m.PageSpec,
            {"name": "Space", "kind": "space", "parent_view_id": "parent"},
            "parent_view_id",
        ),
        (m.PageSpec, {"name": "Document", "layout": "board"}, "layout"),
        (
            m.UpdateInput,
            {"command": "rename", "id": "page", "name": "New", "markdown": "Content"},
            "markdown",
        ),
        (
            m.UpdateInput,
            {
                "command": "append",
                "id": "page",
                "markdown": "Content",
                "expected_markdown": "old",
            },
            "expected_markdown",
        ),
        (
            m.DeleteInput,
            {"kind": "page", "id": "page", "database_id": "db"},
            "database_id",
        ),
        (
            m.DatabaseInput,
            {
                "command": "update_field",
                "database_id": "db",
                "field_id": "field",
                "field_type": 2,
            },
            "field_type",
        ),
        (
            m.DatabaseInput,
            {
                "command": "formula",
                "database_id": "db",
                "field_id": "field",
                "expression": "1",
                "settings": {"format": 0},
            },
            "settings",
        ),
        (
            m.RowsInput,
            {
                "command": "update_cells",
                "database_id": "db",
                "rows": [
                    {
                        "row_id": "row",
                        "cells": {"title": "new"},
                        "document": "Keep this text",
                    }
                ],
            },
            "document",
        ),
        (
            m.RowsInput,
            {
                "command": "create",
                "database_id": "db",
                "rows": [{"row_id": "existing", "cells": {"title": "new"}}],
            },
            "row_id",
        ),
        (
            m.RowsInput,
            {
                "command": "create",
                "database_id": "db",
                "rows": [{"pre_hash": "deduplicate-me"}],
            },
            "pre_hash",
        ),
        (
            m.RowsInput,
            {
                "command": "get",
                "database_id": "db",
                "row_ids": ["row"],
                "rows": [{"document": "Content"}],
            },
            "rows",
        ),
        (
            m.RowsInput,
            {
                "command": "delete",
                "database_id": "db",
                "row_ids": ["row"],
                "with_doc": True,
            },
            "with_doc",
        ),
        (
            m.ReadRowsInput,
            {"command": "list", "database_id": "db", "after": "2026-11-09"},
            "after",
        ),
        (
            m.ReadDatabaseInput,
            {
                "command": "view_settings",
                "database_id": "db",
                "view_id": "view",
                "response_format": "markdown",
            },
            "response_format",
        ),
        (
            m.BlocksInput,
            {
                "command": "add",
                "page_id": "page",
                "block_type": "paragraph",
                "text": "one",
                "markdown": "two",
            },
            "markdown",
        ),
        (
            m.BlocksInput,
            {"command": "add", "page_id": "page", "text": "Content without block type"},
            "text",
        ),
        (
            m.BlocksInput,
            {
                "command": "delete",
                "page_id": "page",
                "block_id": "block",
                "replace_all": True,
            },
            "replace_all",
        ),
    ],
)
def test_rejects_inputs_the_command_cannot_apply(model, payload, field):
    with pytest.raises(ValidationError, match=field):
        model(**payload)


def test_explicit_optional_defaults_are_accepted():
    m.PageSpec(
        name="Space", kind="space", parent_view_id="", layout="grid", markdown=""
    )
    m.RowsInput(
        command="delete",
        database_id="db",
        row_ids=["row"],
        rows=[],
        with_doc=False,
        limit=50,
    )
    m.BlocksInput(command="edit", page_id="page", block_id="block", text="")
    m.UpdateInput(
        command="replace", id="page", markdown="", expected_markdown="old content"
    )


@pytest.mark.asyncio
async def test_mixed_batch_is_rejected_over_mcp_before_any_page_is_created(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(b, "create_page", create)
    server = MCPServer("input-contract")
    w.register(server)
    async with Client(server, mode="2026-07-28") as client:
        result = await client.call_tool(
            "appflowy_create_pages",
            {
                "request": {
                    "workspace_id": "ws-allowed",
                    "pages": [
                        {"name": "Valid", "parent_view_id": "parent"},
                        {
                            "name": "Invalid",
                            "parent_view_id": "parent",
                            "kind": "database",
                            "markdown": "Must not disappear",
                        },
                    ],
                }
            },
        )
    assert result.is_error
    assert "markdown" in str(result)
    create.assert_not_called()
