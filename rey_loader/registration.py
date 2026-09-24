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

from rey_lib.files.file_loader import supported_file_types

__all__ = ["APPLICATION_NAME", "get_registration"]

#: The registered identity. One value, matched against the installation's own
#: declaration; a disagreement is refused rather than reconciled.
APPLICATION_NAME = "rey_loader"

#: An execution mode, not part of what is being defined -- so it is declared
#: beside the action that runs the command rather than among its fields.
_DRY_RUN: dict[str, Any] = {
    "name": "dry-run",
    "required": False,
    "value_type": "flag",
    "placement": "action_bar",
    "description": "Skip the database and file-mutating steps.",
}

#: The three shapes a `load` may take, read from main.py's own refusals.
#:
#: `_check_load_arguments` accepts exactly these and rejects every other
#: combination, but only once the command has been assembled -- so a surface
#: offering all the fields at once can only be corrected after the fact.
#: Declaring the shapes lets one be chosen instead.
#:
#:     load                                  every configured data source
#:     load --file --data-source             one file, the definition decides
#:     load --file --table --connection      one file, no configuration at all
_LOAD_SHAPE = "load_shape"
_DISCOVERY = "discovery"
_CONFIGURED = "configured"
_DIRECT = "direct"

#: Every command this application offers, each with exactly the parameters that
#: invocation reads.
#:
#: DECLARED PER COMMAND, not as one union carried by a positional `command`
#: parameter. Both styles resolve, but the union gives every command every
#: field: `run-workflow` offered a destination table, and `load` offered
#: `source`, which is an sql_step name that no load path reads. The two only
#: looked related because they were shown together.
#:
#: The parser stays wider than this on purpose -- it accepts any option with
#: any command -- so narrowing here removes no invocation. What it removes is
#: the offer of one that does nothing.
_COMMANDS: list[dict[str, Any]] = [
    {
        "name": "run-workflow",
        "description": "Run a configured loader workflow by name.",
        "parameters": [
            {
                "name": "workflow",
                # REQUIRED, and unconditionally so: _run_workflow_command
                # raises "run-workflow requires --workflow <name>" without it.
                "required": True,
                "value_type": "choice",
                "possible_values_from": "workflows",
                "description": "Workflow declared under 'workflows'.",
            },
            {
                "name": "source",
                "required": False,
                "value_type": "string",
                "placeholder": "sql_step_name",
                "description": "For an sql or sql_apply workflow, which "
                               "sql_step to run.",
            },
            _DRY_RUN,
        ],
    },
    {
        "name": "transform",
        "description": "Transform every configured input file.",
        # Takes nothing. run_transform(ctx) reads no argument, and does not
        # consult the dry-run flag either -- so offering one would be a
        # control with nothing behind it.
        "parameters": [],
    },
    {
        "name": "load",
        "description": "Load files into their destinations.",
        "mode_groups": [
            {
                "name": _LOAD_SHAPE,
                "label": "Load",
                "default": _DISCOVERY,
                "modes": [
                    {"name": _DISCOVERY,
                     "label": "Every configured data source"},
                    {"name": _CONFIGURED,
                     "label": "One file, configured data source"},
                    {"name": _DIRECT,
                     "label": "One file, direct destination"},
                ],
            },
        ],
        "parameters": [
            {
                "name": "file",
                "required": False,
                "required_when": {_LOAD_SHAPE: [_CONFIGURED, _DIRECT]},
                "mode_membership": {_LOAD_SHAPE: [_CONFIGURED, _DIRECT]},
                "value_type": "path",
                "placeholder": "/path/to/file.csv",
                "description": "The one file to load.",
            },
            {
                "name": "data-source",
                "required": False,
                "required_when": {_LOAD_SHAPE: [_CONFIGURED]},
                "mode_membership": {_LOAD_SHAPE: [_CONFIGURED]},
                # NOT a choice, though ctx.data_sources exists and would
                # resolve. `_choices` raises when a declared source is absent
                # from the context, and an installation that declares no
                # `data_sources:` block -- admin is one -- has no such
                # attribute at all. Declaring it here took the whole
                # configuration load down for that installation, not just this
                # dropdown. See load_choices_cannot_come_from_an_optional_collection.
                "value_type": "string",
                "placeholder": "data_source_name",
                "description": "The configured load whose definition owns the "
                               "destination, transform and movements.",
            },
            {
                "name": "table",
                "required": False,
                "required_when": {_LOAD_SHAPE: [_DIRECT]},
                "mode_membership": {_LOAD_SHAPE: [_DIRECT]},
                "value_type": "string",
                "placeholder": "schema.table",
                "description": "The destination, as schema.table.",
            },
            {
                "name": "connection",
                "required": False,
                "required_when": {_LOAD_SHAPE: [_DIRECT]},
                "mode_membership": {_LOAD_SHAPE: [_DIRECT]},
                "value_type": "choice",
                "possible_values_from": "connections",
                "description": "The connection the destination is reached "
                               "through.",
            },
            {
                "name": "create",
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT]},
                "value_type": "flag",
                "description": "Create the destination from the file when it "
                               "does not exist.",
            },
            {
                "name": "file-type",
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT]},
                "value_type": "choice",
                # READ, never restated. A format added to the loader appears
                # here without this declaration being maintained.
                "possible_values": supported_file_types(),
                # Empty is a real answer: data_file_for resolves the format
                # from the suffix when none is declared.
                "placeholder": "Auto detect",
                "description": "The file's format, where its suffix does not "
                               "name one.",
            },
            _DRY_RUN,
        ],
    },
    {
        "name": "all",
        "description": "Transform every configured input file, then load.",
        "parameters": [_DRY_RUN],
    },
    {
        "name": "sql",
        "description": "Apply the configured SQL steps.",
        "parameters": [
            {
                "name": "source",
                "required": False,
                "value_type": "string",
                "placeholder": "sql_step_name",
                "description": "Which sql_step to run.",
            },
            _DRY_RUN,
        ],
    },
]

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
    'commands': _COMMANDS}


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
        # The mark this application is known by, published the way its CLI and
        # its operations are: which icon is an application's own is a fact
        # about the application, not a choice an installation makes.
        #
        # A NAME, never markup. The surface that draws it holds the artwork and
        # accepts no SVG from an installed distribution.
        "icon": "app.rey_loader",
        "entry_point": "main.py",
        "cli": CLI,
        "workflow_operations": WORKFLOW_OPERATIONS,
    }
