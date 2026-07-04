"""Smoke tests for the security-critical logic: Bearer auth gate, workspace
guard, and that both HTTP transports boot cleanly."""

import os

import pytest

os.environ.setdefault("MCP_SECRET_TOKEN", "test-secret-123")
os.environ.setdefault("ALLOWED_WORKSPACE_IDS", "ws-allowed")
os.environ.setdefault("MCP_ALLOWED_HOSTS", "testserver")

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_workspace_guard_blocks_other_workspaces():
    server._require_workspace("ws-allowed")  # allowed -> no raise
    with pytest.raises(ValueError):
        server._require_workspace("ws-other")


def test_workspace_guard_unrestricted_when_unset(monkeypatch):
    monkeypatch.delenv("ALLOWED_WORKSPACE_IDS", raising=False)
    assert server._allowed_workspaces() is None
    server._require_workspace("anything")  # unrestricted -> no raise


def test_auth_middleware_and_transports_boot():
    # TestClient context manager runs lifespan -> proves the Streamable HTTP
    # session manager (and both mounts) start without error.
    with TestClient(server.app) as client:
        assert client.get("/robots.txt").status_code == 200  # always open
        assert client.get("/nope").status_code == 401  # no token
        assert (
            client.get("/nope", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )  # wrong token
        # correct token passes the auth gate (404 from routing, not 401)
        assert (
            client.get(
                "/nope", headers={"Authorization": "Bearer test-secret-123"}
            ).status_code
            == 404
        )
        # link method: token as ?token= query param
        assert client.get("/nope?token=test-secret-123").status_code == 404
        assert client.get("/nope?token=wrong").status_code == 401


def test_row_document_id_derivation():
    # A database row's body document is a separate collab at
    # uuid5(row_uuid, "document_id"); add_block/edit_block_text/delete_block
    # resolve a row id to it. Locked against a synthetic id.
    assert (
        server._row_document_id("11111111-1111-1111-1111-111111111111")
        == "f972a45d-1193-586f-99a2-89f5406db9fc"
    )


def test_to_yjs_wraps_nested_json():
    # pycrdt nodes can only be read once integrated into a doc, which is exactly how
    # the tool uses _to_yjs (assigned straight into the field). Mirror that here.
    from pycrdt import Array, Doc, Map

    doc = Doc()
    m = doc.get("t", type=Map)
    with doc.transaction():
        m["v"] = server._to_yjs({"3": {"options": [{"id": "o1", "name": "Open"}]}})
    to = m["v"]
    assert isinstance(to, Map) and isinstance(to["3"], Map)
    assert isinstance(to["3"]["options"], Array)
    assert to["3"]["options"][0]["name"] == "Open"


def _synthetic_db_doc():
    """A database collab shaped like AppFlowy's: data.database.{fields,views}."""
    from pycrdt import Array, Doc, Map

    doc = Doc()
    data = doc.get("data", type=Map)
    with doc.transaction():
        data["database"] = Map(
            {
                "fields": Map(
                    {
                        "F1": Map({"id": "F1", "name": "Title", "is_primary": True}),
                        "F2": Map({"id": "F2", "name": "Status", "ty": 3}),
                    }
                ),
                "views": Map(
                    {
                        "V1": Map(
                            {
                                "field_orders": Array(
                                    [Map({"id": "F1"}), Map({"id": "F2"})]
                                ),
                                "field_settings": Map(
                                    {"F1": Map({"w": 1}), "F2": Map({"w": 2})}
                                ),
                            }
                        )
                    }
                ),
            }
        )
    return doc


def test_field_update_and_delete_mutate_collab(monkeypatch):
    # Exercise the real tools against a synthetic doc with the network stubbed out.
    from pycrdt import Map

    doc = _synthetic_db_doc()
    monkeypatch.setattr(server, "_collab_doc", lambda ws, oid, ct: doc)
    monkeypatch.setattr(server, "_collab_web_update", lambda *a, **k: None)
    root = doc.get("data", type=Map)["database"]

    server.update_database_field("ws-allowed", "db", "F2", name="State")
    assert root["fields"]["F2"]["name"] == "State"

    server.delete_database_field("ws-allowed", "db", "F2")
    assert "F2" not in root["fields"]
    assert [o["id"] for o in list(root["views"]["V1"]["field_orders"])] == ["F1"]
    assert "F2" not in root["views"]["V1"]["field_settings"]

    with pytest.raises(ValueError):  # primary/title field is protected
        server.delete_database_field("ws-allowed", "db", "F1")
    with pytest.raises(ValueError):  # unknown field id
        server.update_database_field("ws-allowed", "db", "NOPE", name="x")


def test_select_option_add_and_delete(monkeypatch):
    # F2 is a SingleSelect (ty=3) with no options yet.
    import json

    from pycrdt import Map

    doc = _synthetic_db_doc()
    monkeypatch.setattr(server, "_collab_doc", lambda ws, oid, ct: doc)
    monkeypatch.setattr(server, "_collab_web_update", lambda *a, **k: None)
    root = doc.get("data", type=Map)["database"]

    oid = server.add_select_option("ws-allowed", "db", "F2", "Blocked", color="Blue")
    assert isinstance(oid, str) and len(oid) == 4
    assert (
        server.add_select_option("ws-allowed", "db", "F2", "Blocked") == oid
    )  # idempotent

    # Options persist as a JSON STRING under type_option["3"]["content"].
    data = json.loads(root["fields"]["F2"]["type_option"]["3"]["content"])
    assert [o["name"] for o in data["options"]] == ["Blocked"]
    assert data["options"][0]["color"] == "Blue"

    with pytest.raises(ValueError):  # bad color would wipe options in AppFlowy
        server.add_select_option("ws-allowed", "db", "F2", "X", color="Neon")
    with pytest.raises(ValueError):  # F1 is not a select column
        server.add_select_option("ws-allowed", "db", "F1", "X")

    assert server.delete_select_option("ws-allowed", "db", "F2", "Blocked") == oid
    data = json.loads(root["fields"]["F2"]["type_option"]["3"]["content"])
    assert data["options"] == []
    with pytest.raises(ValueError):  # no such option
        server.delete_select_option("ws-allowed", "db", "F2", "ghost")


def _synthetic_row_doc(data0="old"):
    from pycrdt import Doc, Map

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["data"] = Map(
            {"cells": Map({"F1": Map({"data": data0, "field_type": 0})})}
        )
    return doc


def test_update_row_cells_confirms_and_creates_new_cell(monkeypatch):
    from pycrdt import Map

    doc = _synthetic_row_doc()
    monkeypatch.setattr(server, "_collab_doc", lambda ws, oid, ct: doc)
    monkeypatch.setattr(server, "_collab_web_update", lambda *a, **k: None)
    monkeypatch.setattr(server, "_field_types", lambda ws, db: {"F2": 3})
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    out = server.update_row_cells(
        "ws-allowed", "db", "row1", '{"F1": "new", "F2": "opt1"}'
    )
    assert out == "row1"
    cells = doc.get("data", type=Map)["data"]["cells"]
    assert cells["F1"]["data"] == "new"
    # a brand-new cell is tagged with the type from _field_types (the collab), not 0
    assert cells["F2"]["data"] == "opt1" and cells["F2"]["field_type"] == 3


def test_update_row_cells_raises_when_write_never_confirms(monkeypatch):
    from pycrdt import Map

    doc = _synthetic_row_doc()
    monkeypatch.setattr(server, "_collab_doc", lambda ws, oid, ct: doc)

    def revert(*a, **k):  # simulate a write that doesn't actually stick
        with doc.transaction():
            doc.get("data", type=Map)["data"]["cells"]["F1"]["data"] = "old"

    monkeypatch.setattr(server, "_collab_web_update", revert)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="did not confirm"):
        server.update_row_cells("ws-allowed", "db", "row1", '{"F1": "new"}')


def test_api_call_actionable_error(monkeypatch):
    # A non-2xx from AppFlowy must surface as a specific, agent-readable message
    # (not a bare traceback), with a hint about what to fix.
    import httpx

    def handler(_request):
        return httpx.Response(404, text="object not found")

    real_client = httpx.Client  # capture before patching to avoid recursion
    monkeypatch.setattr(
        server.httpx,
        "Client",
        lambda **k: real_client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        server, "get_auth_headers", lambda: {"Authorization": "Bearer x"}
    )

    with pytest.raises(RuntimeError) as ei:
        server._api_call("GET", "/api/workspace/x/database/y/fields")
    msg = str(ei.value)
    assert "AppFlowy API 404" in msg
    assert "database_id" in msg  # the 404 hint steers toward list_databases
    assert "object not found" in msg  # includes the server's own words


def test_oauth_store_persists_across_instances(tmp_path):
    # Tokens must survive a restart: a fresh provider pointed at the same store
    # file reloads what a prior instance saved (this is what stops re-sign-in).
    from google_oauth import GoogleOAuthProvider
    from mcp.server.auth.provider import AccessToken

    path = str(tmp_path / "oauth.json")
    p = GoogleOAuthProvider(
        "https://mcp.example.com", "cid", "sec", ["a@b.com"], store_path=path
    )
    p.access["tok1"] = AccessToken(
        token="tok1", client_id="c1", scopes=["appflowy"], expires_at=9999999999
    )
    p._save()

    p2 = GoogleOAuthProvider(
        "https://mcp.example.com", "cid", "sec", ["a@b.com"], store_path=path
    )
    assert "tok1" in p2.access
    assert p2.access["tok1"].client_id == "c1"
