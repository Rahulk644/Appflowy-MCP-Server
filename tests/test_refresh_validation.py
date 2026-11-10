"""Operator refresh evidence must use the exact grant, even inside the expiry buffer."""

import pytest

from appflowy_mcp import api as a


def test_live_compatibility_token_refresh_is_explicit_and_sanitized(monkeypatch):
    import asyncio
    import json

    import live_compatibility

    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class FakeRefreshResponse:
        status_code = 200

        def json(self):
            return {
                "access_token": "new-private-access-token",
                "refresh_token": "new-private-refresh-token",
                "expires_in": 30,
            }

    class FakeClient:
        async def post(self, url, json, headers):
            assert url.endswith("/gotrue/token?grant_type=refresh_token")
            assert json == {"refresh_token": "old-private-refresh-token"}
            assert "Authorization" not in headers
            return FakeRefreshResponse()

        async def request(self, method, url, headers, **kwargs):
            calls.append((method, url.removeprefix(a.BASE_URL), kwargs))
            assert method == "GET"
            assert url == f"{a.BASE_URL}/api/workspace"
            assert headers["Authorization"] == "Bearer new-private-access-token"
            assert a._token_expires_at < a.time.time()
            return FakeResponse()

    async def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        assert path == "/api/workspace"
        return FakeResponse()

    async def fake_get_async_client():
        return FakeClient()

    async def fail_auth_headers():
        raise AssertionError("Pinned follow-up must not use authentication fallback")

    monkeypatch.setattr(a, "_api_call_async", fake_api_call)
    monkeypatch.setattr(a, "_get_async_client", fake_get_async_client)
    monkeypatch.setattr(a, "get_auth_headers_async", fail_auth_headers)
    monkeypatch.setattr(a, "_access_token", "old-private-access-token")
    monkeypatch.setattr(a, "_refresh_token", "old-private-refresh-token")
    monkeypatch.setattr(a, "_token_expires_at", 0)

    report = asyncio.run(
        live_compatibility.run_compatibility_checks(
            live_compatibility.CompatibilityConfig(
                deployment_type="self-hosted-docker",
                version="24.04",
                build="revision",
                workspace_id="",
                database_id="",
                document_id="",
                parent_view_id="",
                validate_token_refresh=True,
            )
        )
    )

    assert report["summary"] == {"passed": 3, "failed": 0, "skipped": 0}
    assert report["checks"][1]["properties"]["refresh_succeeded"] is True
    assert report["checks"][1]["properties"]["access_token_rotated"] is True
    assert report["modes"]["token_refresh_validation_enabled"] is True
    assert [check["name"] for check in report["checks"][:3]] == [
        "auth_and_workspace_listing",
        "auth_token_refresh",
        "auth_after_token_refresh",
    ]
    assert [path for _, path, _ in calls] == ["/api/workspace", "/api/workspace"]
    encoded = json.dumps(report)
    assert "old-private" not in encoded
    assert "new-private" not in encoded


def test_async_refresh_reports_gotrue_success_without_exposing_tokens(monkeypatch):
    import asyncio

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }

    class FakeClient:
        async def post(self, url, json, headers):
            assert url.endswith("/gotrue/token?grant_type=refresh_token")
            assert json == {"refresh_token": "old-refresh"}
            assert "Authorization" not in headers
            return FakeResponse()

    async def fake_get_async_client():
        return FakeClient()

    monkeypatch.setattr(a, "_access_token", "old-access")
    monkeypatch.setattr(a, "_refresh_token", "old-refresh")
    monkeypatch.setattr(a, "_token_expires_at", 0)
    monkeypatch.setattr(a, "_get_async_client", fake_get_async_client)

    assert asyncio.run(a._refresh_async()) is True
    assert a._access_token == "new-access"
    assert a._refresh_token == "new-refresh"
    assert a._token_expires_at > a.time.time()


def test_async_refresh_reports_password_login_fallback(monkeypatch):
    import asyncio

    class FakeResponse:
        status_code = 401

    class FakeClient:
        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    async def fake_get_async_client():
        return FakeClient()

    async def fake_login():
        a._access_token = "login-access"
        a._refresh_token = "login-refresh"
        a._token_expires_at = a.time.time() + 3600

    monkeypatch.setattr(a, "_access_token", "old-access")
    monkeypatch.setattr(a, "_refresh_token", "rejected-refresh")
    monkeypatch.setattr(a, "_get_async_client", fake_get_async_client)
    monkeypatch.setattr(a, "_login_async", fake_login)

    assert asyncio.run(a._refresh_async()) is False
    assert a._access_token == "login-access"


def test_refresh_and_reversible_modes_are_mutually_exclusive():
    import live_compatibility as live

    with pytest.raises(SystemExit):
        live.main(["--run-reversible", "--validate-token-refresh"])
    with pytest.raises(ValueError, match="Choose reversible"):
        live.CompatibilityConfig(
            "test",
            "test",
            "",
            "",
            "",
            "",
            "",
            run_reversible=True,
            validate_token_refresh=True,
        )


def test_refresh_mode_rejects_static_access_token_before_network(monkeypatch):
    from unittest.mock import AsyncMock

    import live_compatibility as live

    monkeypatch.setattr(live, "_refuse_ci_without_explicit_opt_in", lambda: None)
    monkeypatch.setenv("APPFLOWY_ACCESS_TOKEN", "private-static-token")
    run = AsyncMock()
    monkeypatch.setattr(live, "run_compatibility_checks", run)
    with pytest.raises(SystemExit, match="unset APPFLOWY_ACCESS_TOKEN"):
        live.main(["--validate-token-refresh"])
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_harness_closes_shared_client_on_failure(monkeypatch):
    import argparse
    from unittest.mock import AsyncMock

    import live_compatibility as live

    monkeypatch.setattr(live, "_refuse_ci_without_explicit_opt_in", lambda: None)
    monkeypatch.delenv("APPFLOWY_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(
        live,
        "run_compatibility_checks",
        AsyncMock(side_effect=RuntimeError("request failed")),
    )
    close = AsyncMock()
    monkeypatch.setattr(a, "_close_async_client", close)
    with pytest.raises(RuntimeError):
        await live._main_async(
            argparse.Namespace(
                run_reversible=False, validate_token_refresh=True, output=None
            )
        )
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_refresh_does_not_claim_a_post_refresh_read(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    import httpx

    import live_compatibility as live

    initial = AsyncMock(return_value=httpx.Response(200, json={"data": []}))
    monkeypatch.setattr(a, "_api_call_async", initial)
    monkeypatch.setattr(a, "_refresh_token", "private-refresh")
    monkeypatch.setattr(a, "_access_token", "private-access")
    monkeypatch.setattr(a, "_refresh_async", AsyncMock(return_value=False))
    exact = AsyncMock()
    monkeypatch.setattr(live, "_api_json_with_access_token", exact)
    report = await live.run_compatibility_checks(
        live.CompatibilityConfig(
            "test", "test", "", "", "", "", "", validate_token_refresh=True
        )
    )
    assert report["summary"] == {"passed": 1, "failed": 1, "skipped": 0}
    exact.assert_not_awaited()
    assert "private-" not in json.dumps(report)
