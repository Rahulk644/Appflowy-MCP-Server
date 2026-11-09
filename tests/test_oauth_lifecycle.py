"""OAuth expiry, rotation, durable replay detection and independent login families."""

import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull
from starlette.exceptions import HTTPException

from appflowy_mcp import google_oauth as oauth


@pytest.fixture
def clock(monkeypatch):
    now = [time.time()]
    monkeypatch.setattr(oauth.time, "time", lambda: now[0])
    return now


def client(name="client"):
    return OAuthClientInformationFull(
        client_id=name,
        redirect_uris=["http://localhost/callback"],
        token_endpoint_auth_method="none",
    )


def provider(path=None):
    return oauth.GoogleOAuthProvider(
        "https://mcp.example.com",
        "google-client",
        "google-secret",
        ["member@example.com"],
        store_path=str(path) if path else None,
    )


def code(p, c=None):
    c = c or client()
    value = AuthorizationCode(
        code=oauth._tok(),
        client_id=c.client_id,
        scopes=["appflowy"],
        expires_at=time.time() + 300,
        code_challenge="challenge",
        redirect_uri="http://localhost/callback",
        redirect_uri_provided_explicitly=True,
        subject="member@example.com",
        resource=p.issuer,
    )
    p.codes[value.code] = value
    return value


async def issue(p, c=None):
    c = c or client()
    return await p.exchange_authorization_code(c, code(p, c))


async def rotate(p, tokens, c=None):
    c = c or client()
    refresh = await p.load_refresh_token(c, tokens.refresh_token)
    assert refresh is not None
    return await p.exchange_refresh_token(c, refresh, ["appflowy"])


@pytest.mark.asyncio
async def test_replay_revokes_only_its_login_and_survives_restart(tmp_path):
    path = tmp_path / "oauth.json"
    p = provider(path)
    first, independent = await issue(p), await issue(p)
    initial_deadline = p.refresh[first.refresh_token].expires_at
    renewed = await rotate(p, first)
    assert renewed.refresh_token != first.refresh_token
    assert p.refresh[renewed.refresh_token].expires_at == initial_deadline
    assert first.refresh_token not in path.read_text()
    assert await p.load_access_token(first.access_token)
    restarted = provider(path)
    assert await restarted.load_refresh_token(client(), first.refresh_token) is None
    assert await restarted.load_access_token(first.access_token) is None
    assert await restarted.load_access_token(renewed.access_token) is None
    assert await restarted.load_refresh_token(client(), renewed.refresh_token) is None
    assert await restarted.load_access_token(independent.access_token)
    again = provider(path)
    assert await again.load_access_token(renewed.access_token) is None
    assert await again.load_refresh_token(client(), independent.refresh_token)


@pytest.mark.asyncio
async def test_wrong_client_cannot_invalidate_another_clients_login():
    p = provider()
    first = await issue(p)
    renewed = await rotate(p, first)
    assert await p.load_refresh_token(client("other"), first.refresh_token) is None
    assert await p.load_access_token(renewed.access_token)


@pytest.mark.asyncio
async def test_revocation_invalidates_access_and_refresh_for_the_family(tmp_path):
    path = tmp_path / "oauth.json"
    p = provider(path)
    first, other = await issue(p), await issue(p)
    renewed = await rotate(p, first)
    await p.revoke_token(await p.load_access_token(first.access_token))
    restarted = provider(path)
    assert await restarted.load_access_token(renewed.access_token) is None
    assert await restarted.load_refresh_token(client(), renewed.refresh_token) is None
    assert await restarted.load_access_token(other.access_token)


@pytest.mark.asyncio
async def test_stale_loaded_refresh_object_cannot_be_exchanged_again():
    p = provider()
    first = await issue(p)
    loaded = await p.load_refresh_token(client(), first.refresh_token)
    renewed = await p.exchange_refresh_token(client(), loaded, ["appflowy"])
    with pytest.raises(TokenError) as error:
        await p.exchange_refresh_token(client(), loaded, ["appflowy"])
    assert error.value.error == "invalid_grant"
    assert await p.load_access_token(renewed.access_token) is None


@pytest.mark.asyncio
async def test_simultaneous_refresh_reuse_fails_closed():
    p = provider()
    first = await issue(p)
    loaded = await p.load_refresh_token(client(), first.refresh_token)
    results = await asyncio.gather(
        *(p.exchange_refresh_token(client(), loaded, ["appflowy"]) for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, TokenError) for result in results) == 1
    assert not p.access and not p.refresh


@pytest.mark.asyncio
async def test_expired_states_codes_and_token_history_are_pruned(clock):
    p = provider()
    params = AuthorizationParams(
        redirect_uri="http://localhost/callback",
        redirect_uri_provided_explicitly=True,
        state="state",
        scopes=["appflowy"],
        code_challenge="challenge",
    )
    redirect = await p.authorize(client(), params)
    state = parse_qs(urlsplit(redirect).query)["state"][0]
    pending_code = code(p)
    first = await issue(p)
    await rotate(p, first)
    clock[0] += oauth.AUTHORIZATION_TTL + 1
    assert await p.load_authorization_code(client(), pending_code.code) is None
    assert state not in p.pending
    assert (
        await p.handle_google_callback("unused-google-code", state)
    ).status_code == 400
    clock[0] += oauth.SESSION_TTL
    assert await p.load_access_token(first.access_token) is None
    assert not p.access and not p.refresh and not p.spent_refresh


@pytest.mark.asyncio
async def test_authorization_code_is_bound_to_client_and_single_use():
    p = provider()
    value = code(p)
    assert await p.load_authorization_code(client("other"), value.code) is None
    first = await p.exchange_authorization_code(client(), value)
    with pytest.raises(TokenError):
        await p.exchange_authorization_code(client(), value)
    assert await p.load_access_token(first.access_token)


@pytest.mark.asyncio
async def test_refresh_scope_cannot_expand():
    p = provider()
    first = await issue(p)
    grant = await p.load_refresh_token(client(), first.refresh_token)
    with pytest.raises(TokenError) as error:
        await p.exchange_refresh_token(client(), grant, ["admin"])
    assert error.value.error == "invalid_scope"
    assert await p.load_refresh_token(client(), first.refresh_token)


@pytest.mark.asyncio
async def test_resource_indicator_must_belong_to_this_server():
    p = provider()
    params = AuthorizationParams(
        redirect_uri="http://localhost/callback",
        redirect_uri_provided_explicitly=True,
        state=None,
        scopes=["appflowy"],
        code_challenge="challenge",
        resource="https://other.example.com",
    )
    with pytest.raises(AuthorizeError) as error:
        await p.authorize(client(), params)
    assert error.value.error == "invalid_target"
    assert not p.pending


@pytest.mark.asyncio
async def test_rotation_limit_ends_one_login_and_allows_a_fresh_login(monkeypatch):
    monkeypatch.setattr(oauth, "MAX_ROTATIONS", 1)
    p = provider()
    first = await issue(p)
    renewed = await rotate(p, first)
    with pytest.raises(TokenError):
        await rotate(p, renewed)
    assert not p.access and not p.refresh and not p.spent_refresh
    assert await p.load_access_token((await issue(p)).access_token)


@pytest.mark.asyncio
async def test_transient_and_registration_limits_are_explicit(monkeypatch, clock):
    monkeypatch.setattr(oauth, "MAX_PENDING", 1)
    monkeypatch.setattr(oauth, "MAX_CLIENTS", 1)
    p = provider()
    await p.register_client(client())
    with pytest.raises(RegistrationError):
        await p.register_client(client("other"))
    params = AuthorizationParams(
        redirect_uri="http://localhost/callback",
        redirect_uri_provided_explicitly=True,
        state=None,
        scopes=["appflowy"],
        code_challenge="challenge",
    )
    await p.authorize(client(), params)
    with pytest.raises(AuthorizeError):
        await p.authorize(client(), params)
    clock[0] += oauth.AUTHORIZATION_TTL + 1
    await p.authorize(client(), params)
    assert len(p.pending) == 1


@pytest.mark.asyncio
async def test_failed_rotation_write_returns_no_credentials_and_rolls_back(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "oauth.json"
    p = provider(path)
    first = await issue(p)
    original = oauth.os.replace

    def fail(*args):
        raise OSError(first.refresh_token)

    monkeypatch.setattr(oauth.os, "replace", fail)
    with pytest.raises(HTTPException) as error:
        await rotate(p, first)
    assert error.value.status_code == 503
    assert set(p.refresh) == {first.refresh_token}
    assert first.refresh_token not in capsys.readouterr().err
    monkeypatch.setattr(oauth.os, "replace", original)
    renewed = await rotate(p, first)
    assert await provider(path).load_refresh_token(client(), renewed.refresh_token)


def test_legacy_store_preserves_registrations_and_requires_new_sign_in(tmp_path):
    path = tmp_path / "oauth.json"
    path.write_text(
        json.dumps(
            {
                "clients": {"client": client().model_dump(mode="json")},
                "access": {"old": {"token": "old"}},
                "refresh": {"old-refresh": {"token": "old-refresh"}},
            }
        )
    )
    p = provider(path)
    assert "client" in p.clients
    assert not p.access and not p.refresh and not p.spent_refresh


@pytest.mark.asyncio
async def test_storage_failure_surfaces_as_service_unavailable_at_http_gate(
    monkeypatch,
):
    import httpx

    from appflowy_mcp import server

    p = provider()
    tokens = await issue(p)
    p._store_dirty = True
    monkeypatch.setattr(p, "_save", lambda: False)
    monkeypatch.setattr(server, "_oauth_provider", p)
    monkeypatch.delenv("MCP_SECRET_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://testserver"
    ) as http:
        response = await http.get(
            "/protected-test",
            headers={"Authorization": "Bearer " + tokens.access_token},
        )
    assert response.status_code == 503
    assert tokens.access_token not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["none", "client_secret_basic", "client_secret_post"]
)
async def test_revocation_accepts_standard_public_and_confidential_clients(method):
    import httpx
    from fastapi import FastAPI

    p = provider()
    c = client()
    c.token_endpoint_auth_method = method
    c.client_secret = "confidential-secret" if method != "none" else None
    await p.register_client(c)
    tokens = await issue(p, c)
    app = FastAPI()
    app.router.routes.extend(oauth.create_oauth_routes(p))
    data = {"token": tokens.refresh_token}
    auth = None
    if method == "client_secret_basic":
        auth = httpx.BasicAuth(c.client_id, c.client_secret)
    else:
        data["client_id"] = c.client_id
        if method == "client_secret_post":
            data["client_secret"] = c.client_secret
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=p.issuer
    ) as http:
        metadata = (await http.get("/.well-known/oauth-authorization-server")).json()
        assert method in metadata["revocation_endpoint_auth_methods_supported"]
        revoked = await http.post("/revoke", data=data, auth=auth)
        assert revoked.status_code == 200, revoked.text
        assert await p.load_access_token(tokens.access_token) is None
        assert (await http.post("/revoke", data=data, auth=auth)).status_code == 200


@pytest.mark.asyncio
async def test_revocation_keeps_body_limits_and_cors():
    import httpx
    from fastapi import FastAPI

    p = provider()
    app = FastAPI()
    app.router.routes.extend(oauth.create_oauth_routes(p))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=p.issuer
    ) as http:
        response = await http.post(
            "/revoke",
            content=b"x" * (4 * 1024 * 1024 + 1),
            headers={
                "Origin": "https://client.example.com",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "*"


@pytest.mark.asyncio
async def test_basic_revocation_still_checks_the_registered_secret():
    import httpx
    from fastapi import FastAPI

    p = provider()
    c = client()
    c.token_endpoint_auth_method = "client_secret_basic"
    c.client_secret = "correct-secret"
    await p.register_client(c)
    tokens = await issue(p, c)
    app = FastAPI()
    app.router.routes.extend(oauth.create_oauth_routes(p))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=p.issuer
    ) as http:
        response = await http.post(
            "/revoke",
            data={"token": tokens.refresh_token},
            auth=httpx.BasicAuth(c.client_id, "wrong-secret"),
        )
    assert response.status_code == 401
    assert await p.load_access_token(tokens.access_token)
