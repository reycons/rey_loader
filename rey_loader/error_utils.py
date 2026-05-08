"""rey_loader — application exception hierarchy.

All application exceptions extend rey_lib's AppError so callers can catch
at the base level or narrow to specific types.

Public API
----------
ReyLoaderError    Base exception for all rey_loader errors.
"""

from __future__ import annotations

from rey_lib.errors.error_utils import AppError, ConfigError, DatabaseError

__all__ = [
    "ReyLoaderError",
    "ConfigError",
    "DatabaseError",
]


class ReyLoaderError(AppError):
    """Base exception for all rey_loader application errors."""


class LLMError(TradeAnalyzerError):
    """Raised when an LLM API call fails or returns an unexpected response."""
