"""Typed HTTP exceptions used across the API."""
from __future__ import annotations

from fastapi import HTTPException, status


class DomainError(HTTPException):
    def __init__(self, detail: str, code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=code, detail=detail)


class NotFound(DomainError):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail, status.HTTP_404_NOT_FOUND)


class Unauthorized(DomainError):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(detail, status.HTTP_401_UNAUTHORIZED)


class Forbidden(DomainError):
    def __init__(self, detail: str = "Not allowed"):
        super().__init__(detail, status.HTTP_403_FORBIDDEN)


class Conflict(DomainError):
    def __init__(self, detail: str = "Conflict"):
        super().__init__(detail, status.HTTP_409_CONFLICT)


class InsufficientStock(DomainError):
    def __init__(self, detail: str = "Insufficient stock available"):
        super().__init__(detail, status.HTTP_409_CONFLICT)


class CreditLimitExceeded(DomainError):
    def __init__(self, detail: str = "Customer credit limit exceeded"):
        super().__init__(detail, status.HTTP_409_CONFLICT)
