"""Transform stage for rey_loader.

Iterates all data sources declared in ctx and runs the transform pipeline
for each one. All transform logic is provided by rey_lib — no data source
or format specific code lives here.
"""

from __future__ import annotations

from rey_lib.config.config_utils import Namespace
from rey_lib.files.file_loader import run_transform as _run_transform
from rey_lib.logs import get_logger

__all__ = ["run_transform"]

_logger = get_logger(__name__)


def run_transform(ctx: Namespace) -> None:
    """Run the transform stage for all configured data sources.

    Delegates entirely to rey_lib.files.file_loader.run_transform.
    No application-specific logic here.

    Parameters
    ----------
    ctx : Namespace
        Application context built by build_ctx().
    """
    count = _run_transform(ctx)
    _logger.info("Transform stage complete: %d file(s) transformed.", count)
