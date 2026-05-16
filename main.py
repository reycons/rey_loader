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
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_config_dir_env = os.environ.get("APP_CONFIG_DIR")
load_dotenv(Path(_config_dir_env).expanduser() / ".env" if _config_dir_env else None)

from rey_lib.config.config_utils import build_ctx
from rey_lib.errors.error_utils import AppError, handle_exception
from rey_lib.files.file_loader import run_app_hooks
from rey_lib.logs.log_utils import get_logger, setup_logging

from rey_loader.load import run_load
from rey_loader.sync import run_sync
from rey_loader.transform import run_transform


_SQL_DIR = Path(__file__).parent / "sql"




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

    # Stamp batch start time on ctx before any stage runs.
    # pre_run hooks (e.g. begin_batch) read ctx.batch_start_dt.
    object.__setattr__(ctx, "batch_start_dt", datetime.now())

    # Stamp the OS invocation string so sql_config params can reference it
    # via `source: ctx.cli_call` (e.g. BatchDescription on begin_batch).
    object.__setattr__(ctx, "cli_call", " ".join(sys.argv))

    # setup_logging is called once here — stage modules must not call it again.
    setup_logging(ctx, operation=args.stage)
    log = get_logger(__name__)
    log.info("rey_loader starting — env=%s stage=%s", args.env, args.stage)

    sql_dir = _SQL_DIR if _SQL_DIR.exists() else None

    try:
        # Run-level pre hook: fires once per CLI invocation, before any stage.
        # Reads ctx.app_hooks (from config.{env}.yaml) and dispatches bindings
        # whose `hook` field is "hooks.pre_run" — e.g. begin_batch.
        run_app_hooks(ctx, "hooks.pre_run", sql_dir=sql_dir)

        if args.stage in ("sync", "all"):
            run_sync(ctx)

        if args.stage in ("transform", "all"):
            run_transform(ctx)

        if args.stage in ("load", "all"):
            run_load(ctx)

        # Run-level post hook: fires once after all stages complete cleanly.
        # Bindings with `hook: hooks.post_run` — e.g. end_batch.
        run_app_hooks(ctx, "hooks.post_run", sql_dir=sql_dir)

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
