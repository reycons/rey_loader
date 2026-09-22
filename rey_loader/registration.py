"""What this application tells bootstrap about itself.

Identity and the surface this application allows to be invoked. Installing the
distribution is what makes it discoverable; this is what it publishes once it
is.

**One source.** An entry for this application left behind in an installation's
external registry is legacy data. It is not merged, is not a fallback and cannot
override what is here, so a command dropped from this file is gone rather than
preserved by a stale copy.

**Not configuration.** Where the application is checked out, whether an
installation enables it and where it logs are that installation's answers, held
in its ``apps:`` declaration. A registration carrying them would let a package
decide something about an installation it has never seen.

``workflow_operations`` is the approved surface a workflow may invoke, derived
from the handler boundary.

Four of these are **dispatchers**: they read an ``operation`` and accept a
different subset of the rest depending on which one was named. The published
contract is the union that dispatcher intentionally accepts, and requiredness is
declared only where it holds whatever the operation is. What a selected
operation additionally requires -- ``sql_operation`` refusing without a
``procedure_map`` or a ``routine_binding``, for instance -- is validated inside
this application, where the semantics live.

The generic coordinator validates the published outer contract. It does not
learn rey_loader's operations.
"""

from __future__ import annotations

from typing import Any

__all__ = ["APPLICATION_NAME", "get_registration"]

#: The registered identity. One value, matched against the installation's own
#: declaration; a disagreement is refused rather than reconciled.
APPLICATION_NAME = "rey_loader"

#: The command-line surface this application exposes, as an assembler of a
#: pipeline step reads it.
CLI: dict[str, Any] = {   'shared_parameters': [   {   'name': 'config-path',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Path to an app config '
                                                'file or installation '
                                                'config root.'},
                             {   'name': 'config-dir',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Directory containing '
                                                'config.<env>.yaml '
                                                '(overrides '
                                                'APP_CONFIG_DIR).'},
                             {   'name': 'set',
                                 'required': False,
                                 'repeatable': True,
                                 'value_type': 'KEY=VALUE',
                                 'description': 'Override an environment '
                                                'variable for this run.'},
                             {   'name': 'pipeline-name',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Pipeline name supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-run-id',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Unique pipeline run '
                                                'identifier supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-step-name',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Pipeline step name '
                                                'supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-step-id',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Optional unique pipeline '
                                                'step identifier.'},
                             {   'name': 'log-file',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Shared pipeline JSONL log '
                                                'path.'},
                             {   'name': 'ctx-file',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Pipeline step ctx '
                                                'snapshot (JSON); mutually '
                                                'exclusive with '
                                                'config-path.'}],
    'parameters': [   {   'name': 'command',
                          'required': False,
                          'value_type': 'choice',
                          'possible_values': [   'run-workflow',
                                                 'transform',
                                                 'load',
                                                 'all',
                                                 'sql'],
                          'positional': True,
                          'description': 'Public command, or run-workflow '
                                         'with --workflow.'},
                      {   'name': 'workflow',
                          'required': False,
                          'value_type': 'choice',
                          'possible_values_from': 'workflows',
                          'description': "Workflow name under 'workflows' "
                                         'in rey_loader config (with '
                                         'run-workflow).'},
                      {   'name': 'source',
                          'required': False,
                          'value_type': 'string',
                          'description': 'For sql / sql_apply workflow, '
                                         'the sql_step name.'},
                      {   'name': 'file',
                          'required': False,
                          'value_type': 'path',
                          'description': 'With load: load this one file '
                                         'instead of discovering files by '
                                         'pickup pattern. Requires '
                                         'data-source.'},
                      {   'name': 'data-source',
                          'required': False,
                          'value_type': 'string',
                          'description': 'With load and file: the configured '
                                         'data source owning the destination '
                                         'table. Required with file, because '
                                         'an installation may declare more '
                                         'than one.'},
                      {   'name': 'dry-run',
                          'required': False,
                          'value_type': 'flag',
                          'description': 'Skip database/file-mutating '
                                         'steps (load-files, sql-apply).'}]}


#: Read by this application's own guard, which skips a file-scoped step when a
#: run found no file. Declared data to the engine, which never learns what a
#: scope is: the catalog handed over is already wrapped.
_SCOPE = {
    "name": "scope", "required": False, "value_type": "string",
    "description": "Skip this step when the run found no file, where 'file'.",
}


def _operation(name: str, description: str, *parameters: dict[str, Any]) -> dict[str, Any]:
    """One published operation, with the guard's parameter on every one."""
    return {
        "name": name,
        "description": description,
        "parameters": [*parameters, _SCOPE],
    }


def _setting(name: str, description: str, value_type: str = "string") -> dict[str, Any]:
    """One optional setting a dispatcher accepts for some of its operations."""
    return {
        "name": name, "required": False, "value_type": value_type,
        "description": description,
    }


#: The operations a workflow may name.
WORKFLOW_OPERATIONS: list[dict[str, Any]] = [
    _operation(
        "file_operation",
        "Discover, move or delete files.",
        {"name": "operation", "required": True, "value_type": "choice",
         "possible_values": ["discover", "discover_file", "move", "delete"],
         "description": "Which file operation this step performs."},
        _setting("data_source", "Data source whose declared paths and configs this reads."),
        _setting("path", "Named path key on that data source.", "path"),
        _setting("pattern", "Filename pattern selecting files."),
        _setting("output", "Where the operation records what it found."),
        _setting("to", "Destination, for a move.", "path"),
        _setting("max_files_per_run", "Cap on files handled in one run.", "integer"),
    ),
    _operation(
        "sql_operation",
        "Execute one configured routine through the shared procedure map.",
        {"name": "operation", "required": True, "value_type": "choice",
         "possible_values": ["execute_parameter_result", "execute_no_return",
                             "execute_routine_binding"],
         "description": "Which execution shape this step uses."},
        _setting("procedure_map", "Procedure map the routine is resolved through."),
        _setting("routine_binding", "Binding naming the routine and its arguments."),
        _setting("routine_name", "Routine to call, where named directly."),
        _setting("connection", "Configured connection the routine runs on."),
        _setting("params", "Parameters passed to the routine."),
        _setting("values", "Values bound to those parameters."),
    ),
    _operation(
        "validate",
        "Validate a file before it is loaded.",
        {"name": "operation", "required": True, "value_type": "choice",
         "possible_values": ["delimited_header"],
         "description": "Which validation this step performs."},
        _setting("data_source", "Data source whose declared paths and configs this reads."),
    ),
    _operation(
        "etl_operation",
        "Transform or load one file through the loader.",
        {"name": "operation", "required": True, "value_type": "choice",
         "possible_values": ["transform_file", "load_file"],
         "description": "Which ETL operation this step performs."},
        _setting("data_source", "Data source whose declared paths and configs this reads."),
    ),
    _operation("transform_files", "Transform every configured input file."),
    _operation("load_files", "Load every transformed file."),
    _operation("validate_load", "Validate what the load produced."),
    _operation("sql_apply", "Apply the configured SQL steps."),
]


def get_registration() -> dict[str, Any]:
    """Return this application's registration.

    Returns:
        Identity, entry point and published capability.
    """
    return {
        "name": APPLICATION_NAME,
        "entry_point": "main.py",
        "cli": CLI,
        "workflow_operations": WORKFLOW_OPERATIONS,
    }
