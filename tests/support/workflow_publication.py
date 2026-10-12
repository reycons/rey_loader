"""Preparing a workflow fixture for the published-contract coordinator.

A process binds a name to an operation its application publishes, and the
coordinator validates a step's configuration against that publication before
dispatching. A fixture written before that contract existed declares neither,
so this supplies both from what the fixture already says.

It publishes exactly what the workflow uses, which is the weakest publication
under which the fixture is legal: a test still proves what it was written to
prove, and nothing is accidentally allowed through.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Mapping

from rey_lib.config.applications import (
    Application,
    ApplicationCommand,
    ApplicationCommandParameter,
)
from rey_lib.workflow import WorkflowRun, hydrate_workflow, run_workflow

__all__ = ["prepared", "run_hydrated"]

_ENGINE_KEYS = frozenset({"implementation", "apply_only", "enabled", "name"})

#: The installation a fixture context names.
_FIXTURE_INSTALLATION = SimpleNamespace(name="fixture_installation")


def prepared(workflow: dict[str, Any], ctx: Any = None) -> tuple[dict[str, Any], Any]:
    """Return the workflow with implementations bound, and a ctx publishing them."""
    prepared_workflow = deepcopy(workflow)
    owner = str(prepared_workflow.get("app") or "rey_loader")
    prepared_workflow["app"] = owner

    processes = prepared_workflow.get("processes") or {}
    operations: list[ApplicationCommand] = []
    for process, declared in processes.items():
        declared = declared if isinstance(declared, dict) else {}
        declared.setdefault("implementation", process)
        processes[process] = declared
        operations.append(
            ApplicationCommand(
                name=str(declared["implementation"]),
                parameters=tuple(
                    ApplicationCommandParameter(name=name)
                    for name in _configured(prepared_workflow, process, declared)
                ),
            )
        )
    prepared_workflow["processes"] = processes

    application = Application(name=owner, workflow_operations=tuple(operations))
    if ctx is None:
        return prepared_workflow, SimpleNamespace(
            applications=(application,), installation=_FIXTURE_INSTALLATION,
        )
    try:
        setattr(ctx, "applications", (application,))
    except AttributeError:
        object.__setattr__(ctx, "applications", (application,))
    # Every context the configuration load builds names its installation, and
    # the workflow is hydrated into it.
    if getattr(ctx, "installation", None) is None:
        try:
            setattr(ctx, "installation", _FIXTURE_INSTALLATION)
        except AttributeError:
            object.__setattr__(ctx, "installation", _FIXTURE_INSTALLATION)
    return prepared_workflow, ctx


def run_hydrated(
    ctx: Any,
    run_log: Any,
    workflow: Mapping[str, Any],
    registry: Mapping[str, Any],
    **kwargs: Any,
) -> WorkflowRun:
    """Hydrate a fixture definition and run it as its own application."""
    hydrated = hydrate_workflow(workflow, installation=_FIXTURE_INSTALLATION.name)
    return run_workflow(ctx, run_log, hydrated, registry,
                        application=str(workflow.get("app") or ""), **kwargs)


def _configured(
    workflow: Mapping[str, Any],
    process: str,
    declared: Mapping[str, Any],
) -> list[str]:
    """Every setting this process is configured with, defaults and steps."""
    names: set[str] = set(_keys(declared))
    for step in workflow.get("steps") or []:
        if isinstance(step, dict) and step.get("process") == process:
            names.update(_keys(step.get("config") or {}))
    return sorted(names)


def _keys(config: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Configured keys, nested ones written as ``parent.child``."""
    names: list[str] = []
    for key, value in config.items():
        if not prefix and key in _ENGINE_KEYS:
            continue
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            names.extend(_keys(value, prefix=f"{name}."))
        else:
            names.append(name)
    return names
