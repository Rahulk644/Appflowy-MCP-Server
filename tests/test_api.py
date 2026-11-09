"""AppFlowy HTTP errors, session reuse, concurrent login and workspace policy."""

import httpx
import pytest

from appflowy_mcp import api as a

_PRISTINE_HTTPX_ASYNC_CLIENT = httpx.AsyncClient


def test_workspace_guard_blocks_other_workspaces():
    a._require_workspace("ws-allowed")  # allowed -> no raise
    with pytest.raises(ValueError):
        a._require_workspace("ws-other")


def test_workspace_guard_unrestricted_when_unset(monkeypatch):
    monkeypatch.delenv("ALLOWED_WORKSPACE_IDS", raising=False)
    assert a._allowed_workspaces() is None
    a._require_workspace("anything")  # unrestricted -> no raise


@pytest.mark.asyncio
async def test_api_call_actionable_error(monkeypatch, mock_appflowy_api):
    # A non-2xx from AppFlowy must surface as a specific, agent-readable message
    # (not a bare traceback), with a hint about what to fix.
    import httpx

    def handler(_request):
        return httpx.Response(404, text="object not found")

    mock_appflowy_api(handler)

    with pytest.raises(RuntimeError) as ei:
        (await a._api_call("GET", "/api/workspace/x/database/y/fields"))
    msg = str(ei.value)
    assert "AppFlowy API 404" in msg
    assert "database_id" in msg  # the 404 hint steers toward list_databases
    assert "object not found" in msg  # includes the server's own words


@pytest.mark.asyncio
async def test_api_call_rejects_application_error_inside_http_200(
    monkeypatch, mock_appflowy_api
):
    import httpx

    def handler(_request):
        return httpx.Response(
            200,
            json={
                "code": 1012,
                "message": "permission target was not found",
            },
        )

    mock_appflowy_api(handler)
    with pytest.raises(RuntimeError, match="AppFlowy API code 1012") as ei:
        (await a._api_call("POST", "/api/workspace/w/database/v/row", json={}))
    assert "database_id" in str(ei.value)
    assert "permission target was not found" in str(ei.value)


@pytest.mark.asyncio
async def test_api_call_accepts_success_envelope_and_empty_response(
    monkeypatch, mock_appflowy_api
):
    import httpx

    def handler(request):
        if request.url.path.endswith("/row"):
            return httpx.Response(200, json={"code": 0, "data": "row-1"})
        return httpx.Response(204)

    mock_appflowy_api(handler)
    assert (await a._post("/api/workspace/w/database/d/row", {})) == "row-1"
    assert (
        await a._api_call("POST", "/api/workspace/w/collab/d/web-update")
    ).status_code == 204


def test_api_call_works_inside_running_event_loop(monkeypatch, mock_appflowy_api):
    import asyncio

    import httpx

    def handler(_request):
        return httpx.Response(204)

    mock_appflowy_api(handler)

    async def run_inside_loop():
        return await a._api_call("POST", "/api/workspace/w/collab/d/web-update")

    assert asyncio.run(run_inside_loop()).status_code == 204


def test_async_auth_headers_serializes_concurrent_login(monkeypatch):
    import asyncio

    monkeypatch.setattr(a, "_access_token", None)
    monkeypatch.setattr(a, "_refresh_token", None)
    monkeypatch.setattr(a, "_token_expires_at", 0)
    calls = {"login": 0}

    async def fake_login():
        calls["login"] += 1
        await asyncio.sleep(0)
        a._access_token = "token"
        a._refresh_token = "refresh"
        a._token_expires_at = a.time.time() + 3600

    monkeypatch.setattr(a, "_login_async", fake_login)

    async def concurrent_headers():
        return await asyncio.gather(*(a.get_auth_headers_async() for _ in range(5)))

    headers = asyncio.run(concurrent_headers())

    assert calls["login"] == 1
    assert {header["Authorization"] for header in headers} == {"Bearer token"}


def test_async_api_call_reuses_shared_client(monkeypatch):
    import asyncio

    import httpx

    monkeypatch.setattr(a, "_async_client", None)
    created = {"count": 0}

    def handler(_request):
        return httpx.Response(204)

    real_async_client = _PRISTINE_HTTPX_ASYNC_CLIENT

    def fake_async_client(**_kwargs):
        created["count"] += 1
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(a.httpx, "AsyncClient", fake_async_client)

    async def auth_headers():
        return {"Authorization": "Bearer x"}

    monkeypatch.setattr(a, "get_auth_headers_async", auth_headers)

    async def call_twice():
        first = await a._api_call_async("POST", "/api/workspace/w/collab/d/web-update")
        second = await a._api_call_async("POST", "/api/workspace/w/collab/d/web-update")
        await a._close_async_client()
        return first.status_code, second.status_code

    assert asyncio.run(call_twice()) == (204, 204)
    assert created["count"] == 1
