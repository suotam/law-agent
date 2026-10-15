"""Every shape that crosses the HTTP boundary.

One module rather than one per router: these are the contract the FE codes
against, and reading it in one place is worth more than the separation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from law_agent.access.models import Permission, PrincipalType, ResourceType, Role, RoleCapability
from law_agent.documents.models import DocumentStatus
from law_agent.retrieval import ScopeSource
from law_agent.users.models import User


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role_id: UUID


class UserRoleUpdate(BaseModel):
    role_id: UUID


class PasswordChange(BaseModel):
    """Self-service password change. The current password is part of the
    request: knowledge of it, not just token possession, authorizes the change."""

    current_password: str
    new_password: str


class PasswordReset(BaseModel):
    """An admin resetting someone else's password; no current password is
    involved, the caller's capability is the authorization."""

    new_password: str


class RoleRef(BaseModel):
    """The role's id and name, nested in ``UserResponse`` so a client can
    render a user without a second lookup."""

    id: UUID
    name: str


class UserResponse(BaseModel):
    """No ``password_hash`` field, so it cannot be serialised by accident."""

    id: UUID
    email: str
    role: RoleRef
    capabilities: list[RoleCapability]
    is_superuser: bool
    is_active: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, user: User, role: Role) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=RoleRef(id=role.id, name=role.name),
            capabilities=sorted(role.capabilities),
            is_superuser=role.is_superuser,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class ConversationCreate(BaseModel):
    """The retrieval scope frozen with the thread. ``scope``/``limit``
    default to the library's own defaults, so an FE with no source picker
    sends ``{}``. ``org_files_folder_ids``/``org_files_document_ids`` narrow
    `org_files` retrieval further; a client-provided id is intersected with
    the caller's access ceiling in ``create_conversation``, never trusted
    outright (see the chat org files scope picker design doc)."""

    scope: list[ScopeSource] | None = None
    # Bounded here at the boundary: the value is frozen into the conversation's
    # meta and every later turn retrieves with it, twice (corpus + attachments).
    limit: int | None = Field(default=None, ge=1, le=20)
    title: str | None = None
    attachment_ids: list[UUID] = Field(default_factory=list)
    org_files_folder_ids: list[UUID] | None = None
    org_files_document_ids: list[UUID] | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationResponse):
    """One thread, including the scope frozen onto it at creation.

    The list response deliberately stays narrow -- a sidebar has no use for the
    scope -- so the retrieval settings live here, where a client opening a
    thread from history can restore its source picker.
    """

    scope: list[ScopeSource]
    limit: int


class MessageRequest(BaseModel):
    """A chat turn. ``attachment_ids`` holds only fully uploaded files: the
    upload call has already returned by the time the FE sends them."""

    question: str = Field(min_length=1)
    attachment_ids: list[UUID] = Field(default_factory=list)


class HistoryMessage(BaseModel):
    """A stored turn in the shape ``useChat`` hydrates from.

    ``parts`` is loosely typed on purpose: it is the AI SDK's own part union,
    and re-declaring it here would be a second copy to keep in step with the FE.
    """

    id: str
    role: Literal["user", "assistant"]
    parts: list[dict[str, Any]]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    # Carried so the FE can render a chip of the turn being sent from this
    # response alone, in the shape the history's attachments part returns.
    mime: str
    byte_size: int
    status: DocumentStatus
    effective_permission: Permission | None = None
    is_structure_manager: bool = False


class FolderCreate(BaseModel):
    name: str
    parent_id: UUID | None = None


class FolderUpdate(BaseModel):
    """Rename, move, or both. A field left out of the request is left alone;
    ``parent_id`` sent as an explicit ``null`` moves the folder to the root --
    the router tells the two apart through ``model_fields_set``."""

    name: str | None = None
    parent_id: UUID | None = None


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    name: str
    created_at: datetime
    effective_permission: Permission | None = None
    is_structure_manager: bool = False


class OrgFileRootResponse(BaseModel):
    """A member's own virtual root -- see `access/member_view.py`."""

    id: UUID
    name: str
    ancestor_path: str
    # A root's own permission is invisible anywhere else: it is the only node
    # the browser can stand in without having seen it listed as someone's child.
    effective_permission: Permission | None = None
    is_structure_manager: bool = False


class OrgFilesFolderContentsResponse(BaseModel):
    folders: list[FolderResponse]
    files: list[DocumentResponse]


class RoleCreate(BaseModel):
    name: str


class RoleUpdate(BaseModel):
    name: str | None = None


class RoleCapabilitiesUpdate(BaseModel):
    capabilities: list[RoleCapability]


class RoleResponse(BaseModel):
    id: UUID
    name: str
    is_superuser: bool
    capabilities: list[RoleCapability]
    created_at: datetime

    @classmethod
    def from_domain(cls, role: Role) -> RoleResponse:
        return cls(
            id=role.id,
            name=role.name,
            is_superuser=role.is_superuser,
            capabilities=sorted(role.capabilities),
            created_at=role.created_at,
        )


class GroupCreate(BaseModel):
    name: str


class GroupUpdate(BaseModel):
    name: str


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime


class GroupMemberCreate(BaseModel):
    user_id: UUID


class AclEntryCreate(BaseModel):
    resource_type: ResourceType
    resource_id: UUID
    principal_type: PrincipalType
    principal_id: UUID
    permission: Permission


class AclEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_type: ResourceType
    resource_id: UUID
    principal_type: PrincipalType
    principal_id: UUID
    permission: Permission
    created_at: datetime


class AclEffectiveResponse(BaseModel):
    """A resource's grants split by origin: ``own`` is editable, ``inherited``
    is read-only context from an ancestor folder."""

    own: list[AclEntryResponse]
    inherited: list[AclEntryResponse]


class AclBrowseResponse(BaseModel):
    """A principal's whole grant set, for the principal-centric access
    browser: ``entries`` is every explicit grant, ``folders_with_nested_grant``
    is the folders with none of their own but something granted deeper
    inside -- the browser's "worth descending into" signal."""

    entries: list[AclEntryResponse]
    folders_with_nested_grant: list[UUID]
