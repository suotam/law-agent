"""HTTP client for docling-serve: file in, ``DoclingDocument`` out."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Self

import httpx
from docling_core.types.doc.document import DoclingDocument

from law_agent.config import settings

_CONVERT_PATH = "/v1/convert/file"

# Sent as multipart form fields; a list value becomes one repeated field, which
# is how the API takes several OCR languages.
#
# ``ocr_preset`` must be explicit: its default, "auto", selects rapidocr, which
# has no Czech model here. ``ocr_engine`` does the same thing but is deprecated.
#
# OCR runs only over bitmap regions (``force_ocr=false``): digitally created
# PDFs keep their exact text layer and only scans go through Tesseract. Forcing
# OCR everywhere would be slower and less accurate on most documents a law firm
# handles.
_CONVERT_OPTIONS: dict[str, str | list[str]] = {
    "to_formats": "json",
    "do_ocr": "true",
    "force_ocr": "false",
    "ocr_preset": "tesseract",
    "ocr_lang": ["ces", "eng"],
    "table_mode": "accurate",
}

# Scanned pages OCR at seconds per page on CPU, and a whole document is parsed
# in a single synchronous request.
DEFAULT_TIMEOUT = 600.0

_OK_STATUSES = frozenset({"success", "partial_success"})


class DoclingError(RuntimeError):
    """docling-serve could not parse the document.

    Wraps transport failures, HTTP errors and per-document conversion failures
    alike, so that callers never have to know the parser speaks HTTP.
    """


class DoclingClient:
    """Parses documents through a running docling-serve instance."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url or settings.docling_url,
            timeout=timeout,
            transport=transport,
        )

    def parse(self, path: Path) -> DoclingDocument:
        """Convert one file on disk into a :class:`DoclingDocument`.

        Raises:
            FileNotFoundError: ``path`` does not exist.
            DoclingError: the service was unreachable, timed out, or reported a
                conversion failure.
        """
        if not path.is_file():
            msg = f"no such file: {path}"
            raise FileNotFoundError(msg)
        return self.parse_bytes(path.read_bytes(), filename=path.name)

    def parse_bytes(self, data: bytes, *, filename: str) -> DoclingDocument:
        """Convert in-memory bytes into a :class:`DoclingDocument`.

        The upload path: a file posted through the web UI never touches disk
        before it is parsed and stored as a blob.

        Raises:
            DoclingError: the service was unreachable, timed out, or reported a
                conversion failure.
        """
        payload = self._post(data, filename)
        content = payload.get("document", {}).get("json_content")
        if not content:
            msg = f"docling-serve returned no json_content for {filename}"
            raise DoclingError(msg)
        return DoclingDocument.model_validate(content)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _post(self, data: bytes, filename: str) -> dict[str, Any]:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {"files": (filename, data, mime)}
        try:
            response = self._client.post(_CONVERT_PATH, files=files, data=_CONVERT_OPTIONS)
            response.raise_for_status()
        except httpx.TimeoutException as error:
            msg = f"docling-serve timed out while parsing {filename}"
            raise DoclingError(msg) from error
        except httpx.HTTPError as error:
            msg = f"docling-serve request failed for {filename}: {error}"
            raise DoclingError(msg) from error

        payload: dict[str, Any] = response.json()
        if payload.get("status") not in _OK_STATUSES:
            errors = "; ".join(str(e) for e in payload.get("errors", [])) or "unknown error"
            msg = f"docling-serve failed to parse {filename}: {errors}"
            raise DoclingError(msg)
        return payload
