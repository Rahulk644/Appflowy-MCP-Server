"""Google-federated OAuth 2.1 Authorization Server for the AppFlowy MCP.

Active only when GOOGLE_CLIENT_ID/SECRET are set. Claude's connector runs the
standard MCP OAuth flow against THIS server; we federate the human sign-in to
Google and allow-list emails. The SDK (mcp.server.auth) provides the /authorize,
/token, /register and discovery routes; this provider implements the storage and
federates authorize() to Google.

Stores are in-memory by default. Set OAUTH_STORE_PATH (a path on a mounted volume)
to persist issued tokens + registered clients across restarts, so a redeploy doesn't
force users to sign in again; leave it unset to keep everything in-memory. Swap for a
shared store if you scale out.
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
from urllib.parse import unquote, urlencode

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, RedirectResponse

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"


AUTHORIZATION_TTL = 300
ACCESS_TTL = 3600
SESSION_TTL = 30 * 86400
MAX_PENDING = 1024
MAX_CODES = 1024
MAX_CLIENTS = 1000
MAX_ROTATIONS = 1024
STORE_VERSION = 2


class _AccessGrant(AccessToken):
    family_id: str


class _RefreshGrant(RefreshToken):
    family_id: str


class _SpentRefresh(BaseModel):
    family_id: str
    client_id: str
    expires_at: int


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _tok(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


class GoogleOAuthProvider(OAuthAuthorizationServerProvider):
    def __init__(
        self,
        issuer,
        google_client_id,
        google_client_secret,
        allowed_emails,
        store_path=None,
    ):
        self.issuer = issuer.rstrip("/")
        self.gcid = google_client_id
        self.gcs = google_client_secret
        self.allowed = {e.strip().lower() for e in allowed_emails if e.strip()}
        self.callback = f"{self.issuer}/auth/google/callback"
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, dict] = {}  # google state -> mcp auth context
        self.codes: dict[str, AuthorizationCode] = {}
        self.access: dict[str, _AccessGrant] = {}
        self.refresh: dict[str, _RefreshGrant] = {}
        self.spent_refresh: dict[str, _SpentRefresh] = {}
        # Optional persistence so tokens survive restarts. Point at a MOUNTED volume
        # (a bare container path is wiped on rebuild). Transient stores (pending,
        # codes) are intentionally not persisted — a re-auth in flight just retries.
        self.store_path = store_path or None
        self._store_dirty = False
        self._load()

    def _load(self) -> None:
        if not self.store_path or not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path) as f:
                data = json.load(f)
            clients = {
                k: OAuthClientInformationFull.model_validate(v)
                for k, v in data.get("clients", {}).items()
            }
            # Old stores lack the relationships required for safe rotation/replay
            # handling. Preserve registrations, require fresh sign-in for tokens.
            if data.get("version") != STORE_VERSION:
                self.clients = clients
                if data.get("access") or data.get("refresh"):
                    print(
                        "[oauth] legacy tokens require a new sign-in", file=sys.stderr
                    )
                return
            access = {
                k: _AccessGrant.model_validate(v)
                for k, v in data.get("access", {}).items()
            }
            refresh = {
                k: _RefreshGrant.model_validate(v)
                for k, v in data.get("refresh", {}).items()
            }
            spent = {
                k: _SpentRefresh.model_validate(v)
                for k, v in data.get("spent_refresh", {}).items()
            }
            self.clients, self.access, self.refresh, self.spent_refresh = (
                clients,
                access,
                refresh,
                spent,
            )
        except Exception as e:  # noqa: BLE001 - a corrupt/unreadable store must never
            # take the server down; degrade to an empty store and make users re-auth.
            print(
                f"[oauth] token store unreadable ({type(e).__name__}); starting empty",
                file=sys.stderr,
            )
        if self._prune():
            self._save()

    def _save(self) -> bool:
        if not self.store_path:
            return True
        temporary = None
        try:
            data = {
                "version": STORE_VERSION,
                "clients": {
                    k: v.model_dump(mode="json") for k, v in self.clients.items()
                },
                "access": {
                    k: v.model_dump(mode="json") for k, v in self.access.items()
                },
                "refresh": {
                    k: v.model_dump(mode="json") for k, v in self.refresh.items()
                },
                "spent_refresh": {
                    k: v.model_dump(mode="json") for k, v in self.spent_refresh.items()
                },
            }
            os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
            # NamedTemporaryFile starts private (0600) and avoids a predictable
            # shared path. Do not write tokens before restricting permissions.
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=os.path.dirname(self.store_path) or ".",
                prefix=".oauth-",
                suffix=".tmp",
                delete=False,
            ) as f:
                temporary = f.name
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.store_path)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(
                    os.path.dirname(self.store_path) or ".",
                    os.O_RDONLY | os.O_DIRECTORY,
                )
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            self._store_dirty = False
            return True
        except Exception as e:  # noqa: BLE001 - report storage failure without leaking credentials.
            print(
                f"[oauth] could not persist token store ({type(e).__name__})",
                file=sys.stderr,
            )
            self._store_dirty = True
            return False
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass  # Do not mask the original storage failure during cleanup.

    def _maintain(self) -> None:
        if self._prune() or self._store_dirty:
            self._persist()

    def _persist(self) -> None:
        if not self._save():
            raise HTTPException(503, "OAuth token storage unavailable")

    def _prune(self) -> bool:
        """Drop expired transient state and token records on provider activity."""
        now, changed = time.time(), False
        for state, context in list(self.pending.items()):
            if context["expires_at"] <= now:
                del self.pending[state]
        for key, code in list(self.codes.items()):
            if code.expires_at <= now or code.subject not in self.allowed:
                del self.codes[key]
        for tokens in (self.access, self.refresh):
            for key, token in list(tokens.items()):
                if (
                    token.expires_at is None
                    or token.expires_at <= now
                    or token.subject not in self.allowed
                    or token.resource != self.issuer
                ):
                    del tokens[key]
                    changed = True
        families = {
            token.family_id
            for tokens in (self.access, self.refresh)
            for token in tokens.values()
        }
        for key, spent in list(self.spent_refresh.items()):
            if spent.expires_at <= now or spent.family_id not in families:
                del self.spent_refresh[key]
                changed = True
        return changed

    def _revoke_family(self, family_id: str) -> None:
        for tokens in (self.access, self.refresh, self.spent_refresh):
            for key, token in list(tokens.items()):
                if token.family_id == family_id:
                    del tokens[key]

    def _issue_tokens(self, client_id, scopes, subject, family_id, expires_at):
        now = int(time.time())
        access_expiry = min(now + ACCESS_TTL, expires_at)
        at, rt = _tok(), _tok()
        self.access[at] = _AccessGrant(
            token=at,
            client_id=client_id,
            scopes=scopes,
            expires_at=access_expiry,
            resource=self.issuer,
            subject=subject,
            family_id=family_id,
        )
        self.refresh[rt] = _RefreshGrant(
            token=rt,
            client_id=client_id,
            scopes=scopes,
            expires_at=expires_at,
            resource=self.issuer,
            subject=subject,
            family_id=family_id,
        )
        return OAuthToken(
            access_token=at,
            token_type="Bearer",
            expires_in=access_expiry - now,
            scope=" ".join(scopes),
            refresh_token=rt,
        )

    async def get_client(self, client_id):
        self._maintain()
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        if (
            client_info.client_id not in self.clients
            and len(self.clients) >= MAX_CLIENTS
        ):
            raise RegistrationError(
                "invalid_client_metadata",
                "Client registration limit reached; contact the operator",
            )
        previous = self.clients.get(client_info.client_id)
        self.clients[client_info.client_id] = client_info
        if not self._save():
            if previous is None:
                self.clients.pop(client_info.client_id, None)
            else:
                self.clients[client_info.client_id] = previous
            raise HTTPException(503, "OAuth token storage unavailable")

    async def authorize(self, client, params: AuthorizationParams) -> str:
        self._maintain()
        if params.resource and params.resource.rstrip("/") not in {
            self.issuer,
            self.issuer + "/mcp",
            self.issuer + "/sse",
        }:
            raise AuthorizeError(
                "invalid_target", "Resource does not belong to this server"
            )
        if len(self.pending) >= MAX_PENDING:
            raise AuthorizeError(
                "temporarily_unavailable", "Too many pending sign-ins; retry later"
            )
        state = _tok()
        self.pending[state] = {
            "expires_at": time.time() + AUTHORIZATION_TTL,
            "client_id": client.client_id,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "scopes": params.scopes or [],
            "resource": self.issuer,
            "mcp_state": params.state,
        }
        q = urlencode(
            {
                "client_id": self.gcid,
                "redirect_uri": self.callback,
                "response_type": "code",
                "scope": "openid email",
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        return f"{GOOGLE_AUTH}?{q}"

    async def load_authorization_code(self, client, authorization_code):
        self._maintain()
        code = self.codes.get(authorization_code)
        return code if code and code.client_id == client.client_id else None

    async def exchange_authorization_code(self, client, authorization_code):
        code = await self.load_authorization_code(client, authorization_code.code)
        if code is None:
            raise TokenError(
                "invalid_grant", "Authorization code is invalid or expired"
            )
        snapshot = (self.access.copy(), self.refresh.copy(), self.spent_refresh.copy())
        self.codes.pop(code.code)
        result = self._issue_tokens(
            client.client_id,
            code.scopes,
            code.subject,
            _tok(16),
            int(time.time()) + SESSION_TTL,
        )
        if not self._save():
            self.access, self.refresh, self.spent_refresh = snapshot
            self.codes[code.code] = code
            raise HTTPException(503, "OAuth token storage unavailable")
        return result

    async def load_access_token(self, token):
        self._maintain()
        return self.access.get(token)

    async def load_refresh_token(self, client, refresh_token):
        self._maintain()
        token = self.refresh.get(refresh_token)
        if token:
            return token if token.client_id == client.client_id else None
        spent = self.spent_refresh.get(_fingerprint(refresh_token))
        if spent and spent.client_id == client.client_id:
            # Reuse of a rotated credential invalidates every token from that
            # login. Other logins (including the same user's) remain independent.
            self._revoke_family(spent.family_id)
            self._persist()
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        token = await self.load_refresh_token(client, refresh_token.token)
        if token is None:
            raise TokenError("invalid_grant", "Refresh token is invalid or expired")
        if not set(scopes).issubset(token.scopes):
            raise TokenError("invalid_scope", "Requested scope exceeds the grant")
        if (
            sum(
                item.family_id == token.family_id
                for item in self.spent_refresh.values()
            )
            >= MAX_ROTATIONS
        ):
            self._revoke_family(token.family_id)
            self._persist()
            raise TokenError(
                "invalid_grant", "Login rotation limit reached; sign in again"
            )
        snapshot = (self.access.copy(), self.refresh.copy(), self.spent_refresh.copy())
        self.refresh.pop(token.token)
        self.spent_refresh[_fingerprint(token.token)] = _SpentRefresh(
            family_id=token.family_id,
            client_id=token.client_id,
            expires_at=token.expires_at,
        )
        result = self._issue_tokens(
            client.client_id, scopes, token.subject, token.family_id, token.expires_at
        )
        if not self._save():
            self.access, self.refresh, self.spent_refresh = snapshot
            raise HTTPException(503, "OAuth token storage unavailable")
        return result

    async def revoke_token(self, token):
        self._revoke_family(token.family_id)
        self._persist()

    async def handle_google_callback(self, code: str, state: str):
        """Called by the /auth/google/callback route after Google sign-in."""
        self._maintain()
        ctx = self.pending.pop(state, None)
        if not ctx or not code:
            return JSONResponse({"error": "invalid or expired state"}, status_code=400)
        async with httpx.AsyncClient(timeout=15) as c:
            tr = await c.post(
                GOOGLE_TOKEN,
                data={
                    "code": code,
                    "client_id": self.gcid,
                    "client_secret": self.gcs,
                    "redirect_uri": self.callback,
                    "grant_type": "authorization_code",
                },
            )
            tr.raise_for_status()
            g_access = tr.json().get("access_token")
            ui = await c.get(
                GOOGLE_USERINFO, headers={"Authorization": f"Bearer {g_access}"}
            )
            ui.raise_for_status()
            identity = ui.json()
            email = (identity.get("email") or "").lower()
        if identity.get("verified_email") is not True or email not in self.allowed:
            return JSONResponse(
                {"error": "access_denied", "detail": f"{email} is not allow-listed"},
                status_code=403,
            )
        if len(self.codes) >= MAX_CODES:
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
        my_code = _tok()
        self.codes[my_code] = AuthorizationCode(
            code=my_code,
            scopes=ctx["scopes"],
            expires_at=time.time() + AUTHORIZATION_TTL,
            client_id=ctx["client_id"],
            code_challenge=ctx["code_challenge"],
            redirect_uri=ctx["redirect_uri"],
            redirect_uri_provided_explicitly=ctx["redirect_uri_provided_explicitly"],
            resource=ctx["resource"],
            subject=email,
        )
        params = {"code": my_code}
        if ctx["mcp_state"]:
            params["state"] = ctx["mcp_state"]
        sep = "&" if "?" in ctx["redirect_uri"] else "?"
        return RedirectResponse(f"{ctx['redirect_uri']}{sep}{urlencode(params)}")


def create_oauth_routes(provider: GoogleOAuthProvider):
    """Use SDK routes with RFC 7009 public-client revocation compatibility.

    SDK 2.3's revocation model requires a client_secret form field even for
    registered public clients, and client_id even when HTTP Basic authenticates
    a confidential client. Keep SDK client authentication, CORS and body limits;
    parse only the revocation fields that RFC 7009 actually requires.
    """
    from mcp.server.auth.handlers.metadata import MetadataHandler
    from mcp.server.auth.middleware.client_auth import (
        AuthenticationError,
        ClientAuthenticator,
    )
    from mcp.server.auth.routes import build_metadata, create_auth_routes
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from mcp.server.transport_security import (
        DEFAULT_MAX_REQUEST_BODY_SIZE,
        RequestBodyLimitMiddleware,
    )
    from pydantic import AnyHttpUrl
    from starlette.datastructures import FormData
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route, request_response

    authenticator = ClientAuthenticator(provider)

    async def revoke(request: Request):
        headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
        authentication_request = request
        scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "basic":
            try:
                basic_id = unquote(
                    base64.b64decode(credentials, validate=True)
                    .decode("utf-8")
                    .split(":", 1)[0]
                )
            except (ValueError, UnicodeError):
                return JSONResponse(
                    {"error": "invalid_client"}, status_code=401, headers=headers
                )
            fields = dict(await request.form())
            fields.setdefault("client_id", basic_id)
            scope = {
                **request.scope,
                "headers": [
                    (key, value)
                    for key, value in request.scope["headers"]
                    if key.lower() != b"authorization"
                ]
                + [(b"authorization", ("Basic " + credentials).encode())],
            }
            authentication_request = Request(scope)
            # Narrow SDK 2.3 compatibility: normalize its required form client_id
            # without reimplementing secret, expiry or registered-method checks.
            authentication_request._form = FormData(fields)
        try:
            client = await authenticator.authenticate_request(authentication_request)
        except AuthenticationError:
            return JSONResponse(
                {"error": "invalid_client"}, status_code=401, headers=headers
            )
        form = await request.form()
        value = form.get("token")
        if not isinstance(value, str) or not value:
            return JSONResponse(
                {"error": "invalid_request"}, status_code=400, headers=headers
            )
        token = await provider.load_access_token(value)
        if token is None:
            token = await provider.load_refresh_token(client, value)
        if token and token.client_id == client.client_id:
            await provider.revoke_token(token)
        return Response(status_code=200, headers=headers)

    issuer = AnyHttpUrl(provider.issuer)
    registration = ClientRegistrationOptions(
        enabled=True, valid_scopes=["appflowy"], default_scopes=["appflowy"]
    )
    revocation_options = RevocationOptions(enabled=True)
    routes = create_auth_routes(
        provider,
        issuer,
        client_registration_options=registration,
        revocation_options=revocation_options,
    )
    metadata = build_metadata(issuer, None, registration, revocation_options)
    metadata.token_endpoint_auth_methods_supported = [
        "none",
        "client_secret_post",
        "client_secret_basic",
    ]
    metadata.revocation_endpoint_auth_methods_supported = [
        "none",
        "client_secret_post",
        "client_secret_basic",
    ]

    def endpoint(handler, methods):
        return CORSMiddleware(
            RequestBodyLimitMiddleware(
                request_response(handler), DEFAULT_MAX_REQUEST_BODY_SIZE
            ),
            allow_origins=["*"],
            allow_methods=methods,
            allow_headers=["authorization", "content-type", "mcp-protocol-version"],
        )

    result = []
    for route in routes:
        if route.path == "/revoke":
            route = Route(
                route.path,
                endpoint=endpoint(revoke, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            )
        elif route.path == "/.well-known/oauth-authorization-server":
            route = Route(
                route.path,
                endpoint=endpoint(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
                methods=["GET", "OPTIONS"],
            )
        result.append(route)
    return result
