from typing import Any

from pydantic import BaseModel


class SuccessResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    code: str = "ERROR"
    details: dict[str, Any] | None = None
