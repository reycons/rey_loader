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

from typing import Any

from rey_lib.logs import get_logger
from rey_lib.workflow import RunContext, StepResult, StepSpec, build_steps, run_steps

from rey_loader.error_utils import ReyLoaderError
from rey_loader.load import run_load
from rey_loader.sql_apply import run_sql_apply
from rey_loader.transform import run_transform

__all__ = ["run_workflow", "build_registry"]

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
