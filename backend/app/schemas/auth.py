from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)


class SetupRequest(Credentials):
    email: str | None = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: Role
    is_active: bool


class UserCreate(SetupRequest):
    role: Role = Role.user


class UserUpdate(BaseModel):
    email: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class SetupStatus(BaseModel):
    needs_setup: bool
    allow_registration: bool
