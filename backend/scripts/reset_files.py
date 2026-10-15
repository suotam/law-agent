"""Empty both file namespaces, in Qdrant and in Postgres.

    uv run scripts/reset_files.py --dry-run
    uv run scripts/reset_files.py --yes

A one-off for the size-first chunking switch: chunk ids are derived from the
chunk index, so every id moves and an incremental update has nothing to salvage.

Both stores have to go. ``ingest_files.py`` turns away a file whose content is
already in ``documents``, so leaving those rows behind would make the re-ingest
skip everything and leave the index empty. Orphaned blobs are left to GC.

Laws are untouched.
"""

from __future__ import annotations

import argparse
import sys

from qdrant_client import models
from sqlalchemy import delete, func, select

from law_agent.config import settings
from law_agent.db import session_scope
from law_agent.db.models import Document
from law_agent.documents import Namespace
from law_agent.indexing.qdrant_store import get_qdrant_client

_NAMESPACES = [str(Namespace.ORG_FILES), str(Namespace.USER_FILES)]

_FILTER = models.Filter(
    must=[models.FieldCondition(key="namespace", match=models.MatchAny(any=_NAMESPACES))]
)


def count_points() -> int:
    client = get_qdrant_client()
    return client.count(
        collection_name=settings.qdrant_collection, count_filter=_FILTER, exact=True
    ).count


def count_rows() -> int:
    with session_scope() as session:
        statement = (
            select(func.count()).select_from(Document).where(Document.namespace.in_(_NAMESPACES))
        )
        return session.execute(statement).scalar_one()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report what would be deleted")
    parser.add_argument("--yes", action="store_true", help="required for a real run")
    args = parser.parse_args(argv)

    points, rows = count_points(), count_rows()
    print(f"{points} Qdrant points and {rows} documents rows in {', '.join(_NAMESPACES)}")

    if args.dry_run:
        return 0
    if not args.yes:
        print("refusing to delete without --yes", file=sys.stderr)
        return 2

    get_qdrant_client().delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(filter=_FILTER),
        wait=True,
    )
    with session_scope() as session:
        session.execute(delete(Document).where(Document.namespace.in_(_NAMESPACES)))
        session.commit()

    print(f"deleted; {count_points()} points and {count_rows()} rows remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
