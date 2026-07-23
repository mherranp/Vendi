from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """Query parameters for paginated list endpoints. skip/limit style."""

    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)


class PagedList[T](BaseModel):
    """Sobre estándar de las respuestas paginadas de toda la API.

    Sintaxis de genéricos de PEP 695 (Python 3.12) en vez de `Generic[T]`:
    equivalente, y es lo que pide ruff con `target-version = py312`.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    total: int
    skip: int
    limit: int
