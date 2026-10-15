"""Content-addressed blob storage for original uploads.

A file is stored under the sha256 of its content, which makes deduplication
free and the stored bytes immutable: the same contract uploaded twice takes
space once, and a stored blob can never disagree with its name.

Only original uploads live here. Laws have no binary original on our side and
parsed Docling JSON is derived data.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol

from law_agent.config import settings


class BlobStore(Protocol):
    """What the application needs from a blob store.

    Kept minimal so that a later S3-backed implementation is a drop-in: no
    filesystem paths appear in the protocol.
    """

    def put(self, data: bytes) -> str:
        """Store ``data`` and return its sha256."""
        ...

    def open(self, sha256: str) -> BinaryIO:
        """Open the stored blob for reading."""
        ...

    def exists(self, sha256: str) -> bool: ...

    def delete(self, sha256: str) -> bool:
        """Remove the blob; ``False`` when it was not there."""
        ...


class FilesystemBlobStore:
    """Blobs as files under ``root/ab/cd/abcd...``.

    The two sharding levels keep any single directory to a manageable number of
    entries; a flat directory degrades once uploads reach tens of thousands.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else settings.blob_root

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256[2:4] / sha256

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.path_for(digest)
        if target.exists():
            # Keeps the blob outside the GC sweep's grace period: a deduplicated
            # put writes nothing, and without this the sweep could delete a blob
            # a live document has just started to reference.
            os.utime(target)
            return digest

        target.parent.mkdir(parents=True, exist_ok=True)
        # Written aside and renamed, so the final path never holds a half-written
        # file -- under content addressing that would be a blob whose bytes do
        # not match its name.
        staged = target.with_name(f"{digest}.{os.getpid()}.tmp")
        staged.write_bytes(data)
        staged.replace(target)
        return digest

    def open(self, sha256: str) -> BinaryIO:
        return self.path_for(sha256).open("rb")

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

    def delete(self, sha256: str) -> bool:
        target = self.path_for(sha256)
        if not target.is_file():
            return False
        target.unlink()
        return True

    def iter_blobs(self) -> Iterator[Path]:
        """Every stored blob, staged partial writes excluded."""
        for path in self._root.glob("*/*/*"):
            if path.is_file() and not path.name.endswith(".tmp"):
                yield path


@lru_cache(maxsize=1)
def get_blob_store() -> FilesystemBlobStore:
    return FilesystemBlobStore()
