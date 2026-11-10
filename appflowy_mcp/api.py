"""Shared async AppFlowy session, authentication and workspace policy.

One process owns one reusable client and login lock. Protocol/application modules
call this module; it does not import the MCP server or register tools.
"""

import asyncio
import os
import re
import time

import httpx

BASE_URL = os.environ.get("APPFLOWY_BASE_URL", "https://beta.appflowy.cloud").rstrip(
    "/"
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _read_only() -> bool:
    return os.environ.get("APPFLOWY_READ_ONLY", "false").lower() in {"1", "true", "yes"}


# Token management
_access_token = None
_refresh_token = None
_token_expires_at = 0
_async_auth_lock = asyncio.Lock()
_async_client: httpx.AsyncClient | None = None


def _allowed_workspaces() -> set[str] | None:
    """Workspace ids this server may touch, or None if unrestricted."""
    ids = _csv_env("ALLOWED_WORKSPACE_IDS")
    return set(ids) if ids else None


def _require_workspace(workspace_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", workspace_id):
        raise ValueError("workspace_id must be an ID without path separators")
    allowed = _allowed_workspaces()
    if allowed is not None and workspace_id not in allowed:
        raise ValueError(
            f"Workspace '{workspace_id}' is not permitted by this server's "
            "ALLOWED_WORKSPACE_IDS policy."
        )


def _default_workspace_id(workspace_id: str = "") -> str:
    """Return an explicit workspace id, or infer it from a single allowed workspace.

    v2 read verbs should be ergonomic for single-workspace deployments while staying
    explicit for multi-workspace servers. If ALLOWED_WORKSPACE_IDS contains exactly one
    id, callers may omit workspace_id; otherwise they must pass it.
    """
    if workspace_id:
        _require_workspace(workspace_id)
        return workspace_id
    allowed = _allowed_workspaces()
    if allowed is not None and len(allowed) == 1:
        return next(iter(allowed))
    raise ValueError(
        "workspace_id is required unless ALLOWED_WORKSPACE_IDS contains exactly one id"
    )


async def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(timeout=30.0)
    return _async_client


async def _close_async_client() -> None:
    global _async_client
    if _async_client is not None and not _async_client.is_closed:
        await _async_client.aclose()
    _async_client = None


async def _login_async() -> None:
    global _access_token, _refresh_token, _token_expires_at
    email = os.environ.get("APPFLOWY_EMAIL")
    password = os.environ.get("APPFLOWY_PASSWORD")

    if not email or not password:
        raise ValueError("APPFLOWY_EMAIL and APPFLOWY_PASSWORD must be set.")

    url = f"{BASE_URL}/gotrue/token?grant_type=password"
    data = {"email": email, "password": password}

    client = await _get_async_client()
    res = await client.post(url, json=data, headers={"User-Agent": USER_AGENT})
    res.raise_for_status()

    body = res.json()
    _access_token = body.get("access_token")
    _refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in", 3600)
    _token_expires_at = time.time() + expires_in - 60  # 60s buffer


async def _refresh_async() -> bool:
    """Return True for an accepted GoTrue refresh, False for password fallback."""
    global _access_token, _refresh_token, _token_expires_at
    if not _refresh_token:
        await _login_async()
        return False

    url = f"{BASE_URL}/gotrue/token?grant_type=refresh_token"
    data = {"refresh_token": _refresh_token}

    client = await _get_async_client()
    res = await client.post(url, json=data, headers={"User-Agent": USER_AGENT})
    if res.status_code != 200:
        await _login_async()  # refresh token expired -> re-login
        return False

    body = res.json()
    _access_token = body.get("access_token")
    if body.get("refresh_token"):
        _refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in", 3600)
    _token_expires_at = time.time() + expires_in - 60

    return True


async def get_auth_headers_async() -> dict:
    configured = os.environ.get("APPFLOWY_ACCESS_TOKEN")
    if configured:
        return {
            "Authorization": f"Bearer {configured}",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        }
    if not _access_token or time.time() >= _token_expires_at:
        async with _async_auth_lock:
            if not _access_token or time.time() >= _token_expires_at:
                try:
                    await _refresh_async() if _refresh_token else await _login_async()
                except Exception:  # noqa: BLE001 - any refresh failure (expired/revoked/
                    # malformed token, transport error) is recoverable by a full re-login.
                    await _login_async()

    return {
        "Authorization": f"Bearer {_access_token}",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }


get_auth_headers = get_auth_headers_async


# Status-code → what the agent should do about it. Surfaced in tool errors so a
# failed call is self-explanatory instead of a bare stack trace.
_ERROR_HINTS = {
    400: "check the ids and the JSON payload shape",
    401: "the server's AppFlowy login is invalid or expired",
    403: "the account lacks access to this workspace or resource",
    404: "verify the id exists — a folder view_id is NOT a database_id (call list_databases)",
    409: "the resource already exists or was modified concurrently",
    413: "the payload is too large — split it into smaller writes",
    429: "rate limited — wait briefly and retry",
}


def _raise_appflowy_application_error(payload, path: str) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("code"), int):
        return
    code = payload["code"]
    if code == 0:
        return
    message = " ".join(str(payload.get("message", "Request failed"))[:200].split())
    hint = (
        "check that database_id is the actual database ID, not a view_id "
        "(call list_databases)"
        if code == 1012 and "/database/" in path
        else "check the request and resource permissions"
    )
    raise RuntimeError(f"AppFlowy API code {code}: {message}; {hint}.")


async def _api_call_async(method: str, path: str, **kwargs) -> httpx.Response:
    """Authenticated AppFlowy API call with actionable errors. `path` is joined to
    BASE_URL. Raises RuntimeError with a specific, agent-readable message on failure so a
    tool error tells the agent how to fix its call rather than dumping a raw traceback."""
    if _read_only() and method.upper() not in {"GET", "HEAD"}:
        raise PermissionError("APPFLOWY_READ_ONLY is enabled; writes are disabled")
    if (
        not path.startswith("/api/")
        or any(part in {".", ".."} for part in path.split("/"))
        or any(char in path for char in ("%", "?", "#", "\\"))
    ):
        raise ValueError("Invalid AppFlowy API path")
    try:
        client = await _get_async_client()
        extra_headers = kwargs.pop("headers", {})
        res = await client.request(
            method,
            f"{BASE_URL}{path}",
            headers={**(await get_auth_headers_async()), **extra_headers},
            **kwargs,
        )
        res.raise_for_status()
        # AppFlowy can report an application error inside HTTP 200. In particular,
        # row writes with a view_id in place of database_id return code 1012 without
        # an HTTP error status.
        try:
            payload = res.json()
        except ValueError:
            payload = None
        _raise_appflowy_application_error(payload, path)
        return res
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        hint = _ERROR_HINTS.get(code, "unexpected AppFlowy API error")
        body = " ".join(e.response.text[:200].split())
        raise RuntimeError(f"AppFlowy API {code}: {hint}. Server said: {body}") from e
    except httpx.RequestError as e:
        raise RuntimeError(
            f"AppFlowy API request did not complete ({type(e).__name__}) — retry shortly"
        ) from e


async def _api_call(method: str, path: str, **kwargs) -> httpx.Response:
    return await _api_call_async(method, path, **kwargs)


async def _post(path: str, body: dict):
    """POST JSON to the AppFlowy API; return the response's `data` field."""
    return (await _api_call("POST", path, json=body)).json().get("data", "")
