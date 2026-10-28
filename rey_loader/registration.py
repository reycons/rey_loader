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
from rey_lib.load.source import SOURCE_FIELD_METADATA
from rey_lib.load.target import TARGET_FIELD_METADATA
from rey_lib.load.transform import TRANSFORM_FIELD_METADATA

__all__ = ["APPLICATION_NAME", "CAPABILITIES", "SERVED_KINDS", "get_registration"]

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
#:     load --statement --source-connection  one query, no configuration
#:          --table --connection
#:     load --sql-file --source-connection   the same query, from a file
#:          --table --connection
#:     load --statement --source-connection  one query, to a file
#:          --out-file
#:
#: THE FOURTH SHAPE IS TWO-ENDED. Its source is a statement on one configured
#: connection and its destination is a table on another, and they may differ --
#: which is why the source options say which end they belong to and the
#: destination ones keep the names they already had.

#: Which of the load's three OBJECTS a parameter configures.
#:
#: A load has two, and after the fourth shape they may be different databases.
#: The shape a parameter belongs to is `mode_membership` and where it is drawn
#: is `placement`; neither says which side it is, and `connection` on its own
#: is ambiguous once there are two of them.
#:
#: `file-type` is a SOURCE property, which is settled rather than decided here:
#: it sat among the destination options and was moved for that reason.
#:
#: `data-source` DECLARES NEITHER, deliberately. It names a configured load
#: whose definition owns the destination, the transform and the movements -- it
#: is not itself an end -- and it never appears beside `table`, `connection` or
#: `create`, so there is no ambiguity for it to resolve. Calling it a
#: destination would widen this field from "which side is this" to "roughly
#: destination-related", and the first thing that costs is the ability to see
#: an incomplete declaration for what it is.
#: The three objects a load composes. A parameter says which one it
#: configures, and a surface draws one per object -- so a transform is not an
#: afterthought beside two ends, it is the middle of the three.
_SOURCE = "source"
_TRANSFORM = "transform"
_DESTINATION = "destination"

#: What each object's fields ARE -- value type, meaning, an example of the form
#: where one helps -- is that object's own vocabulary (#1151). This declaration
#: reads it rather than stating it a second time.
_FIELD_METADATA: dict[str, dict[str, dict[str, str]]] = {
    _SOURCE: SOURCE_FIELD_METADATA,
    _TRANSFORM: TRANSFORM_FIELD_METADATA,
    _DESTINATION: TARGET_FIELD_METADATA,
}


def _described(parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The parameters, each one an object configures given that field's own metadata."""
    return [
        {**parameter, **_FIELD_METADATA[parameter["load_object"]][parameter["name"]]}
        if parameter.get("load_object") else parameter
        for parameter in parameters
    ]

_LOAD_SHAPE = "load_shape"
_DISCOVERY = "discovery"
_CONFIGURED = "configured"
_DIRECT = "direct"
_QUERY = "query"
#: The same query shape, with the statement read from a file instead of given
#: inline.
#:
#: A FIFTH MODE RATHER THAN A SECOND FIELD IN THE FOURTH, because
#: `required_when` maps a group to modes and cannot say "one of these two".
#: With both in `query`, neither could claim the requirement and a reader
#: could press Run having named no source at all -- which is exactly what the
#: mode group exists to stop.
#:
#: It is not a second SOURCE. Both modes build one QuerySource through one
#: entry point; the mode says which control to draw, and nothing below the CLI
#: learns which was used.
_QUERY_FILE = "query_file"

#: One file the CONTROL DATABASE already governs, named by its own identity.
#:
#: A MODE RATHER THAN A SECOND FIELD IN `direct`, for the reason `query_file` is
#: one: `required_when` maps a group to modes and cannot say "one of these two".
#: A manifest source is named by an identity and a direct source by a path, so
#: with both in one mode neither could claim the requirement and a reader could
#: press Run having named no source at all.
#:
#: It is not a second kind of load. The identity resolves to the same file a
#: path would have reached, and everything downstream -- transform, destination
#: -- is the same; what differs is that the estate's own knowledge of the file
#: comes with it, which a path cannot carry.
_MANIFEST = "manifest"

#: A query whose destination is a FILE rather than a table.
#:
#: A SIXTH MODE rather than a destination choice inside the fourth, for the
#: reason `query_file` is a fifth: `required_when` maps a group to modes and
#: cannot say "one of these two". With a table and a file destination in one
#: mode, neither could claim the requirement and a reader could press Run
#: having named nowhere for the rows to go.
#:
#: It names NO CONNECTION, because a file has none, and no format, because
#: `--out-file`'s own suffix answers that through the resolver every file
#: source already goes through.
_QUERY_TO_FILE = "query_to_file"

#: Every command this application offers, each with exactly the parameters that
#: invocation reads.
#:
#: DECLARED PER COMMAND, not as one union carried by a positional `command`
#: parameter. Both styles resolve, but the union gives every command every
#: field: a command offered a destination table, and `load` offered
#: `source`, which is an sql_step name that no load path reads. The two only
#: looked related because they were shown together.
#:
#: The parser stays wider than this on purpose -- it accepts any option with
#: any command -- so narrowing here removes no invocation. What it removes is
#: the offer of one that does nothing.
_COMMANDS: list[dict[str, Any]] = [
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
                # THE MARKS SHOW THE MOVEMENT, because that is what a shape is:
                # where the rows come from, and where they go. Source, arrow,
                # destination -- so the six are told apart by the picture and
                # not by reading six similar sentences.
                #
                # Names in the drawing surface's vocabulary, never artwork. The
                # label stays what the shape IS: it names the choice for
                # assistive technology and is what shows on rollover.
                "modes": [
                    {"name": _DISCOVERY,
                     "label": "Every configured data source",
                     "icons": ["queue", "next", "database"]},
                    {"name": _CONFIGURED,
                     "label": "One file, configured data source",
                     "icons": ["config-file", "next", "database"]},
                    {"name": _DIRECT,
                     "label": "One file, direct destination",
                     "icons": ["csv", "next", "table"]},
                    {"name": _QUERY,
                     "label": "One query, direct destination",
                     "icons": ["database", "next", "table"]},
                    {"name": _QUERY_FILE,
                     "label": "One query from a file, direct destination",
                     "icons": ["contract", "next", "table"]},
                    {"name": _QUERY_TO_FILE,
                     "label": "One query, to a file",
                     "icons": ["database", "next", "csv"]},
                    # The governed file's own mark on the left: what is named
                    # is a file the estate already holds, not a location.
                    {"name": _MANIFEST,
                     "label": "One governed file, direct destination",
                     "icons": ["map-cog", "next", "table"]},
                ],
            },
        ],
        # Each object's field is described by that object (``_described``).
        "parameters": _described([
            {
                "name": "file",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_CONFIGURED, _DIRECT]},
                "mode_membership": {_LOAD_SHAPE: [_CONFIGURED, _DIRECT]},
            },
            # -- the governed file, by identity ---------------------------
            #
            # NEITHER IS `required`, AND THE PAIR IS THE REASON. One of the two
            # must name the working file, and `required_when` maps a group to
            # modes rather than expressing "one of these two" -- so marking
            # either would refuse a caller that legitimately gave the other.
            # The rule belongs to the pair, and the contract that reads them
            # already enforces it: control.f_file_manifest_get refuses a
            # call that supplies neither, by name.
            {
                "name": "file-manifest-id",
                "load_object": _SOURCE,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_MANIFEST]},
            },
            {
                "name": "file-mutation-id",
                "load_object": _SOURCE,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_MANIFEST]},
                # A SPECIFIC MATERIALISED STATE, which is why this exists
                # beside the manifest rather than being derived from it. Given
                # one, that exact state is the working file and the
                # effective-mutation rule is not consulted.
            },
            {
                "name": "file-type-id",
                "load_object": _SOURCE,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_MANIFEST]},
                # NEVER REQUIRED, and never inferred. It is the GOVERNING
                # scope a caller intends to work within, not a fact about the
                # file: the manifest's own type is returned either way, and
                # promoting it would let a type-level edit reach every file of
                # that type when nobody chose to. Omitted means the file opens
                # read-only.
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
                "name": "source-connection",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {
                    _LOAD_SHAPE: [_QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "mode_membership": {
                    _LOAD_SHAPE: [_QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "possible_values_from": "database_connections",
            },
            {
                "name": "statement",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_QUERY, _QUERY_TO_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_QUERY, _QUERY_TO_FILE]},
            },
            {
                "name": "sql-file",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_QUERY_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_QUERY_FILE]},
            },
            {
                "name": "out-file",
                "load_object": _DESTINATION,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_QUERY_TO_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_QUERY_TO_FILE]},
                # NO FORMAT BESIDE IT. The suffix names it, through the same
                # resolver every file source goes through, and a suffix that
                # names nothing is refused rather than guessed at. `file-type`
                # stays what it is -- a property of a file being READ.
            },
            {
                "name": "transform",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                # OPTIONAL IN EVERY SHAPE THAT HAS ONE, and not a mode of its
                # own. A transform is not an alternative to a source or a
                # destination -- it is the third object, and a load either
                # states one or asks for its records as they are.
            },
            {
                "name": "transform-file",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
            },
            {
                "name": "http-adapter",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "possible_values_from": "http_operations",
            },
            {
                "name": "http-transform",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
            },
            {
                "name": "http-request",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
            },
            {
                "name": "table",
                "load_object": _DESTINATION,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
            },
            {
                "name": "connection",
                "load_object": _DESTINATION,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "possible_values_from": "database_connections",
            },
            {
                "name": "create",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
            },
            # THE OTHER TWO DISPOSITIONS TOWARD A DESTINATION, and the three
            # exclude each other: `create` acts on one that is ABSENT, these on
            # one that is there. A reader naming two has not said what they
            # want, which `_check_load_arguments` refuses rather than guesses.
            {
                "name": "replace",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
            },
            {
                "name": "recreate",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                # THE ONE THAT IS DESTRUCTIVE AT SCHEMA LEVEL, and its
                # description says so rather than leaving it to be discovered:
                # `replace` keeps the table it empties, this does not keep the
                # table at all.
            },
            {
                "name": "append",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                # NAMING WHAT ALREADY HAPPENS. A load told nothing adds to its
                # destination and always has, so this changes no behaviour --
                # it lets a reader SAY so, and lets a surface show which mode is
                # in force rather than three empty controls over a load that is
                # going to append anyway.
            },
            {
                "name": "file-type",
                "load_object": _SOURCE,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT]},
                # READ, never restated. A format added to the loader appears
                # here without this declaration being maintained. Empty is a
                # real answer: data_file_for resolves the format from the
                # suffix when none is declared.
                "possible_values": supported_file_types(),
            },
            _DRY_RUN,
        ]),
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
    {
        # Launched through LaunchedApp.launch: holds the one live Load -- its
        # Source, Transform and Target -- and serves it on the launcher's
        # commands (#1151).
        "name": "serve",
        # Needs the launcher's channel, so the application runner does not offer it (#1166).
        "invocation": "hosted",
        # The selected Tree subjects a Load opens on (#1151): the Load button's
        # reference kinds. The selected row's subject travels as --subject.
        "hosted_subject_kinds": ["governed_file", "mutation_file", "mutation_object"],
        "description": "Hold one load for the launcher attached through the app channel.",
        # Exactly one identity; the parser refuses none or several, so none is
        # required on its own. A statement comes with the connection it runs on.
        "parameter_groups": [
            {"name": "load_identity", "required": True, "mutually_exclusive": True,
             "description": "A governed file, a file, or a statement.",
             "members": ["file-manifest-id", "file-mutation-id", "file", "statement"]},
        ],
        "parameters": [
            {"name": "file-manifest-id", "required": False, "value_type": "string",
             "description": "A governed file, at its current state."},
            {"name": "file-mutation-id", "required": False, "value_type": "string",
             "description": "A governed file, at exactly that recorded state."},
            {"name": "file", "required": False, "value_type": "path",
             "description": "A file, by its path beneath the installation's permitted roots."},
            {"name": "statement", "required": False, "value_type": "string",
             "description": "A statement whose result is the load's source."},
            {"name": "source-connection", "required": False, "value_type": "string",
             "description": "With statement: the configured connection it runs on."},
            {"name": "subject", "required": False, "value_type": "string",
             "description": "The selected subject the Load acts on (its subject_key); "
                            "the Load presents itself as loader.<its first segment>."},
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
                             ],
    'commands': _COMMANDS}


#: The operations a workflow may name, each with its settings contract (backlog
#: 939): a JSON Schema 2020-12 definition of the settings its reader takes, and
#: the starter settings a new instance copies. Built from the readers, not from
#: the earlier parameter lists:
#:
#:   sql_operation, validate, etl_operation  rey_loader/workflow.py
#:
#: Canonical names only: the readers still accept file_pattern, values,
#: routine_name and a bare-string folder for compatibility, and those are not
#: published. excel_conversion's name and enabled are read but never reach the
#: reader -- the workflow engine strips them (#928) -- so they are not published.

_SCHEMA = "https://json-schema.org/draft/2020-12/schema"

#: Read by this application's own guard, which skips a file-scoped step when a
#: run found no file. Every loader operation accepts it.
_SCOPE: dict[str, Any] = {
    "type": "string",
    "description": "'file' skips this step when the run found no file.",
}

_DATA_SOURCE: dict[str, Any] = {
    "type": "string",
    "description": "Data source whose declared paths and configs this step reads.",
    "x-rey-reference": {"collection": "data_sources"},
}


def _contract(description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """A closed settings object, with the guard's scope."""
    return {
        "$schema": _SCHEMA,
        "type": "object",
        "description": description,
        "properties": {**properties, "scope": _SCOPE},
        "required": required,
        "additionalProperties": False,
    }


WORKFLOW_OPERATIONS: list[dict[str, Any]] = [
    {
        "name": "sql_operation",
        "description": "Execute one configured routine through the shared procedure map.",
        "contract_definition": _contract(
            "Execute one configured routine through the shared procedure map.",
            {
                "operation": {
                    "type": "string",
                    "enum": ["execute_parameter_result", "execute_no_return", "execute_routine_binding"],
                    "description": "Which execution shape this step uses.",
                },
                "procedure_map": {
                    "type": "string",
                    "description": "Procedure map the routine is resolved through.",
                    "x-rey-reference": {"collection": "procedure_maps"},
                },
                "routine_binding": {
                    "type": "string",
                    "description": "Binding in that procedure map naming the routine and its arguments.",
                },
                "connection": {
                    "type": "string",
                    "description": "Configured connection the routine runs on.",
                    "x-rey-reference": {"collection": "connections"},
                },
                "params": {
                    "type": "object",
                    "description": "Values passed to the routine, keyed by its parameter names.",
                    "additionalProperties": {"type": ["string", "number", "boolean", "null"]},
                },
            },
            ["operation", "procedure_map", "routine_binding", "connection"],
        ),
        "contract_sample": {
            "operation": "execute_parameter_result", "procedure_map": "", "routine_binding": "",
            "connection": "", "params": {},
        },
    },
    {
        "name": "validate",
        "description": "Validate the current file against its data source's file type.",
        "contract_definition": _contract(
            "Validate the current file against its data source's file type.",
            {
                "operation": {"type": "string", "enum": ["validate_file"], "description": "The validation performed."},
                "data_source": _DATA_SOURCE,
            },
            ["operation", "data_source"],
        ),
        "contract_sample": {"operation": "validate_file", "data_source": ""},
    },
    {
        "name": "etl_operation",
        "description": "Transform or load the current file through the loader.",
        "contract_definition": _contract(
            "Transform or load the current file through the loader.",
            {
                "operation": {
                    "type": "string", "enum": ["transform_file", "load_file"],
                    "description": "transform_file -- transform the current file; load_file -- load it.",
                },
                "data_source": _DATA_SOURCE,
            },
            ["operation", "data_source"],
        ),
        "contract_sample": {"operation": "transform_file", "data_source": ""},
    },
    {
        "name": "transform_files",
        "description": "Transform every configured input file.",
        "contract_definition": _contract("Transform every configured input file.", {}, []),
        "contract_sample": {},
    },
    {
        "name": "load_files",
        "description": "Load every transformed file.",
        "contract_definition": _contract("Load every transformed file.", {}, []),
        "contract_sample": {},
    },
    {
        "name": "validate_load",
        "description": "Validate what the load produced.",
        "contract_definition": _contract("Validate what the load produced.", {}, []),
        "contract_sample": {},
    },
    {
        "name": "sql_apply",
        "description": "Apply the configured SQL steps named by the run's --source.",
        "contract_definition": _contract(
            "Apply the configured SQL steps named by the run's --source; the step itself takes no settings.",
            {}, [],
        ),
        "contract_sample": {},
    },
]

#: The identity kinds serve opens a Load on (main._SERVE_IDENTITIES, by the option
#: giving each). Provisional (#1199 S5): no governed opening names them yet, and
#: when #1151 establishes the opening vocabulary these follow it.
SERVED_KINDS: list[str] = ["file_manifest", "file_mutation", "file", "statement"]

#: The input contract of a definition: it takes nothing.
_NO_INPUTS: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
}

#: The canonical-object capabilities answered against the objects serve holds
#: (#1199 S5): one read per held object -- Source, Transform, Target -- never a
#: composite Load. Preview (records), run (execution) and the objects' edits are
#: not capabilities.
CAPABILITIES: list[dict[str, Any]] = [
    {
        "key": "load_source.definition",
        "description": "What the held Source is: the kind in force, its configuration "
                       "and what it still needs.",
        "target_kinds": SERVED_KINDS,
        "input_contract": _NO_INPUTS,
        "access": "read",
    },
    {
        "key": "load_transform.definition",
        "description": "What the held Transform is: the kind in force, its configuration "
                       "and its declaration.",
        "target_kinds": SERVED_KINDS,
        "input_contract": _NO_INPUTS,
        "access": "read",
    },
    {
        "key": "load_target.definition",
        "description": "What the held Target is: the kind in force, its configuration, "
                       "its write policy and what it still needs.",
        "target_kinds": SERVED_KINDS,
        "input_contract": _NO_INPUTS,
        "access": "read",
    },
]


def get_registration() -> dict[str, Any]:
    """Return this application's registration.

    Returns:
        Identity, entry point and published capability.
    """
    # Deferred: rey_loader.workflow imports from this module.
    from rey_lib.db.db_adapter import DBAdapter  # noqa: PLC0415
    from rey_loader.workflow import build_process_registry  # noqa: PLC0415

    return {
        "name": APPLICATION_NAME,
        # What to CALL it, as distinct from what it is identified by. The name
        # above is an identifier and reads like one; a surface with nothing else
        # to go on had no choice but to draw it. Published here beside the icon
        # and the CLI because what an application is called is its own fact.
        "label": "Loader",
        # The mark this application is known by, published the way its CLI and
        # its operations are: which icon is an application's own is a fact
        # about the application, not a choice an installation makes.
        #
        # A NAME, never markup. The surface that draws it holds the artwork and
        # accepts no SVG from an installed distribution.
        "icon": "app.rey_loader",
        # The panel kind this application is drawn by, published as its icon is.
        "panel": "loader_panel",
        "entry_point": "main.py",
        "cli": CLI,
        "workflow_operations": WORKFLOW_OPERATIONS,
        # The approved implementation for each published operation, as the
        # finished mapping (backlog 963): what a canonical workflow step binds to.
        "approved_implementations": build_process_registry(DBAdapter()),
        # Beside the operations, never inside them: what may be invoked on the
        # objects a serve holds (#1199 S5).
        "capabilities": CAPABILITIES,
    }
