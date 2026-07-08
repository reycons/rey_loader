"""rey_loader — SQL apply stage.

Executes generated SQL files (e.g. trade_analyzer DDL artifacts) against a
named database connection. The stage is driven entirely by workflow-level
``sql_steps:`` config — one step per SQL folder — so no arbitrary inline SQL
or shell commands ever appear in workflow YAML.

Each ``sql_step`` declares:
  - connection      : logical name resolved from ctx.db_connections
  - sql_path        : folder of .sql files (config path tokens pre-resolved)
  - file_pattern    : glob for SQL files (default ``*.sql``)
  - execution_order : ``filename`` (deterministic, the only supported order)
  - stop_on_error   : stop on the first failing file (default True)
  - dry_run         : enumerate and log files without executing (default False)

All database execution goes through ``rey_lib.db.db_adapter.DBAdapter`` so no
provider-specific code lives here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from rey_lib.config.config_utils import Namespace
from rey_lib.db.db_adapter import DBAdapter
from rey_lib.db.procedure_map import execute_sql_text
from rey_lib.logs import get_logger

from rey_loader.error_utils import ConfigError, DatabaseError

_logger = get_logger(__name__)

# Module-level DBAdapter instance. All DB calls in this module go through it.
_db_adapter = DBAdapter()


def run_sql_apply(ctx: Namespace, source: str) -> None:
    """Execute the SQL files declared by the named ``sql_step``.

    Parameters
    ----------
    ctx : Namespace
        Application context. Must expose ``sql_steps`` and ``db_connections``.
    source : str
        Name of the ``sql_step`` to run (matches the workflow step ``source``).

    Raises
    ------
    ConfigError
        If ``source`` is empty, the sql_step is not found, or its connection
        is not defined.
    DatabaseError
        If a SQL file fails to execute and ``stop_on_error`` is True.
    """
    if not source:
        raise ConfigError(
            "sql apply stage requires --source naming the sql_step to run."
        )

    step = _find_sql_step(ctx, source)
    sql_dir = Path(str(getattr(step, "sql_path", "")))
    pattern = str(getattr(step, "file_pattern", "*.sql") or "*.sql")
    order = str(getattr(step, "execution_order", "filename") or "filename")
    dry_run = bool(getattr(step, "dry_run", False))
    stop_on_error = bool(getattr(step, "stop_on_error", True))

    # Pipeline run metadata for traceability (set by pipeline_coordinator).
    runtime = getattr(ctx, "runtime", None)
    run_id = str(getattr(runtime, "pipeline_run_id", "") or "")
    pipeline = str(getattr(runtime, "pipeline_name", "") or "")
    step_name = str(getattr(runtime, "step_name", source) or source)

    if order != "filename":
        # Only deterministic filename ordering is supported; fall back to it.
        _logger.warning(
            "sql_step '%s': unsupported execution_order '%s' — using filename.",
            source, order,
        )

    files = sorted(sql_dir.glob(pattern), key=lambda p: p.name)
    _logger.info(
        "sql apply '%s': %d file(s) in %s (pattern=%s, dry_run=%s, "
        "stop_on_error=%s, connection=%s)",
        source, len(files), sql_dir, pattern, dry_run, stop_on_error,
        getattr(step, "connection", None),
    )

    if not files:
        _logger.warning("sql apply '%s': no SQL files matched — nothing to do.", source)
        return

    if dry_run:
        for sql_file in files:
            _logger.info(
                "DRY RUN sql apply: run_id=%s pipeline=%s step=%s file=%s "
                "checksum=%s connection=%s",
                run_id, pipeline, step_name, sql_file.name,
                _checksum(sql_file), getattr(step, "connection", None),
            )
        return

    _execute_files(ctx, step, source, files, stop_on_error,
                   run_id, pipeline, step_name)


def _execute_files(
    ctx: Namespace,
    step: Namespace,
    source: str,
    files: list[Path],
    stop_on_error: bool,
    run_id: str,
    pipeline: str,
    step_name: str,
) -> None:
    """Open the connection and execute each SQL file in deterministic order.

    Parameters
    ----------
    ctx : Namespace
        Application context (for connection resolution).
    step : Namespace
        The resolved ``sql_step`` config.
    source : str
        sql_step name (for log context).
    files : list[Path]
        SQL files to execute, already sorted by filename.
    stop_on_error : bool
        Stop on the first failing file when True.
    run_id, pipeline, step_name : str
        Pipeline run metadata for logging.

    Raises
    ------
    DatabaseError
        If a file fails and ``stop_on_error`` is True.
    """
    conn_name = str(getattr(step, "connection", "") or "")
    db_cfg = _find_connection(ctx, conn_name, source)
    conn = _db_adapter.get_connection(db_cfg)

    failures = 0
    try:
        for sql_file in files:
            sql_text = sql_file.read_text(encoding="utf-8")
            checksum = _checksum(sql_file)
            _logger.info(
                "sql apply start: run_id=%s pipeline=%s step=%s file=%s "
                "checksum=%s connection=%s",
                run_id, pipeline, step_name, sql_file.name, checksum,
                conn_name,
            )
            try:
                execute_sql_text(
                    ctx,
                    conn,
                    sql_text,
                    sql_label=sql_file.name,
                    operation="sql_apply",
                    sql_path=str(sql_file),
                    safe_to_preview=True,
                    sql_step=source,
                    connection_name=conn_name,
                    checksum=checksum,
                )
            except Exception as exc:  # noqa: BLE001 — logged and re-classified
                failures += 1
                _logger.error(
                    "sql apply FAILED: run_id=%s pipeline=%s step=%s file=%s "
                    "connection=%s error=%s",
                    run_id, pipeline, step_name, sql_file.name, conn_name,
                    exc,
                )
                if stop_on_error:
                    raise DatabaseError(
                        f"sql apply '{source}': {sql_file.name} failed: {exc}"
                    ) from exc
                continue
            _logger.info(
                "sql apply ok: run_id=%s pipeline=%s step=%s file=%s "
                "connection=%s status=success",
                run_id, pipeline, step_name, sql_file.name, conn_name,
            )
    finally:
        conn.close()

    if failures:
        _logger.warning(
            "sql apply '%s': completed with %d failure(s) "
            "(stop_on_error was False).", source, failures,
        )


def _find_sql_step(ctx: Namespace, source: str) -> Namespace:
    """Return the ``sql_step`` Namespace whose name matches ``source``.

    Parameters
    ----------
    ctx : Namespace
        Application context exposing ``sql_steps``.
    source : str
        sql_step name to find.

    Returns
    -------
    Namespace
        The matching sql_step config.

    Raises
    ------
    ConfigError
        If ``sql_steps`` is missing or no step matches ``source``.
    """
    steps = getattr(ctx, "sql_steps", None) or []
    for step in steps:
        if str(getattr(step, "name", "")) == source:
            return step
    available = [str(getattr(s, "name", "")) for s in steps]
    raise ConfigError(
        f"sql_step '{source}' not found in ctx.sql_steps. "
        f"Available: {available}."
    )


def _find_connection(ctx: Namespace, conn_name: str, source: str) -> Namespace:
    """Return the connection config named ``conn_name`` from ctx.db_connections.

    Parameters
    ----------
    ctx : Namespace
        Application context exposing ``db_connections``.
    conn_name : str
        Logical connection name referenced by the sql_step.
    source : str
        sql_step name (for the error message).

    Returns
    -------
    Namespace
        The matching connection config.

    Raises
    ------
    ConfigError
        If ``conn_name`` is empty or not defined.
    """
    if not conn_name:
        raise ConfigError(
            f"sql_step '{source}' is missing 'connection'. "
            "Add 'connection: <name>' to the sql_step entry."
        )
    for db_cfg in getattr(ctx, "db_connections", None) or []:
        if str(getattr(db_cfg, "name", "")) == conn_name:
            return db_cfg
    raise ConfigError(
        f"Connection '{conn_name}' (referenced by sql_step '{source}') "
        "not found in ctx.db_connections."
    )


def _checksum(sql_file: Path) -> str:
    """Return the SHA-256 hex digest of a SQL file's bytes.

    Parameters
    ----------
    sql_file : Path
        SQL file to hash.

    Returns
    -------
    str
        SHA-256 hex digest used for execution audit logging.
    """
    return hashlib.sha256(sql_file.read_bytes()).hexdigest()
