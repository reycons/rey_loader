"""
rey_loader — entry point.

Runs loader public commands and explicit internal workflows. FTP is NOT a loader
concern — ftp_sync is sequenced ahead of rey_loader by pipeline_coordinator.

Usage
-----
    # Public commands:
    python main.py --config-path .../config.yaml transform
    python main.py --config-path .../config.yaml sql --source <sql_step>

    # Explicit internal workflow:
    python main.py --config-path .../config.yaml run-workflow --workflow transform_load
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Pre-parse --config-path / --config-dir and call load_dotenv before other imports.
from rey_lib.config.cli import preparse_config_args
preparse_config_args()

from rey_lib.config.cli import add_config_args, apply_env_overrides, build_ctx_from_args
from rey_lib.errors.error_utils import AppError, handle_exception
from rey_lib.logs import get_logger, log_artifact_manifest_from_run_log, setup_logging
from rey_lib.run_lifecycle import run_app_operation
from rey_lib.logs import finalize_run_log

from rey_lib.db.db_adapter import DBAdapter

from rey_loader.error_utils import ReyLoaderError
from rey_loader.load import run_load
from rey_loader.sql_apply import run_sql_apply
from rey_loader.transform import run_transform
from rey_loader.workflow import needs_file_loop, run_file_workflow, run_process_workflow


__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
APP_NAME = "rey_loader"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments, build ctx, and run the requested command."""
    args = _parse_args()
    apply_env_overrides(args.env_overrides)

    # build_ctx_from_args accepts either --config-path (standalone) or
    # --ctx-file (pipeline step snapshot) and validates that one is present.
    ctx = build_ctx_from_args(args, app_name=APP_NAME)

    # Stamp batch start time on ctx before any step runs. pre_run hooks
    # (e.g. begin_batch) read ctx.batch_start_dt.
    object.__setattr__(ctx, "batch_start_dt", datetime.now())

    # Stamp the OS invocation string so sql_config params can reference it
    # via `source: ctx.cli_call` (e.g. BatchDescription on begin_batch).
    object.__setattr__(ctx, "cli_call", " ".join(sys.argv))

    operation = str(args.command)
    apply = not args.dry_run

    # setup_logging is called once here — step modules must not call it again.
    setup_logging(ctx, operation=operation)
    log = get_logger(__name__)
    log.info("rey_loader starting — command=%s (mode=%s)",
             operation, "apply" if apply else "dry-run")

    try:
        if args.command == "run-workflow":
            code = _run_workflow_command(ctx, args, apply)
        else:
            code = _run_app_command(ctx, args, apply, log)

        log.info("rey_loader complete.")
        sys.exit(code)

    except AppError as exc:
        handle_exception(log, exc, "rey_loader pipeline error")
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001  — top-level safety net only
        handle_exception(log, exc, "Unexpected error in rey_loader")
        sys.exit(2)

    finally:
        # Top-level owner (standalone run, not a pipeline step) explicitly creates the
        # RESULTS_SUMMARY after its final RUN_COMPLETE — on success or failure. Pipeline
        # steps (invoked with --ctx-file) leave finalization to pipeline_coordinator
        # (SGC_Rey_Lib_Explicit_Results_Summary_Creation).
        if not getattr(args, "ctx_file", None):
            try:
                finalize_run_log(ctx.run_log_path)
            finally:
                log_artifact_manifest_from_run_log(ctx)


def _run_workflow_command(ctx: object, args: argparse.Namespace, apply: bool) -> int:
    """Run an explicitly named loader workflow."""
    if not args.workflow:
        raise ReyLoaderError("run-workflow requires --workflow <name>.")

    if needs_file_loop(ctx, args.workflow):
        return run_file_workflow(ctx, DBAdapter(), args.workflow, apply=apply)
    return run_process_workflow(
        ctx, DBAdapter(), args.workflow, apply=apply, source=args.source
    )


def _run_app_command(
    ctx: object,
    args: argparse.Namespace,
    apply: bool,
    log: object,
) -> int:
    """Run a public rey_loader command without workflow-name translation."""
    return run_app_operation(
        ctx,
        str(args.command),
        lambda: _execute_app_command(ctx, args, apply, log),
    )


def _execute_app_command(
    ctx: object,
    args: argparse.Namespace,
    apply: bool,
    log: object,
) -> int:
    """Execute a public rey_loader command body."""
    if args.command == "transform":
        run_transform(ctx)
        return 0

    if args.command == "load":
        if apply:
            run_load(ctx)
        else:
            log.info("load skipped (dry-run).")
        return 0

    if args.command == "all":
        run_transform(ctx)
        if apply:
            run_load(ctx)
        else:
            log.info("load skipped (dry-run).")
        return 0

    if args.command == "sql":
        if apply:
            run_sql_apply(ctx, args.source)
        else:
            log.info("sql skipped (dry-run).")
        return 0

    raise ReyLoaderError(f"Unknown command: {args.command}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse and validate CLI arguments.

    Supports public commands, explicit ``run-workflow --workflow <name>``, and
    an opt-in ``--dry-run``.
    """
    parser = argparse.ArgumentParser(
        description="rey_loader — internal ETL workflow runner"
    )
    add_config_args(parser)
    parser.add_argument(
        "command",
        choices=("run-workflow", "transform", "load", "all", "sql"),
        help="Public command, or run-workflow with --workflow.",
    )
    parser.add_argument(
        "--workflow",
        default=None,
        help="Workflow name under 'workflows' in rey_loader config.",
    )
    parser.add_argument(
        "--source",
        default="",
        help="For sql / sql_apply workflow: the sql_step name.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Skip database/file-mutating steps (load-files, sql-apply). "
             "Default applies changes, preserving current loader behaviour.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
