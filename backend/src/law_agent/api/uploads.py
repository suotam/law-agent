"""Validation of uploaded files, before any byte reaches ingestion.

The gate is the filename extension, not the client-sent MIME type: the MIME
header is whatever the client claims, while the extension is also what
docling-serve itself picks its parser by. The whitelist is docling's set of
text-bearing formats -- images belong in it because scans go through OCR --
and everything else, video and audio above all, is refused before the body
is read into memory.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import HTTPException, UploadFile, status

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".htm",
        ".xhtml",
        ".md",
        ".markdown",
        ".adoc",
        ".asciidoc",
        ".csv",
        # Scanned documents: OCR extracts their text.
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".webp",
    }
)


def read_upload(file: UploadFile) -> bytes:
    """The upload's bytes, once the file passes the type and size gates.

    Raises:
        HTTPException: 415 for an extension outside the whitelist, 413 for a
            body over :data:`MAX_UPLOAD_BYTES`.
    """
    extension = PurePosixPath(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported file type {extension or '(none)'!r}",
        )

    # One byte past the limit is all that is needed to know it was crossed,
    # without ever holding an arbitrarily large body in memory.
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )
    return data
