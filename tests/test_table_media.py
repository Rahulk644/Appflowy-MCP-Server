"""Native table round trips and bounded uploads through the compact interface."""

import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pycrdt import Array, Doc, Map

from appflowy_mcp import api, documents, models, server, workflows


def test_table_survives_collab_encoding_and_markdown_roundtrip():
    markdown = "| Name | Notes |\n| --- | --- |\n| **Alpha** | pipe \\| value<br>second line |\n| Short | |"
    table = documents._md_to_blocks(markdown)[0]
    assert table["type"] == "simple_table"
    assert table["data"]["enable_header_row"] is True
    assert [len(row["children"]) for row in table["children"]] == [2, 2, 2]
    assert table["children"][1]["children"][0]["children"][0]["data"]["delta"] == [
        {"insert": "Alpha", "attributes": {"bold": True}}
    ]
    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["document"] = Map(
            {
                "blocks": Map({"page": Map({"ty": "page", "children": "pc"})}),
                "meta": Map(
                    {"children_map": Map({"pc": Array([])}), "text_map": Map()}
                ),
                "page_id": "page",
            }
        )
        document = root["document"]
        meta = document["meta"]
        meta["children_map"]["pc"].append(
            documents._insert_pd_block(
                document["blocks"],
                meta["children_map"],
                meta["text_map"],
                table,
                "page",
            )
        )
    fresh = Doc()
    fresh.apply_update(doc.get_update())
    rendered = documents._doc_to_markdown(fresh.get("data", type=Map)["document"])
    assert "**Alpha**" in rendered
    assert "pipe \\| value<br>second line" in rendered
    assert documents._md_to_blocks(rendered) == [table]


def upload_request(**kwargs):
    return models.ImportInput(
        workspace_id="ws-allowed",
        parent_view_id="page",
        files=[
            models.FileEntry(
                name="proof.png",
                content_base64=base64.b64encode(b"image bytes").decode(),
                **kwargs,
            )
        ],
    )


@pytest.mark.asyncio
async def test_upload_uses_internal_origin_and_inserts_client_facing_image(
    monkeypatch, mock_appflowy_api
):
    monkeypatch.setattr(api, "BASE_URL", "http://internal.example:8000")
    monkeypatch.setenv("APPFLOWY_PUBLIC_URL", "https://appflowy.example/")
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "data": {"file_id": "blob/one"}})

    mock_appflowy_api(handle)
    insert = AsyncMock(return_value="image-block")
    monkeypatch.setattr(server, "add_block", insert)
    result = await workflows.appflowy_import(upload_request(append_image=True))
    assert result["ok"] is True
    file = result["files"][0]
    assert (
        file["url"]
        == "https://appflowy.example/api/file_storage/ws-allowed/v1/blob/page/blob%2Fone"
    )
    assert file["image_block_id"] == "image-block"
    assert (
        str(seen[0].url)
        == "http://internal.example:8000/api/file_storage/ws-allowed/v1/blob/page"
    )
    assert seen[0].headers["content-type"] == "image/png"
    assert seen[0].content == b"image bytes"
    assert insert.await_args.args == ("ws-allowed", "page", "image")
    assert json.loads(insert.await_args.kwargs["data"]) == {
        "url": file["url"],
        "image_type": 2,
        "name": "proof.png",
        "source": "upload",
    }


@pytest.mark.asyncio
async def test_upload_only_remains_default_and_preserves_file_on_image_failure(
    monkeypatch,
):
    monkeypatch.delenv("APPFLOWY_PUBLIC_URL", raising=False)
    call = AsyncMock(
        return_value=httpx.Response(200, json={"data": {"file_id": "stored"}})
    )
    monkeypatch.setattr(api, "_api_call_async", call)
    insert = AsyncMock(side_effect=RuntimeError("upstream timeout after submission"))
    monkeypatch.setattr(server, "add_block", insert)
    result = await workflows.appflowy_import(upload_request())
    assert result["ok"] is True
    insert.assert_not_called()
    result = await workflows.appflowy_import(upload_request(append_image=True))
    assert result["ok"] is False
    file = result["files"][0]
    assert file["file_id"] == "stored" and file["url"]
    assert file["uploaded"] is True
    assert file["image_insertion_confirmed"] is False
    assert "Do not upload again" in file["retry"]
    assert call.await_count == 2
    insert.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_validates_entire_batch_before_any_write(monkeypatch):
    upload, create = AsyncMock(), AsyncMock()
    monkeypatch.setattr(api, "_api_call_async", upload)
    monkeypatch.setattr(server, "create_page", create)
    monkeypatch.delenv("APPFLOWY_PUBLIC_URL", raising=False)
    request = upload_request(append_image=True, content_type="text/plain")
    request.entries = [models.Entry(path="valid.md", markdown="Should not be created")]
    with pytest.raises(ValueError, match="requires an image"):
        await workflows.appflowy_import(request)
    request = upload_request()
    request.files.append(models.FileEntry(name="bad.bin", content_base64="!invalid!"))
    with pytest.raises(ValueError):
        await workflows.appflowy_import(request)
    monkeypatch.setenv("APPFLOWY_PUBLIC_URL", "https://user:password@example.com")
    with pytest.raises(ValueError, match="origin without credentials"):
        await workflows.appflowy_import(upload_request())
    with pytest.raises(ValueError):
        models.ImportInput(
            workspace_id="ws-allowed",
            parent_view_id="../../other",
            files=upload_request().files,
        )
    upload.assert_not_called()
    create.assert_not_called()


@pytest.mark.asyncio
async def test_read_only_upload_stops_before_network(monkeypatch):
    monkeypatch.setenv("APPFLOWY_READ_ONLY", "true")
    client = AsyncMock()
    monkeypatch.setattr(api, "_get_async_client", client)
    with pytest.raises(PermissionError, match="writes are disabled"):
        await workflows.appflowy_import(upload_request(append_image=True))
    client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": None}, {"data": []}, []])
async def test_malformed_upload_metadata_is_an_explicit_partial_failure(
    monkeypatch, payload
):
    monkeypatch.setattr(
        api,
        "_api_call_async",
        AsyncMock(return_value=httpx.Response(200, json=payload)),
    )
    result = await workflows.appflowy_import(upload_request())
    assert result["ok"] is False
    assert "inspect target files before retrying" in result["files"][0]["error"]


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com/path",
        "file:///tmp",
        "https://example.com?secret=x",
        "https://example.com/#fragment",
        "https://example.com:70000",
        "https://exa mple.com",
        "https://example.com\\other",
    ],
)
def test_public_file_origin_refuses_unsafe_configuration(monkeypatch, origin):
    monkeypatch.setenv("APPFLOWY_PUBLIC_URL", origin)
    with pytest.raises(ValueError, match="http\\(s\\) origin"):
        api.public_file_origin()
