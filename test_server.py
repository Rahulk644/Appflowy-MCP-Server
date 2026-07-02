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
