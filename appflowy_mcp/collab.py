"""Local collaboration decoding and CRDT value/identity helpers.

Network access and incremental upload remain in the async backend.
"""

import base64
import secrets
import string
import uuid
from importlib.metadata import version

from pycrdt import Array, Doc, Map


def _collab_doc_state(payload) -> bytes:
    """Extract the yrs `doc_state` bytes from AppFlowy's collab GET response.

    AppFlowy Cloud has changed this response shape across releases, so be tolerant:
    the body may or may not be wrapped in an `AppResponse` `{code,message,data}`
    envelope, the encoded collab may sit under `encode_collab`/`encoded_collab` or at
    the top level, and `doc_state` is a byte array (list[int]) in older builds or a
    base64 string in newer ones. Unknown shapes raise an error containing only the
    response keys so maintainers can identify contract changes without logging content.
    """
    body = payload.get("data", payload) if isinstance(payload, dict) else payload
    node = body
    if isinstance(node, dict):
        for key in ("encode_collab", "encoded_collab", "encode_collab_v1", "collab"):
            if isinstance(node.get(key), dict):
                node = node[key]
                break
    ds = node.get("doc_state") if isinstance(node, dict) else None
    if ds is None and isinstance(body, dict):
        ds = body.get("doc_state")
    if ds is None:
        shape = (
            list(payload.keys())
            if isinstance(payload, dict)
            else type(payload).__name__
        )
        raise RuntimeError(
            f"AppFlowy collab response has no doc_state (response keys={shape}); "
            "the collab endpoint shape changed — update _collab_doc_state()."
        )
    return base64.b64decode(ds) if isinstance(ds, str) else bytes(ds)


class CollabDecodeError(RuntimeError):
    """An incompatible snapshot must never turn into an empty document write."""


def _decode_collab(state: bytes, collab_type: int) -> Doc:
    doc = Doc()
    try:
        doc.apply_update(state)
    except (ValueError, RuntimeError) as exc:
        raise CollabDecodeError(
            f"Cannot decode AppFlowy collab type {collab_type} with pycrdt {version('pycrdt')}; "
            "no write was sent. Use the supported dependency pin and attach a disposable "
            "snapshot to a compatibility report before upgrading."
        ) from exc
    return doc


def _nid(n: int = 10) -> str:
    """AppFlowy-style short id for new blocks/text-map keys."""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(n)
    )


def _row_document_id(row_id: str) -> str:
    """A database row's body document (the card page below the row) is a separate
    collab; AppFlowy derives its object id as uuid5(row_uuid, "document_id")."""
    return str(uuid.uuid5(uuid.UUID(row_id), "document_id"))


def _to_yjs(v):
    """Recursively wrap plain JSON into pycrdt shared types for collab insertion."""
    if isinstance(v, dict):
        return Map({k: _to_yjs(x) for k, x in v.items()})
    if isinstance(v, list):
        return Array([_to_yjs(x) for x in v])
    return v
