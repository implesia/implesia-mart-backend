from pydantic import BaseModel, ConfigDict, Field


def page_count(total: int, page_size: int) -> int:
    if page_size <= 0:
        return 0
    return (total + page_size - 1) // page_size


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(BaseModel):
    message: str


class WriteModel(BaseModel):
    """Admin request body. A field the schema does not declare is rejected."""

    model_config = ConfigDict(extra="forbid")
