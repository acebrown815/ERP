import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[RoleRef]
    permissions: dict[str, str]
    restricted_access: bool = False  # a hired manager, contractor or freelancer
    can_select_hire: bool = False
    csrf_token: str


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_locked: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[RoleRef]
    version: int


class UserCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    role_ids: list[uuid.UUID] = []


class UserUpdateIn(BaseModel):
    version: int
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    role_ids: list[uuid.UUID] | None = None


class SetPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
