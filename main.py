"""
rey_loader — entry point.

Runs the loader's internal ETL workflows. Sequencing is delegated to the shared
``rey_lib.workflow`` engine; rey_loader owns the step registry and handlers
(transform-files, load-files, validate-load, sql-apply). FTP is NOT a loader
concern — ftp_sync is sequenced ahead of rey_loader by pipeline_coordinator.

Usage
-----
    # Native internal workflow:
    python main.py --config-path .../config.yaml run-workflow --workflow transform_load

    # Compatibility (route to the same workflow steps):
    python main.py --config-path .../config.yaml --stage transform
    python main.py --config-path .../config.yaml --stage sql --source <sql_step>

The 'sql' stage applies generated SQL files and does not participate in the
file-ingestion batch (no begin_batch/end_batch hooks). All other stages run
inside the run-level batch hooks, exactly as before.
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
from rey_lib.files.file_loader import run_app_hooks
from rey_lib.logs import get_logger, setup_logging

from rey_lib.db.db_adapter import DBAdapter

from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import is_process_workflow, run_process_workflow, run_workflow


__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
APP_NAME = "rey_loader"

# Legacy --stage / positional compatibility -> internal workflow name.
# 'sync' is intentionally gone: rey_loader never invokes ftp_sync (that is
# coordinated by pipeline_coordinator). 'sql' maps to the self-contained
# sql_apply workflow that runs outside the file-ingestion batch.
_VALID_STAGES = ("transform", "load", "all", "sql")
_STAGE_TO_WORKFLOW = {
    "transform": "transform_only",
    "load":      "load_only",
    "all":       "transform_load",
    "sql":       "sql_apply",
}
_SQL_WORKFLOW = "sql_apply"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments, build ctx, and run the requested workflow."""
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

    workflow_name, operation = _resolve_target(args)
    apply = not args.dry_run

    # setup_logging is called once here — step modules must not call it again.
    setup_logging(ctx, operation=operation)
    log = get_logger(__name__)
    log.info("rey_loader starting — workflow=%s (mode=%s)",
             workflow_name, "apply" if apply else "dry-run")

    try:
        # Process-shape workflows run through the shared coordinator (batch/step
        # lifecycle is explicit sql_operation steps, not run-level hooks).
        if is_process_workflow(ctx, workflow_name):
            code = run_process_workflow(ctx, DBAdapter(), workflow_name, apply=apply)
            log.info("rey_loader complete.")
            sys.exit(code)

        # The sql_apply workflow is self-contained — it does not participate in
        # the file-ingestion batch (no begin_batch/end_batch hooks).
        if workflow_name == _SQL_WORKFLOW:
            code = run_workflow(ctx, workflow_name, source=args.source, apply=apply)
            log.info("rey_loader complete.")
            sys.exit(code)

        # Run-level pre hook: fires once per invocation before the workflow.
        # Bindings with `hook: hooks.pre_run` — e.g. begin_batch.
        run_app_hooks(ctx, "hooks.pre_run", sql_dir=getattr(ctx, "sql_dir", None))

        code = run_workflow(ctx, workflow_name, source=args.source, apply=apply)

        # Run-level post hook fires once, only after a clean workflow run.
        # Bindings with `hook: hooks.post_run` — e.g. end_batch.
        if code == 0:
            run_app_hooks(ctx, "hooks.post_run", sql_dir=getattr(ctx, "sql_dir", None))

        log.info("rey_loader complete.")
        sys.exit(code)

    except AppError as exc:
        handle_exception(log, exc, "rey_loader pipeline error")
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001  — top-level safety net only
        handle_exception(log, exc, "Unexpected error in rey_loader")
        sys.exit(2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_target(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve the workflow to run and an operation label for logging.

    Precedence: an explicit --workflow (or 'run-workflow' command) wins;
    otherwise the legacy positional/stage maps to an internal workflow.

    Raises
    ------
    ReyLoaderError
        If 'run-workflow' is given without --workflow, or nothing is specified.
    """
    if args.command == "run-workflow" and not args.workflow:
        raise ReyLoaderError("run-workflow requires --workflow <name>.")

    if args.workflow:
        return args.workflow, args.workflow

    stage = args.command if args.command in _VALID_STAGES else args.stage
    if not stage:
        raise ReyLoaderError(
            "Nothing to run. Use 'run-workflow --workflow <name>', a stage "
            "(transform|load|all|sql), or --stage <stage>."
        )
    return _STAGE_TO_WORKFLOW[stage], stage


def _parse_args() -> argparse.Namespace:
    """Parse and validate CLI arguments.

    Supports the native ``run-workflow --workflow <name>`` form, compatibility
    positionals/stages (transform|load|all|sql), and an opt-in ``--dry-run``.
    """
    parser = argparse.ArgumentParser(
        description="rey_loader — internal ETL workflow runner"
    )
    add_config_args(parser)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run-workflow", *_VALID_STAGES),
        default=None,
        help="run-workflow (with --workflow), or a compatibility stage.",
    )
    parser.add_argument(
        "--workflow",
        default=None,
        help="Workflow name under 'workflows' in rey_loader config.",
    )
    parser.add_argument(
        "--stage",
        choices=_VALID_STAGES,
        default=None,
        help="Compatibility: run a stage (maps to an internal workflow).",
    )
    parser.add_argument(
        "--source",
        default="",
        help="For the sql_apply workflow / sql stage: the sql_step name.",
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
