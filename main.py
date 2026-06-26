"""
rey_loader — entry point.

Orchestrates the file ingestion pipeline. Each stage is self-contained
and can be run independently via --stage. The 'all' stage runs the full
pipeline in sequence.

Usage
-----
    python main.py --config-path /path/to/configs/v01/config.yaml --stage sync
    python main.py --config-path /path/to/configs/v01/config.yaml --stage all
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

from rey_loader.load import run_load
from rey_loader.sql_apply import run_sql_apply
from rey_loader.sync import run_sync
from rey_loader.transform import run_transform


__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
_VALID_STAGES = frozenset({"sync", "transform", "load", "sql", "all"})
APP_NAME = "rey_loader"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments, build ctx, and dispatch to the requested stage."""
    args = _parse_args()
    apply_env_overrides(args.env_overrides)

    # build_ctx_from_args accepts either --config-path (standalone) or
    # --ctx-file (pipeline step snapshot) and validates that one is present.
    ctx = build_ctx_from_args(args, app_name=APP_NAME)

    # Stamp batch start time on ctx before any stage runs.
    # pre_run hooks (e.g. begin_batch) read ctx.batch_start_dt.
    object.__setattr__(ctx, "batch_start_dt", datetime.now())

    # Stamp the OS invocation string so sql_config params can reference it
    # via `source: ctx.cli_call` (e.g. BatchDescription on begin_batch).
    object.__setattr__(ctx, "cli_call", " ".join(sys.argv))

    # setup_logging is called once here — stage modules must not call it again.
    setup_logging(ctx, operation=args.stage)
    log = get_logger(__name__)
    log.info("rey_loader starting — stage=%s", args.stage)

    try:
        # The 'sql' stage applies generated SQL files against a named
        # connection. It is self-contained — it does not participate in the
        # file-ingestion batch (no begin_batch/end_batch hooks, no sync/
        # transform/load).
        if args.stage == "sql":
            run_sql_apply(ctx, args.source)
            log.info("rey_loader complete.")
            sys.exit(0)

        # Run-level pre hook: fires once per CLI invocation, before any stage.
        # Reads ctx.app_hooks (from config.{env}.yaml) and dispatches bindings
        # whose `hook` field is "hooks.pre_run" — e.g. begin_batch.
        run_app_hooks(ctx, "hooks.pre_run", sql_dir=getattr(ctx, "sql_dir", None))

        if args.stage in ("sync", "all"):
            run_sync(ctx)

        if args.stage in ("transform", "all"):
            run_transform(ctx)

        if args.stage in ("load", "all"):
            run_load(ctx)

        # Run-level post hook: fires once after all stages complete cleanly.
        # Bindings with `hook: hooks.post_run` — e.g. end_batch.
        run_app_hooks(ctx, "hooks.post_run", sql_dir=getattr(ctx, "sql_dir", None))

        log.info("rey_loader complete.")
        sys.exit(0)

    except AppError as exc:
        handle_exception(log, exc, "rey_loader pipeline error")
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001  — top-level safety net only
        handle_exception(log, exc, "Unexpected error in rey_loader")
        sys.exit(2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse and validate CLI arguments."""
    parser = argparse.ArgumentParser(
        description="rey_loader — file ingestion orchestrator"
    )
    add_config_args(parser)
    parser.add_argument(
        "--stage",
        required=True,
        choices=sorted(_VALID_STAGES),
        help="Stage to run: sync, transform, load, sql, or all.",
    )
    parser.add_argument(
        "--source",
        default="",
        help="For --stage sql: the sql_step name to execute.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
