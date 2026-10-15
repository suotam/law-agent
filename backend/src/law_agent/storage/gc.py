"""Deleting blobs nothing points at any more.

A safety net for a process that dies between ``put()`` and the ``INSERT``, not
the main deletion path -- deleting a document removes its blob directly.

Reference counts deliberately live nowhere: a counter column drifts whenever a
process dies mid-write, while the ``documents`` table is a reference index in
its own right. The caller passes that lookup in as a predicate, which is also
what keeps this module free of any database import.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from law_agent.storage.blobs import FilesystemBlobStore

GRACE_PERIOD = timedelta(hours=24)
"""How long a blob is spared regardless of references.

Without it there is a window between finding a blob unreferenced and unlinking
it, in which another user uploads the same file: the deduplicated ``put()``
writes nothing, and the sweep then deletes a live document's blob. That failure
shows up as missing data, not as an error.
"""


@dataclass(frozen=True, slots=True)
class SweepStats:
    scanned: int
    deleted: int
    kept_referenced: int
    kept_young: int


def sweep_blobs(
    store: FilesystemBlobStore,
    *,
    is_referenced: Callable[[str], bool],
    grace: timedelta = GRACE_PERIOD,
    now: float | None = None,
) -> SweepStats:
    """Delete blobs that nothing references and that are older than ``grace``.

    Args:
        store: Store to sweep.
        is_referenced: Whether any document still points at this sha256.
        grace: Minimum age before a blob may be deleted.
        now: Reference timestamp; defaults to the current time.

    Returns:
        Counts of what was scanned, deleted and kept, and why.
    """
    moment = time.time() if now is None else now
    cutoff = moment - grace.total_seconds()
    scanned = deleted = kept_referenced = kept_young = 0

    for path in store.iter_blobs():
        scanned += 1
        if path.stat().st_mtime > cutoff:
            kept_young += 1
            continue
        if is_referenced(path.name):
            kept_referenced += 1
            continue
        store.delete(path.name)
        deleted += 1

    return SweepStats(
        scanned=scanned,
        deleted=deleted,
        kept_referenced=kept_referenced,
        kept_young=kept_young,
    )
