from typing import Annotated

from pydantic import AfterValidator, EmailStr, Field, computed_field

from app.core.password_policy import MAX_LENGTH, MIN_LENGTH, password_problems
from app.core.permissions import permissions_for
from app.models.enums import UserRole
from app.schemas.common import InputModel, OutputModel, UtcDateTime


def _check_password_strength(value: str) -> str:
    problems = password_problems(value)
    if problems:
        raise ValueError("; ".join(problems))
    return value


Password = Annotated[str, Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH), AfterValidator(_check_password_strength)]


class LoginRequest(InputModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_LENGTH)


class UserSummary(OutputModel):
    id: int
    name: str
    email: str
    role: UserRole


class UserOut(UserSummary):
    is_active: bool
    is_verified: bool
    totp_enabled: bool
    created_at: UtcDateTime
    last_login_at: UtcDateTime | None = None


class CurrentUserOut(UserOut):
    """The signed-in user, with what they may do (the web app renders by permission)."""

    password_changed_at: UtcDateTime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def permissions(self) -> list[str]:
        return sorted(permission.value for permission in permissions_for(self.role))


class UserCreate(InputModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: Password
    role: UserRole


class UserUpdate(InputModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None
    password: Password | None = None
