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
from typing import Any

from rey_lib.config.cli import preparse_config_args
preparse_config_args()

from rey_lib.config.bootstrap import app_runtime
from rey_lib.config.cli import add_config_args, apply_env_overrides, build_ctx_from_args
from rey_lib.errors.error_utils import AppError
from rey_lib.logs import get_logger
from rey_lib.run_lifecycle import run_app_operation
from rey_lib.logs import finalize_run_log
from rey_lib.workflow.cli import add_workflow_selection_args, workflow_selection

from rey_lib.db.db_adapter import DBAdapter

from rey_loader.error_utils import ReyLoaderError
from rey_lib.load import Source, Target, Transform
from rey_loader.load import run_load, run_load_objects, run_load_one
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
            log.error("rey_loader pipeline error: %s", exc, exc_info=exc)
            raise AppError(f"rey_loader pipeline error: {exc}") from exc

        except Exception as exc:  # noqa: BLE001  — top-level safety net only
            log.error("Unexpected error in rey_loader: %s", exc, exc_info=exc)
            raise AppError(f"Unexpected error in rey_loader: {exc}") from exc

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

    # The step selection the shared engine resolves against the workflow's
    # ordered steps: one step, or an inclusive range.
    selection = workflow_selection(args)
    if needs_file_loop(ctx, args.workflow):
        return run_file_workflow(ctx, run_log, DBAdapter(), args.workflow, apply=apply,
                                 **selection)
    return run_process_workflow(
        ctx, run_log, DBAdapter(), args.workflow, apply=apply, source=args.source,
        **selection,
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
        elif _names_a_direct_load(args):
            # DIRECT: the arguments ARE the load. They are parsed into the
            # canonical Source, Transform and Target, which validate, resolve
            # and execute themselves -- the CLI decides nothing about them.
            run_load_objects(ctx, run_log, *_load_objects_from(args))
        elif args.file:
            # CONFIGURED, one named file with --data-source. The definition
            # still decides the destination, the transform and the movements.
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
    "replace":    "load.replace_destination_contents",
    "recreate":   "load.recreate_destination",
    "append":     "load.replace_destination_contents",
    "file_type":  "transforms[].file_type",
}

#: What a FILE source may carry and a statement may not.
#:
#: ``file_type`` is a source property that sat among destination ones. A
#: statement has no format, so offering it for a query shape would be a
#: control with nothing behind it.
_FILE_ONLY_OPTIONS: tuple[str, ...] = ("file_type",)


#: The options that name a DIRECT load: a source statement, a destination, or
#: what may be done to it. `--file` is not here: with --data-source it names a
#: configured load's file, and it joins a direct load only beside a destination.
_DIRECT_OPTIONS: tuple[str, ...] = (
    "statement", "sql_file", "source_connection", "table", "connection",
    "out_file", "create", "replace", "recreate", "append",
    "file_manifest_id", "file_mutation_id", "file_type_id",
)

#: Each argument, under the canonical object and field it configures. Only the
#: spelling differs: the field names ARE the loader's declared parameters.
_SOURCE_ARGUMENTS: dict[str, str] = {
    "file": "file", "file_type": "file-type", "statement": "statement",
    "source_connection": "source-connection", "sql_file": "sql-file",
    "file_manifest_id": "file-manifest-id", "file_mutation_id": "file-mutation-id",
    "file_type_id": "file-type-id",
}
_TRANSFORM_ARGUMENTS: dict[str, str] = {
    "transform": "transform", "transform_file": "transform-file",
    "http_connection": "http-connection", "http_adapter": "http-adapter",
    "http_options": "http-options",
}
_TARGET_ARGUMENTS: dict[str, str] = {
    "table": "table", "connection": "connection", "out_file": "out-file",
    "create": "create", "replace": "replace", "recreate": "recreate",
    "append": "append",
}


def _names_a_direct_load(args: argparse.Namespace) -> bool:
    """Whether the invocation names a direct load rather than a configured one."""
    if args.data_source:
        return False
    return any(getattr(args, name, None) for name in _DIRECT_OPTIONS)


def _load_objects_from(args: argparse.Namespace) -> tuple[Source, Transform, Target]:
    """The canonical Source, Transform and Target the arguments configure.

    **PARSING ONLY.** Each given argument becomes a value under its object's own
    field; no kind is chosen here -- each object infers its kind from its own
    fields, by the one rule every entry point shares -- and nothing is read,
    parsed or validated. Those are the objects' to do.
    """
    def values(names: dict[str, str]) -> dict[str, Any]:
        return {
            field: getattr(args, name)
            for name, field in names.items()
            if getattr(args, name, None) not in (None, "", False)
        }

    return (
        Source(values(_SOURCE_ARGUMENTS)),
        Transform(values(_TRANSFORM_ARGUMENTS)),
        Target(values(_TARGET_ARGUMENTS)),
    )


def _check_load_arguments(args: argparse.Namespace) -> None:
    """Refuse an AMBIGUOUS `load` invocation, by name.

    **INVOCATION AMBIGUITY ONLY.** What makes a load complete -- a statement's
    connection, a table's connection -- and the rule that a destination has one
    mode are the canonical objects' own, and they refuse by their own
    contracts. What is refused here is an invocation that says two things at
    once, which the objects would otherwise settle silently by inference:

        --file --data-source                     CONFIGURED
        --file / --statement / --sql-file        one SOURCE, never two
        --table / --out-file                     one DESTINATION, never two

    Raises:
        ReyLoaderError: Naming the options that cannot go together.
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

    # TWO WAYS OF SAYING ONE THING, twice over. Each pair carries one value
    # and giving both leaves nothing to decide between them.
    if args.transform and args.transform_file:
        raise ReyLoaderError(
            "--transform and --transform-file both give the TRANSFORM "
            "declaration. Drop whichever you did not mean."
        )
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

    # TWO DESTINATIONS. A table and a file are both where the rows go, and
    # choosing between them silently would write one and leave the operator
    # believing they had asked for the other.
    if args.out_file and args.table:
        raise ReyLoaderError(
            "--out-file and --table each name a DESTINATION, and a load has "
            "one. Drop whichever you did not mean."
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
    # The runner's standard step selection, defined by the shared workflow
    # layer rather than declared again here.
    add_workflow_selection_args(parser)
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
        "--replace",
        action="store_true",
        default=False,
        help="With load --file --table: replace the destination's contents "
             "with what this load carries. Its rows are removed first; the "
             "table, its constraints and its grants are not touched.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        default=False,
        help="With load --file --table: destroy the destination and build it "
             "again from what this load carries. The table is dropped and "
             "created, so its indexes, constraints and triggers go with it "
             "and are not rebuilt. Use --replace to keep the table and "
             "change only its rows.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        default=False,
        help="With load --file --table: add to the destination's contents. "
             "This is what a load does when told nothing, and naming it says "
             "so rather than changing it.",
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
        "--transform",
        default="",
        help="With load: a transform declaration, inline. Its columns name "
             "where each value comes from, what the output column is called, "
             "and what is applied on the way.",
    )
    parser.add_argument(
        "--transform-file",
        dest="transform_file",
        default="",
        help="With load: a file holding the transform declaration, instead "
             "of giving it inline with --transform. The same declaration, "
             "from somewhere it can be version-controlled and reviewed.",
    )
    parser.add_argument(
        "--http-connection",
        dest="http_connection",
        default="",
        help="With load: an http transform -- the configured HTTP connection "
             "the records are sent through.",
    )
    parser.add_argument(
        "--http-adapter",
        dest="http_adapter",
        default="",
        help="With load --http-connection: the registered HTTP transform "
             "adapter that turns the records into the provider's requests "
             "and its answers back into records.",
    )
    parser.add_argument(
        "--http-options",
        dest="http_options",
        default="",
        help="With load --http-connection: the adapter's options as JSON. "
             "Their meaning and validation are the adapter's.",
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
    # A GOVERNED FILE, named by its identity rather than a path -- the three
    # options the registration declares for `load`. Each becomes the Source's
    # own field of the same name.
    parser.add_argument(
        "--file-manifest-id",
        dest="file_manifest_id",
        default="",
        help="With load: the governed file's manifest id.",
    )
    parser.add_argument(
        "--file-mutation-id",
        dest="file_mutation_id",
        default="",
        help="With load: the governed file's mutation id.",
    )
    parser.add_argument(
        "--file-type-id",
        dest="file_type_id",
        default="",
        help="With load --file-manifest-id / --file-mutation-id: the governing "
             "file type, where it is not the file's own.",
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
