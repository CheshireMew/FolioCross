"""User-facing FolioCross errors."""

from __future__ import annotations


class FolioCrossError(Exception):
    """An expected failure with a stable error code and actionable message."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message, "details": self.details},
        }
