"""Google-federated OAuth 2.1 Authorization Server for the AppFlowy MCP.

Active only when GOOGLE_CLIENT_ID/SECRET are set. Claude's connector runs the
standard MCP OAuth flow against THIS server; we federate the human sign-in to
Google and allow-list emails. The SDK (mcp.server.auth) provides the /authorize,
/token, /register and discovery routes; this provider implements the storage and
federates authorize() to Google.

Stores are in-memory (single instance) — tokens are lost on restart and users
just sign in again. Fine for a personal / OSS server; swap for a shared store if
you scale out.
"""

import secrets
import time
from urllib.parse import urlencode

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.responses import JSONResponse, RedirectResponse

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"


def _tok(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


class GoogleOAuthProvider(OAuthAuthorizationServerProvider):
    def __init__(self, issuer, google_client_id, google_client_secret, allowed_emails):
        self.issuer = issuer.rstrip("/")
        self.gcid = google_client_id
        self.gcs = google_client_secret
        self.allowed = {e.strip().lower() for e in allowed_emails if e.strip()}
        self.callback = f"{self.issuer}/auth/google/callback"
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, dict] = {}  # google state -> mcp auth context
        self.codes: dict[str, AuthorizationCode] = {}
        self.access: dict[str, AccessToken] = {}
        self.refresh: dict[str, RefreshToken] = {}

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params: AuthorizationParams) -> str:
        # Stash the MCP client's authorization request, then send the browser to
        # Google. The Google callback finishes the flow.
        state = _tok()
        self.pending[state] = {
            "client_id": client.client_id,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "scopes": params.scopes or [],
            "resource": params.resource,
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
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(self, client, authorization_code):
        self.codes.pop(authorization_code.code, None)  # single use
        now = int(time.time())
        at, rt = _tok(), _tok()
        self.access[at] = AccessToken(
            token=at,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + 3600,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )
        self.refresh[rt] = RefreshToken(
            token=rt,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + 30 * 86400,
            subject=authorization_code.subject,
        )
        return OAuthToken(
            access_token=at,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes or []),
            refresh_token=rt,
        )

    async def load_access_token(self, token):
        t = self.access.get(token)
        if t and t.expires_at and t.expires_at < time.time():
            self.access.pop(token, None)
            return None
        return t

    async def load_refresh_token(self, client, refresh_token):
        return self.refresh.get(refresh_token)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        now = int(time.time())
        at = _tok()
        self.access[at] = AccessToken(
            token=at,
            client_id=client.client_id,
            scopes=refresh_token.scopes,
            expires_at=now + 3600,
            subject=refresh_token.subject,
        )
        return OAuthToken(
            access_token=at,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(refresh_token.scopes or []),
            refresh_token=refresh_token.token,
        )

    async def revoke_token(self, token):
        tok = getattr(token, "token", None)
        self.access.pop(tok, None)
        self.refresh.pop(tok, None)

    async def handle_google_callback(self, code: str, state: str):
        """Called by the /auth/google/callback route after Google sign-in."""
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
            email = (ui.json().get("email") or "").lower()
        if email not in self.allowed:
            return JSONResponse(
                {"error": "access_denied", "detail": f"{email} is not allow-listed"},
                status_code=403,
            )
        my_code = _tok()
        self.codes[my_code] = AuthorizationCode(
            code=my_code,
            scopes=ctx["scopes"],
            expires_at=time.time() + 300,
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
