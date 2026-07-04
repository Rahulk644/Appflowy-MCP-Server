"""AppFlowy MCP Server.

An MCP server over the AppFlowy Cloud REST API. Exposes workspace/folder/database
reads plus row create + upsert so an AI agent can both see and *finish* work
(e.g. move a Board card by upserting its Status cell).

Transports:
  * stdio             — run this file directly (local use).
  * Streamable HTTP   — mounted at /mcp   (current MCP standard).
  * SSE               — mounted at /sse   (legacy; kept for existing clients).

Security model (see README/SECURITY):
  * AppFlowy Cloud has no scoped API keys — auth is full-account GoTrue login.
    Use a DEDICATED bot account invited to only the workspace(s) you expose.
  * ALLOWED_WORKSPACE_IDS pins the server to specific workspace(s); every tool
    refuses any other id (defence-in-depth on top of account isolation).
  * MCP_SECRET_TOKEN gates every HTTP request. Send it as an `Authorization:
    Bearer` header (preferred), OR as a `?token=` URL query param ("link method"
    — for UIs like Claude's connector dialog that can't set a header). With the
    link method the token rides in the URL and can appear in logs, so treat the
    whole link like a password.
"""

import base64
import hmac
import json
import os
import secrets
import string
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pycrdt import Array, Doc, Map, Text

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

BASE_URL = os.environ.get("APPFLOWY_BASE_URL", "https://beta.appflowy.cloud").rstrip(
    "/"
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Sent to MCP clients as server instructions — teaches the agent AppFlowy's model,
# the tool set, the block schema, and the limits so it builds clean structures.
APPFLOWY_INSTRUCTIONS = """\
AppFlowy MCP — you can READ and BUILD in this AppFlowy workspace.

MODEL: workspace → Spaces → pages. A page is a Document, or a Database shown as a
Grid/Board/Calendar/List/Gallery. A Board's columns are a SingleSelect field;
cards are rows. IMPORTANT: a view_id (from get_workspace_folder) is NOT a
database_id — call list_databases to map a view to its database_id before using
row/field tools.

CREATE (clean JSON — the user should never have to set anything up by hand):
create_page, append_blocks, create_database (grid/board/calendar),
create_database_view, add_database_field, create_database_row,
upsert_database_row, create_space, move_page, duplicate_page, trash_page.

EDIT/DELETE ANY ROW (Tier 2 / collab — works even on UI-created rows):
update_row_cells (change cells on any existing row — e.g. move a Board card by
setting its Status cell to the target option id), delete_row (hard-delete a row).

EDIT SCHEMA: update_database_field (rename a column) and delete_database_field
(drop it) — Tier 2/collab, no REST. add_select_option (returns the new option id —
use THAT as the cell value) and delete_select_option manage SingleSelect/MultiSelect
options. rename_page renames a page/database/space; restore_page un-trashes a page.

ROW/CARD DOCUMENTS accept MARKDOWN and render as real blocks: #/##/### headings,
"- "/"1. " lists, "- [ ]" interactive checkboxes, "> " quote, ```lang code,
GFM tables, "---" divider, links, images, $math$. Use markdown for card bodies.

PAGE page_data is a JSON block tree, e.g.
{"type":"page","children":[
  {"type":"heading","data":{"level":1,"delta":[{"insert":"Title"}]}},
  {"type":"paragraph","data":{"delta":[{"insert":"hi ","attributes":{}},
     {"insert":"bold","attributes":{"bold":true}}]}},
  {"type":"todo_list","data":{"delta":[{"insert":"task"}],"checked":false}},
  {"type":"divider"}]}
Block types: paragraph, heading(data.level 1-6), bulleted_list, numbered_list,
todo_list(data.checked), quote, divider, image(data.url). Delta attributes:
bold, italic, underline, strikethrough, code, color, href.

FIELD TYPES (add_database_field): 0=RichText 1=Number 2=DateTime 3=SingleSelect
4=MultiSelect 5=Checkbox 6=URL 7=Checklist 8=LastEditedTime 9=CreatedTime.

EDIT DOCUMENT BLOCKS (Tier 2 / collab): add_block (any type incl. ADVANCED —
callout, toggle_list, quote, code, heading; pass block-specific `data`),
edit_block_text, delete_block. page_id may be a document view id OR a database ROW
id — a row id auto-resolves to the card's BODY document, so this is how you add a
checkbox/sub-task to a Board card. Put per-card checklists in the card BODY, never
in a shared column (a column value shows on every card).

BEST PRACTICE: To update a row in place instead of creating a duplicate, upsert with a
stable pre_hash and reuse that pre_hash on later calls. Keep cells for title/status/
metadata and put long content or checklists in a row's BODY document, never in a shared
column (a column value shows on every row).

AVOID: (1) Trusting an immediate re-read — get_database_row_details reads /row/detail,
a materialized view that LAGS the live data by up to minutes; a write can be correct even
when the re-read still shows the old value, so don't conclude it failed. (2) Guessing a
database_id from a folder view_id (use list_databases). (3) Full-overwriting a document —
the edit tools send merging updates; never PUT a whole collab.

LIMITS: edited/added text is plain (inline bold/links not applied); multi-column
layout and @mentions need specific block/data shapes — attempt via add_block. Not in
AppFlowy at all: web-bookmark card, iframe/Drive embed, "Feed" view. Full guide with
recipes + data model: KNOWLEDGE.md.
"""

# Server logo (three kanban columns on AppFlowy purple). Declared in the MCP
# initialize response and served at /icon.svg. NOTE: Claude.ai currently shows a
# generic globe for all custom connectors regardless — this is for spec
# compliance, other clients, and future support.
ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
    '<rect width="128" height="128" rx="28" fill="#A34AFD"/>'
    '<rect x="30" y="34" width="18" height="60" rx="6" fill="#fff"/>'
    '<rect x="55" y="34" width="18" height="42" rx="6" fill="#fff" fill-opacity="0.9"/>'
    '<rect x="80" y="34" width="18" height="30" rx="6" fill="#fff" fill-opacity="0.8"/>'
    "</svg>"
)
ICON_DATA_URI = (
    "data:image/svg+xml;base64," + base64.b64encode(ICON_SVG.encode()).decode()
)


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


# DNS-rebinding protection guards against browser-driven attacks on the HTTP
# transports. Enabled by default; set MCP_ALLOWED_HOSTS to your public host
# (e.g. mcp.example.com) when behind a reverse proxy, or MCP_DNS_REBINDING_
# PROTECTION=false as an escape hatch if a proxy setup misreports Host.
_dns_protect = os.environ.get("MCP_DNS_REBINDING_PROTECTION", "true").lower() != "false"
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=_dns_protect,
    allowed_hosts=_csv_env("MCP_ALLOWED_HOSTS")
    or ["localhost", "127.0.0.1", "localhost:8000", "127.0.0.1:8000"],
    allowed_origins=_csv_env("MCP_ALLOWED_ORIGINS")
    or ["http://localhost", "http://127.0.0.1"],
)

# streamable_http_path="/" so mounting the app at /mcp yields a clean /mcp/
# endpoint (not the doubled /mcp/mcp you'd get with the default path).
mcp = FastMCP(
    "appflowy-mcp",
    instructions=APPFLOWY_INSTRUCTIONS,
    icons=[{"src": ICON_DATA_URI, "mimeType": "image/svg+xml", "sizes": ["any"]}],
    website_url="https://github.com/Rahulk644/appflowy-mcp-server",
    transport_security=_transport_security,
    streamable_http_path="/",
)

# Tool behavior hints for MCP clients (advisory — they help an agent choose safe
# operations; they are NOT a security boundary). readOnly = performs no writes;
# destructive = makes an irreversible change; idempotent = repeating with the same
# args reaches the same state; openWorld = calls the external AppFlowy service (always
# true here). Presets are applied per tool via @mcp.tool(annotations=...).
_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_CREATE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_DESTRUCTIVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

# ---- Optional OAuth (Google-federated) — active only if GOOGLE_CLIENT_ID set --
OAUTH_ISSUER = os.environ.get("OAUTH_ISSUER", "").rstrip("/")
_oauth_provider = None
if os.environ.get("GOOGLE_CLIENT_ID") and OAUTH_ISSUER:
    from google_oauth import GoogleOAuthProvider

    _oauth_provider = GoogleOAuthProvider(
        issuer=OAUTH_ISSUER,
        google_client_id=os.environ["GOOGLE_CLIENT_ID"],
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        allowed_emails=_csv_env("ALLOWED_EMAILS"),
        store_path=os.environ.get("OAUTH_STORE_PATH") or None,
    )

# Token management
_access_token = None
_refresh_token = None
_token_expires_at = 0


def _allowed_workspaces() -> set[str] | None:
    """Workspace ids this server may touch, or None if unrestricted."""
    ids = _csv_env("ALLOWED_WORKSPACE_IDS")
    return set(ids) if ids else None


def _require_workspace(workspace_id: str) -> None:
    allowed = _allowed_workspaces()
    if allowed is not None and workspace_id not in allowed:
        raise ValueError(
            f"Workspace '{workspace_id}' is not permitted by this server's "
            "ALLOWED_WORKSPACE_IDS policy."
        )


def _login() -> None:
    global _access_token, _refresh_token, _token_expires_at
    email = os.environ.get("APPFLOWY_EMAIL")
    password = os.environ.get("APPFLOWY_PASSWORD")

    if not email or not password:
        raise ValueError("APPFLOWY_EMAIL and APPFLOWY_PASSWORD must be set.")

    url = f"{BASE_URL}/gotrue/token?grant_type=password"
    data = {"email": email, "password": password}

    with httpx.Client() as client:
        res = client.post(url, json=data, headers={"User-Agent": USER_AGENT})
        res.raise_for_status()

        body = res.json()
        _access_token = body.get("access_token")
        _refresh_token = body.get("refresh_token")
        expires_in = body.get("expires_in", 3600)
        _token_expires_at = time.time() + expires_in - 60  # 60s buffer


def _refresh() -> None:
    global _access_token, _refresh_token, _token_expires_at
    if not _refresh_token:
        _login()
        return

    url = f"{BASE_URL}/gotrue/token?grant_type=refresh_token"
    data = {"refresh_token": _refresh_token}

    with httpx.Client() as client:
        res = client.post(url, json=data, headers={"User-Agent": USER_AGENT})
        if res.status_code != 200:
            _login()  # refresh token expired -> re-login
            return

        body = res.json()
        _access_token = body.get("access_token")
        if body.get("refresh_token"):
            _refresh_token = body.get("refresh_token")
        expires_in = body.get("expires_in", 3600)
        _token_expires_at = time.time() + expires_in - 60


def get_auth_headers() -> dict:
    if not _access_token or time.time() >= _token_expires_at:
        try:
            _refresh() if _refresh_token else _login()
        except Exception:
            _login()

    return {
        "Authorization": f"Bearer {_access_token}",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }


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


def _api_call(method: str, path: str, **kwargs) -> httpx.Response:
    """Authenticated AppFlowy API call with actionable errors. `path` is joined to
    BASE_URL. Raises RuntimeError with a specific, agent-readable message on failure so a
    tool error tells the agent how to fix its call rather than dumping a raw traceback."""
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.request(
                method, f"{BASE_URL}{path}", headers=get_auth_headers(), **kwargs
            )
            res.raise_for_status()
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


def _post(path: str, body: dict):
    """POST JSON to the AppFlowy API; return the response's `data` field."""
    return _api_call("POST", path, json=body).json().get("data", "")


# ---- Collab / CRDT layer (Tier 2): edit/delete any block or row --------------
# The REST API is create/append-only. For surgical edits we fetch the object's
# yrs collab, mutate it with pycrdt, and POST the *diff* to the merging web-update
# endpoint (never the full-overwrite PUT, which clobbers concurrent edits).
# collab_type: 0=Document, 1=Database, 5=DatabaseRow.


def _collab_doc(workspace_id: str, object_id: str, collab_type: int) -> Doc:
    """Fetch a collab object and load it into a pycrdt Doc."""
    res = _api_call(
        "GET",
        f"/api/workspace/v1/{workspace_id}/collab/{object_id}",
        params={"collab_type": collab_type},
    )
    doc = Doc()
    doc.apply_update(bytes(res.json()["data"]["doc_state"]))
    return doc


def _collab_web_update(
    workspace_id: str, object_id: str, doc: Doc, state_vector: bytes, collab_type: int
) -> None:
    """POST the yrs update diff (changes since state_vector) — the server merges it."""
    update = doc.get_update(state_vector)
    _api_call(
        "POST",
        f"/api/workspace/v1/{workspace_id}/collab/{object_id}/web-update",
        json={"doc_state": list(update), "collab_type": collab_type},
    )


def _nid(n: int = 10) -> str:
    """AppFlowy-style short id for new blocks/text-map keys."""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(n)
    )


def _row_document_id(row_id: str) -> str:
    """A database row's body document (the card page below the row) is a separate
    collab; AppFlowy derives its object id as uuid5(row_uuid, "document_id")."""
    return str(uuid.uuid5(uuid.UUID(row_id), "document_id"))


def _open_document(workspace_id: str, page_id: str):
    """Load a document collab for block editing. `page_id` may be the document's own
    view id OR a database row id — a row id is transparently resolved to the row's
    body document (so agents can edit a Board card's checklist by its row id).
    Returns (doc, object_id, document_map); pass object_id back to _collab_web_update."""
    doc = _collab_doc(workspace_id, page_id, 0)
    root = doc.get("data", type=Map)
    if "document" not in root:
        page_id = _row_document_id(page_id)
        doc = _collab_doc(workspace_id, page_id, 0)
        root = doc.get("data", type=Map)
    return doc, page_id, root["document"]


def _open_database(workspace_id: str, database_id: str):
    """Load a database collab (type 1); return (doc, root) where root is the DATABASE
    map holding 'fields' (field_id -> field) and 'views' (view_id -> view)."""
    doc = _collab_doc(workspace_id, database_id, 1)
    return doc, doc.get("data", type=Map)["database"]


def _to_yjs(v):
    """Recursively wrap plain JSON into pycrdt shared types for collab insertion."""
    if isinstance(v, dict):
        return Map({k: _to_yjs(x) for k, x in v.items()})
    if isinstance(v, list):
        return Array([_to_yjs(x) for x in v])
    return v


# Select fields store their whole SelectTypeOption as a JSON STRING under
# type_option["<field_type>"]["content"] = {"options":[{id,name,color}], "disable_color"}.
# color must be one of these exact names — an invalid value makes AppFlowy's
# deserialize fail and silently drop every option, so we validate strictly.
_SELECT_TYPES = {3, 4}  # 3=SingleSelect, 4=MultiSelect
SELECT_COLORS = [
    "Purple",
    "Pink",
    "LightPink",
    "Orange",
    "Yellow",
    "Lime",
    "Green",
    "Aqua",
    "Blue",
    "Cream",
    "Mint",
    "Sky",
    "Lilac",
    "Pearl",
    "Sunset",
    "Coral",
    "Sapphire",
    "Moss",
    "Sand",
    "Charcoal",
]


def _read_select(field):
    """Parse a select field's options. Returns (type_key, data) where data is
    {"options":[{id,name,color}], "disable_color":bool}. Raises if not a select."""
    ty = int(field["ty"]) if "ty" in field else -1
    if ty not in _SELECT_TYPES:
        raise ValueError("field is not a SingleSelect/MultiSelect column")
    tk = str(ty)
    content = ""
    to = field["type_option"] if "type_option" in field else None
    if to is not None and tk in to and "content" in to[tk]:
        content = to[tk]["content"]
    data = json.loads(content) if content else {}
    data.setdefault("options", [])
    data.setdefault("disable_color", False)
    return tk, data


def _write_select(field, tk, data):
    """Serialize the options dict back into type_option[tk]["content"] (a JSON string)."""
    if "type_option" not in field:
        field["type_option"] = Map()
    to = field["type_option"]
    if tk not in to:
        to[tk] = Map()
    to[tk]["content"] = json.dumps(data, separators=(",", ":"))


@mcp.tool(annotations=_READ)
def get_workspaces() -> list:
    """Retrieves your AppFlowy workspaces (filtered to ALLOWED_WORKSPACE_IDS if set)."""
    data = _api_call("GET", "/api/workspace").json().get("data", [])
    allowed = _allowed_workspaces()
    if allowed is not None:
        data = [w for w in data if (w.get("workspace_id") or w.get("id")) in allowed]
    return data


@mcp.tool(annotations=_READ)
def get_workspace_folder(workspace_id: str, depth: int = 1) -> dict:
    """
    Fetches the folder structure (pages and databases) of a workspace.
    Useful for finding the database_id to query.
    """
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/folder"
    return _api_call("GET", path, params={"depth": depth}).json().get("data", {})


@mcp.tool(annotations=_READ)
def get_database_fields(workspace_id: str, database_id: str) -> list:
    """Retrieves the fields/columns available in a database."""
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/database/{database_id}/fields"
    return _api_call("GET", path).json().get("data", [])


@mcp.tool(annotations=_READ)
def get_database_row_ids(workspace_id: str, database_id: str) -> list:
    """Retrieves the row IDs in a database."""
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/database/{database_id}/row"
    return _api_call("GET", path).json().get("data", [])


@mcp.tool(annotations=_READ)
def get_database_row_details(
    workspace_id: str, database_id: str, row_ids: str, with_doc: bool = False
) -> list:
    """
    Retrieves detailed content for specific database rows.
    row_ids: comma-separated row UUIDs (e.g. 'uuid1,uuid2').
    """
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/database/{database_id}/row/detail"
    params = {"ids": row_ids}
    if with_doc:
        params["with_doc"] = "true"
    return _api_call("GET", path, params=params).json().get("data", [])


@mcp.tool(annotations=_CREATE)
def create_database_row(workspace_id: str, database_id: str, row_data: str) -> str:
    """
    Creates a new row in a database.
    row_data: JSON string with keys `cells` (field_id/field_name -> value) and
    optional `document` (Markdown). Returns the new row id.
    """
    _require_workspace(workspace_id)
    try:
        data = json.loads(row_data)
    except json.JSONDecodeError as exc:
        raise ValueError("row_data must be a valid JSON string") from exc
    path = f"/api/workspace/{workspace_id}/database/{database_id}/row"
    return _api_call("POST", path, json=data).json().get("data", "")


@mcp.tool(annotations=_WRITE)
def upsert_database_row(workspace_id: str, database_id: str, row_data: str) -> str:
    """
    Creates or updates (upserts) a row — the idempotent way to write. Use it to
    update a row in place (e.g. move a Board card by setting its Status cell) without
    creating duplicates on re-runs.

    row_data: JSON string with keys:
      * pre_hash (str): identifies the row. Reuse an existing row's pre_hash to
        UPDATE it (e.g. to set its Status cell and move it between columns);
        a new pre_hash creates a new row.
      * cells (obj): field_id or field_name -> value.
      * document (str, optional): Markdown body.
    Returns the created/updated row id.
    """
    _require_workspace(workspace_id)
    try:
        data = json.loads(row_data)
    except json.JSONDecodeError as exc:
        raise ValueError("row_data must be a valid JSON string") from exc
    path = f"/api/workspace/{workspace_id}/database/{database_id}/row"
    return _api_call("PUT", path, json=data).json().get("data", "")


@mcp.tool(annotations=_READ)
def list_updated_rows(workspace_id: str, database_id: str, after: str = "") -> list:
    """
    Lists rows updated in a database (change feed) — useful for syncing "what
    changed" into a pipeline.
    after: optional cursor/timestamp forwarded to AppFlowy's /row/updated.
    """
    # ponytail: `after` semantics come straight from AppFlowy's /row/updated;
    # confirm the exact cursor format against a live workspace before relying on it.
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/database/{database_id}/row/updated"
    params = {"after": after} if after else {}
    return _api_call("GET", path, params=params).json().get("data", [])


# ---- Structure & document tools (create/manage pages, databases, blocks) ----

_DB_LAYOUTS = {"grid": 1, "board": 2, "calendar": 3}


@mcp.tool(annotations=_READ)
def list_databases(workspace_id: str) -> list:
    """Lists databases in the workspace with their id and views. Use this to map a
    Board/Grid view to its database_id (a folder view_id is NOT the database_id)."""
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/database"
    return _api_call("GET", path).json().get("data", [])


@mcp.tool(annotations=_CREATE)
def create_page(
    workspace_id: str, parent_view_id: str, name: str, page_data: str = ""
) -> str:
    """Creates a Document page under parent_view_id; returns the new view_id.
    page_data (optional): JSON string of a block tree
    {"type":"page","children":[...]}. Block types: paragraph, heading
    (data.level), bulleted_list, numbered_list, todo_list (data.checked), quote,
    divider, image (data.url); delta attrs: bold/italic/underline/strikethrough/
    code/color/href. For long prose prefer creating a row with a Markdown document."""
    _require_workspace(workspace_id)
    body = {"parent_view_id": parent_view_id, "layout": 0, "name": name}
    if page_data:
        body["page_data"] = json.loads(page_data)
    res = _post(f"/api/workspace/{workspace_id}/page-view", body)
    # this endpoint returns {"view_id","database_id"}; the tool contract is the view_id
    return res["view_id"] if isinstance(res, dict) else res


@mcp.tool(annotations=_CREATE)
def create_database(
    workspace_id: str, parent_view_id: str, name: str, layout: str = "grid"
) -> str:
    """Creates a new database page (layout: grid | board | calendar); returns the
    new view_id. Creates default fields — add more with add_database_field, then
    resolve the database_id via list_databases."""
    _require_workspace(workspace_id)
    if layout not in _DB_LAYOUTS:
        raise ValueError("layout must be one of: grid, board, calendar")
    body = {
        "parent_view_id": parent_view_id,
        "layout": _DB_LAYOUTS[layout],
        "name": name,
    }
    res = _post(f"/api/workspace/{workspace_id}/page-view", body)
    return res["view_id"] if isinstance(res, dict) else res


@mcp.tool(annotations=_CREATE)
def create_database_view(
    workspace_id: str, view_id: str, layout: str, name: str = ""
) -> str:
    """Adds another view (grid | board | calendar) over an EXISTING database's
    data. view_id: any existing view of the target database."""
    _require_workspace(workspace_id)
    if layout not in _DB_LAYOUTS:
        raise ValueError("layout must be one of: grid, board, calendar")
    body = {"layout": _DB_LAYOUTS[layout]}
    if name:
        body["name"] = name
    return _post(
        f"/api/workspace/{workspace_id}/page-view/{view_id}/database-view", body
    )


@mcp.tool(annotations=_CREATE)
def add_database_field(
    workspace_id: str,
    database_id: str,
    name: str,
    field_type: int,
    type_option: str = "",
) -> str:
    """Adds a field/column; returns the new field_id. field_type: 0=RichText
    1=Number 2=DateTime 3=SingleSelect 4=MultiSelect 5=Checkbox 6=URL 7=Checklist.
    type_option (optional): JSON string of type-specific options."""
    _require_workspace(workspace_id)
    body = {"name": name, "field_type": field_type}
    if type_option:
        body["type_option_data"] = json.loads(type_option)
    return _post(f"/api/workspace/{workspace_id}/database/{database_id}/fields", body)


@mcp.tool(annotations=_WRITE)
def update_database_field(
    workspace_id: str,
    database_id: str,
    field_id: str,
    name: str = "",
    type_option: str = "",
) -> str:
    """Renames a field/column and/or replaces its raw type-option data (Tier 2 / collab —
    AppFlowy has no REST endpoint for this). name: the new column name. To add/remove
    SingleSelect/MultiSelect OPTIONS use add_select_option / delete_select_option — NOT
    this. type_option (advanced escape hatch): JSON of the field's raw collab type_option
    map, stored verbatim; note select options live as a JSON string at
    type_option["<ty>"]["content"], so a naive options array here will corrupt the field.
    Does NOT convert the field's data type. Only the given attributes change. Returns
    the field_id."""
    _require_workspace(workspace_id)
    if not name and not type_option:
        raise ValueError("provide name and/or type_option to change")
    doc, root = _open_database(workspace_id, database_id)
    fields = root["fields"]
    if field_id not in fields:
        raise ValueError(f"field {field_id} not found in this database")
    sv = doc.get_state()
    with doc.transaction():
        fld = fields[field_id]
        if name:
            fld["name"] = name
        if type_option:
            fld["type_option"] = _to_yjs(json.loads(type_option))
        fld["last_modified"] = int(time.time())
    _collab_web_update(workspace_id, database_id, doc, sv, 1)
    return field_id


@mcp.tool(annotations=_DESTRUCTIVE)
def delete_database_field(workspace_id: str, database_id: str, field_id: str) -> str:
    """Deletes a field/column (Tier 2 / collab — AppFlowy has no REST endpoint for this).
    Removes it from the schema and from every view's column order. The primary/title
    field cannot be deleted. Rows keep the now-orphaned cell harmlessly. There is no
    field trash, so this is irreversible via the API. Returns the deleted field_id."""
    _require_workspace(workspace_id)
    doc, root = _open_database(workspace_id, database_id)
    fields = root["fields"]
    if field_id not in fields:
        raise ValueError(f"field {field_id} not found in this database")
    if "is_primary" in fields[field_id] and fields[field_id]["is_primary"]:
        raise ValueError("the primary (title) field cannot be deleted")
    sv = doc.get_state()
    with doc.transaction():
        del fields[field_id]
        views = root["views"]
        for vid in list(views.keys()):
            view = views[vid]
            if "field_orders" in view:
                orders = view["field_orders"]
                for i in range(len(orders) - 1, -1, -1):
                    if orders[i]["id"] == field_id:
                        del orders[i]
            # ponytail: also drop the per-view setting; a filter/sort/group that
            # referenced this field is left for the client to ignore (rare, tolerated).
            if "field_settings" in view and field_id in view["field_settings"]:
                del view["field_settings"][field_id]
    _collab_web_update(workspace_id, database_id, doc, sv, 1)
    return field_id


@mcp.tool(annotations=_WRITE)
def add_select_option(
    workspace_id: str,
    database_id: str,
    field_id: str,
    name: str,
    color: str = "Purple",
) -> str:
    """Adds an option to a SingleSelect/MultiSelect column (Tier 2 / collab — AppFlowy
    has no REST for it). Returns the option id — pass THAT id (not the label) as the
    cell value in update_row_cells. Idempotent by name: if an option with this name
    already exists its id is returned unchanged. color must be one of Purple, Pink,
    LightPink, Orange, Yellow, Lime, Green, Aqua, Blue, Cream, Mint, Sky, Lilac, Pearl,
    Sunset, Coral, Sapphire, Moss, Sand, Charcoal (default Purple)."""
    _require_workspace(workspace_id)
    if not name:
        raise ValueError("option name is required")
    if color not in SELECT_COLORS:
        raise ValueError(f"color must be one of: {', '.join(SELECT_COLORS)}")
    doc, root = _open_database(workspace_id, database_id)
    fields = root["fields"]
    if field_id not in fields:
        raise ValueError(f"field {field_id} not found in this database")
    field = fields[field_id]
    tk, data = _read_select(field)
    for opt in data["options"]:
        if opt.get("name") == name:
            return opt["id"]  # idempotent — don't create a duplicate
    existing = {o["id"] for o in data["options"]}
    oid = _nid(4)
    while oid in existing:
        oid = _nid(4)
    sv = doc.get_state()
    with doc.transaction():
        data["options"].append({"id": oid, "name": name, "color": color})
        _write_select(field, tk, data)
    _collab_web_update(workspace_id, database_id, doc, sv, 1)
    return oid


@mcp.tool(annotations=_DESTRUCTIVE)
def delete_select_option(
    workspace_id: str, database_id: str, field_id: str, option: str
) -> str:
    """Removes an option from a SingleSelect/MultiSelect column by its option id OR its
    label/name (Tier 2 / collab). Rows still tagged with it keep the now-orphaned id
    harmlessly (AppFlowy ignores unknown option ids). Returns the removed option id."""
    _require_workspace(workspace_id)
    doc, root = _open_database(workspace_id, database_id)
    fields = root["fields"]
    if field_id not in fields:
        raise ValueError(f"field {field_id} not found in this database")
    field = fields[field_id]
    tk, data = _read_select(field)
    match = next(
        (o for o in data["options"] if o["id"] == option or o.get("name") == option),
        None,
    )
    if match is None:
        raise ValueError(f"no option with id or name {option!r} in this field")
    sv = doc.get_state()
    with doc.transaction():
        data["options"] = [o for o in data["options"] if o["id"] != match["id"]]
        _write_select(field, tk, data)
    _collab_web_update(workspace_id, database_id, doc, sv, 1)
    return match["id"]


@mcp.tool(annotations=_CREATE)
def append_blocks(workspace_id: str, view_id: str, blocks: str) -> str:
    """Appends blocks to the END of a document (append-only — cannot edit/insert
    mid-document). blocks: JSON array of block objects (same shape as create_page
    children)."""
    _require_workspace(workspace_id)
    return _post(
        f"/api/workspace/{workspace_id}/page-view/{view_id}/append-block",
        {"blocks": json.loads(blocks)},
    )


@mcp.tool(annotations=_CREATE)
def create_space(workspace_id: str, name: str, is_private: bool = False) -> str:
    """Creates a top-level Space; returns its view_id."""
    _require_workspace(workspace_id)
    return _post(
        f"/api/workspace/{workspace_id}/space",
        {
            "name": name,
            "space_permission": 1 if is_private else 0,
            "space_icon": "interface_essential/home-3",
            "space_icon_color": "0xFFA34AFD",
        },
    )


@mcp.tool(annotations=_WRITE)
def move_page(
    workspace_id: str, view_id: str, new_parent_view_id: str, prev_view_id: str = ""
) -> str:
    """Moves a page under new_parent_view_id (prev_view_id: optional sibling to
    place it after)."""
    _require_workspace(workspace_id)
    body = {"new_parent_view_id": new_parent_view_id}
    if prev_view_id:
        body["prev_view_id"] = prev_view_id
    return _post(f"/api/workspace/{workspace_id}/page-view/{view_id}/move", body)


@mcp.tool(annotations=_CREATE)
def duplicate_page(workspace_id: str, view_id: str, suffix: str = "") -> str:
    """Duplicates a page and its subtree."""
    _require_workspace(workspace_id)
    body = {"suffix": suffix} if suffix else {}
    return _post(f"/api/workspace/{workspace_id}/page-view/{view_id}/duplicate", body)


@mcp.tool(annotations=_WRITE)
def trash_page(workspace_id: str, view_id: str) -> str:
    """Moves a page to trash (reversible in-app; there is no hard delete via REST)."""
    _require_workspace(workspace_id)
    return _post(f"/api/workspace/{workspace_id}/page-view/{view_id}/move-to-trash", {})


@mcp.tool(annotations=_WRITE)
def rename_page(workspace_id: str, view_id: str, name: str) -> str:
    """Renames any page, database/board, or space (by its view_id). To retitle a Kanban
    CARD, set the row's primary cell via update_row_cells instead — a card is a row,
    not a page."""
    _require_workspace(workspace_id)
    return _post(
        f"/api/workspace/{workspace_id}/page-view/{view_id}/update-name",
        {"name": name},
    )


@mcp.tool(annotations=_WRITE)
def restore_page(workspace_id: str, view_id: str) -> str:
    """Restores a page from trash — the inverse of trash_page."""
    _require_workspace(workspace_id)
    return _post(
        f"/api/workspace/{workspace_id}/page-view/{view_id}/restore-from-trash", {}
    )


@mcp.tool(annotations=_READ)
def get_page(workspace_id: str, view_id: str) -> dict:
    """Gets a page's metadata (name, icon, layout, ...)."""
    _require_workspace(workspace_id)
    path = f"/api/workspace/{workspace_id}/page-view/{view_id}"
    return _api_call("GET", path).json().get("data", {})


@mcp.tool(annotations=_WRITE)
def update_row_cells(
    workspace_id: str, database_id: str, row_id: str, cells: str
) -> str:
    """Updates cells on an EXISTING row — works for ANY row, including ones created
    in the UI (Tier 2 / collab). cells: JSON object {field_id: value}. Values:
    text → string; SingleSelect → the option id (see get_database_fields
    type_option options); Checkbox → "Yes"/"No"; Number/URL → string. Only the
    given cells change. To move a Board card, set its Status field's cell."""
    _require_workspace(workspace_id)
    updates = json.loads(cells)
    doc = _collab_doc(workspace_id, row_id, 5)
    row_cells = doc.get("data", type=Map)["data"]["cells"]
    ftypes = {}
    if any(fid not in row_cells for fid in updates):
        ftypes = {
            f["id"]: f.get("field_type_id", 0)
            for f in get_database_fields(workspace_id, database_id)
        }
    sv = doc.get_state()
    now = int(time.time())
    with doc.transaction():
        for fid, val in updates.items():
            if fid in row_cells:
                row_cells[fid]["data"] = val
                row_cells[fid]["last_modified"] = now
            else:
                row_cells[fid] = Map(
                    {
                        "data": val,
                        "field_type": int(ftypes.get(fid, 0)),
                        "created_at": now,
                        "last_modified": now,
                    }
                )
    _collab_web_update(workspace_id, row_id, doc, sv, 5)
    return row_id


@mcp.tool(annotations=_DESTRUCTIVE)
def delete_row(workspace_id: str, database_id: str, row_id: str) -> str:
    """Deletes a row from a database — works for ANY row, including UI-created ones
    (Tier 2 / collab). Removes it from every view's row_orders and deletes the
    row's collab object. This is a hard delete (not trash)."""
    _require_workspace(workspace_id)
    doc = _collab_doc(workspace_id, database_id, 1)
    views = doc.get("data", type=Map)["database"]["views"]
    sv = doc.get_state()
    removed = 0
    with doc.transaction():
        for vid in list(views.keys()):
            row_orders = views[vid]["row_orders"]
            for i in reversed(range(len(row_orders))):
                if row_orders[i]["id"] == row_id:
                    del row_orders[i]
                    removed += 1
    if removed:
        _collab_web_update(workspace_id, database_id, doc, sv, 1)
    # Best effort: the row is already gone from every view; a failure here only leaves
    # an orphaned collab object, so don't surface it as a tool error.
    try:
        _api_call(
            "DELETE",
            f"/api/workspace/{workspace_id}/collab/{row_id}",
            json={"object_id": row_id, "workspace_id": workspace_id, "collab_type": 5},
        )
    except RuntimeError:
        pass
    return f"deleted row {row_id} (removed from {removed} view order(s))"


@mcp.tool(annotations=_CREATE)
def add_block(
    workspace_id: str,
    page_id: str,
    block_type: str,
    text: str = "",
    data: str = "",
    parent_block_id: str = "",
) -> str:
    """Adds a block to a document (Tier 2 / collab) — including ADVANCED blocks the
    create/markdown paths can't make: callout, toggle_list, quote, heading, code,
    bulleted_list, numbered_list, todo_list, divider, paragraph, etc. Appends to the
    end of the page (or of parent_block_id). Returns the new block id.
    data (optional): JSON of block-specific data, e.g. {"level":2} heading,
    {"icon":"💡"} callout, {"checked":false} todo_list, {"language":"rust"} code.
    page_id = a document's view id, OR a database row id — a row id is auto-resolved
    to the row's body document (this is how you add a checkbox/sub-task to a card)."""
    _require_workspace(workspace_id)
    doc, page_id, d = _open_document(workspace_id, page_id)
    blocks, meta = d["blocks"], d["meta"]
    cmap, tmap = meta["children_map"], meta["text_map"]
    parent = parent_block_id or d["page_id"]
    parent_children_key = blocks[parent]["children"]
    bid, ckey = _nid(), _nid()
    block = {
        "id": bid,
        "ty": block_type,
        "parent": parent,
        "children": ckey,
        "data": data or "{}",
    }
    sv = doc.get_state()
    with doc.transaction():
        cmap[ckey] = Array([])
        if text:
            ext = _nid()
            block["external_id"] = ext
            block["external_type"] = "text"
            tmap[ext] = Text(text)
        blocks[bid] = Map(block)
        cmap[parent_children_key].append(bid)
    _collab_web_update(workspace_id, page_id, doc, sv, 0)
    return bid


@mcp.tool(annotations=_WRITE)
def edit_block_text(workspace_id: str, page_id: str, block_id: str, text: str) -> str:
    """Replaces the text of an existing document block (plain-text replacement).
    page_id may be a document view id or a database row id (auto-resolved)."""
    _require_workspace(workspace_id)
    doc, page_id, d = _open_document(workspace_id, page_id)
    block = d["blocks"][block_id]
    tmap = d["meta"]["text_map"]
    ext = block["external_id"] if "external_id" in block else None
    sv = doc.get_state()
    with doc.transaction():
        if ext and ext in tmap:
            t = tmap[ext]
            if len(t) > 0:
                del t[0 : len(t)]
            t.insert(0, text)
        else:
            ext = _nid()
            block["external_id"] = ext
            block["external_type"] = "text"
            tmap[ext] = Text(text)
    _collab_web_update(workspace_id, page_id, doc, sv, 0)
    return block_id


@mcp.tool(annotations=_DESTRUCTIVE)
def delete_block(workspace_id: str, page_id: str, block_id: str) -> str:
    """Deletes a block from a document (removes it from its parent, plus its text
    and children references). page_id may be a document view id or a row id."""
    _require_workspace(workspace_id)
    doc, page_id, d = _open_document(workspace_id, page_id)
    blocks, cmap, tmap = d["blocks"], d["meta"]["children_map"], d["meta"]["text_map"]
    if block_id not in blocks:
        raise ValueError(f"block {block_id} not found")
    block = blocks[block_id]
    parent = block["parent"] if "parent" in block else ""
    ext = block["external_id"] if "external_id" in block else None
    ckey = block["children"] if "children" in block else None
    sv = doc.get_state()
    with doc.transaction():
        if parent and parent in blocks:
            pkey = blocks[parent]["children"]
            if pkey in cmap:
                arr = cmap[pkey]
                for i in reversed(range(len(arr))):
                    if arr[i] == block_id:
                        del arr[i]
        if ext and ext in tmap:
            del tmap[ext]
        if ckey and ckey in cmap:
            del cmap[ckey]
        del blocks[block_id]
    _collab_web_update(workspace_id, page_id, doc, sv, 0)
    return f"deleted block {block_id}"


# ---- HTTP app (Streamable HTTP + SSE), Bearer-gated -------------------------

_streamable_app = mcp.streamable_http_app()
_sse_app = mcp.sse_app()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Streamable HTTP needs its session manager running for the app's lifetime.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AppFlowy MCP Server", lifespan=lifespan)


_PUBLIC_PREFIXES = (
    "/robots.txt",
    "/icon.svg",
    "/.well-known/",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
    "/auth/google/",
)


@app.middleware("http")
async def verify_token(request: Request, call_next):
    path = request.url.path
    public = any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES)
    secret = os.environ.get("MCP_SECRET_TOKEN")
    if not public and secret:
        auth = request.headers.get("Authorization", "")
        # Bearer header (technical clients) or ?token= (link method for UIs that
        # can't set a header — the token then rides in the URL/logs).
        token = (
            auth[7:]
            if auth.startswith("Bearer ")
            else request.query_params.get("token", "")
        )
        ok = bool(token) and hmac.compare_digest(token, secret)
        if not ok and _oauth_provider and token:
            ok = bool(await _oauth_provider.load_access_token(token))
        if not ok:
            resp = JSONResponse(
                status_code=401,
                content={
                    "detail": "Unauthorized. Use a Bearer token, ?token=, or OAuth sign-in."
                },
            )
            if _oauth_provider:
                resp.headers["WWW-Authenticate"] = (
                    f'Bearer resource_metadata="{OAUTH_ISSUER}'
                    '/.well-known/oauth-protected-resource"'
                )
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
            return resp

    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.get("/robots.txt")
async def robots_txt():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/icon.svg")
async def icon_svg():
    return Response(ICON_SVG, media_type="image/svg+xml")


if _oauth_provider:
    from mcp.server.auth.routes import (
        create_auth_routes,
        create_protected_resource_routes,
    )
    from mcp.server.auth.settings import ClientRegistrationOptions
    from pydantic import AnyHttpUrl

    _issuer = AnyHttpUrl(OAUTH_ISSUER)
    app.router.routes.extend(
        create_auth_routes(
            _oauth_provider,
            _issuer,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=["appflowy"], default_scopes=["appflowy"]
            ),
        )
    )
    app.router.routes.extend(
        create_protected_resource_routes(
            resource_url=_issuer,
            authorization_servers=[_issuer],
            scopes_supported=["appflowy"],
            resource_name="AppFlowy MCP",
        )
    )

    @app.get("/auth/google/callback")
    async def google_callback(request: Request):
        return await _oauth_provider.handle_google_callback(
            request.query_params.get("code", ""),
            request.query_params.get("state", ""),
        )


app.mount("/mcp", _streamable_app)
app.mount("/sse", _sse_app)


if __name__ == "__main__":
    # Run directly for local use over stdio.
    mcp.run(transport="stdio")
