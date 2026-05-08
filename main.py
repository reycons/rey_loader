"""
rey_loader — entry point.

Orchestrates the file ingestion pipeline. Each stage is self-contained
and can be run independently via --stage. The 'all' stage runs the full
pipeline in sequence.

Usage
-----
    python main.py --env dev  --stage sync
    python main.py --env prod --stage transform
    python main.py --env prod --stage load
    python main.py --env prod --stage all
"""

from __future__ import annotations

import argparse
import functools
import subprocess
import sys
from pathlib import Path
from typing import Any

from rey_lib.config.config_utils import build_ctx
from rey_lib.config.ctx import find_by_name
from rey_lib.db import sqlserver_utils
from rey_lib.errors.error_utils import AppError, handle_exception
from rey_lib.files.file_loader import load_files, transform_files
from rey_lib.logs.log_utils import get_logger, setup_logging

from rey_loader import db as app_db

__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
_VALID_STAGES = frozenset({"sync", "transform", "load", "all"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments, build ctx, and dispatch to the requested stage."""
    args = _parse_args()

    ctx = build_ctx(env=args.env, project_root=_PROJECT_ROOT)

    setup_logging(ctx, operation=args.stage)
    log = get_logger(__name__)
    log.info("rey_loader starting — env=%s stage=%s", args.env, args.stage)

    try:
        if args.stage in ("sync", "all"):
            _run_sync(ctx)

        if args.stage in ("transform", "all"):
            _run_transform(ctx)

        if args.stage in ("load", "all"):
            _run_load(ctx)

        log.info("rey_loader complete.")
        sys.exit(0)

    except AppError as exc:
        handle_exception(exc)
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001  — top-level safety net only
        handle_exception(exc)
        sys.exit(2)


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_sync(ctx: Any) -> None:
    """
    Invoke ftp_sync as a subprocess.

    ftp_sync is a fully independent application — rey_loader calls it
    via subprocess and checks the exit code. All ftp_sync config and
    state live in the ftp_sync project directory.
    """
    log = get_logger(__name__)
    stage_cfg = ctx.stages.ftp_sync

    cmd = [
        str(stage_cfg.python),
        str(stage_cfg.script),
        "--env", ctx.env,
    ]

    log.info("Running ftp_sync: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        raise AppError(
            f"ftp_sync exited with code {result.returncode}."
        )

    log.info("ftp_sync complete.")


def _run_transform(ctx: Any) -> None:
    """
    Transform all pending files for all configured data sources.

    Opens a batch in NaviControl, transforms each data source, and closes
    the batch on completion. batch_id is stamped onto ctx so all downstream
    functions — including constants resolution — can read it without being
    passed it explicitly.

    Each file transform is self-contained — a failure on one file does
    not prevent processing of others.
    """
    log       = get_logger(__name__)
    batch_cfg = find_by_name(ctx.db.connections, ctx.db.batch_connection)

    sql_dir = _PROJECT_ROOT / "sql" / "sqlserver"
    if sql_dir.exists():
        sqlserver_utils.init_db(sql_dir)

    with sqlserver_utils.get_connection(batch_cfg) as batch_conn:
        app_db.start_batch(ctx, batch_conn, f"rey_loader: transform — {ctx.env}")

        step_id = app_db.start_step(
            ctx, batch_conn, ctx.batch_id,
            severity=app_db.SEVERITY_INFO,
            source="main",
            message="Transform stage started.",
        )

        try:
            _transform_all_sources(ctx, batch_conn)
            app_db.end_step(ctx, batch_conn, step_id)
            app_db.end_batch(ctx, batch_conn, ctx.batch_id)
            log.info("Transform stage complete — BatchID=%d", ctx.batch_id)

        except Exception as exc:  # noqa: BLE001  — re-raised after batch logging
            app_db.start_step(
                ctx, batch_conn, ctx.batch_id,
                severity=app_db.SEVERITY_ERROR,
                source="main",
                message=f"Transform stage failed: {exc}",
                parent_step_id=step_id,
            )
            app_db.end_batch(ctx, batch_conn, ctx.batch_id)
            raise(ctx: Any, batch_conn: Any) -> None:
    """
    Iterate all configured data sources and transform each one.

    Parameters
    ----------
    ctx : Any
        Application context — ctx.batch_id is already set by start_batch.
    batch_conn : pyodbc.Connection
        Open connection to NaviControl for batch logging.
    """
    log = get_logger(__name__)

    for data_source in ctx.data_sources:
        for transform_cfg in data_source.transforms:

            step_id = app_db.start_step(
                ctx, batch_conn, ctx.batch_id,
                severity=app_db.SEVERITY_INFO,
                source="transform",
                message=(
                    f"Transforming {data_source.name} / "
                    f"{transform_cfg.name} {transform_cfg.version}"
                ),
            )

            count = transform_files(ctx, data_source, transform_cfg)

            app_db.start_step(
                ctx, batch_conn, ctx.batch_id,
                severity=app_db.SEVERITY_INFO,
                source="transform",
                message=(
                    f"Transformed {count} file(s) — "
                    f"{data_source.name} / {transform_cfg.name} {transform_cfg.version}"
                ),
                record_count=count,
                parent_step_id=step_id,
            )
            app_db.end_step(ctx, batch_conn, step_id)

            log.info(
                "Transformed %d file(s) — %s / %s %s",
                count, data_source.name,
                transform_cfg.name, transform_cfg.version,
            )


def _run_load(ctx: Any) -> None:
    """
    Load all pending files for all configured data sources.

    Opens a batch in NaviControl, loads each data source, and closes
    the batch on completion. batch_id is stamped onto ctx so all downstream
    functions — including constants resolution — can read it without being
    passed it explicitly.

    Each file load is self-contained — a failure on one file does not
    prevent processing of others.
    """
    log       = get_logger(__name__)
    batch_cfg = find_by_name(ctx.db.connections, ctx.db.batch_connection)

    sql_dir = _PROJECT_ROOT / "sql" / "sqlserver"
    if sql_dir.exists():
        sqlserver_utils.init_db(sql_dir)

    with sqlserver_utils.get_connection(batch_cfg) as batch_conn:
        app_db.start_batch(ctx, batch_conn, f"rey_loader: load — {ctx.env}")

        step_id = app_db.start_step(
            ctx, batch_conn, ctx.batch_id,
            severity=app_db.SEVERITY_INFO,
            source="main",
            message="Load stage started.",
        )

        try:
            _load_all_sources(ctx, batch_conn)
            app_db.end_step(ctx, batch_conn, step_id)
            app_db.end_batch(ctx, batch_conn, ctx.batch_id)
            log.info("Load stage complete — BatchID=%d", ctx.batch_id)

        except Exception as exc:  # noqa: BLE001  — re-raised after batch logging
            app_db.start_step(
                ctx, batch_conn, ctx.batch_id,
                severity=app_db.SEVERITY_ERROR,
                source="main",
                message=f"Load stage failed: {exc}",
                parent_step_id=step_id,
            )
            app_db.end_batch(ctx, batch_conn, ctx.batch_id)
            raise


def _load_all_sources(ctx: Any, batch_conn: Any) -> None:
    """
    Iterate all configured data sources and load each one.

    Parameters
    ----------
    ctx : Any
        Application context — ctx.batch_id is already set by start_batch.
    batch_conn : pyodbc.Connection
        Open connection to NaviControl for batch logging.
    """
    log = get_logger(__name__)

    for data_source in ctx.data_sources:
        for load_cfg in data_source.loads:

            # Resolve the load connection from config.
            load_conn_name = load_cfg.load.connection
            load_cfg_db    = find_by_name(ctx.db.connections, load_conn_name)

            with sqlserver_utils.get_connection(load_cfg_db) as load_conn:
                on_reload = functools.partial(
                    app_db.log_reload, ctx, batch_conn
                )

                step_id = app_db.start_step(
                    ctx, batch_conn, ctx.batch_id,
                    severity=app_db.SEVERITY_INFO,
                    source="file_loader",
                    message=f"Loading {data_source.name} / {load_cfg.name}",
                )

                rows = load_files(
                    ctx, load_conn, data_source, load_cfg,
                    on_reload=on_reload,
                )

                app_db.start_step(
                    ctx, batch_conn, ctx.batch_id,
                    severity=app_db.SEVERITY_INFO,
                    source="file_loader",
                    message=(
                        f"Loaded {rows} row(s) — "
                        f"{data_source.name} / {load_cfg.name}"
                    ),
                    record_count=rows,
                    parent_step_id=step_id,
                )
                app_db.end_step(ctx, batch_conn, step_id)

                log.info(
                    "Loaded %d row(s) — %s / %s",
                    rows, data_source.name, load_cfg.name,
                )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse and validate CLI arguments."""
    parser = argparse.ArgumentParser(
        description="rey_loader — file ingestion orchestrator"
    )
    parser.add_argument(
        "--env",
        required=True,
        choices=["dev", "prod"],
        help="Target environment.",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=sorted(_VALID_STAGES),
        help="Stage to run: sync, transform, load, or all.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
