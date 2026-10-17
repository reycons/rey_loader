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
        "parameters": [
            {
                "name": "file",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_CONFIGURED, _DIRECT]},
                "mode_membership": {_LOAD_SHAPE: [_CONFIGURED, _DIRECT]},
                "value_type": "path",
                "placeholder": "/path/to/file.csv",
                "description": "The one file to load.",
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
                "value_type": "string",
                "description": "The governed file to load, by its manifest "
                               "identity. The current state of that file is "
                               "resolved from it.",
            },
            {
                "name": "file-mutation-id",
                "load_object": _SOURCE,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_MANIFEST]},
                "value_type": "string",
                # A SPECIFIC MATERIALISED STATE, which is why this exists
                # beside the manifest rather than being derived from it. Given
                # one, that exact state is the working file and the
                # effective-mutation rule is not consulted.
                "description": "One specific materialised state of a governed "
                               "file. Use it to load that state rather than "
                               "the file's current one.",
            },
            {
                "name": "file-type-id",
                "load_object": _SOURCE,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_MANIFEST]},
                "value_type": "string",
                # NEVER REQUIRED, and never inferred. It is the GOVERNING
                # scope a caller intends to work within, not a fact about the
                # file: the manifest's own type is returned either way, and
                # promoting it would let a type-level edit reach every file of
                # that type when nobody chose to. Omitted means the file opens
                # read-only.
                "description": "The file type to work within, where type-level "
                               "configuration is being edited. Omit it to open "
                               "the file without a governing scope.",
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
                "value_type": "choice",
                "possible_values_from": "database_connections",
                "description": "The connection the SOURCE statement runs on. "
                               "The destination has its own, and they may "
                               "differ.",
            },
            {
                "name": "statement",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_QUERY, _QUERY_TO_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_QUERY, _QUERY_TO_FILE]},
                # SQL, SAID BY THE DECLARATION. A surface gives it a code
                # editor because the value IS code -- the same way every other
                # value_type decides its control, and without anything
                # recognising a parameter called "statement". `sql-file` stays
                # a path: it is the alternate transport for this text, not the
                # text itself.
                "value_type": "sql",
                "placeholder": "select ... from ...",
                "description": "The SOURCE query, whose result is loaded.",
            },
            {
                "name": "sql-file",
                "load_object": _SOURCE,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_QUERY_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_QUERY_FILE]},
                "value_type": "path",
                "placeholder": "/path/to/query.sql",
                "description": "A file holding the SOURCE query, instead of "
                               "giving it inline.",
            },
            {
                "name": "out-file",
                "load_object": _DESTINATION,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_QUERY_TO_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_QUERY_TO_FILE]},
                "value_type": "path",
                "placeholder": "/path/to/rows.csv",
                # NO FORMAT BESIDE IT. The suffix names it, through the same
                # resolver every file source goes through, and a suffix that
                # names nothing is refused rather than guessed at. `file-type`
                # stays what it is -- a property of a file being READ.
                "description": "The destination file. Its suffix names the "
                               "format, and it needs no connection.",
            },
            {
                "name": "transform",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "value_type": "string",
                "placeholder": "columns: [{name: ..., source: ...}]",
                # OPTIONAL IN EVERY SHAPE THAT HAS ONE, and not a mode of its
                # own. A transform is not an alternative to a source or a
                # destination -- it is the third object, and a load either
                # states one or asks for its records as they are.
                "description": "What each output column is and where it "
                               "comes from. Omit it to load the rows "
                               "unchanged.",
            },
            {
                "name": "transform-file",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "value_type": "path",
                "placeholder": "/path/to/transform.yaml",
                "description": "A file holding that declaration, instead of "
                               "giving it inline.",
            },
            {
                "name": "http-adapter",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "value_type": "choice",
                "possible_values_from": "http_operations",
                "description": "The HTTP operation the records are sent through: "
                               "a governed job of this installation.",
            },
            {
                "name": "http-transform",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "value_type": "string",
                "placeholder": "columns: [{name: ..., source: ...}]",
                "description": "The column mapping applied to the records before "
                               "they are sent. Omit it to send them as they are.",
            },
            {
                "name": "http-request",
                "load_object": _TRANSFORM,
                "required": False,
                "mode_membership": {
                    _LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE, _QUERY_TO_FILE],
                },
                "value_type": "string",
                "description": "The values set for the HTTP operation's request "
                               "settings, as {part: {name: value}}. Omit it to send "
                               "the operation's own.",
            },
            {
                "name": "table",
                "load_object": _DESTINATION,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "value_type": "string",
                "placeholder": "schema.table",
                "description": "The destination, as schema.table.",
            },
            {
                "name": "connection",
                "load_object": _DESTINATION,
                "required": False,
                "required_when": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "value_type": "choice",
                "possible_values_from": "database_connections",
                "description": "The connection the DESTINATION is reached "
                               "through.",
            },
            {
                "name": "create",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "value_type": "flag",
                "description": "Create the destination from the source when "
                               "it does not exist.",
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
                "value_type": "flag",
                "description": "Replace the destination's contents with what "
                               "this load carries. Its rows are removed first; "
                               "the table, its constraints and its grants are "
                               "not touched.",
            },
            {
                "name": "recreate",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "value_type": "flag",
                # THE ONE THAT IS DESTRUCTIVE AT SCHEMA LEVEL, and it is said
                # here rather than discovered: `replace` keeps the table it
                # empties, this does not keep the table at all.
                "description": "Destroy the destination and build it again "
                               "from what this load carries. The table is "
                               "dropped and created, so its indexes, "
                               "constraints and triggers go with it and are "
                               "not rebuilt.",
            },
            {
                "name": "append",
                "load_object": _DESTINATION,
                "required": False,
                "mode_membership": {_LOAD_SHAPE: [_DIRECT, _MANIFEST, _QUERY, _QUERY_FILE]},
                "value_type": "flag",
                # NAMING WHAT ALREADY HAPPENS. A load told nothing adds to its
                # destination and always has, so this changes no behaviour --
                # it lets a reader SAY so, and lets a surface show which mode is
                # in force rather than three empty controls over a load that is
                # going to append anyway.
                "description": "Add to the destination's contents. This is "
                               "what a load does when told nothing.",
            },
            {
                "name": "file-type",
                "load_object": _SOURCE,
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


#: The operations a workflow may name, each with its settings contract (backlog
#: 939): a JSON Schema 2020-12 definition of the settings its reader takes, and
#: the starter settings a new instance copies. Built from the readers, not from
#: the earlier parameter lists:
#:
#:   file_operation, sql_operation, validate, etl_operation  rey_loader/workflow.py
#:   inventory_source_files    rey_lib/load/inventory.py resolve_inventory_source_configs
#:   classify_source_files     rey_lib/load/classify.py _classification_source_config, _variables
#:   excel_conversion          rey_lib/load/convert.py _resolve_inline_excel_conversion_config
#:   sanitize_file             rey_lib/load/sanitize.py _resolve_config, rey_lib/files/sanitization.py
#:   profile_csv_record_types  rey_lib/load/profile.py run_record_type_profiling
#:   create_prepared_files     rey_lib/load/prepare.py _resolve_config
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


def _file_selection(*, with_source_field: bool = True) -> dict[str, Any]:
    """The manifest selection a governed file step reads its files through."""
    properties: dict[str, Any] = {
        "operation": {
            "type": "string",
            "description": "Manifest retrieval operation naming the files this step still has to handle.",
        },
    }
    required = ["operation"]
    if with_source_field:
        properties["source_field"] = {
            "type": "string",
            "description": "Field of each selected row that holds the file's path.",
        }
        required.append("source_field")
    return {
        "type": "object",
        "description": "Which governed files this step handles.",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _folder(description: str, **extra: dict[str, Any]) -> dict[str, Any]:
    """A destination folder with its own collision policy."""
    return {
        "type": "object",
        "description": description,
        "properties": {
            "path": {"type": "string", "description": "Folder path; placeholders resolve per file."},
            "overwrite": {
                "type": "boolean", "default": False,
                "description": "Replace an existing file of the same name.",
            },
            **extra,
        },
        "required": ["path"],
        "additionalProperties": False,
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


def _variant(operation: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """One variant of a dispatcher, chosen by its operation value."""
    return {
        "properties": {"operation": {"const": operation}, **properties, "scope": _SCOPE},
        "required": ["operation", *required],
        "additionalProperties": False,
    }


def _dispatcher(description: str, choices: dict[str, str], variants: list[dict[str, Any]]) -> dict[str, Any]:
    """A settings object whose operation value selects one variant."""
    return {
        "$schema": _SCHEMA,
        "type": "object",
        "description": description,
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(choices),
                "description": "Which operation this step performs: "
                + "; ".join(f"{name} -- {meaning}" for name, meaning in choices.items()),
            },
        },
        "required": ["operation"],
        "oneOf": variants,
    }


_PATH_KEY = "Named path key on the data source."
_CHARACTER_RULE: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["name", "reason"],
    "additionalProperties": False,
}
_CHARACTER_TABLE: dict[str, Any] = {
    "type": "object",
    "description": "Rules keyed by code point (U+XXXX).",
    "propertyNames": {"pattern": "^U\\+[0-9A-F]{4,6}$"},
    "additionalProperties": {"$ref": "#/$defs/character_rule"},
}
_SANITIZATION_DEFS: dict[str, Any] = {
    "character_rule": _CHARACTER_RULE,
    "policy": {
        "type": "object",
        "description": "One sanitization policy layer; a feed's layer overlays the global one.",
        "properties": {
            "policy_name": {"type": "string"},
            "policy_version": {"type": "string"},
            "remove": _CHARACTER_TABLE,
            "preserve": _CHARACTER_TABLE,
            "preserve_if_quoted": _CHARACTER_TABLE,
            "replace": {
                "type": "object",
                "description": "Replacement rules keyed by code point (U+XXXX).",
                "propertyNames": {"pattern": "^U\\+[0-9A-F]{4,6}$"},
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "reason": {"type": "string"},
                        "with": {"type": "string", "description": "Replacement text."},
                    },
                    "required": ["name", "reason", "with"],
                    "additionalProperties": False,
                },
            },
            "line_repair": {
                "type": "object",
                "description": "Line-repair rules keyed by rule name; a feed rule replaces a global rule of the same name.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regular expression; must not match empty."},
                        "replacement": {"type": "string"},
                        "reason": {"type": "string"},
                        "flags": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["ASCII", "IGNORECASE"]},
                        },
                    },
                    "required": ["pattern", "replacement", "reason"],
                    "additionalProperties": False,
                },
            },
            "max_logical_line_characters": {
                "type": "integer", "minimum": 1,
                "description": "Required in the effective policy when any line_repair rule applies.",
            },
        },
        "required": [
            "policy_name", "policy_version", "remove", "preserve", "preserve_if_quoted",
            "replace", "line_repair",
        ],
        "additionalProperties": False,
    },
}
_EMPTY_POLICY: dict[str, Any] = {
    "policy_name": "", "policy_version": "", "remove": {}, "preserve": {},
    "preserve_if_quoted": {}, "replace": {}, "line_repair": {},
}

WORKFLOW_OPERATIONS: list[dict[str, Any]] = [
    {
        "name": "file_operation",
        "description": "Discover, move or delete files.",
        "contract_definition": _dispatcher(
            "Discover, move or delete files.",
            {
                "discover": "list the files a data-source path holds",
                "discover_file": "bind the first file a data-source path holds as the current file",
                "move": "move the current file to a data-source path",
                "delete": "delete the current file",
            },
            [
                _variant("discover", {
                    "data_source": _DATA_SOURCE,
                    "path": {"type": "string", "description": _PATH_KEY},
                    "pattern": {"type": "string", "default": "*", "description": "Filename pattern."},
                    "max_files_per_run": {"type": "integer", "minimum": 1, "description": "Cap on files listed."},
                    "output": {
                        "type": "object",
                        "properties": {"files": {
                            "type": "string", "default": "discovered_files",
                            "description": "Run-context name the list is bound to.",
                        }},
                        "additionalProperties": False,
                    },
                }, ["data_source", "path"]),
                _variant("discover_file", {
                    "data_source": _DATA_SOURCE,
                    "path": {"type": "string", "description": _PATH_KEY},
                    "pattern": {"type": "string", "default": "*", "description": "Filename pattern."},
                    "output": {
                        "type": "object",
                        "properties": {"current_file": {
                            "type": "string", "default": "current_file",
                            "description": "Run-context name the file is bound to.",
                        }},
                        "additionalProperties": False,
                    },
                }, ["data_source", "path"]),
                _variant("move", {
                    "data_source": _DATA_SOURCE,
                    "to": {"type": "string", "description": _PATH_KEY},
                }, ["data_source", "to"]),
                _variant("delete", {}, []),
            ],
        ),
        "contract_sample": {"operation": "discover_file", "data_source": "", "path": "", "pattern": "*"},
    },
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
        "name": "inventory_source_files",
        "description": "Inventory every configured source set into the governed manifest.",
        "contract_definition": _contract(
            "Inventory every configured source set into the governed manifest.",
            {
                "sources": {
                    "type": "array",
                    "description": "The source sets this step enumerates; a disabled one is skipped unvalidated.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "enabled": {"type": "boolean"},
                            "source": {
                                "type": "object",
                                "properties": {
                                    "path": {
                                        "type": "string",
                                        "description": "Glob locating the files; no placeholders.",
                                    },
                                    "file_patterns": {
                                        "type": "array", "minItems": 1,
                                        "items": {"type": "string"},
                                        "description": "File name patterns the files must match.",
                                    },
                                    "recursive": {"type": "boolean", "default": False},
                                },
                                "required": ["path", "file_patterns"],
                                "additionalProperties": False,
                            },
                            "exclusions": {
                                "type": "array", "items": {"type": "string"},
                                "description": "File name patterns never inventoried.",
                            },
                        },
                        "required": ["name", "enabled", "source"],
                        "additionalProperties": False,
                    },
                },
            },
            ["sources"],
        ),
        "contract_sample": {"sources": [{
            "name": "", "enabled": True,
            "source": {"path": "", "file_patterns": ["*.csv"], "recursive": False},
            "exclusions": [],
        }]},
    },
    {
        "name": "classify_source_files",
        "description": "Classify inventoried files by their structural type.",
        "contract_definition": _contract(
            "Classify inventoried files by their structural type.",
            {
                "sources": {
                    "type": "array",
                    "description": "The classification sources, each with its own selection.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "enabled": {"type": "boolean"},
                            "classification_type": {"type": "string"},
                            "retry_rejects": {"type": "boolean", "default": False},
                            "processing": {
                                "type": "string",
                                "description": "Folder a classified file moves to; placeholders name variables.",
                            },
                            "file_selection": _file_selection(),
                            "variables": {
                                "type": "array", "minItems": 1,
                                "description": "Values the path regex captures, each by a named group.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "source": {"type": "string", "enum": ["classification"]},
                                        "required": {"type": "boolean", "default": True},
                                        "values": {
                                            "type": "array", "items": {"type": "string"},
                                            "description": "The values the capture may take.",
                                        },
                                        "format": {"type": "string", "description": "Format the value must parse in."},
                                    },
                                    "required": ["name", "source"],
                                    "additionalProperties": False,
                                },
                            },
                            "classification": {
                                "type": "object",
                                "properties": {
                                    "path_regex": {
                                        "type": "string",
                                        "description": "Regular expression over the path, a named group per variable.",
                                    },
                                    "profile": {
                                        "type": "object",
                                        "properties": {"key_fields": {
                                            "type": "array", "minItems": 1, "items": {"type": "string"},
                                            "description": "Declared variables whose values form the data_profile_key.",
                                        }},
                                        "required": ["key_fields"],
                                        "additionalProperties": False,
                                    },
                                },
                                "required": ["path_regex"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["name", "enabled", "classification_type", "file_selection", "variables", "classification"],
                        "additionalProperties": False,
                    },
                },
            },
            ["sources"],
        ),
        "contract_sample": {"sources": [{
            "name": "", "enabled": True, "classification_type": "", "retry_rejects": False,
            "file_selection": {"operation": "", "source_field": ""},
            "variables": [{"name": "", "source": "classification", "required": True}],
            "classification": {"path_regex": ""},
        }]},
    },
    {
        "name": "excel_conversion",
        "description": "Convert classified workbooks to CSV.",
        "contract_definition": _contract(
            "Convert classified workbooks to CSV.",
            {
                "file_selection": _file_selection(),
                "outbox": _folder("Where converted files are written."),
                "processing": _folder("Working folder for the conversion."),
                "archive": _folder("Where consumed workbooks are kept."),
                "include_hidden_sheets": {"type": "boolean", "default": False},
                "include_empty_sheets": {"type": "boolean", "default": False},
            },
            ["file_selection", "outbox"],
        ),
        "contract_sample": {
            "file_selection": {"operation": "", "source_field": ""},
            "outbox": {"path": "", "overwrite": False},
            "include_hidden_sheets": False, "include_empty_sheets": False,
        },
    },
    {
        "name": "create_prepared_files",
        "description": "Create the prepared file, clear or redacted, for each selected source.",
        "contract_definition": _contract(
            "Create the prepared file, clear or redacted, for each selected source.",
            {
                "file_selection": _file_selection(),
                "outbox": _folder("Where prepared files are written."),
                "output": {
                    "type": "string", "enum": ["clear", "redacted"], "default": "clear",
                    "description": "Which prepared file this process writes.",
                },
                "preparation": {
                    "type": "object",
                    "properties": {"headers": {
                        "type": "object",
                        "properties": {"convert_to": {"type": "string", "enum": ["snake_case"]}},
                        "required": ["convert_to"],
                        "additionalProperties": False,
                    }},
                    "required": ["headers"],
                    "additionalProperties": False,
                },
            },
            ["file_selection", "outbox", "preparation"],
        ),
        "contract_sample": {
            "file_selection": {"operation": "", "source_field": ""},
            "outbox": {"path": "", "overwrite": False},
            "output": "clear",
            "preparation": {"headers": {"convert_to": "snake_case"}},
        },
    },
    {
        "name": "profile_csv_record_types",
        "description": "Profile every sanitized file a routine selects.",
        "contract_definition": _contract(
            "Profile every sanitized file a routine selects.",
            {"file_selection": _file_selection(with_source_field=False)},
            ["file_selection"],
        ),
        "contract_sample": {"file_selection": {"operation": ""}},
    },
    {
        "name": "sanitize_file",
        "description": "Sanitize the governed files a routine selects.",
        "contract_definition": {
            **_contract(
                "Sanitize the governed files a routine selects.",
                {
                    "file_selection": _file_selection(),
                    "outbox": _folder(
                        "Where sanitized files are written.",
                        redacted_copy={
                            "type": "boolean", "default": False,
                            "description": "Also publish a redacted sister of each sanitized file.",
                        },
                    ),
                    "feed": {
                        "type": "string",
                        "description": "The feed whose policy in sanitization.feeds applies to this step.",
                    },
                    "sanitization": {
                        "type": "object",
                        "properties": {
                            "global": {"$ref": "#/$defs/policy"},
                            "feeds": {
                                "type": "object",
                                "description": "Feed policies keyed by feed name; each overlays the global policy.",
                                "additionalProperties": {"$ref": "#/$defs/policy"},
                            },
                        },
                        "required": ["global", "feeds"],
                        "additionalProperties": False,
                    },
                },
                ["file_selection", "outbox", "feed", "sanitization"],
            ),
            "$defs": _SANITIZATION_DEFS,
        },
        "contract_sample": {
            "file_selection": {"operation": "", "source_field": ""},
            "outbox": {"path": "", "overwrite": False},
            "feed": "all",
            "sanitization": {"global": dict(_EMPTY_POLICY), "feeds": {"all": dict(_EMPTY_POLICY)}},
        },
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
    }
