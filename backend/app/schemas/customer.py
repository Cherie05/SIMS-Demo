from pydantic import EmailStr, Field

from app.schemas.common import InputModel, OutputModel, UtcDateTime

PHONE_PATTERN = r"^[0-9+()\-\s]{7,20}$"


class CustomerBase(InputModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    address: str | None = Field(default=None, max_length=500)


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(InputModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class CustomerSummary(OutputModel):
    id: int
    name: str
    email: str


class CustomerOut(CustomerSummary):
    phone: str | None
    address: str | None
    is_active: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime
