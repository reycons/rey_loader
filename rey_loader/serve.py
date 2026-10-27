"""rey_loader serving one Load to the launcher it is attached to (#1151).

The application model (recipe app.serve_a_live_object_to_a_panel; workflow_app and
file_operator are the precedent): rey_loader hosts the live Load -- the canonical
Source, Transform and Target, the Transform holding the other two (backlog 831) --
for as long as the launcher stays attached. The Console only connects, sends the
reader's actions and displays:

    launcher --{"command": ...}--> serve --> the live objects' own methods
    the composed Load projection ---------> serve --> launcher

Nothing here decides a Load's state: each object owns its own, and changes it only
through its own methods. This builds the three objects from one opening identity,
holds them, routes each command to the object it names, and composes the Load's
projection from the three objects' own projections. There is no Load object: the
composition is this host's presentation of the three, projected under the subject the
live Load is (#1151): ``loader.`` and the first segment of the selected subject the
Load acts on (``presentation_key``), whose tree.subject_panel row chooses its panel.
"""

from __future__ import annotations

import inspect
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Optional

from rey_lib.config.applications import configured_application
from rey_lib.db.connection import build_connections, is_database_connection
from rey_lib.db.database_query import DatabaseQuery
from rey_lib.errors.error_utils import AppError, ConfigError, StateError
from rey_lib.files.data_file.base import DataFile
from rey_lib.load import Source, Target, Transform
from rey_lib.logs import AppLogger
from rey_lib.run.capabilities import HostedCapabilities
from rey_lib.run_lifecycle import run_app_operation

from rey_loader.load import run_load_objects
from rey_loader.registration import APPLICATION_NAME

__all__ = ["hosted_capabilities", "hosted_load", "presentation_key", "serve"]

_logger = AppLogger(__name__)

#: The presentation subject of a live Load (#1151): this prefix and the first segment
#: of the selected subject the Load acts on (file -> loader.file, mutation.record ->
#: loader.mutation). Which panel presents it is its tree.subject_panel row.
_PRESENTATION_PREFIX: Final[str] = "loader."

#: The kinds a handed-over Source opens on: a viewer hands over a file, a query
#: surface a statement and the connection it runs on.
_SOURCE_KIND_FILE: Final[str] = "file"
_SOURCE_KIND_DATABASE: Final[str] = "database"

#: What each of the three objects answers to: its own methods, named as the object
#: names them, under the panel's name for the object.
_OPERATIONS: Final[dict[str, dict[str, Callable[..., Any]]]] = {
    "source": {
        "select": Source.select,
        "update": Source.update,
        "save_query": Source.save_query,
        "save_saved_settings": Source.save_saved_settings,
    },
    "transform": {
        "select": Transform.select,
        "update": Transform.update,
        "edit_column": Transform.edit_column,
        "edit_column_setting": Transform.edit_column_setting,
        "add_column": Transform.add_column,
        "move_column": Transform.move_column,
        "select_http_operation": Transform.select_http_operation,
        "edit_request_field": Transform.edit_request_field,
        "save": Transform.save,
        "select_saved_setting": Transform.select_saved_setting,
        "new_saved_setting": Transform.new_saved_setting,
        "delete_saved_setting": Transform.delete_saved_setting,
    },
    "destination": {
        "select": Target.select,
        "update": Target.update,
        "set_write_policy": Target.set_write_policy,
    },
}


def hosted_load(
    ctx: Any,
    *,
    file_manifest_id: str | None = None,
    file_mutation_id: str | None = None,
    file: str | None = None,
    source_connection: str | None = None,
    statement: str | None = None,
) -> tuple[Source, Transform, Target]:
    """The Source, Transform and Target one opening identity names.

    Exactly one identity is given. A governed file establishes its Source from its
    one governed read; a handed-over file, authorized beneath the installation's
    permitted roots, opens a file-kind Source on that path, and nothing more is
    made of it; a handed-over statement opens a database-kind Source. The Target
    starts empty -- where the rows go is the reader's -- and the Transform is built
    on the two, holding them.

    Raises:
        ConfigError: When the identity names nothing that can be opened, or the
            file is outside the installation's permitted roots.
    """
    if file_manifest_id or file_mutation_id:
        # The launch inputs are text; the governed read takes and checks ids.
        source = Source.from_governed(
            ctx, file_manifest_id=_governed_id("file_manifest_id", file_manifest_id),
            file_mutation_id=_governed_id("file_mutation_id", file_mutation_id),
        )
    elif file:
        authorized = ctx.paths.authorize(file)
        source = Source.from_declaration(
            {"values": _load_values(authorized), "selected": _SOURCE_KIND_FILE},
        )
    elif statement:
        source = Source.from_declaration({
            "values": {"statement": statement, "source-connection": source_connection or ""},
            "selected": _SOURCE_KIND_DATABASE,
        })
    else:
        raise ConfigError("rey_loader serve: no load identity was given.")
    target = Target.from_declaration({})
    transform = Transform.from_source(ctx, source, {}, target=target)
    return source, transform, target


#: How a reader reads the Source's query: a DatabaseQuery's reading state.
_READING: Final[frozenset[str]] = frozenset(
    {"pageable", "rows_per_page", "current_page", "order_by", "filters"})


def _execute(channel: Any, query: Any, request_id: Any) -> None:
    """Execute the Source's query as it is being read, and answer the reader (#1151).

    The admitted answer boundary rey_db_admin and file_operator keep for the same
    protocol: DatabaseQuery.execute owns the operation; a failure it did not expect
    is converted to AppError, reported once and answered, and serving goes on.
    """
    try:
        answer = query.execute()
    except Exception as exc:  # noqa: BLE001 -- the admitted execution answer boundary
        _answer_failure(channel, exc, "execute", request_id)
        return
    channel.emit({"result": answer, "request_id": request_id})


def _lint(channel: Any, query: Any, ctx: Any, request_id: Any) -> None:
    """Lint the Source's statement through its query, and answer the reader (#1252).

    The same admitted answer boundary as ``_execute``: DatabaseQuery.lint owns the
    operation; a failure is reported once and answered, and serving goes on.
    """
    try:
        answer = query.lint(ctx)
    except Exception as exc:  # noqa: BLE001 -- the admitted lint answer boundary
        _answer_failure(channel, exc, "lint", request_id)
        return
    channel.emit({"result": answer, "request_id": request_id})


def _governed_id(name: str, given: str | None) -> int | None:
    """One governed identity from its launch input, as the id it names; None when absent.

    Raises:
        ConfigError: When the input is not a whole number.
    """
    if not given:
        return None
    try:
        return int(given)
    except ValueError as exc:
        raise ConfigError(f"rey_loader serve: {name} is not an id: {given!r}.") from exc


def _load_values(path: Path) -> dict[str, Any]:
    """A handed-over file's Source values: the path, and its type where its suffix names one.

    The file type is the suffix mapping's answer (``DataFile.for_path``), not a
    second one written here. Where it does not recognise the file the key is
    omitted, which the Source reads as Auto detect -- a guess would be worse than
    none.
    """
    values: dict[str, Any] = {"file": str(path)}
    try:
        values["file-type"] = DataFile.for_path(path).file_type
    except ConfigError:
        # An unrecognised file is ordinary. The Source resolves it the same way
        # when the field is left blank, so there is nothing to report.
        pass
    return values


def hosted_capabilities(
    ctx: Any, control: Any, source: Source, transform: Transform, target: Target,
    hosted_kind: str,
) -> HostedCapabilities:
    """The capabilities answered against the three objects this serve holds (#1199 S5).

    The catalogue is this application's code: each key reaches one held object's
    own definition -- never a composite of the three, and nothing that reads
    records, columns or tables. ``hosted_kind`` is the identity this serve was
    opened by. Whether a key may be invoked is HostedCapabilities' answer,
    against this application's registration and governed declarations.
    """
    catalogue = {
        "load_source.definition": lambda inputs: source.definition(),
        "load_transform.definition": lambda inputs: transform.definition(),
        "load_target.definition": lambda inputs: target.definition(),
    }
    return HostedCapabilities(configured_application(ctx, APPLICATION_NAME), control,
                              catalogue, hosted_kind)


def serve(
    channel: Any, source: Source, transform: Transform, target: Target, ctx: Any,
    *, run_log: Any, capabilities: Any, declared: Any,
) -> None:
    """Hold the Load for the launcher on ``channel`` until it closes or detaches.

    The launcher first receives the Load's projection. Then each command it sends
    is answered, in order:

    - ``{"command": "projection"}`` is answered with the current projection, so a
      view that attaches to this running application draws what the objects hold.
    - ``{"command": "operate", "object": "source" | "transform" | "destination",
      "operation": ..., "arguments": {...}}`` calls that object's own method, in
      its own act, and answers ``{"projection": ..., "request_id": ...}``.
    - ``{"command": "preview", "request_id": ...}`` previews through the
      Transform and answers ``{"preview": ..., "projection": ..., "request_id":
      ...}``, both taken in one act of the Transform.
    - ``{"command": "run", "dry_run": bool, "request_id": ...}`` performs one load
      of the live objects as an operation of this application's Run (``_run``),
      off the thread reading commands, and answers ``{"loaded": {"status",
      "rows"}, "request_id"}``. While it runs, ``run``, ``operate`` and
      ``preview`` are refused -- the load is reading the objects -- and
      ``projection`` is answered.
    - ``{"command": "lint", "request_id": ...}`` lints the Source's statement
      through an ephemeral DatabaseQuery on it, off the thread reading commands,
      and answers ``{"result": {formattedSql, diagnostics}, "request_id"}`` (#1252).
    - ``{"command": "invoke", "capability": ..., "inputs": {...}, "request_id"}``
      asks ``capabilities``, answered inline ``{"result": ..., "request_id"}``
      (#1199 S5) -- a read of one held object, so a running load does not
      refuse it.
    - ``{"command": "close"}`` -- the panel's explicit close, sent by
      ``LaunchedApp.close`` -- waits for a running load, then releases the
      Transform's Source and Target and ends serving.

    A view going away, moving or being restored never reaches this channel: its
    stream ends at the Console, and it reattaches to the launcher by its token.
    Serving also ends when the launcher itself detaches, as workflow_app's does;
    only ``close`` releases anything. A refusal is reported and answered
    ``{"error": <message>, "command", "request_id"}``, and serving goes on.

    Args:
        channel: This application's end of the channel (AttachedApp.attach).
        source, transform, target: The Load's three objects (``hosted_load``).
        ctx: The runtime they are projected and operated in.
        run_log: This application's run log, which records each load operation.
        capabilities: What may be invoked on the three objects (``hosted_capabilities``).
    """
    held = {"source": source, "transform": transform, "destination": target}
    channel.emit({"projection": _projection(ctx, declared, source, transform, target)})
    # How the reader is reading the Source's statement (#1151): the page, ordering
    # and filters the SQL card last asked for. The statement and its connection are
    # the Source's own and are never held here.
    reading: dict[str, Any] = {}
    running: Optional[Future[None]] = None
    closed = False
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rey_loader-load") as loading:
        for command in channel.commands():
            name = str(command.get("command") or "")
            request_id = command.get("request_id")
            if name == "close":
                closed = True
                break
            if name == "projection":
                channel.emit({"projection": _projection(ctx, declared, source, transform, target)})
                continue
            if name == "update":
                # THE SQL CARD'S LIVE QUERY IS THE SOURCE'S (#1151): its statement is
                # the Source's field, the rest is how it is being read.
                changes = dict(command.get("changes") or {})
                try:
                    if "statement" in changes:
                        with source.act():
                            source.update("statement", changes.pop("statement"))
                    unknown = sorted(set(changes) - _READING)
                    if unknown:
                        raise ConfigError(f"The Source's query has no live property {unknown}.")
                except AppError as refusal:
                    _answer_failure(channel, refusal, name, request_id)
                    continue
                reading.update(changes)
                channel.emit({"projection": _projection(ctx, declared, source, transform, target)})
                continue
            if name == "execute":
                try:
                    query = source.query(ctx)
                    query.update(**reading)
                except AppError as refusal:
                    _answer_failure(channel, refusal, name, request_id)
                    continue
                loading.submit(_execute, channel, query, request_id)
                continue
            if name == "lint":
                # The Source owns the statement (#1252): an ephemeral, connection-free
                # query over it lints it, as Source.query builds one per execute.
                with source.act():
                    statement = str(source.value("statement") or "")
                loading.submit(_lint, channel, DatabaseQuery(statement), ctx, request_id)
                continue
            if name == "invoke":
                try:
                    answer = capabilities.invoke(str(command.get("capability") or ""),
                                                 command.get("inputs", {}))
                except AppError as refusal:
                    _answer_failure(channel, refusal, name, request_id)
                    continue
                channel.emit({"result": answer, "request_id": request_id})
                continue
            if name in ("run", "operate", "preview") and running is not None \
                    and not running.done():
                _answer_failure(channel, StateError(
                    f"A load is running; the {name} waits until it has finished."),
                    name, request_id)
                continue
            if name == "run":
                running = loading.submit(_run, channel, ctx, run_log, source, transform,
                                         target, not bool(command.get("dry_run")),
                                         request_id)
                continue
            if name in ("operate", "preview"):
                try:
                    if name == "operate":
                        _operate(ctx, held, command)
                        answer = {"projection": _projection(ctx, declared, source, transform, target),
                                  "request_id": request_id}
                    else:
                        answer = {**_preview(ctx, declared, source, transform, target),
                                  "request_id": request_id}
                # What the legacy preview answered rather than raised
                # (LoadObjects.preview): an object's refusal, and a source that
                # cannot be read or parsed.
                except (AppError, ValueError, OSError) as refusal:
                    _answer_failure(channel, refusal, name, request_id)
                    continue
                channel.emit(answer)
                continue
            channel.emit({"error": f"rey_loader does not answer the command {name!r}.",
                          "command": name, "request_id": request_id})
        else:
            # The launcher's handle is gone, and with it the token any view
            # reattaches by: serving ends as workflow_app's does, and nothing is
            # released here.
            _logger.info("rey_loader serve: the launcher detached.")
    # Leaving the executor waited for a running load: closing is not cancelling.
    if closed:
        # THE SEMANTIC CLOSE, and the only thing that ends the hosted Load: the
        # Transform stops referencing its two.
        transform.release(source)
        transform.release(target)


def presentation_key(subject: str) -> str:
    """The subject the live Load presents itself as (#1151).

    ``loader.`` and the first segment of the selected subject the Load acts on:
    ``file`` -> ``loader.file``, ``mutation.record`` -> ``loader.mutation``. The
    selected subject is the Tree row's own, passed by the Load interaction; which
    panel presents the Load is the result's tree.subject_panel row.

    Raises:
        ConfigError: When no selected subject was given.
    """
    head = str(subject or "").strip().split(".", 1)[0]
    if not head:
        raise ConfigError("rey_loader serve: a Load opens on the selected subject it acts on; "
                          "none was given.")
    return f"{_PRESENTATION_PREFIX}{head}"


def _projection(ctx: Any, declared: Any, source: Source, transform: Transform,
                target: Target) -> dict[str, Any]:
    """The Load, as this host presents it: its governed presentation (``declared``, the
    Projection of its subject), each object's own projection, and the configured
    database connections a reader may choose for either end.

    The connections are this host's runtime, not either object's vocabulary
    (file_operator's serve offers its query the same way): in configured order,
    and which one is chosen is the reader's.
    """
    projected = {
        "source": source.projection(ctx),
        "transform": transform.projection(ctx),
        "destination": target.projection(ctx),
    }
    return declared.projecting({
        **projected,
        # What can be invoked, each with the complete command that invokes it
        # (#1151, the Workflow pattern): the panel sends it unchanged.
        "actions": _actions(projected),
        "connections": [connection.name for connection in build_connections(ctx).values()
                        if is_database_connection(connection)],
    }).to_dict()


#: Operations an object offers only when its own projection says it can (#1151): the
#: Source saves its query, the Transform saves itself, only where each declares so.
_DECLARED_OPERATIONS: Final[frozenset[str]] = frozenset({"save_query", "save"})


#: WHAT EACH ROUTED OPERATION DOES TO THE PROJECTED STATE A CONTROL DRAWS (#1151 row 5):
#: its role -- an ``act`` on ``on``, a key of its object's projection (with ``field``
#: for one value) -- and each role input's method parameter. A surface finds an action
#: by the state it draws and what it does to it, never by the operation's name. An
#: operation with no role here is reached through a field edit (``update``, or its
#: object's ``field_operations``) and is not otherwise presented.
_ROLES: Final[dict[str, dict[str, tuple[dict[str, str], dict[str, str]]]]] = {
    "source": {
        "select": ({"act": "choose", "on": "kinds"}, {"choice": "kind"}),
        "save_query": ({"act": "save", "on": "values", "field": "statement"}, {}),
        "save_saved_settings": ({"act": "save", "on": "saved_settings"},
                                {"settings": "settings"}),
    },
    "transform": {
        "select": ({"act": "choose", "on": "kinds"}, {"choice": "kind"}),
        "edit_column": ({"act": "set", "on": "columns"},
                        {"index": "at", "field": "field", "value": "value"}),
        "edit_column_setting": ({"act": "set", "on": "column_settings"},
                                {"index": "at", "setting": "setting", "value": "value"}),
        "add_column": ({"act": "add", "on": "columns"}, {"after": "after"}),
        "move_column": ({"act": "move", "on": "columns"}, {"index": "at", "to": "to"}),
        "edit_request_field": ({"act": "set", "on": "http_request"},
                               {"part": "part", "name": "name", "value": "value"}),
        "save": ({"act": "save", "on": "columns"}, {}),
        "select_saved_setting": ({"act": "choose", "on": "saved_settings"},
                                 {"choice": "transform_id"}),
        "new_saved_setting": ({"act": "add", "on": "saved_settings"}, {}),
        "delete_saved_setting": ({"act": "remove", "on": "saved_settings"}, {}),
    },
    "destination": {
        "select": ({"act": "choose", "on": "kinds"}, {"choice": "kind"}),
        "set_write_policy": ({"act": "choose", "on": "modes"}, {"choice": "policy"}),
    },
}


def _actions(projected: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The Load's invokable actions, each ``{role, command, inputs?}`` (#1151).

    Derived, never a second capability model: from this host's own routing table
    (``_OPERATIONS``, with each operation's role, ``_ROLES``) and from what the
    objects already declare -- their fields and field operations, and the operations
    they offer. ``role`` says what the action does to which projected state;
    ``command`` is the complete command this host answers; ``inputs`` maps each of
    the role's inputs a reader supplies to its path in that command. A field is its
    own action, setting that value: which operation editing it invokes is the
    object's ``field_operations`` answer, else ``update``.
    """
    actions: dict[str, list[dict[str, Any]]] = {}
    for name in _OPERATIONS:
        shown = projected.get(name) or {}
        offered = set(shown.get("operations") or [])
        field_operations = dict(shown.get("field_operations") or {})
        # EVERY VALUE THE OBJECT HAS DRAWN: its form fields, the fields that choose a
        # request it carries, and any field whose edit is an operation of its own.
        fields = sorted(
            {field for listed in (shown.get("fields") or {}).values() for field in listed}
            | {field for listed in (shown.get("request_fields") or {}).values()
               for field in listed}
            | set(field_operations)
        )
        listed: list[dict[str, Any]] = [
            {"role": {"act": "set", "on": "values", "field": field},
             "command": {"command": "operate", "object": name,
                         "operation": field_operations.get(field, "update"),
                         "arguments": {"name": field}},
             "inputs": {"value": ["arguments", "value"]}}
            for field in fields
        ]
        for operation, (role, inputs) in _ROLES[name].items():
            if operation in _DECLARED_OPERATIONS and operation not in offered:
                continue
            listed.append({
                "role": dict(role),
                "command": {"command": "operate", "object": name, "operation": operation,
                            "arguments": {}},
                **({"inputs": {given: ["arguments", parameter]
                               for given, parameter in inputs.items()}} if inputs else {}),
            })
        actions[name] = listed
    actions["load"] = [
        {"role": {"act": "read", "on": "load"}, "command": {"command": "projection"}},
        {"role": {"act": "read", "on": "preview"}, "command": {"command": "preview"}},
        {"role": {"act": "run", "on": "load"}, "command": {"command": "run"},
         "inputs": {"dry_run": ["dry_run"]}},
    ]
    return actions


def _operate(ctx: Any, held: Mapping[str, Any], command: Mapping[str, Any]) -> None:
    """Call the one method ``command`` names on the object it names, in that object's act.

    An operation that reads through the runtime takes it as ``ctx``.

    Raises:
        ConfigError: When the object or the operation is not one the Load answers to.
        AppError: When the object refuses what it was asked.
    """
    object_name = str(command.get("object") or "")
    operations = _OPERATIONS.get(object_name)
    if operations is None:
        raise ConfigError(
            f"A Load has no object '{object_name}'. Objects: {', '.join(_OPERATIONS)}."
        )
    operation = str(command.get("operation") or "")
    method = operations.get(operation)
    if method is None:
        raise ConfigError(
            f"A {object_name} has no operation '{operation}'. "
            f"Operations: {', '.join(sorted(operations))}."
        )
    given = dict(command.get("arguments") or {})
    if "ctx" in inspect.signature(method).parameters:
        given["ctx"] = ctx
    instance = held[object_name]
    _logger.debug("rey_loader serve: %s.%s", object_name, operation)
    with instance.act():
        method(instance, **given)


def _preview(ctx: Any, declared: Any, source: Source, transform: Transform,
             target: Target) -> dict[str, Any]:
    """Preview through the Transform, with the Load's projection of the same state.

    The Transform's own preview (backlog 831), in one act of the Transform with the
    projection, so the two describe the same state.

    Raises:
        AppError: When the Transform refuses to preview.
        ValueError, OSError: When its Source cannot be read or parsed.
    """
    with transform.act():
        found = transform.preview(ctx)
        return {
            "preview": {"columns": list(found.columns), "rows": list(found.rows),
                        "truncated": found.truncated},
            "projection": _projection(ctx, declared, source, transform, target),
        }


def _run(
    channel: Any, ctx: Any, run_log: Any, source: Source, transform: Transform,
    target: Target, apply: bool, request_id: Any,
) -> None:
    """Perform one load of the live objects, as an operation of this application's Run.

    ``run_app_operation`` gives it its lifecycle in this application's run log --
    RUN_START, the effects, RUN_COMPLETE -- exactly as the ``load`` command has one;
    no Run of its own is made. A dry run records the operation and skips the load
    entirely, as ``load --dry-run`` does: nothing is validated or executed.

    The body answers the operation's protocol (0) and the rows go to the caller.
    A failed load is the operation's, recorded RUN_COMPLETE failed and answered;
    it does not fail this application's Run, which goes on serving.

    The hosting application's answer boundary for one load (rule
    exceptions_are_caught_narrowly, admitted 2026-10-21): run off the command
    thread, a failure the load did not expect is converted to AppError with the
    original as its cause, reported once and answered, and serving goes on with
    the hosted Load alive.
    """
    loaded = {"rows": 0}

    def body() -> int:
        if not apply:
            _logger.info("load skipped (dry-run).")
            return 0
        loaded["rows"] = run_load_objects(ctx, run_log, source, transform, target)
        return 0

    try:
        run_app_operation(ctx, run_log, "load", body, settings={"apply": apply})
    except Exception as exc:  # noqa: BLE001 -- the admitted load answer boundary
        _answer_failure(channel, exc, "run", request_id)
        return
    channel.emit({"loaded": {"status": "SUCCEEDED", "rows": loaded["rows"]},
                  "request_id": request_id})


def _answer_failure(channel: Any, exc: Exception, command: str, request_id: Any) -> None:
    """Report a refusal when it happens, and answer it."""
    failure = exc if isinstance(exc, AppError) else AppError(
        f"rey_loader serve: the {command} failed: {exc}")
    if failure is not exc:
        failure.__cause__ = exc
    # Answered to the launcher, so reported here (rule 79).
    failure.report(f"rey_loader serve: {command}", source=__name__)
    channel.emit({"error": str(failure), "command": command, "request_id": request_id})
