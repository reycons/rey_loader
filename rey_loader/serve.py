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
composition is this host's presentation of the three, under its ``PANEL_TYPE``.
"""

from __future__ import annotations

import inspect
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Optional

from rey_lib.db.connection import build_connections, is_database_connection
from rey_lib.errors.error_utils import AppError, ConfigError, StateError
from rey_lib.files.data_file.base import DataFile
from rey_lib.load import Source, Target, Transform
from rey_lib.logs import AppLogger
from rey_lib.run_lifecycle import run_app_operation

from rey_loader.load import run_load_objects

__all__ = ["PANEL_TYPE", "hosted_load", "serve"]

_logger = AppLogger(__name__)

#: The presentation type of the Load this host composes. Which Console panel
#: presents it is the Console's (``PANELS``); this only names what is presented.
PANEL_TYPE: Final[str] = "load"

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
        source = Source.from_governed(
            ctx, file_manifest_id=file_manifest_id, file_mutation_id=file_mutation_id,
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


def serve(
    channel: Any, source: Source, transform: Transform, target: Target, ctx: Any,
    *, run_log: Any,
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
    """
    held = {"source": source, "transform": transform, "destination": target}
    channel.emit({"projection": _projection(ctx, source, transform, target)})
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
                channel.emit({"projection": _projection(ctx, source, transform, target)})
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
                        answer = {"projection": _projection(ctx, source, transform, target),
                                  "request_id": request_id}
                    else:
                        answer = {**_preview(ctx, source, transform, target),
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


def _projection(ctx: Any, source: Source, transform: Transform, target: Target) -> dict[str, Any]:
    """The Load, as this host presents it: its type, each object's own projection, and
    the configured database connections a reader may choose for either end.

    The connections are this host's runtime, not either object's vocabulary
    (file_operator's serve offers its query the same way): in configured order,
    and which one is chosen is the reader's.
    """
    return {
        "panel_type": PANEL_TYPE,
        "source": source.projection(ctx),
        "transform": transform.projection(ctx),
        "destination": target.projection(ctx),
        "connections": [connection.name for connection in build_connections(ctx).values()
                        if is_database_connection(connection)],
    }


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


def _preview(ctx: Any, source: Source, transform: Transform, target: Target) -> dict[str, Any]:
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
            "projection": _projection(ctx, source, transform, target),
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
