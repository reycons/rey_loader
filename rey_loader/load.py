"""Load stage for rey_loader.

Delegates entirely to rey_lib.files.file_loader.run_load. Connection
management, bulk insert, file movements, hooks, and post_load_sql are
all handled by rey_lib — DB calls inside rey_lib now route through
DBAdapter, so this module stays backend-agnostic. Connection details
are read from each load config's load.connection field in the data
source YAML.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rey_lib.config.config_utils import Namespace
from rey_lib.files.file_loader import run_load as _run_load

__all__ = ["run_load"]

_logger = logging.getLogger(__name__)

# SQL files for post_load_sql are resolved relative to the project sql/ directory.
_SQL_DIR = Path(__file__).parent.parent / "sql"


def run_load(ctx: Namespace) -> None:
    """Run the load stage for all configured data sources.

    Delegates to rey_lib.files.file_loader.run_load. All connection
    management, bulk insert, file movements, hook dispatch, and
    post_load_sql execution are handled by rey_lib — no
    application-specific code here.

    Parameters
    ----------
    ctx : Namespace
        Application context built by build_ctx().
    """
    sql_dir = _SQL_DIR if _SQL_DIR.exists() else None
    total = _run_load(ctx, sql_dir=sql_dir)
    _logger.info("Load stage complete: %d row(s) loaded.", total)
