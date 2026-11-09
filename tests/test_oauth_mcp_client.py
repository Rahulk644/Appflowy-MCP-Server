"""Official MCP client OAuth flow over ASGI; only Google identity is mocked."""

import time
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
from fastapi import FastAPI, Request
from mcp import ClientSession
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyHttpUrl

from appflowy_mcp import google_oauth as oauth
from appflowy_mcp import server as backend


class ClientStorage:
    def __init__(self):
        self.tokens = None
        self.client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, value):
        self.client_info = value


@pytest.mark.asyncio
async def test_official_client_login_refresh_replay_and_reauthentication(
    monkeypatch, tmp_path
):
    issuer = "https://mcp.example.com"
    clock = [time.time()]
    monkeypatch.setattr(oauth.time, "time", lambda: clock[0])
    provider = oauth.GoogleOAuthProvider(
        issuer,
        "google-client",
        "secret",
        ["member@example.com"],
        store_path=str(tmp_path / "oauth.json"),
    )
    monkeypatch.setattr(backend, "_oauth_provider", provider)
    monkeypatch.setattr(backend, "OAUTH_ISSUER", issuer)
    monkeypatch.delenv("MCP_SECRET_TOKEN", raising=False)
    mcp = MCPServer("oauth-contract", version="2.0.1")

    @mcp.tool()
    async def probe() -> str:
        return "ready"

    app = FastAPI()
    app.middleware("http")(backend.verify_token)
    app.router.routes.extend(oauth.create_oauth_routes(provider))
    app.router.routes.extend(
        create_protected_resource_routes(
            resource_url=AnyHttpUrl(issuer),
            authorization_servers=[AnyHttpUrl(issuer)],
            scopes_supported=["appflowy"],
        )
    )

    @app.get("/auth/google/callback")
    async def callback(request: Request):
        return await provider.handle_google_callback(
            request.query_params["code"], request.query_params["state"]
        )

    app.mount(
        "/mcp",
        mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                allowed_hosts=["mcp.example.com"], allowed_origins=[issuer]
            ),
        ),
    )
    real_google_client = httpx.AsyncClient

    def google(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "google-token"})
        assert request.url.host == "www.googleapis.com"
        return httpx.Response(
            200, json={"email": "member@example.com", "verified_email": True}
        )

    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_google_client(transport=httpx.MockTransport(google)),
    )
    storage = ClientStorage()
    callback_result = None
    sign_ins = 0
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url=issuer, follow_redirects=False
    ) as browser:

        async def redirect_handler(url):
            nonlocal callback_result, sign_ins
            response = await browser.get(url)
            assert response.status_code == 302
            state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
            completed = await browser.get(
                "/auth/google/callback", params={"code": "google-code", "state": state}
            )
            assert completed.status_code == 307
            query = parse_qs(urlsplit(completed.headers["location"]).query)
            callback_result = AuthorizationCodeResult(
                code=query["code"][0], state=query.get("state", [None])[0]
            )
            sign_ins += 1

        async def callback_handler():
            assert callback_result is not None
            return callback_result

        auth = OAuthClientProvider(
            server_url=issuer + "/mcp/",
            client_metadata=OAuthClientMetadata(
                redirect_uris=["http://localhost/callback"],
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope="appflowy",
            ),
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
        async with (
            mcp.session_manager.run(),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                auth=auth,
                follow_redirects=True,
            ) as http_client,
            streamable_http_client(issuer + "/mcp/", http_client=http_client) as (
                read,
                write,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("probe", {})
            assert not result.is_error and sign_ins == 1
            original = storage.tokens
            assert original and original.refresh_token
            clock[0] += oauth.ACCESS_TTL + 2
            assert not (await session.call_tool("probe", {})).is_error
            refreshed = storage.tokens
            assert refreshed.refresh_token != original.refresh_token
            assert sign_ins == 1
            replay = await browser.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": storage.client_info.client_id,
                    "refresh_token": original.refresh_token,
                },
            )
            assert replay.status_code == 400
            assert replay.json()["error"] == "invalid_grant"
            assert await provider.load_access_token(refreshed.access_token) is None
            assert not (await session.call_tool("probe", {})).is_error
            assert sign_ins == 2

            current = storage.tokens
            revoked = await browser.post(
                "/revoke",
                data={
                    "client_id": storage.client_info.client_id,
                    "token": current.refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )
            assert revoked.status_code == 200
            assert await provider.load_access_token(current.access_token) is None
