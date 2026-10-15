"""Conversations: the archive, its block shape and the turn that fills it.

Only the domain is re-exported here. ``ask`` and ``create_conversation`` live
in :mod:`law_agent.conversations.service` and are imported from there, because
the repositories in ``law_agent.db`` import this package for its models --
pulling the service in would close that loop.
"""

from law_agent.conversations.models import (
    Conversation,
    ConversationMeta,
    ConversationNotFoundError,
    Message,
    Role,
    SourceItem,
)

__all__ = [
    "Conversation",
    "ConversationMeta",
    "ConversationNotFoundError",
    "Message",
    "Role",
    "SourceItem",
]
