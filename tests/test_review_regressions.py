"""Regressions found during the v2 maintenance review."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import jsonschema
import pytest
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken

from appflowy_mcp import diagnostics
from appflowy_mcp import server as b
from appflowy_mcp import workflows as w


@pytest.mark.asyncio
async def test_mutation_manifest_never_promises_safe_automatic_retries(monkeypatch):
    monkeypatch.delenv("APPFLOWY_READ_ONLY", raising=False)
    monkeypatch.setenv("APPFLOWY_ENABLE_AI", "true")
    server = MCPServer("manifest-test", version="2.0.0")
    w.register(server)
    tools = await server.list_tools()
    for tool in tools:
        if tool.annotations.read_only_hint:
            assert tool.annotations.idempotent_hint is True
        else:
            assert tool.annotations.idempotent_hint is False, tool.name


@pytest.mark.asyncio
async def test_documented_evaluation_calls_match_the_published_input_schemas():
    server = MCPServer("evaluation-test", version="2.0.0")
    w.register(server)
    schemas = {
        tool.name: tool.model_dump(by_alias=True)["inputSchema"]
        for tool in await server.list_tools()
    }
    cases = (
        ET.parse(Path(__file__).with_name("evaluation.xml")).getroot().findall("case")
    )
    assert len(cases) == 10
    for case in cases:
        tool = case.find("tool")
        jsonschema.validate(json.loads(tool.text), schemas[tool.attrib["name"]])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variable,value",
    [
        ("APPFLOWY_TOOL_PROFILE", "invalid"),
        ("APPFLOWY_BASE_URL", "https://cloud.example:invalid"),
        ("APPFLOWY_BASE_URL", "https://cloud.example/prefix"),
    ],
)
async def test_doctor_skips_network_when_local_configuration_is_invalid(
    monkeypatch, variable, value
):
    monkeypatch.setenv("APPFLOWY_ACCESS_TOKEN", "do-not-print-this")
    monkeypatch.setenv(variable, value)
    network = AsyncMock()
    monkeypatch.setattr(b, "get_workspaces", network)
    report = await diagnostics.diagnose(True)
    assert not report["ok"] and not report["connection_checked"]
    assert "do-not-print-this" not in str(report)
    network.assert_not_awaited()


@pytest.mark.asyncio
async def test_doctor_does_not_report_success_for_an_empty_allowlist_result(
    monkeypatch,
):
    monkeypatch.setenv("APPFLOWY_ACCESS_TOKEN", "fixture")
    monkeypatch.setattr(b, "get_workspaces", AsyncMock(return_value=[]))
    result = await diagnostics.diagnose(True)
    assert result["connection_checked"] and not result["ok"]
    assert any(
        c["name"] == "workspace_access" and not c["ok"] for c in result["checks"]
    )


@pytest.mark.parametrize(
    "value",
    [
        {"timestamp": True},
        {"timestamp": None},
        {"timestamp": "invalid"},
        {"timestamp": float("inf")},
        {"timestamp": 0, "include_time": "false"},
        {"timestamp": 0, "end_timestamp": False},
    ],
)
def test_malformed_dates_are_rejected_before_a_cell_write(value):
    with pytest.raises(ValueError, match="DateTime"):
        w.encode_cells([{"id": "date", "field_type_id": 2}], {"date": value})


@pytest.mark.asyncio
async def test_oauth_access_without_appflowy_scope_is_rejected(monkeypatch):
    provider = type(
        "Provider",
        (),
        {
            "load_access_token": AsyncMock(
                return_value=AccessToken(token="token", client_id="client", scopes=[])
            )
        },
    )()
    monkeypatch.delenv("MCP_SECRET_TOKEN", raising=False)
    monkeypatch.setattr(b, "_oauth_provider", provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=b.app), base_url="http://testserver"
    ) as client:
        assert (
            await client.get(
                "/protected-test", headers={"Authorization": "Bearer token"}
            )
        ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header,status", [("bearer correct", 404), ("BEARER correct", 404)]
)
async def test_bearer_scheme_is_case_insensitive(monkeypatch, header, status):
    monkeypatch.setenv("MCP_SECRET_TOKEN", "correct")
    monkeypatch.setattr(b, "_oauth_provider", None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=b.app), base_url="http://testserver"
    ) as client:
        assert (
            await client.get("/protected-test", headers={"Authorization": header})
        ).status_code == status


@pytest.mark.asyncio
async def test_non_ascii_query_token_is_rejected_without_a_server_error(monkeypatch):
    monkeypatch.setenv("MCP_SECRET_TOKEN", "correct")
    monkeypatch.setattr(b, "_oauth_provider", None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=b.app), base_url="http://testserver"
    ) as client:
        assert (
            await client.get("/protected-test", params={"token": "inválido"})
        ).status_code == 401
