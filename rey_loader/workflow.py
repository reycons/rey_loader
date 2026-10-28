"""
rey_loader workflow operations -- the approved implementation catalog and its handlers.

The canonical Workflow (rey_lib.workflow) binds each WorkflowStep to an
implementation this application approves (``build_process_registry``, published
on the registration as ``approved_implementations``) and runs it through the
step's Run. This module owns only the loader domain: the handlers that wrap the
existing loader functions (transform, load, validate, sql-apply, the file
operations and the per-file ingestion groups). It runs no workflow itself.

Public API
----------
build_process_registry  operation name -> approved implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rey_lib.db.connection import shared_connection
from rey_lib.db.procedure_map import ProcedureMap, get_procedure_map
from rey_lib.files.file_loader import transform_one, validate_one
from rey_lib.load.load_operation import load_one
from rey_lib.files.file_utils import delete_file, move_file, visible_files
from rey_lib.files.classify import run_source_file_classification
from rey_lib.files.convert import ConversionError, run_excel_conversion
from rey_lib.files.inventory import run_source_inventory
from rey_lib.files.prepare import run_create_prepared_files
from rey_lib.files.profile import run_record_type_profiling

from rey_loader import __version__ as _LOADER_VERSION
from rey_lib.files.sanitize import run_file_sanitization
from rey_lib.logs import AppLogger
from rey_lib.workflow import RunContext, StepResult

from rey_loader.error_utils import ReyLoaderError
from rey_loader.load import run_load
from rey_loader.sql_apply import run_sql_apply
from rey_loader.transform import run_transform

__all__ = ["build_process_registry"]

_logger = AppLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> list[Any]:
    """Coerce a config value to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "values") and not isinstance(value, (str, bytes)):
        return list(value.values())
    return [value]


# ===========================================================================
# Process model (SGC_Rey_Loader_Workflow_Process_Model)
#
# Loader workflows execute through the shared coordinator
# (``rey_lib.workflow.run_workflow``) once per discovered file. This app owns a
# small registry of generic process groups; the DB utility layer owns routine
# execution; the workflow YAML owns sequencing. The legacy stage model above is
# retained during the additive migration and is unchanged.
#
# NOTE: ``etl_operation`` is intentionally fail-closed here — real per-file
# transform/load requires public per-file APIs from rey_lib and is delivered by
# SGC_Rey_Loader_Public_Per_File_ETL_API_And_Hook_Removal. It refuses to run
# rather than risk re-processing the whole batch per file.
# ===========================================================================

def build_process_registry(adapter: Any) -> dict[str, Any]:
    """Return the loader's approved implementation catalog (key -> handler).

    Not workflow membership. It answers what this application will let the
    engine call; which processes exist, and how many name one of these, is the
    workflow's declaration. Every key here is published in this application's
    registration, and the engine refuses a workflow naming anything else.

    Two families share one catalog, dispatched by implementation key:
    the per-file ingestion groups (file_operation / sql_operation / validate /
    etl_operation) and the internal batch-ETL groups (transform_files /
    load_files / validate_load / sql_apply). Stored procedures are routine
    bindings executed by the rey_lib DB utility layer, never one Python function
    per routine.

    Each implementation takes the canonical WorkflowStep as an optional last
    argument (Run.execute passes it); the legacy coordinator passes none.
    """
    def file_operation(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_file_operation(ctx, run_log, config, run)

    def sql_operation(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_sql_operation(ctx, run_log, config, run, adapter)

    def validate(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_validate(ctx, run_log, config, run)

    def etl_operation(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_etl_operation(ctx, run_log, config, run)

    def transform_files(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_transform_files(ctx, run_log, config, run)

    def load_files(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_load_files(ctx, run_log, config, run)

    def validate_load(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_validate_load(ctx, run_log, config, run)

    def sql_apply(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext, step: Any = None) -> StepResult:
        return _process_sql_apply(ctx, run_log, config, run)

    def inventory_source_files(ctx: Any, run_log: Any, config: dict[str, Any],
                               run: RunContext, step: Any = None) -> StepResult:
        return _process_inventory_source_files(ctx, run_log, config, run)

    def classify_source_files(ctx: Any, run_log: Any, config: dict[str, Any],
                              run: RunContext, step: Any = None) -> StepResult:
        return _process_classify_source_files(ctx, run_log, config, run)

    def sanitize_file(ctx: Any, run_log: Any, config: dict[str, Any],
                      run: RunContext, step: Any = None) -> StepResult:
        return _process_sanitize_file(ctx, run_log, config, run)

    def excel_conversion(ctx: Any, run_log: Any, config: dict[str, Any],
                         run: RunContext, step: Any = None) -> StepResult:
        return _process_excel_conversion(ctx, run_log, config, run)

    def profile_csv_record_types(ctx: Any, run_log: Any, config: dict[str, Any],
                                 run: RunContext, step: Any = None) -> StepResult:
        return _process_profile_csv_record_types(ctx, run_log, config, run)

    def create_prepared_files(ctx: Any, run_log: Any, config: dict[str, Any],
                              run: RunContext, step: Any = None) -> StepResult:
        return _process_create_prepared_files(ctx, run_log, config, run)

    return {
        "create_prepared_files": create_prepared_files,
        "profile_csv_record_types": profile_csv_record_types,
        "inventory_source_files": inventory_source_files,
        "classify_source_files": classify_source_files,
        "excel_conversion": excel_conversion,
        "sanitize_file": sanitize_file,
        "file_operation": file_operation,
        "sql_operation": sql_operation,
        "validate": validate,
        "etl_operation": etl_operation,
        "transform_files": transform_files,
        "load_files": load_files,
        "validate_load": validate_load,
        "sql_apply": sql_apply,
    }


# ---------------------------------------------------------------------------
# Internal batch-ETL process handlers (coordinator signature: ctx, config, run)
#
# These wrap the existing loader functions unchanged (run_transform / run_load /
# run_sql_apply); business behaviour is preserved from the retired step engine.
# Cross-step values live on ``run.data``; recorded values on ``run.metadata``.
# ---------------------------------------------------------------------------

def _process_transform_files(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Transform local files. Calls the existing run_transform unchanged."""
    count = run_transform(ctx, run_log)
    run.data["transformed_count"] = count
    run.metadata["transformed_files"] = count
    return StepResult("transform_files", "ok", f"{count} file(s)")


def _process_load_files(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Load converted files. Calls the existing run_load unchanged."""
    rows = run_load(ctx)
    run.data["loaded_rows"] = rows
    run.metadata["loaded_rows"] = rows
    return StepResult("load_files", "ok", f"{rows} row(s)")


def _process_validate_load(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Record the load row count as the run's validation result (reporting only).

    When load was skipped (dry-run) there is no count to validate, matching the
    retired engine's behaviour exactly.
    """
    if "loaded_rows" not in run.data:
        run.metadata["validation_result"] = "skipped (load not applied)"
        return StepResult("validate_load", "skipped", "no load in this run")
    rows = run.data["loaded_rows"]
    run.metadata["validation_result"] = f"{rows} row(s) loaded"
    return StepResult("validate_load", "ok", f"{rows} row(s)")


def _process_sql_apply(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Apply generated SQL files for the run's ``source`` sql_step.

    ``source`` is loader-specific runtime input carried on the run metadata (seeded
    by ``run_process_workflow``), never a shared-coordinator concept.
    """
    source = str(run.metadata.get("source", "") or "")
    run_sql_apply(ctx, run_log, source)
    return StepResult("sql_apply", "ok", f"source={source}")


# ---------------------------------------------------------------------------
# Process handlers
# ---------------------------------------------------------------------------

def _process_sql_operation(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext,
                           adapter: Any) -> StepResult:
    """Execute a control routine binding via the rey_lib DB utility layer.

    Delegates entirely to ``ProcedureMap`` — no routine-binding internals are
    parsed here. Runtime values come from the step config plus the
    run context (batch_id/step ids loaded back onto ctx by the DB utility).
    """
    operation = str(_get(config, "operation", ""))
    if operation not in {"execute_parameter_result", "execute_no_return",
                         "execute_routine_binding"}:
        raise ReyLoaderError(f"sql_operation: unsupported operation '{operation}'.")
    procedure_map = _get(config, "procedure_map")
    routine = _get(config, "routine_binding") or _get(config, "routine_name")
    if not procedure_map:
        raise ReyLoaderError("sql_operation: missing 'procedure_map'.")
    if not routine:
        raise ReyLoaderError("sql_operation: missing 'routine_binding'.")

    # The step says which database the routine runs on. A procedure map is a
    # routine contract and no longer answers that: binding one to a connection
    # meant the same bindings could not be run against a second database.
    connection = _get(config, "connection")
    if not connection:
        raise ReyLoaderError("sql_operation: missing 'connection'.")

    params = _get(config, "params")
    if params is None:
        params = _get(config, "values")
    values = dict(_plain_dict(params))
    conn = shared_connection(ctx, str(connection)).handle()
    # Not closed: shared, and held by every other consumer of this name.
    procedure = ProcedureMap.resolve(
        conn, get_procedure_map(ctx, str(procedure_map)), str(procedure_map), str(routine),
    )
    procedure.call(conn, values, run_log, run_ctx=ctx)
    return StepResult(f"sql:{routine}", "ok", str(routine))


def _process_validate(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Validate the current file per its data-source ``file_type`` (fail closed)."""
    operation = str(_get(config, "operation", ""))
    if operation != "validate_file":
        raise ReyLoaderError(f"validate: unsupported operation '{operation}'.")
    current = _current_file(ctx)
    transform_cfg = _first_transform(_data_source(ctx, config))
    file_type = str(_get(transform_cfg, "file_type", "") or "")
    supported = {"delimited_header", "delimited_no_header", "fixed_width", "excel"}
    if file_type not in supported:
        raise ReyLoaderError(
            f"validate: unsupported file_type '{file_type}' for {current.name}."
        )
    status = "ok"
    if file_type == "delimited_header" and not validate_one(current, transform_cfg):
        status = "rejected"
    object.__setattr__(ctx, "validation_status", status)
    run.metadata["validation_status"] = status
    if status != "ok":
        return StepResult("validate", "failed", f"{file_type}: header mismatch")
    return StepResult("validate", "ok", file_type)


def _process_etl_operation(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Transform or load exactly the current file via the public per-file APIs.

    Delegates to ``rey_lib.files.file_loader.transform_one`` / ``load_one`` for
    ``ctx.current_file`` only — never the batch runners, never rediscovery.
    """
    operation = str(_get(config, "operation", ""))
    current = _current_file(ctx)
    data_source = _data_source(ctx, config)

    if operation == "transform_file":
        if not transform_one(ctx, run_log, data_source, current):
            raise ReyLoaderError(f"etl_operation: transform rejected file '{current.name}'.")
        return StepResult("etl:transform_file", "ok", current.name)

    if operation == "load_file":
        load_cfg = _first_load(data_source)
        rows = load_one(ctx, run_log, data_source, load_cfg, current)
        run.metadata["loaded_rows"] = rows
        return StepResult("etl:load_file", "ok", f"{rows} row(s)")

    raise ReyLoaderError(f"etl_operation: unsupported operation '{operation}'.")


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _current_file(ctx: Any) -> Path:
    """Return the current file path from run context, or fail closed."""
    current = getattr(ctx, "current_file", None)
    if not current:
        raise ReyLoaderError("no current file in run context for this step.")
    return Path(str(current))


def _data_source(ctx: Any, config: dict[str, Any]) -> Any:
    """Return the named data source record from ctx.data_sources (fail closed)."""
    name = str(_get(config, "data_source", "") or "")
    for data_source in _as_list(getattr(ctx, "data_sources", None)):
        if str(_get(data_source, "name", "")) == name:
            return data_source
    raise ReyLoaderError(f"data source '{name}' not found in ctx.data_sources.")


def _first_transform(data_source: Any) -> Any:
    """Return the data source's transform config (fail closed when absent)."""
    transforms = _as_list(_get(data_source, "transforms"))
    if not transforms:
        raise ReyLoaderError("validate: data source has no transform config.")
    return transforms[0]


def _first_load(data_source: Any) -> Any:
    """Return the data source's load config (fail closed when absent)."""
    loads = _as_list(_get(data_source, "loads"))
    if not loads:
        raise ReyLoaderError("etl_operation: data source has no load config.")
    return loads[0]


def _plain_dict(value: Any) -> dict[str, Any]:
    """Return a plain dict view of a dict- or Namespace-like value."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "items"):
        try:
            return dict(value.items())
        except Exception:  # noqa: BLE001 — fall through
            pass
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Return obj[key] / obj.key, or default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


