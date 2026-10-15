"""Deterministic chunk identity, shared by every ingestion source.

Lives outside ``laws/`` and ``files/`` because both need it: if it stayed next
to the law models, the file pipeline would have to import from ``laws/`` and the
boundary between the two sources would leak on the first import.
"""

from __future__ import annotations

import uuid

# Stable namespace so that ``point_id`` is reproducible across processes and runs.
_POINT_ID_NAMESPACE = uuid.UUID("6f1a5a6e-9f4a-5d2b-8c31-2b7f5a0d4e11")


def make_point_id(chunk_id: str) -> str:
    """Derive a stable UUID for ``chunk_id`` (vector stores need UUID/int ids)."""
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, chunk_id))
