"""Dependency rejection must happen before a destructive CRDT update."""

import json
from unittest.mock import AsyncMock

import pytest
from pycrdt import Doc, Map

from appflowy_mcp import server as b
from appflowy_mcp.database_schema import field_dependencies, formula_references


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("prop(\"Status\") + prop('count')", {"Status", "count"}),
        ('/* prop("hidden") */ prop /* comment */ ("visible")', {"visible"}),
        ('"prop(\\"hidden\\")" + prop("visible")', {"visible"}),
        ('current.prop("related") + prop("local")', {"local"}),
        ('prop("one") + /* unclosed prop("hidden")', {"one"}),
        ('prop("one") + "unclosed prop(\'hidden\')', {"one"}),
        ('prop("Quote\\" and \\w")', {'Quote" and \\w'}),
        ('otherprop("hidden") + prop(variable)', set()),
    ],
)
def test_formula_reference_contract(expression, expected):
    assert formula_references(expression) == expected


def database_doc(view_settings=None, extra_fields=None):
    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["database"] = b._to_yjs(
            {
                "fields": {
                    "title": {"name": "Title", "ty": 0, "is_primary": True},
                    "target": {"name": "Status", "ty": 3},
                    **(extra_fields or {}),
                },
                "views": {
                    "grid": {
                        "field_orders": [{"id": "title"}, {"id": "target"}],
                        "field_settings": {"target": {"width": 100}},
                        "form_field_settings": {"target": {"required": True}},
                        **(view_settings or {}),
                    }
                },
            }
        )
    return doc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,path",
    [
        (
            {"filters": [{"children": [{"field_id": "target", "condition": 0}]}]},
            "filters",
        ),
        ({"sorts": [{"field_id": "target"}]}, "sorts"),
        ({"groups": [{"field_id": "target", "groups": []}]}, "groups"),
        ({"layout_settings": {"8": {"end_field_id": "target"}}}, "end_field_id"),
        (
            {"layout_settings": {"6": {"visible_field_ids": ["target"]}}},
            "visible_field_ids",
        ),
        ({"layout_settings": {"3": json.dumps({"xFieldId": "target"})}}, "xFieldId"),
        ({"calculations": [{"field_id": "target", "ty": 1}]}, "calculations"),
    ],
)
async def test_rejects_active_view_dependencies_without_mutating(
    monkeypatch, settings, path
):
    doc = database_doc(settings)
    write = AsyncMock()
    monkeypatch.setattr(b, "_collab_doc", AsyncMock(return_value=doc))
    monkeypatch.setattr(b, "_collab_web_update", write)
    before = doc.get_update()
    with pytest.raises(ValueError, match=path):
        await b.delete_database_field("ws-allowed", "database", "target")
    assert doc.get_update() == before
    write.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", ['prop("target")', 'prop("Status") * 2'])
async def test_rejects_formula_dependencies_by_id_or_name(monkeypatch, expression):
    doc = database_doc(
        extra_fields={
            "formula": {
                "name": "Computed",
                "ty": 19,
                "type_option": {"19": {"expression": expression}},
            }
        }
    )
    monkeypatch.setattr(b, "_collab_doc", AsyncMock(return_value=doc))
    write = AsyncMock()
    monkeypatch.setattr(b, "_collab_web_update", write)
    before = doc.get_update()
    with pytest.raises(ValueError, match="field:formula.formula"):
        await b.delete_database_field("ws-allowed", "database", "target")
    assert doc.get_update() == before
    write.assert_not_called()


def test_rollup_dependency_and_formula_id_precedence():
    doc = database_doc(
        extra_fields={
            "rollup": {
                "ty": 16,
                "type_option": {"16": {"relation_field_id": "target"}},
            },
            "Status": {"name": "Other", "ty": 0},
            "formula": {
                "ty": 19,
                "type_option": {"19": {"expression": 'prop("Status")'}},
            },
        }
    )
    assert field_dependencies(
        doc.get("data", type=Map)["database"].to_py(), "target"
    ) == ["field:rollup.type_option.16.relation_field_id"]


@pytest.mark.asyncio
async def test_unreferenced_field_deletion_removes_direct_settings_only(monkeypatch):
    doc = database_doc({"filters": [{"field_id": "title", "content": "target"}]})
    monkeypatch.setattr(b, "_collab_doc", AsyncMock(return_value=doc))
    write = AsyncMock()
    monkeypatch.setattr(b, "_collab_web_update", write)
    await b.delete_database_field("ws-allowed", "database", "target")
    root = doc.get("data", type=Map)["database"]
    assert "target" not in root["fields"]
    view = root["views"]["grid"]
    assert view["field_orders"].to_py() == [{"id": "title"}]
    assert "target" not in view["field_settings"]
    assert "target" not in view["form_field_settings"]
    assert view["filters"][0]["content"] == "target"
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_relation_deletion_delegates_reciprocal_cleanup_to_appflowy(monkeypatch):
    doc = database_doc(extra_fields={"relation": {"ty": 10}})
    monkeypatch.setattr(b, "_collab_doc", AsyncMock(return_value=doc))
    write = AsyncMock()
    monkeypatch.setattr(b, "_collab_web_update", write)
    with pytest.raises(ValueError, match="reciprocal"):
        await b.delete_database_field("ws-allowed", "database", "relation")
    write.assert_not_called()
