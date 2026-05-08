"""
App-specific exception types for rey_loader.

All rey_loader exceptions extend AppError from rey_lib so that the
top-level handler in main.py can catch them uniformly. Raise these
instead of the base AppError when the error is specific to rey_loader.
"""

from __future__ import annotations

from rey_lib.errors.error_utils import AppError

__all__ = ["ReyLoaderError"]


class ReyLoaderError(AppError):
    """Raised for any rey_loader-specific runtime failure."""
