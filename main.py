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

from rey_lib.config.bootstrap import app_runtime
from rey_lib.config.cli import add_config_args, apply_env_overrides, build_ctx_from_args
from rey_lib.errors.error_utils import AppError, handle_exception
from rey_lib.logs import get_logger
from rey_lib.run_lifecycle import run_app_operation
from rey_lib.logs import finalize_run_log

from rey_lib.db.db_adapter import DBAdapter

from rey_loader.error_utils import ReyLoaderError
from rey_loader.load import run_load, run_load_direct, run_load_one
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

    # The shared bootstrap owns logging startup — step modules must not
    # start it again. app_runtime is the process boundary: it composes the
    # context and, when this block exits, collects the shared runtime objects
    # it created. It encloses the finally below so the run log is finalized
    # while those objects are still live, and collection happens after.
    with app_runtime(ctx=ctx, operation=operation) as (ctx, run_log):
        log = get_logger(__name__)
        log.info("rey_loader starting — command=%s (mode=%s)",
                 operation, "apply" if apply else "dry-run")

        try:
            if args.command == "run-workflow":
                code = _run_workflow_command(ctx, run_log, args, apply)
            else:
                code = _run_app_command(ctx, run_log, args, apply, log)

            log.info("rey_loader complete.")
            sys.exit(code)

        except AppError as exc:
            handle_exception(log, exc, "rey_loader pipeline error")
            sys.exit(1)

        except Exception as exc:  # noqa: BLE001  — top-level safety net only
            handle_exception(log, exc, "Unexpected error in rey_loader")
            sys.exit(2)

        finally:
            # Top-level owner (standalone run, not a pipeline step) explicitly creates
            # the RESULTS_SUMMARY after its final RUN_COMPLETE — on success or failure.
            # Pipeline steps (invoked with --ctx-file) leave finalization to
            # pipeline_coordinator (SGC_Rey_Lib_Explicit_Results_Summary_Creation).
            if not getattr(args, "ctx_file", None):
                finalize_run_log(run_log, ai=getattr(ctx, "shared_ai", None))


def _run_workflow_command(ctx: object, run_log, args: argparse.Namespace, apply: bool) -> int:
    """Run an explicitly named loader workflow."""
    if not args.workflow:
        raise ReyLoaderError("run-workflow requires --workflow <name>.")

    if needs_file_loop(ctx, args.workflow):
        return run_file_workflow(ctx, run_log, DBAdapter(), args.workflow, apply=apply)
    return run_process_workflow(
        ctx, run_log, DBAdapter(), args.workflow, apply=apply, source=args.source
    )


def _invocation_settings(
    args: argparse.Namespace,
    *,
    apply: bool,
) -> dict[str, object]:
    """What this command was asked to do, for the run to record.

    THE OPTIONS AS GIVEN, including the ones that were not. A load refused for
    naming a table with no connection is diagnosable only if the record shows
    that --connection was empty; omitting the empty ones would hide exactly the
    value that explains the refusal.

    Scalars only. An option holding anything else is rendered as text rather
    than dropped, because a reader needs to see that it was set at all.
    """
    given: dict[str, object] = {}
    for name, value in sorted(vars(args).items()):
        if name == "command":
            continue
        given[name] = (
            value if value is None or isinstance(value, (str, int, float, bool))
            else str(value)
        )
    # Not an option the reader typed: it says whether this run was allowed to
    # change anything, which is the first thing to know about a run that did
    # not.
    given["apply"] = apply
    return given


def _run_app_command(
    ctx: object, run_log,
    args: argparse.Namespace,
    apply: bool,
    log: object,
) -> int:
    """Run a public rey_loader command without workflow-name translation."""
    return run_app_operation(
        ctx,
        run_log, str(args.command),
        lambda: _execute_app_command(ctx, run_log, args, apply, log),
        settings=_invocation_settings(args, apply=apply),
    )


def _execute_app_command(
    ctx: object, run_log,
    args: argparse.Namespace,
    apply: bool,
    log: object,
) -> int:
    """Execute a public rey_loader command body."""
    if args.command == "transform":
        run_transform(ctx)
        return 0

    if args.command == "load":
        _check_load_arguments(args)
        if not apply:
            log.info("load skipped (dry-run).")
        elif args.file and args.table:
            # DIRECT: the arguments say everything. No data source, no
            # configured definition, nothing manufactured to stand in for one.
            run_load_direct(
                ctx, run_log, Path(args.file), args.table, args.connection,
                create_destination=args.create, file_type=args.file_type,
            )
        elif args.file:
            # CONFIGURED, one named file. The definition still decides the
            # destination, the transform and the movements.
            run_load_one(ctx, run_log, args.data_source, Path(args.file))
        else:
            run_load(ctx)
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
            run_sql_apply(ctx, run_log, args.source)
        else:
            log.info("sql skipped (dry-run).")
        return 0

    raise ReyLoaderError(f"Unknown command: {args.command}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


#: Options only a DIRECT load may carry, and what a configured definition
#: already declares instead.
#:
#: A configured load's definition owns its destination, connection, create
#: policy and file type. Accepting one of these flags alongside
#: ``--data-source`` would parse cleanly, do nothing, and leave the operator
#: believing they had overridden the definition -- so they are REFUSED rather
#: than ignored. A silent no-op flag is worse than a rejected one.
_DIRECT_ONLY_OPTIONS: dict[str, str] = {
    "table":      "load.destination_table",
    "connection": "load.connection",
    "create":     "load.create_destination_table",
    "file_type":  "transforms[].file_type",
}


def _check_load_arguments(args: argparse.Namespace) -> None:
    """Refuse an incomplete or mixed `load` invocation, by name.

    Two valid single-file modes, and they must not collapse into one:

        --file --data-source                CONFIGURED, the existing surface
        --file --table --connection         DIRECT, no configuration at all

    Raises:
        ReyLoaderError: Naming the option that is missing or does not belong.
    """
    direct_given = [
        name for name in _DIRECT_ONLY_OPTIONS if getattr(args, name, None)
    ]

    if args.data_source and direct_given:
        owned = ", ".join(
            f"--{name.replace('_', '-')} (the definition declares "
            f"{_DIRECT_ONLY_OPTIONS[name]})"
            for name in sorted(direct_given)
        )
        raise ReyLoaderError(
            f"--data-source names a configured load, which already decides "
            f"{owned}. Drop the option, or drop --data-source and give "
            f"--table and --connection instead."
        )

    if direct_given and not args.file:
        raise ReyLoaderError(
            "--table and --connection load ONE named file; add --file, or "
            "drop them to load every discovered file."
        )

    if args.table and not args.connection:
        raise ReyLoaderError(
            f"--table {args.table} names a destination with no way to reach "
            "it. Add --connection <name>."
        )
    if args.connection and not args.table:
        raise ReyLoaderError(
            f"--connection {args.connection} names a connection with no "
            "destination. Add --table <schema.table>."
        )
    if args.file and not (args.data_source or args.table):
        raise ReyLoaderError(
            "--file does not say where the file goes. Add --data-source to "
            "use a configured load, or --table and --connection to load it "
            "directly."
        )


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
        "--file",
        default="",
        help="With load: load this one file instead of discovering files by "
             "pickup pattern. Requires --data-source.",
    )
    parser.add_argument(
        "--data-source",
        dest="data_source",
        default="",
        help="With load --file: the configured data source owning the "
             "destination table. Required, because an installation may "
             "declare more than one.",
    )
    parser.add_argument(
        "--table",
        default="",
        help="With load --file: the destination as schema.table, loading it "
             "directly with no configured data source. Requires "
             "--connection.",
    )
    parser.add_argument(
        "--connection",
        default="",
        help="With load --file --table: the configured connection the "
             "destination is reached through.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        default=False,
        help="With load --file --table: create the destination from the "
             "file when it does not exist. A configured load declares this "
             "in its own 'load:' block instead.",
    )
    parser.add_argument(
        "--file-type",
        dest="file_type",
        default="",
        help="With load --file --table: the file's format, where its suffix "
             "does not name one. A configured load declares this on its "
             "transform instead.",
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
