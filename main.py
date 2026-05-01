"""
lupo_loader — entry point.

Orchestrates the file ingestion pipeline. Each stage is self-contained
and can be run independently via --stage. The 'all' stage runs the full
pipeline in sequence.

Usage
-----
    python main.py --env dev  --stage sync
    python main.py --env prod --stage load
    python main.py --env prod --stage all
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from rey_lib.config.config_utils import build_ctx, inject_secrets
from rey_lib.db import sqlserver_utils
from rey_lib.errors.error_utils import AppError
from rey_lib.files.file_loader import load_files
from rey_lib.logs.log_utils import setup_logging

from app import db as app_db

__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
_VALID_STAGES = frozenset({"sync", "load", "all"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments, build ctx, and dispatch to the requested stage."""
    args = _parse_args()

    ctx = build_ctx(env=args.env, project_root=_PROJECT_ROOT)
    inject_secrets(ctx, {
        "SQLSERVER_NAVICONTROL_PASSWORD": "db.connections.0.password",
        "SQLSERVER_NAVISTAGE_PASSWORD":   "db.connections.1.password",
    })

    setup_logging(ctx, operation=args.stage)
    log = logging.getLogger(__name__)
    log.info("lupo_loader starting — env=%s stage=%s", args.env, args.stage)

    try:
        if args.stage in ("sync", "all"):
            _run_sync(ctx)

        if args.stage in ("load", "all"):
            _run_load(ctx)

        log.info("lupo_loader complete.")
        sys.exit(0)

    except AppError as exc:
        log.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)

    except Exception as exc:
        log.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(2)


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_sync(ctx: Any) -> None:
    """
    Invoke ftp_sync as a subprocess.

    ftp_sync is a fully independent application — lupo_loader calls it
    via subprocess and checks the exit code. All ftp_sync config and
    state live in the ftp_sync project directory.
    """
    log = logging.getLogger(__name__)
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


def _run_load(ctx: Any) -> None:
    """
    Load all pending files for all configured data sources.

    Opens a batch in NaviControl, loads each data source, and closes
    the batch on completion. Each file load is self-contained — a
    failure on one file does not prevent processing of others.
    """
    log = logging.getLogger(__name__)

    # Resolve batch connection from config.
    from rey_lib.config.ctx import find_in_ctx
    batch_conn_name = ctx.db.batch_connection
    batch_cfg       = find_in_ctx(ctx, "db.connections", batch_conn_name)
    sqlserver_utils.init_db(Path("sql/sqlserver"))

    with sqlserver_utils.get_connection(batch_cfg) as batch_conn:
        batch_id = app_db.start_batch(
            ctx, batch_conn, f"lupo_loader: load — {ctx.env}"
        )
        step_id = app_db.start_step(
            ctx, batch_conn, batch_id,
            severity=app_db.SEVERITY_INFO,
            source="main",
            message="Load stage started.",
        )

        try:
            _load_all_sources(ctx, batch_conn, batch_id)
            app_db.end_step(ctx, batch_conn, step_id)
            app_db.end_batch(ctx, batch_conn, batch_id)
            log.info("Load stage complete — BatchID=%d", batch_id)

        except Exception as exc:
            app_db.start_step(
                ctx, batch_conn, batch_id,
                severity=app_db.SEVERITY_ERROR,
                source="main",
                message=f"Load stage failed: {exc}",
                parent_step_id=step_id,
            )
            app_db.end_batch(ctx, batch_conn, batch_id)
            raise


def _load_all_sources(
    ctx: Any,
    batch_conn: Any,
    batch_id: int,
) -> None:
    """
    Iterate all configured data sources and load each one.

    Parameters
    ----------
    ctx : Any
        Application context.
    batch_conn : pyodbc.Connection
        Open connection to NaviControl for batch logging.
    batch_id : int
        Active BatchID.
    """
    import functools
    log = logging.getLogger(__name__)

    for data_source in ctx.data_sources:
        for load_cfg in data_source.loads:
            # Resolve the load connection from config.
            from rey_lib.config.ctx import find_in_ctx
            load_conn_name = load_cfg.load.connection
            load_cfg_db    = find_in_ctx(ctx, "db.connections", load_conn_name)

            with sqlserver_utils.get_connection(load_cfg_db) as load_conn:
                on_reload = functools.partial(
                    app_db.log_reload, ctx, batch_conn
                )

                step_id = app_db.start_step(
                    ctx, batch_conn, batch_id,
                    severity=app_db.SEVERITY_INFO,
                    source="file_loader",
                    message=f"Loading {data_source.name} / {load_cfg.name}",
                )

                rows = load_files(
                    ctx, load_conn, data_source, load_cfg,
                    batch_id=batch_id,
                    on_reload=on_reload,
                )

                app_db.start_step(
                    ctx, batch_conn, batch_id,
                    severity=app_db.SEVERITY_INFO,
                    source="file_loader",
                    message=f"Loaded {rows} row(s) — {data_source.name} / {load_cfg.name}",
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
        description="lupo_loader — file ingestion orchestrator"
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
        help="Stage to run: sync, load, or all.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()