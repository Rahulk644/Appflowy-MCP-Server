"""Publication retries must not interpret failures as permission to overwrite."""

import hashlib
import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from scripts import release_artifacts as r

IMAGE = "ghcr.io/rahulk644/appflowy-mcp-server:2.0.2"


@pytest.mark.parametrize("status,expected", [(200, True), (404, False)])
def test_image_probe_checks_manifest_with_a_scoped_public_token(
    monkeypatch, status, expected
):
    calls = []

    def open_url(request, **kwargs):
        calls.append(request)
        if isinstance(request, str):
            assert "repository%3Arahulk644%2Fappflowy-mcp-server%3Apull" in request
            return io.BytesIO(b'{"token":"public-read-only-token"}')
        assert request.get_method() == "HEAD"
        if status == 404:
            raise urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)
        response = io.BytesIO(b"")
        response.status = 200
        return response

    monkeypatch.setattr(r.urllib.request, "urlopen", open_url)
    assert r.image_exists(IMAGE) is expected
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("https://ghcr.io", 401, "Denied", {}, None),
        urllib.error.HTTPError("https://ghcr.io", 429, "Rate limited", {}, None),
        urllib.error.HTTPError("https://ghcr.io", 503, "Unavailable", {}, None),
        urllib.error.URLError("network unavailable"),
    ],
)
def test_image_probe_never_treats_network_or_auth_failure_as_missing(
    monkeypatch, failure
):
    def open_url(request, **kwargs):
        if isinstance(request, str):
            return io.BytesIO(b'{"token":"public-read-only-token"}')
        raise failure

    monkeypatch.setattr(r.urllib.request, "urlopen", open_url)
    with pytest.raises(urllib.error.URLError):
        r.image_exists(IMAGE)


def distributions(tmp_path):
    wheel = tmp_path / "appflowy_mcp_server-2.0.2-py3-none-any.whl"
    source = tmp_path / "appflowy_mcp_server-2.0.2.tar.gz"
    wheel.write_bytes(b"verified wheel bytes")
    source.write_bytes(b"verified source bytes")
    return wheel, source


def mock_release(monkeypatch, assets):
    read = Mock(return_value=json.dumps({"assets": assets}))
    upload = Mock()
    monkeypatch.setattr(r.subprocess, "check_output", read)
    monkeypatch.setattr(r.subprocess, "run", upload)
    return read, upload


def test_identical_release_assets_are_verified_without_upload(monkeypatch, tmp_path):
    files = distributions(tmp_path)
    _, upload = mock_release(
        monkeypatch,
        [
            {"name": file.name, "digest": "sha256:" + r.sha256_file(file)}
            for file in files
        ],
    )
    r.attach_assets(tmp_path, "Rahulk644/Appflowy-MCP-Server", "v2.0.2", "2.0.2")
    upload.assert_not_called()


def test_any_conflicting_asset_prevents_all_uploads(monkeypatch, tmp_path):
    _, source = distributions(tmp_path)
    _, upload = mock_release(
        monkeypatch, [{"name": source.name, "digest": "sha256:wrong"}]
    )
    with pytest.raises(ValueError, match="Refusing to replace"):
        r.attach_assets(tmp_path, "Rahulk644/Appflowy-MCP-Server", "v2.0.2", "2.0.2")
    upload.assert_not_called()


def test_new_release_assets_are_attached_without_clobber(monkeypatch, tmp_path):
    files = distributions(tmp_path)
    _, upload = mock_release(monkeypatch, [])
    r.attach_assets(tmp_path, "Rahulk644/Appflowy-MCP-Server", "v2.0.2", "2.0.2")
    assert upload.call_count == 2
    for call, file in zip(upload.call_args_list, files, strict=True):
        assert str(file) in call.args[0]
        assert "--clobber" not in call.args[0]


def test_mismatched_tag_or_missing_distribution_does_not_contact_github(
    monkeypatch, tmp_path
):
    read, upload = mock_release(monkeypatch, [])
    for tag in ("v0.0.0", "v2.0.2"):
        with pytest.raises(ValueError):
            r.attach_assets(tmp_path, "Rahulk644/Appflowy-MCP-Server", tag, "2.0.2")
    read.assert_not_called()
    upload.assert_not_called()


def test_old_asset_without_digest_is_hashed_anonymously(monkeypatch):
    def open_url(url, **kwargs):
        assert isinstance(url, str)
        return io.BytesIO(b"public bytes")

    monkeypatch.setattr(r.urllib.request, "urlopen", open_url)
    assert (
        r.asset_digest({"browser_download_url": "https://github.com/public/asset"})
        == hashlib.sha256(b"public bytes").hexdigest()
    )
