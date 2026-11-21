import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import Page

AccessLevel = Literal["none", "read_only", "read_write", "full"]


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    role: str = Field(default=UserRole.VIEWER.value, min_length=1, max_length=50)
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=12, max_length=72)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(None, min_length=1, max_length=160)
    role: str | None = Field(None, min_length=1, max_length=50)
    is_active: bool | None = None
    password: str | None = Field(None, min_length=12, max_length=72)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None = None
    phone: str | None = None
    full_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    admin_access: bool = False
    permissions: dict[str, str] = Field(default_factory=dict)


class UserSummaryCounts(BaseModel):
    total_users: int
    staff_count: int
    customer_count: int
    active_count: int


class UserListResponse(Page[UserRead]):
    summary: UserSummaryCounts


class ModuleDefinition(BaseModel):
    key: str
    label: str
    description: str


class RoleModuleAccess(BaseModel):
    module_key: str
    module: str
    access: str  # "full" | "read_write" | "read_only" | "self_only" | "none"
    summary: str


class RoleDefinition(BaseModel):
    role: str
    label: str
    category: str  # "staff" | "storefront"
    admin_access: bool
    is_system: bool = False
    editable: bool
    user_count: int = 0
    description: str
    permissions: list[RoleModuleAccess]


class RolesMatrixResponse(BaseModel):
    roles: list[RoleDefinition]
    modules: list[str]
    module_definitions: list[ModuleDefinition]


class RolePermissionUpdateItem(BaseModel):
    role: str = Field(min_length=1, max_length=50)
    module_key: str = Field(min_length=1, max_length=64)
    access_level: AccessLevel


class RolesMatrixUpdateRequest(BaseModel):
    updates: list[RolePermissionUpdateItem] = Field(min_length=1, max_length=200)


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    label: str
    description: str
    category: str
    admin_access: bool
    is_system: bool
    editable: bool = True
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    slug: str | None = Field(None, min_length=2, max_length=50)
    description: str = Field(default="", max_length=500)
    clone_from_role: str | None = Field(None, max_length=50)


class RoleUpdate(BaseModel):
    label: str | None = Field(None, min_length=2, max_length=80)
    description: str | None = Field(None, max_length=500)


class RoleDeleteImpact(BaseModel):
    slug: str
    label: str
    is_system: bool
    can_delete: bool
    assigned_users_count: int
    reassignment_targets: list[RoleRead]


class RoleDeleteRequest(BaseModel):
    reassign_to_role: str | None = Field(None, max_length=50)
