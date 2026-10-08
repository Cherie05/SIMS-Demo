from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer

T = TypeVar("T")

# Money is Decimal internally (exact arithmetic) and a JSON number on the wire.
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]

# The database stores naive UTC timestamps; tag them as UTC so clients render local time correctly.
UtcDateTime = Annotated[datetime, AfterValidator(lambda v: v.replace(tzinfo=UTC) if v.tzinfo is None else v)]


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class OutputModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str
