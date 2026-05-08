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
import sys
from datetime import datetime
from pathlib import Path

from rey_lib.config.config_utils import build_ctx
from rey_lib.errors.error_utils import AppError, handle_exception
from rey_lib.logs.log_utils import get_logger, setup_logging

from rey_loader.load import run_load
from rey_loader.sync import run_sync
from rey_loader.transform import run_transform

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
    # pre_transform hooks (e.g. begin_batch) read ctx.batch_start_dt.
    object.__setattr__(ctx, "batch_start_dt", datetime.now())

    # setup_logging is called once here — stage modules must not call it again.
    setup_logging(ctx, operation=args.stage)
    log = get_logger(__name__)
    log.info("rey_loader starting — env=%s stage=%s", args.env, args.stage)

    try:
        if args.stage in ("sync", "all"):
            run_sync(ctx)

        if args.stage in ("transform", "all"):
            run_transform(ctx)

        if args.stage in ("load", "all"):
            run_load(ctx)

        log.info("rey_loader complete.")
        sys.exit(0)

    except AppError as exc:
        handle_exception(exc)
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001  — top-level safety net only
        handle_exception(exc)
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
