"""Storage of original uploaded files, outside the vector store.

Knows nothing about the database: the GC sweep is handed a reference predicate
rather than a session, so this package stays swappable for S3 on its own.
"""

from law_agent.storage.blobs import BlobStore, FilesystemBlobStore, get_blob_store
from law_agent.storage.gc import GRACE_PERIOD, SweepStats, sweep_blobs

__all__ = [
    "GRACE_PERIOD",
    "BlobStore",
    "FilesystemBlobStore",
    "SweepStats",
    "get_blob_store",
    "sweep_blobs",
]
