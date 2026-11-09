"""Deterministic configuration for offline tests, including selected-file runs."""

import os

import httpx
import pytest_asyncio

os.environ.setdefault("APPFLOWY_TOOL_PROFILE", "legacy")
os.environ.setdefault("MCP_SECRET_TOKEN", "test-secret-123")
os.environ.setdefault("ALLOWED_WORKSPACE_IDS", "ws-allowed")
os.environ.setdefault("MCP_ALLOWED_HOSTS", "testserver")


@pytest_asyncio.fixture
async def mock_appflowy_api(monkeypatch):
    """Install HTTP-level AppFlowy responses and close every created mock client."""
    from appflowy_mcp import api

    clients = []

    async def auth_headers():
        return {"Authorization": "Bearer x"}

    def install(handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        monkeypatch.setattr(api, "_async_client", client)
        monkeypatch.setattr(api, "get_auth_headers_async", auth_headers)

    yield install
    for client in clients:
        await client.aclose()
