"""Postgres access: engine, session and repositories.

``ingestion``, ``indexing`` and ``retrieval`` never import from here -- they
keep working against their existing contracts (``ChunkLike``, ``index_chunks``,
``prune_orphans``).
"""

from law_agent.db.engine import get_engine, get_sessionmaker, session_scope
from law_agent.db.repositories import (
    AclRepository,
    ConversationRepository,
    DocumentRepository,
    FolderRepository,
    GroupRepository,
    MessageRepository,
    RoleRepository,
    UserRepository,
)

__all__ = [
    "AclRepository",
    "ConversationRepository",
    "DocumentRepository",
    "FolderRepository",
    "GroupRepository",
    "MessageRepository",
    "RoleRepository",
    "UserRepository",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
