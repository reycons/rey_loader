"""Load stage for rey_loader.

Delegates entirely to rey_lib.files.file_loader.run_load. Connection
management, bulk insert, file movements, and post_load_sql are all
handled by rey_lib. Connection details are read from each load config's
load.connection field in the data source YAML.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rey_lib.config.config_utils import Namespace
from rey_lib.db.db_adapter import DBAdapter
from rey_lib.files.loader import load_files

__all__ = ["run_load"]

_logger = logging.getLogger(__name__)

# SQL files for post_load_sql are resolved relative to the project sql/ directory.
_SQL_DIR = Path(__file__).parent.parent / "sql"


def run_load(ctx: Namespace) -> None:
    """Run the load stage for all configured data sources using backend-agnostic loader."""
    db_adapter = DBAdapter()
    # Example: iterate over data sources and load configs from ctx
    # This assumes ctx.data_sources and each has .load_cfg, .connection, etc.
    total = 0
    for data_source in getattr(ctx, 'data_sources', []):
        load_cfg = getattr(data_source, 'load_cfg', None)
        if not load_cfg:
            continue
        conn = db_adapter.get_connection(load_cfg.connection)
        total += load_files(ctx, db_adapter, conn, data_source, load_cfg)
    _logger.info("Load stage complete: %d row(s) loaded.", total)
