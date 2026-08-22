"""Uploading a LOCAL file from the terminal.

The rule this file defends: bytes never travel through the model. A tool call
that inlines a megabyte of base64 is truncated by the provider before it is
ever sent, and the upload fails in a way that looks like the file vanished. So
the client reads the file off disk itself and only ids come back.

The id that matters afterwards is document_id, NOT file_id: file_id addresses
File Reader's own record, document_id addresses the stored bytes. Placing a
file into another extension means passing {"document_id": N}, which the
gateway inflates into real bytes on the way in.
"""
import base64
import json

import httpx
import pytest
import respx

from imperal_mcp.config import Config
from imperal_mcp.client import ImperalClient, ImperalError

CFG = Config(api_url="http://gw", token="jwt-abc")


def _me():
    respx.get("http://gw/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"imperal_id": "imp_u_1"})
    )


@respx.mock
@pytest.mark.asyncio
async def test_upload_sends_the_bytes_to_file_reader(tmp_path):
    _me()
    call = respx.post("http://gw/v1/extensions/file-reader/call").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {
            "items": [{"file_id": "f1", "document_id": 42, "status": "ready"}]}})
    )
    f = tmp_path / "photo.jpeg"
    f.write_bytes(b"\xff\xd8\xff-not-really-a-jpeg")

    out = await ImperalClient(CFG).upload_file(str(f))

    body = json.loads(call.calls.last.request.read().decode())
    assert body["function"] == "receive_files"
    item = body["params"]["files"][0]
    assert base64.b64decode(item["data_base64"]) == b"\xff\xd8\xff-not-really-a-jpeg"
    assert item["name"] == "photo.jpeg"
    assert item["mime_type"] == "image/jpeg", "mime is guessed so the engine can extract"
    # document_id is what makes the file placeable anywhere.
    assert out["document_id"] == 42
    assert out["filename"] == "photo.jpeg"


@respx.mock
@pytest.mark.asyncio
async def test_a_missing_file_is_named_not_swallowed(tmp_path):
    with pytest.raises(ImperalError, match="no such file"):
        await ImperalClient(CFG).upload_file(str(tmp_path / "nope.txt"))


@respx.mock
@pytest.mark.asyncio
async def test_an_oversized_file_is_refused_before_it_is_uploaded(tmp_path, monkeypatch):
    """The ceiling must be checked locally: the alternative is uploading tens of
    megabytes and being told 413 by nginx after the whole body has travelled."""
    import imperal_mcp.client as mod
    monkeypatch.setattr(mod, "_UPLOAD_MAX_BYTES", 10)
    route = respx.post("http://gw/v1/extensions/file-reader/call")
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 50)

    with pytest.raises(ImperalError, match="ceiling"):
        await ImperalClient(CFG).upload_file(str(f))
    assert not route.called, "nothing may be sent once the file is known to be too big"


@respx.mock
@pytest.mark.asyncio
async def test_an_empty_result_fails_loud(tmp_path):
    """A rejected upload that returns quietly becomes an EMPTY attachment three
    steps later, with nothing pointing back at the upload as the cause."""
    _me()
    respx.post("http://gw/v1/extensions/file-reader/call").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {
            "items": [], "rejected": [{"reason": "quota exceeded"}]}})
    )
    f = tmp_path / "a.txt"
    f.write_bytes(b"hi")

    with pytest.raises(ImperalError, match="quota exceeded"):
        await ImperalClient(CFG).upload_file(str(f))


@respx.mock
@pytest.mark.asyncio
async def test_upload_gets_a_longer_timeout_than_a_json_call(tmp_path, monkeypatch):
    """Tens of megabytes plus the engine ingest behind the call do not fit the
    60s default; a too-short timeout looks exactly like a lost file."""
    _me()
    seen = {}
    real = httpx.AsyncClient.__init__

    def spy(self, *a, **kw):
        seen["timeout"] = kw.get("timeout")
        return real(self, *a, **kw)

    respx.post("http://gw/v1/extensions/file-reader/call").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {
            "items": [{"file_id": "f1", "document_id": 7}]}})
    )
    f = tmp_path / "a.txt"
    f.write_bytes(b"hi")
    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy)
    await ImperalClient(CFG).upload_file(str(f))
    assert seen["timeout"] and seen["timeout"] > 60
