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
from rey_lib.files import read_text_file
from rey_lib.logs import get_logger
from rey_lib.run_lifecycle import run_app_operation
from rey_lib.logs import finalize_run_log

from rey_lib.db.db_adapter import DBAdapter

from rey_loader.error_utils import ReyLoaderError
from rey_loader.load import (
    run_load,
    run_load_direct,
    run_load_one,
    run_load_query,
    run_load_query_to_file,
)
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
        elif (args.statement or args.sql_file) and args.out_file:
            # DIRECT, a query to a FILE. ONE connection, the source's: the
            # destination is a file and has none.
            # NO FILE TYPE. `--file-type` is a SOURCE fact -- it describes a
            # data file being read, and the guard refuses it beside a
            # statement. The destination's format comes from --out-file's own
            # suffix, through the same resolver every file source goes
            # through, which refuses by name rather than guessing.
            run_load_query_to_file(
                ctx, run_log, _statement_from(args), args.source_connection,
                args.out_file,
            )
        elif args.statement or args.sql_file:
            # DIRECT, a query to a TABLE. Two connections: the statement runs
            # on one and the destination lives on the other, and they may
            # differ.
            run_load_query(
                ctx, run_log, _statement_from(args), args.source_connection,
                args.table, args.connection,
                create_destination=args.create,
            )
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


#: Options a configured definition already declares, and what it calls them.
#:
#: A configured load's definition owns its destination, connection, create
#: policy and file type. Accepting one of these flags alongside
#: ``--data-source`` would parse cleanly, do nothing, and leave the operator
#: believing they had overridden the definition -- so they are REFUSED rather
#: than ignored. A silent no-op flag is worse than a rejected one.
#:
#: THE DESTINATION THREE ARE SHARED. A query load names its destination the
#: same way a direct file load does, so these say "not with --data-source"
#: rather than "only with --file".
_UNCONFIGURED_ONLY_OPTIONS: dict[str, str] = {
    "table":      "load.destination_table",
    "connection": "load.connection",
    "create":     "load.create_destination_table",
    "file_type":  "transforms[].file_type",
}

#: What a FILE source may carry and a statement may not.
#:
#: ``file_type`` is a source property that sat among destination ones. A
#: statement has no format, so offering it for a query shape would be a
#: control with nothing behind it.
_FILE_ONLY_OPTIONS: tuple[str, ...] = ("file_type",)


def _statement_from(args: argparse.Namespace) -> str:
    """The SOURCE statement, however it was given.

    **THE FILE IS A TRANSPORT, NOT A SOURCE.** ``--sql-file`` carries the same
    statement ``--statement`` carries inline; a statement long enough to be
    worth version-controlling cannot be pasted onto a command line and cannot
    be reviewed in a diff. Both produce one ``QuerySource``, and nothing below
    this function learns which form was used.

    Resolved HERE, at the CLI boundary, rather than in ``load.py``.
    ``run_load_direct`` refuses a missing file down there because there the
    file IS the source; this one holds text and is read where the transport is
    interpreted.

    Args:
        args: The parsed invocation. Exactly one form is present -- the guard
            refuses both, and refuses neither where a query shape is named.

    Returns:
        The statement.

    Raises:
        ReyLoaderError: When the named file does not exist, or holds nothing.
            An empty file is a mistyped path or an unsaved editor, and letting
            it through would reach the database as a syntax error naming the
            wrong thing.
    """
    if not args.sql_file:
        return str(args.statement or "")

    path = Path(args.sql_file)
    if not path.is_file():
        raise ReyLoaderError(f"load --sql-file: no such file: {path}")

    statement = read_text_file(path)
    if not statement.strip():
        raise ReyLoaderError(f"load --sql-file: {path} holds no statement.")
    return statement


def _check_load_arguments(args: argparse.Namespace) -> None:
    """Refuse an incomplete or mixed `load` invocation, by name.

    Three valid single-source modes, and they must not collapse into one:

        --file --data-source                     CONFIGURED
        --file --table --connection              DIRECT, a file
        --statement --source-connection
                    --table --connection         DIRECT, a query to a table
        --statement --source-connection
                    --out-file                   DIRECT, a query to a file

    **THE LOADER IS TWO-ENDED NOW, SO A REFUSAL MUST NAME THE END.** A query
    load carries two connections -- one the statement runs on, one the
    destination lives on -- and a message that says only "add --connection"
    sends an operator to fix whichever end they were not thinking about.

    Raises:
        ReyLoaderError: Naming the option that is missing or does not belong,
            and which END it belongs to.
    """
    unconfigured_given = [
        name for name in _UNCONFIGURED_ONLY_OPTIONS if getattr(args, name, None)
    ]

    if args.data_source and unconfigured_given:
        owned = ", ".join(
            f"--{name.replace('_', '-')} (the definition declares "
            f"{_UNCONFIGURED_ONLY_OPTIONS[name]})"
            for name in sorted(unconfigured_given)
        )
        raise ReyLoaderError(
            f"--data-source names a configured load, which already decides "
            f"{owned}. Drop the option, or drop --data-source and give "
            f"--table and --connection instead."
        )

    # TWO WAYS OF SAYING ONE THING. --sql-file carries the same statement
    # --statement does; giving both leaves nothing to decide between them.
    if args.statement and args.sql_file:
        raise ReyLoaderError(
            "--statement and --sql-file both give the SOURCE statement. Drop "
            "whichever you did not mean."
        )

    # A QUERY IS NAMED EITHER WAY. Normalised once so every refusal below
    # holds for both forms rather than being written twice -- the shape they
    # produce is identical, and only the transport differs.
    names_a_query = bool(args.statement or args.sql_file)

    # ONE SOURCE. A statement and a file are two, and choosing between them
    # silently would load whichever the dispatch happens to test first.
    if names_a_query and args.file:
        raise ReyLoaderError(
            "A statement and --file each name a SOURCE, and a load has one. "
            "Drop whichever you did not mean."
        )
    if names_a_query and args.data_source:
        raise ReyLoaderError(
            "A statement names a SOURCE directly, and --data-source names a "
            "configured load that decides its own. Drop one."
        )

    file_only_given = [
        name for name in _FILE_ONLY_OPTIONS if getattr(args, name, None)
    ]
    if names_a_query and file_only_given:
        named = ", ".join(
            f"--{name.replace('_', '-')}" for name in sorted(file_only_given)
        )
        raise ReyLoaderError(
            f"{named} describes a DATA file's format, and a statement names "
            "a query. Drop it."
        )

    # THE QUERY SHAPE, PROVED WHOLE. Each half is checked on its own terms so
    # the message names the end that is short -- a statement with no table is
    # a DESTINATION fault, not a source one.
    if names_a_query and not args.source_connection:
        raise ReyLoaderError(
            "A statement names a SOURCE with no way to reach it. Add "
            "--source-connection <name>."
        )
    if args.source_connection and not names_a_query:
        raise ReyLoaderError(
            f"--source-connection {args.source_connection} names a source "
            "connection with no statement to run on it. Add --statement or "
            "--sql-file, or drop it."
        )
    # TWO DESTINATIONS. A table and a file are both where the rows go, and
    # choosing between them silently would write one and leave the operator
    # believing they had asked for the other.
    if args.out_file and args.table:
        raise ReyLoaderError(
            "--out-file and --table each name a DESTINATION, and a load has "
            "one. Drop whichever you did not mean."
        )
    if names_a_query and not (args.table or args.out_file):
        raise ReyLoaderError(
            "A statement does not say where its rows go. Add --table "
            "<schema.table> and --connection <name>, or --out-file <path>, "
            "for the DESTINATION."
        )
    # A FILE DESTINATION HAS NO CONNECTION, so one given beside it is a
    # destination connection with no destination to reach -- said here rather
    # than by the --connection refusal below, which would name --table and
    # send the operator to add a second destination.
    if args.out_file and args.connection:
        raise ReyLoaderError(
            f"--connection {args.connection} reaches a DESTINATION database, "
            "and --out-file names a file, which has none. Drop it."
        )
    if args.out_file and not names_a_query:
        raise ReyLoaderError(
            f"--out-file {args.out_file} names a DESTINATION with no source "
            "to fill it. Add --statement or --sql-file."
        )

    # A DESTINATION WITH NO SOURCE AT ALL. This used to say "add --file",
    # which would now refuse every valid query load: --table and --connection
    # are given without a --file whenever the source is a statement.
    if unconfigured_given and not (args.file or names_a_query):
        raise ReyLoaderError(
            "--table and --connection load ONE named source; add --file, "
            "--statement or --sql-file, or drop them to load every "
            "discovered file."
        )

    if args.table and not args.connection:
        raise ReyLoaderError(
            f"--table {args.table} names a DESTINATION with no way to reach "
            "it. Add --connection <name>."
        )
    if args.connection and not args.table:
        raise ReyLoaderError(
            f"--connection {args.connection} names a DESTINATION connection "
            "with no destination. Add --table <schema.table>."
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
        "--statement",
        default="",
        help="With load: the SQL whose result is loaded, instead of a file. "
             "Requires --source-connection, and the destination options.",
    )
    parser.add_argument(
        "--sql-file",
        dest="sql_file",
        default="",
        help="With load: a file holding the SQL to load from, instead of "
             "giving it inline with --statement. The same statement, from "
             "somewhere it can be version-controlled and reviewed.",
    )
    parser.add_argument(
        "--source-connection",
        dest="source_connection",
        default="",
        help="With load --statement: the configured connection the SOURCE "
             "statement runs on. The destination has its own --connection, "
             "and the two may differ.",
    )
    parser.add_argument(
        "--out-file",
        dest="out_file",
        default="",
        help="With load --statement: write the rows to this file instead of "
             "a table. Its suffix names the format, and no connection is "
             "needed because a file has none.",
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
