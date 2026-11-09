"""OAuth identity, refresh and persistence contracts without real Google credentials."""

import json
import os
import stat
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from appflowy_mcp import google_oauth as oauth


def provider(path=None, emails=("member@example.com",)):
    return oauth.GoogleOAuthProvider(
        "https://mcp.example.com",
        "client-id",
        "secret",
        emails,
        store_path=str(path) if path else None,
    )


def client():
    return OAuthClientInformationFull(
        client_id="client", redirect_uris=["http://localhost/callback"]
    )


@pytest.mark.asyncio
async def test_refresh_preserves_audience_and_honors_narrowed_scopes():
    p = provider()
    code = AuthorizationCode(
        code="code",
        scopes=["appflowy", "other"],
        expires_at=time.time() + 300,
        client_id="client",
        code_challenge="challenge",
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://mcp.example.com",
        subject="member@example.com",
    )
    initial = await p.exchange_authorization_code(client(), code)
    refresh = await p.load_refresh_token(client(), initial.refresh_token)
    assert refresh.resource == code.resource
    renewed = await p.exchange_refresh_token(client(), refresh, ["appflowy"])
    access = await p.load_access_token(renewed.access_token)
    assert access.resource == code.resource
    assert access.scopes == ["appflowy"] and renewed.scope == "appflowy"


@pytest.mark.asyncio
async def test_removed_member_cannot_reuse_persisted_access_or_refresh(tmp_path):
    path = tmp_path / "oauth.json"
    p = provider(path)
    p.access["access"] = AccessToken(
        token="access",
        client_id="client",
        scopes=["appflowy"],
        subject="member@example.com",
    )
    p.refresh["refresh"] = RefreshToken(
        token="refresh",
        client_id="client",
        scopes=["appflowy"],
        subject="member@example.com",
    )
    p._save()
    restarted = provider(path, emails=("other@example.com",))
    assert await restarted.load_access_token("access") is None
    assert await restarted.load_refresh_token(client(), "refresh") is None
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.asyncio
async def test_expired_tokens_are_refused_by_the_provider():
    p = provider()
    p.access["access"] = AccessToken(
        token="access",
        client_id="client",
        scopes=["appflowy"],
        expires_at=int(time.time()) - 1,
        subject="member@example.com",
    )
    p.refresh["refresh"] = RefreshToken(
        token="refresh",
        client_id="client",
        scopes=["appflowy"],
        expires_at=int(time.time()) - 1,
        subject="member@example.com",
    )
    assert await p.load_access_token("access") is None
    assert await p.load_refresh_token(client(), "refresh") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_google_callback_requires_verified_allowlisted_email(
    monkeypatch, verified
):
    p = provider()
    params = AuthorizationParams(
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        state="client-state",
        scopes=["appflowy"],
        resource="https://mcp.example.com",
    )
    redirect = await p.authorize(client(), params)
    state = parse_qs(urlsplit(redirect).query)["state"][0]
    real_client = httpx.AsyncClient

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "google-access"})
        assert request.headers["Authorization"] == "Bearer google-access"
        return httpx.Response(
            200, json={"email": "member@example.com", "verified_email": verified}
        )

    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )
    response = await p.handle_google_callback("google-code", state)
    assert response.status_code == (307 if verified else 403)
    assert bool(p.codes) is verified
    assert state not in p.pending


def test_invalid_store_is_atomic_and_does_not_log_token_values(tmp_path, capsys):
    path = tmp_path / "oauth.json"
    path.write_text(
        json.dumps(
            {
                "clients": {},
                "access": {
                    "token": {
                        "token": "must-not-be-logged",
                        "client_id": "client",
                        "scopes": "must-not-be-logged",
                    }
                },
            }
        )
    )
    p = provider(path)
    assert not p.clients and not p.access and not p.refresh
    assert "must-not-be-logged" not in capsys.readouterr().err
