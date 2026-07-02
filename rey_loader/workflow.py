"""
rey_loader internal ETL workflows — step registry, handlers, and runner.

Ownership: the shared engine (``rey_lib.workflow``) owns orchestration mechanics
(ordered execution, fail-closed behaviour, dry-run/apply propagation, run
context, step results, run metadata). This module owns only the loader domain:
the step *registry* and *handlers* that wrap the existing, unchanged loader
functions (transform, load, validate, sql-apply).

This is an orchestration refactor only — every handler calls the existing loader
function as-is. No transform/load behaviour, output, config semantics, or
success/failure rules change here. FTP is NOT a loader concern: there is no
sync/ftp step (``pipeline_coordinator`` sequences ftp_sync -> rey_loader).

Apply semantics: dry-run is supported, but to preserve current loader behaviour
the default is apply=True (legacy ``--stage load``/``all``/``sql`` apply
directly). Database/file-mutating steps (load-files, sql-apply) are apply_only,
so a dry-run skips them while transform still runs.

Public API
----------
run_workflow    Execute a configured loader workflow via the shared engine.
build_registry  The loader step registry (name -> StepSpec).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rey_lib.db.procedure_map import execute_mapped_routine, get_connection_config
from rey_lib.files.file_utils import delete_file, move_file, visible_files
from rey_lib.logs import get_logger
from rey_lib.workflow import (
    RunContext,
    StepResult,
    StepSpec,
    build_steps,
    run_steps,
    run_workflow as coordinate_workflow,
)

from rey_loader.error_utils import ReyLoaderError
from rey_loader.load import run_load
from rey_loader.sql_apply import run_sql_apply
from rey_loader.transform import run_transform

__all__ = [
    "run_workflow",
    "build_registry",
    "build_process_registry",
    "run_process_workflow",
    "run_file_workflow",
    "is_process_workflow",
]

_logger = get_logger(__name__)

CONTRACT = "SGC_Rey_Loader_Internal_Workflow_Refactor"

# This app's identity. Workflow ownership is ``app + name``; rey_loader consumes
# only workflows assigned to itself from the resolved ctx (never another app's).
APP_NAME = "rey_loader"


# ---------------------------------------------------------------------------
# Step registry + handlers (RunContext-driven; each wraps an existing fn)
# ---------------------------------------------------------------------------

def build_registry() -> dict[str, StepSpec]:
    """Return the loader step registry (name -> StepSpec).

    load-files and sql-apply are ``apply_only`` (skipped in dry-run); the
    engine runs them by default (apply=True) to preserve current semantics.
    """
    return {
        "transform-files": StepSpec("transform-files", _step_transform),
        "load-files":      StepSpec("load-files", _step_load, apply_only=True),
        "validate-load":   StepSpec("validate-load", _step_validate),
        "sql-apply":       StepSpec("sql-apply", _step_sql_apply, apply_only=True),
    }


def _step_transform(ctx: RunContext) -> StepResult:
    """Transform local files. Calls the existing run_transform unchanged."""
    count = run_transform(ctx.data["ctx"])
    ctx.data["transformed_count"] = count
    ctx.metadata["transformed_files"] = count
    return StepResult("transform-files", "ok", f"{count} file(s)")


def _step_load(ctx: RunContext) -> StepResult:
    """Load converted files. Calls the existing run_load unchanged."""
    rows = run_load(ctx.data["ctx"])
    ctx.data["loaded_rows"] = rows
    ctx.metadata["loaded_rows"] = rows
    return StepResult("load-files", "ok", f"{rows} row(s)")


def _step_validate(ctx: RunContext) -> StepResult:
    """Record the load row count as the run's validation result.

    Reporting/metadata only — it does not add new pass/fail rules, so existing
    load semantics are unchanged. When load was skipped (dry-run) there is no
    count to validate.
    """
    if "loaded_rows" not in ctx.data:
        ctx.metadata["validation_result"] = "skipped (load not applied)"
        return StepResult("validate-load", "skipped", "no load in this run")
    rows = ctx.data["loaded_rows"]
    ctx.metadata["validation_result"] = f"{rows} row(s) loaded"
    return StepResult("validate-load", "ok", f"{rows} row(s)")


def _step_sql_apply(ctx: RunContext) -> StepResult:
    """Apply generated SQL files. Calls the existing run_sql_apply unchanged."""
    source = str(ctx.data.get("source", "") or "")
    run_sql_apply(ctx.data["ctx"], source)
    return StepResult("sql-apply", "ok", f"source={source}")


# ---------------------------------------------------------------------------
# Runner (delegates orchestration to rey_lib.workflow)
# ---------------------------------------------------------------------------

def run_workflow(
    ctx: Any,
    workflow_name: str,
    *,
    source: str = "",
    apply: bool = True,
) -> int:
    """Execute the named loader workflow via the shared engine.

    Parameters
    ----------
    ctx : Any
        Application context (must expose ``workflows`` with the named workflow).
    workflow_name : str
        Workflow name defined under ``workflows`` in rey_loader config.
    source : str
        sql_step name for the sql-apply step (workflows without it ignore it).
    apply : bool
        True (default) runs apply_only steps — preserving current loader
        semantics; False is dry-run (load/sql-apply skipped).

    Returns
    -------
    int
        0 on success, 1 on failure.
    """
    wf = _get_workflow(ctx, workflow_name)
    step_names = _as_list(_require(wf, "steps", workflow_name))

    metadata: dict[str, Any] = {
        "workflow": workflow_name,
        "source": source,
        "mode": "apply" if apply else "dry-run",
        "contracts": [CONTRACT],
    }
    run_ctx = RunContext(apply=apply, metadata=metadata,
                         data={"ctx": ctx, "source": source})

    steps = build_steps(step_names, build_registry())
    result = run_steps(steps, run_ctx, name=workflow_name)

    if result.status != "success":
        failed = result.results[-1].name if result.results else "?"
        _logger.error("workflow '%s' failed at step: %s", workflow_name, failed)
        return 1
    _logger.info("workflow '%s' complete (%s).", workflow_name, metadata["mode"])
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_workflow(ctx: Any, name: str) -> Any:
    """Return the named workflow config from the resolved ctx, or raise.

    Consumes ``ctx.workflows`` only — no filesystem discovery — and enforces
    ownership before returning: a workflow assigned to another app is refused,
    so rey_loader can never list or run a workflow it does not own.
    """
    workflows = getattr(ctx, "workflows", None)
    wf = None
    if isinstance(workflows, list):
        for item in workflows:
            if str(getattr(item, "name", "")) == name:
                wf = item
                break
    elif workflows is not None:
        wf = getattr(workflows, name, None)
    if wf is None:
        raise ReyLoaderError(
            f"workflow '{name}' not found in rey_loader config (ctx.workflows)."
        )
    _enforce_ownership(wf, name)
    return wf


def _enforce_ownership(wf: Any, name: str) -> None:
    """Refuse a workflow owned by another app (fail-closed on mismatch).

    Ownership is the resolved workflow's ``app`` property, stamped during ctx
    construction. An empty owner is treated as this app's (backward compatible
    with workflows authored before ownership stamping); a foreign owner raises.
    """
    owner = getattr(wf, "app", None) if not isinstance(wf, dict) else wf.get("app")
    owner = str(owner or "")
    if owner and owner != APP_NAME:
        raise ReyLoaderError(
            f"Workflow {name} is assigned to {owner} and cannot be executed "
            f"by {APP_NAME}."
        )


def _require(obj: Any, key: str, label: str) -> Any:
    """Return obj.key, raising ReyLoaderError when missing."""
    value = getattr(obj, key, None) if not isinstance(obj, dict) else obj.get(key)
    if value is None:
        raise ReyLoaderError(f"workflow '{label}' is missing required '{key}'.")
    return value


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
    """Return the loader's generic workflow process registry (name -> handler).

    Exactly the four generic process groups loader workflows call; stored
    procedures are routine bindings executed by the rey_lib DB utility layer,
    never one Python function per routine.
    """
    def file_operation(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
        return _process_file_operation(ctx, config, run)

    def sql_operation(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
        return _process_sql_operation(ctx, config, run, adapter)

    def validate(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
        return _process_validate(ctx, config, run)

    def etl_operation(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
        return _process_etl_operation(ctx, config, run)

    return {
        "file_operation": file_operation,
        "sql_operation": sql_operation,
        "validate": validate,
        "etl_operation": etl_operation,
    }


# ---------------------------------------------------------------------------
# Coordinator-per-file runner
# ---------------------------------------------------------------------------

def is_process_workflow(ctx: Any, name: str) -> bool:
    """Return True when the named workflow uses the process/step shape."""
    try:
        wf = _get_workflow(ctx, name)
    except ReyLoaderError:
        return False
    return _get(wf, "processes") is not None


def run_file_workflow(ctx: Any, adapter: Any, workflow_name: str, *,
                      apply: bool = True, max_files: int = 100000) -> int:
    """Repeatedly run a single-file workflow until discovery finds no file.

    rey_loader owns the file-processing loop (the shared coordinator does not):
    each ``run_process_workflow`` pass processes at most one discovered file,
    bound to ``ctx.current_file`` by the ``discover_file`` step. When discovery
    reports no eligible file (``ctx.no_file``) the loop stops cleanly. A dry-run
    performs a single pass — files are not consumed, so repeating would
    rediscover the same file. ``max_files`` bounds the loop as a safety net.
    """
    processed = 0
    while processed < max_files:
        object.__setattr__(ctx, "current_file", None)
        object.__setattr__(ctx, "no_file", False)
        code = run_process_workflow(ctx, adapter, workflow_name, apply=apply)
        if code != 0:
            return code
        if getattr(ctx, "no_file", False):
            break
        processed += 1
        if not apply:
            break
    _logger.info("workflow '%s' processed %d file(s) (%s).",
                 workflow_name, processed, "apply" if apply else "dry-run")
    return 0


def run_process_workflow(ctx: Any, adapter: Any, workflow_name: str, *,
                         apply: bool = True) -> int:
    """Execute one single-file workflow pass through the shared coordinator.

    The shared coordinator runs exactly one ordered pass and is unchanged for
    this use case (no file-list / loop / foreach). ``discover_file`` binds a
    single ``ctx.current_file`` or sets ``ctx.no_file``; file-scoped steps
    (``config.scope: file``) are skipped when no file was found, so a no-file
    pass ends cleanly while batch start/end still run. Returns 0 / 1.
    """
    wf = _get_workflow(ctx, workflow_name)
    _require(wf, "steps", workflow_name)
    registry = _guarded_registry(build_process_registry(adapter))
    run = coordinate_workflow(ctx, wf, registry, apply=apply)
    if run.status != "success":
        failed = next((o for o in run.outcomes if o.status == "failed"), None)
        _logger.error("workflow '%s' failed at step: %s",
                      workflow_name, failed.id if failed else "?")
        return 1
    _logger.info("workflow '%s' pass complete (%s).",
                 workflow_name, "apply" if apply else "dry-run")
    return 0


def _guarded_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Wrap handlers to skip ``config.scope: file`` steps when no file was found."""
    def guard(handler: Any) -> Any:
        def wrapped(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
            if getattr(ctx, "no_file", False) and str(_get(config, "scope", "")) == "file":
                return StepResult("skipped", "skipped", "no file")
            return handler(ctx, config, run)
        return wrapped
    return {name: guard(handler) for name, handler in registry.items()}


# ---------------------------------------------------------------------------
# Process handlers
# ---------------------------------------------------------------------------

def _process_sql_operation(ctx: Any, config: dict[str, Any], run: RunContext,
                           adapter: Any) -> StepResult:
    """Execute a control routine binding via the rey_lib DB utility layer.

    Delegates entirely to ``execute_mapped_routine`` — no routine-binding
    internals are parsed here. Runtime values come from the step config plus the
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

    params = _get(config, "params")
    if params is None:
        params = _get(config, "values")
    values = dict(_plain_dict(params))
    conn = adapter.get_connection(get_connection_config(ctx, str(procedure_map)))
    try:
        execute_mapped_routine(ctx, conn, str(procedure_map), str(routine),
                               values, run_ctx=ctx)
    finally:
        _close_quietly(conn)
    return StepResult(f"sql:{routine}", "ok", str(routine))


def _process_file_operation(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Discover, move, or delete files against the data source's declared paths."""
    operation = str(_get(config, "operation", ""))
    if operation == "discover_file":
        base = _data_source_path(ctx, config, str(_get(config, "path", "")))
        pattern = str(_get(config, "pattern", "*"))
        files = sorted(visible_files(base, pattern))
        key = str(_get(_get(config, "output"), "current_file", "") or "current_file")
        if not files:
            object.__setattr__(ctx, "no_file", True)
            object.__setattr__(ctx, key, None)
            run.metadata["current_file"] = None
            return StepResult("file:discover_file", "ok", "no file")
        current = files[0]
        object.__setattr__(ctx, "no_file", False)
        object.__setattr__(ctx, key, str(current))
        run.metadata["current_file"] = str(current)
        return StepResult("file:discover_file", "ok", current.name)

    if operation == "discover":
        base = _data_source_path(ctx, config, str(_get(config, "path", "")))
        pattern = str(_get(config, "pattern", "*"))
        files = sorted(visible_files(base, pattern))
        limit = _get(config, "max_files_per_run")
        if limit:
            files = files[:int(limit)]
        key = str(_get(_get(config, "output"), "files", "") or "discovered_files")
        object.__setattr__(ctx, key, [str(path) for path in files])
        run.metadata["discovered_files"] = len(files)
        return StepResult("file:discover", "ok", f"{len(files)} file(s)")

    if operation == "move":
        current = _current_file(ctx)
        dest_dir = _data_source_path(ctx, config, str(_get(config, "to", "")))
        moved = move_file(current, dest_dir)
        new_path = Path(str(moved)) if moved else dest_dir / current.name
        object.__setattr__(ctx, "current_file", str(new_path))
        return StepResult("file:move", "ok", new_path.name)

    if operation == "delete":
        current = _current_file(ctx)
        delete_file(current)
        return StepResult("file:delete", "ok", current.name)

    raise ReyLoaderError(f"file_operation: unsupported operation '{operation}'.")


def _process_validate(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
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
    if file_type == "delimited_header":
        from rey_lib.files.file_loader import _validate_header  # noqa: PLC0415
        if not _validate_header(current, transform_cfg):
            status = "rejected"
    object.__setattr__(ctx, "validation_status", status)
    run.metadata["validation_status"] = status
    if status != "ok":
        return StepResult("validate", "failed", f"{file_type}: header mismatch")
    return StepResult("validate", "ok", file_type)


def _process_etl_operation(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Fail closed — per-file transform/load is not yet wired (see NOTE above)."""
    operation = str(_get(config, "operation", ""))
    raise ReyLoaderError(
        f"etl_operation '{operation}' is not yet wired to per-file transform/load. "
        "Pending SGC_Rey_Loader_Public_Per_File_ETL_API_And_Hook_Removal — refusing "
        "to run rather than risk re-processing the whole batch per file."
    )


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


def _data_source_path(ctx: Any, config: dict[str, Any], key: str) -> Path:
    """Resolve a named path key from the data source's declared paths."""
    if not key:
        raise ReyLoaderError("file_operation: missing path key.")
    paths = _get(_data_source(ctx, config), "paths")
    value = _get(paths, key)
    if not value:
        raise ReyLoaderError(f"file_operation: path key '{key}' not found on data source.")
    return Path(str(value))


def _first_transform(data_source: Any) -> Any:
    """Return the data source's transform config (fail closed when absent)."""
    transforms = _as_list(_get(data_source, "transforms"))
    if not transforms:
        raise ReyLoaderError("validate: data source has no transform config.")
    return transforms[0]


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


def _close_quietly(conn: Any) -> None:
    """Close a DB connection, ignoring any close-time error."""
    if conn is None:
        return
    try:
        conn.close()
    except Exception:  # noqa: BLE001 — close failures must not mask the result
        pass
