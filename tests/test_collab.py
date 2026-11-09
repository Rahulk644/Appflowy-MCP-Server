"""Snapshot response shapes, collaboration identities and CRDT values."""

import pytest

from appflowy_mcp import collab


def test_collab_doc_state_tolerates_shapes():
    import base64

    b = collab._collab_doc_state
    # old envelope: {"data": {"doc_state": [ints]}}
    assert b({"data": {"doc_state": [1, 2, 3]}}) == bytes([1, 2, 3])
    # newer: encoded collab nested, envelope stripped
    assert b({"encode_collab": {"doc_state": [4, 5]}}) == bytes([4, 5])
    # newer, still wrapped: envelope + nested encode_collab
    assert b({"data": {"encode_collab": {"doc_state": [6]}}}) == bytes([6])
    # base64-string doc_state (newer builds)
    assert b({"data": {"doc_state": base64.b64encode(b"yjs").decode()}}) == b"yjs"
    # unknown shape -> loud error that names the keys (never a bare KeyError)
    with pytest.raises(RuntimeError, match="doc_state"):
        b({"weird": {"nope": 1}})


def test_row_document_id_derivation():
    # A database row's body document is a separate collab at
    # uuid5(row_uuid, "document_id"); add_block/edit_block_text/delete_block
    # resolve a row id to it. Locked against a synthetic id.
    assert (
        collab._row_document_id("11111111-1111-1111-1111-111111111111")
        == "f972a45d-1193-586f-99a2-89f5406db9fc"
    )


def test_to_yjs_wraps_nested_json():
    # pycrdt nodes can only be read once integrated into a doc, which is exactly how
    # the tool uses _to_yjs (assigned straight into the field). Mirror that here.
    from pycrdt import Array, Doc, Map

    doc = Doc()
    m = doc.get("t", type=Map)
    with doc.transaction():
        m["v"] = collab._to_yjs({"3": {"options": [{"id": "o1", "name": "Open"}]}})
    to = m["v"]
    assert isinstance(to, Map) and isinstance(to["3"], Map)
    assert isinstance(to["3"]["options"], Array)
    assert to["3"]["options"][0]["name"] == "Open"
