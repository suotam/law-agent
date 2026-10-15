"""Tests for the docling-serve HTTP client, against a mocked transport."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from law_agent.ingestion.files.client import DoclingClient, DoclingError

# Every other field of a DoclingDocument has a default, so this is the smallest
# payload that validates. Captured from docling-core rather than invented.
_MINIMAL_DOC = {
    "schema_name": "DoclingDocument",
    "version": "1.10.0",
    "name": "smlouva",
}

_Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: _Handler) -> DoclingClient:
    return DoclingClient(transport=httpx.MockTransport(handler))


def _success(request: httpx.Request) -> httpx.Response:  # noqa: ARG001 - handler signature
    return httpx.Response(
        200, json={"document": {"json_content": _MINIMAL_DOC}, "status": "success"}
    )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "smlouva.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def test_parse_posts_the_file_to_the_convert_endpoint(source: Path) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return _success(request)

    _client(handler).parse(source)

    assert captured["url"].endswith("/v1/convert/file")
    assert "smlouva.pdf" in captured["body"]


def test_parse_requests_czech_tesseract_ocr(source: Path) -> None:
    """The default preset is 'auto', which picks rapidocr -- not what we want."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return _success(request)

    _client(handler).parse(source)
    body = captured["body"]

    assert "tesseract" in body
    assert body.count("ocr_lang") == 2  # ces and eng are sent as separate parts
    assert "ces" in body
    assert "json" in body  # to_formats


def test_parse_returns_a_docling_document(source: Path) -> None:
    document = _client(_success).parse(source)

    assert document.name == "smlouva"


def test_failure_status_raises_docling_error(source: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001 - handler signature
        return httpx.Response(
            200, json={"document": {}, "status": "failure", "errors": ["ocr crashed"]}
        )

    with pytest.raises(DoclingError, match="ocr crashed"):
        _client(handler).parse(source)


def test_missing_json_content_raises_docling_error(source: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001 - handler signature
        return httpx.Response(200, json={"document": {"md_content": "# hi"}, "status": "success"})

    with pytest.raises(DoclingError, match="no json_content"):
        _client(handler).parse(source)


def test_http_error_raises_docling_error(source: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001 - handler signature
        return httpx.Response(503, text="service unavailable")

    with pytest.raises(DoclingError, match="request failed"):
        _client(handler).parse(source)


def test_timeout_raises_docling_error(source: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(DoclingError, match="timed out"):
        _client(handler).parse(source)


def test_missing_file_raises_before_any_request(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001 - handler signature
        raise AssertionError("the client must not call the service for a missing file")

    with pytest.raises(FileNotFoundError):
        _client(handler).parse(tmp_path / "chybi.pdf")


def test_parse_bytes_needs_no_file_on_disk() -> None:
    """An upload arrives as bytes; there is no path to read."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return _success(request)

    document = _client(handler).parse_bytes(b"%PDF-1.7", filename="smlouva.pdf")

    assert document.name == "smlouva"
    assert "smlouva.pdf" in captured["body"]
