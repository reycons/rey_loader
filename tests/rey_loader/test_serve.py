"""rey_loader serving one Load to the launcher (#1151 S1).

The Load is the canonical Source, Transform and Target themselves, on a CSV file in
a temporary directory, so these tests need no installation. serve() routes each
command to the object it names and composes the Load's projection from the three
objects' own projections.
"""

from __future__ import annotations

import inspect
import queue
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from rey_lib.errors.error_utils import AppError, ConfigError, StateError
from rey_lib.load import Source, Target, Transform
from rey_lib.presentation import Projection
from rey_lib.run.app_channel import LaunchedApp

import main as loader_main
from rey_loader.registration import get_registration
from rey_loader.serve import _OPERATIONS, _ROLES, _actions, hosted_load, presentation_key, serve

_ROOT = Path(__file__).resolve().parents[2]

#: How long any one wait in these tests may take.
WAIT = 20.0


def _rows(tmp_path: Path) -> Path:
    path = tmp_path / "rows.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    return path


def _load(path: Path) -> tuple[Source, Transform, Target]:
    """The three objects of a load on ``path``, built as ``hosted_load`` builds them."""
    source = Source.from_declaration(
        {"values": {"file": str(path), "file-type": "csv"}, "selected": "file"})
    target = Target.from_declaration({})
    return source, Transform.from_source(SimpleNamespace(), source, {}, target=target), target


class _RunLog:
    """A stand-in for the application's run log: the records appended to it, in order."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def append(self, record_type: str, **fields: Any) -> int:
        self.records.append((record_type, fields))
        return len(self.records)

    def set_nest_level(self, level: str) -> None:
        del level

    def require_structural_record(self, run_log_id: Any, record_type: str) -> None:
        del run_log_id, record_type

    def completions(self) -> list[str]:
        """The status of each RUN_COMPLETE, in order."""
        return [fields.get("status", "") for kind, fields in self.records
                if kind == "RUN_COMPLETE"]


class _Capabilities:
    """A stand-in HostedCapabilities for the tests that do not invoke."""

    def invoke(self, capability: str, inputs: Any) -> Any:
        raise AssertionError(f"not invoked here: {capability}")


#: The governed presentation of a Load opened on a selected file (#1151).
_DECLARED = Projection(subject_key="loader.file", panel="loader_panel", panel_settings={},
                       content={})


def _hosting() -> dict[str, Any]:
    """What a serve call in these tests is hosted with: a runtime, a run log, capabilities,
    and the Load's governed presentation."""
    return {"ctx": SimpleNamespace(), "run_log": _RunLog(), "capabilities": _Capabilities(),
            "declared": _DECLARED}


class _Channel:
    """A stand-in for this application's end of the channel.

    Given a queue, its commands are those put on it, until None.
    """

    def __init__(self, commands: "list[dict[str, Any]] | queue.Queue[Any]") -> None:
        self._commands = commands
        self.emitted: list[dict[str, Any]] = []
        self.pushed: queue.Queue[dict[str, Any]] = queue.Queue()

    def commands(self) -> Any:
        if isinstance(self._commands, list):
            yield from self._commands
            return
        while (command := self._commands.get(timeout=WAIT)) is not None:
            yield command

    def emit(self, message: dict[str, Any]) -> None:
        self.emitted.append(message)
        self.pushed.put(message)


@pytest.fixture(autouse=True)
def _reports(monkeypatch: pytest.MonkeyPatch) -> list[AppError]:
    """Refusals are reported; collected here rather than written to a log."""
    reported: list[AppError] = []
    monkeypatch.setattr(AppError, "report", lambda self, *_a, **_k: reported.append(self))
    return reported


class _Query:
    """A stand-in DatabaseQuery: what it was built with, read with and answered."""

    def __init__(self, statement: str, connection: str) -> None:
        self.statement, self.connection = statement, connection
        self.reading: dict[str, Any] = {}

    def update(self, **changes: Any) -> None:
        self.reading.update(changes)

    def execute(self) -> dict[str, Any]:
        return {"pageable": True, "rows": [{"statement": self.statement}]}


def _database_load(monkeypatch: pytest.MonkeyPatch) -> tuple[Source, Transform, Target]:
    """A Load on a database Source whose query is the stand-in, built from its own fields."""
    source = Source.from_declaration({"values": {
        "statement": "select 1", "source-connection": "file_reader"}, "selected": "database"})
    monkeypatch.setattr(source, "query", lambda ctx: _Query(
        str(source.value("statement")), str(source.value("source-connection"))))
    target = Target.from_declaration({})
    return source, Transform.from_source(SimpleNamespace(), source, {}, target=target), target


def test_the_sql_cards_query_is_the_sources_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """#1151: the card's update writes the Source's statement; execute runs it, read as asked."""
    source, transform, target = _database_load(monkeypatch)
    channel = _Channel([
        {"command": "update", "changes": {"statement": "select 2", "current_page": 0,
                                          "rows_per_page": 25, "order_by": [], "filters": []}},
        {"command": "execute", "request_id": "sql-card-1"},
        {"command": "close"},
    ])

    serve(channel, source, transform, target, **_hosting())

    assert source.value("statement") == "select 2"
    answered = [one for one in channel.emitted if one.get("request_id") == "sql-card-1"]
    assert answered == [{"result": {"pageable": True, "rows": [{"statement": "select 2"}]},
                         "request_id": "sql-card-1"}]
    # The update is answered with the Load's projection, carrying the Source's statement.
    projected = [one["projection"] for one in channel.emitted if "projection" in one]
    assert projected[-1]["source"]["values"]["statement"] == "select 2"


class _Linted:
    """A stand-in DatabaseQuery for lint: what it was built with, and its lint answer."""

    built: list[tuple[str, dict[str, Any]]] = []
    raises: Exception | None = None

    def __init__(self, statement: str, **kwargs: Any) -> None:
        self.statement = statement
        _Linted.built.append((statement, kwargs))

    def lint(self, ctx: Any) -> dict[str, Any]:
        if _Linted.raises is not None:
            raise _Linted.raises
        return {"formattedSql": self.statement.upper(), "diagnostics": []}


def test_lint_lints_the_sources_statement_and_holds_no_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1252: an ephemeral, connection-free query over the Source's statement lints it."""
    from rey_loader import serve as module

    monkeypatch.setattr(_Linted, "built", [])
    monkeypatch.setattr(_Linted, "raises", None)
    monkeypatch.setattr(module, "DatabaseQuery", _Linted)
    source, transform, target = _database_load(monkeypatch)
    channel = _Channel([
        {"command": "update", "changes": {"statement": "select 2"}},
        {"command": "lint", "request_id": "lint-1"},
        {"command": "close"},
    ])

    serve(channel, source, transform, target, **_hosting())

    assert _Linted.built == [("select 2", {})]
    answered = [one for one in channel.emitted if one.get("request_id") == "lint-1"]
    assert answered == [{"result": {"formattedSql": "SELECT 2", "diagnostics": []},
                         "request_id": "lint-1"}]
    # Lint is read-only: the Source's statement is what the reader wrote.
    assert source.value("statement") == "select 2"


def test_a_failed_lint_is_answered_and_serving_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rey_loader import serve as module

    monkeypatch.setattr(_Linted, "built", [])
    monkeypatch.setattr(_Linted, "raises", AppError("unparsable"))
    monkeypatch.setattr(module, "DatabaseQuery", _Linted)
    source, transform, target = _database_load(monkeypatch)
    channel = _Channel([
        {"command": "lint", "request_id": "lint-2"},
        {"command": "projection"},
        {"command": "close"},
    ])

    serve(channel, source, transform, target, **_hosting())

    (refused,) = [one for one in channel.emitted if "error" in one]
    assert refused["command"] == "lint" and refused["request_id"] == "lint-2"
    assert "unparsable" in refused["error"]
    # The projection asked for after it is still answered: serving went on.
    assert len([one for one in channel.emitted if "projection" in one]) == 2


def test_a_property_the_query_does_not_have_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    source, transform, target = _database_load(monkeypatch)
    channel = _Channel([{"command": "update", "changes": {"connection": "elsewhere"},
                         "request_id": "u1"}, {"command": "close"}])

    serve(channel, source, transform, target, **_hosting())

    (refused,) = [one for one in channel.emitted if "error" in one]
    assert "no live property ['connection']" in refused["error"]
    assert source.value("source-connection") == "file_reader"


def test_serve_sends_the_composed_projection_first(tmp_path: Path) -> None:
    channel = _Channel([{"command": "close"}])

    serve(channel, *_load(_rows(tmp_path)), **_hosting())

    (first,) = channel.emitted
    projection = first["projection"]
    # Projected under the live Load's subject (#1151): its governed panel beside the
    # three objects' own projections.
    assert (projection["subject_key"], projection["panel"]) == ("loader.file", "loader_panel")
    assert set(projection) == {"subject_key", "panel", "panel_settings", "source",
                               "transform", "destination", "connections", "actions"}
    # The host's runtime offers no configured connection here.
    assert projection["connections"] == []
    # Each object describes its own fields, and offers its own choices.
    assert projection["source"]["field_metadata"]["statement"]["value_type"] == "sql"
    assert projection["destination"]["field_metadata"]["table"]["placeholder"] == "schema.table"
    # #1151 rows 1-3: what each value IS, and which kind the modes are of, reach the
    # panel as the objects state them.
    assert projection["source"]["field_metadata"]["source-connection"]["value_type"] \
        == "connection"
    assert projection["destination"]["field_metadata"]["connection"]["value_type"] \
        == "connection"
    assert projection["destination"]["field_metadata"]["table"]["value_type"] == "table"
    assert projection["destination"]["modes_kind"] == "database"
    # #1151 row 4: which kinds map columns, and the HTTP request (none chosen here),
    # as the Transform states them.
    assert projection["transform"]["mapping_kinds"] == ["declaration", "http", "manifest"]
    assert projection["transform"]["http_request"] is None
    assert projection["transform"]["request_fields"]["http"] == ["http-adapter"]
    assert "file-type" in projection["source"]["choices"]
    assert projection["source"]["selected"] == "file"
    assert projection["transform"]["source_columns"] == ["a", "b"]
    assert projection["destination"]["selected"] == "database"


def test_operate_calls_the_named_objects_own_method_and_answers_the_projection(
    tmp_path: Path,
) -> None:
    source, transform, target = _load(_rows(tmp_path))
    channel = _Channel([
        {"command": "operate", "object": "destination", "operation": "update",
         "arguments": {"name": "table", "value": "stage.rows"}, "request_id": "o1"},
        {"command": "close"},
    ])

    serve(channel, source, transform, target, **_hosting())

    assert target.value("table") == "stage.rows"
    assert channel.emitted[-1]["projection"]["destination"]["values"]["table"] == "stage.rows"
    # Answered under the request it was asked as, so the browser can match it.
    assert channel.emitted[-1]["request_id"] == "o1"


def test_a_change_to_one_object_is_what_the_others_project_next(tmp_path: Path) -> None:
    """The Transform holds the same Source the reader edits: no copy is answered."""
    other = tmp_path / "other.csv"
    other.write_text("x,y,z\n1,2,3\n", encoding="utf-8")
    channel = _Channel([
        {"command": "operate", "object": "source", "operation": "update",
         "arguments": {"name": "file", "value": str(other)}},
        {"command": "close"},
    ])

    serve(channel, *_load(_rows(tmp_path)), **_hosting())

    assert channel.emitted[-1]["projection"]["transform"]["source_columns"] == ["x", "y", "z"]


@pytest.mark.parametrize("command, message", [
    ({"command": "operate", "object": "load", "operation": "update"},
     "A Load has no object 'load'. Objects: source, transform, destination."),
    ({"command": "operate", "object": "destination", "operation": "drop"},
     "A destination has no operation 'drop'. Operations: select, set_write_policy, update."),
    ({"command": "frobnicate"}, "rey_loader does not answer the command 'frobnicate'."),
], ids=["object", "operation", "command"])
def test_a_refusal_is_answered_and_serving_goes_on(
    tmp_path: Path, command: dict[str, Any], message: str,
) -> None:
    channel = _Channel([{**command, "request_id": 7}, {"command": "projection"}])

    serve(channel, *_load(_rows(tmp_path)), **_hosting())

    assert channel.emitted[1] == {"error": message, "command": command["command"],
                                  "request_id": 7}
    assert channel.emitted[2]["projection"]["subject_key"] == "loader.file"


def test_an_objects_own_refusal_is_reported_and_answered(
    tmp_path: Path, _reports: list[AppError],
) -> None:
    channel = _Channel([
        {"command": "operate", "object": "destination", "operation": "set_write_policy",
         "arguments": {"policy": "obliterate"}, "request_id": 3},
    ])

    serve(channel, *_load(_rows(tmp_path)), **_hosting())

    assert channel.emitted[-1]["command"] == "operate"
    assert channel.emitted[-1]["request_id"] == 3
    assert len(_reports) == 1 and str(_reports[0]) == channel.emitted[-1]["error"]


def test_preview_answers_the_result_with_the_projection_of_the_same_state(
    tmp_path: Path,
) -> None:
    channel = _Channel([{"command": "preview", "request_id": "p1"}])

    serve(channel, *_load(_rows(tmp_path)), **_hosting())

    answer = channel.emitted[-1]
    assert answer["request_id"] == "p1"
    assert answer["preview"] == {"columns": ["a", "b"],
                                 "rows": [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
                                 "truncated": False}
    assert answer["projection"]["subject_key"] == "loader.file"


def test_a_preview_of_a_vanished_file_is_answered_and_serving_goes_on(
    tmp_path: Path,
) -> None:
    rows = _rows(tmp_path)
    loaded = _load(rows)
    rows.unlink()
    channel = _Channel([{"command": "preview", "request_id": "p2"}, {"command": "projection"}])

    serve(channel, *loaded, **_hosting())

    assert channel.emitted[1]["command"] == "preview"
    assert channel.emitted[1]["request_id"] == "p2"
    assert channel.emitted[2]["projection"]["subject_key"] == "loader.file"


def test_the_explicit_close_releases_the_transforms_source_and_target(
    tmp_path: Path,
) -> None:
    source, transform, target = _load(_rows(tmp_path))

    serve(_Channel([{"command": "close"}]), source, transform, target, **_hosting())

    with pytest.raises(StateError):
        transform.preview(SimpleNamespace())


def test_the_launcher_detaching_releases_nothing(tmp_path: Path) -> None:
    """Connection lifetime is not the Load's: only the semantic close releases it."""
    source, transform, target = _load(_rows(tmp_path))

    serve(_Channel([]), source, transform, target, **_hosting())

    assert transform.preview(SimpleNamespace()).columns == ("a", "b")


def test_a_projection_request_is_answered_while_serving(tmp_path: Path) -> None:
    """A view that has just attached asks; it is answered with what the objects hold."""
    commands: queue.Queue[Any] = queue.Queue()
    channel = _Channel(commands)
    served = threading.Thread(target=serve, args=(channel, *_load(_rows(tmp_path)),
                                                   SimpleNamespace()),
                              kwargs={"run_log": _RunLog(), "capabilities": _Capabilities(),
                                      "declared": _DECLARED},
                              daemon=True)
    served.start()
    try:
        first = channel.pushed.get(timeout=WAIT)
        commands.put({"command": "projection"})
        assert channel.pushed.get(timeout=WAIT) == first
    finally:
        commands.put(None)
        served.join(timeout=WAIT)
    assert not served.is_alive()


# -- a load, as an operation of the serving application's Run (S2) ----------------


def _complete_or_refuse(rows: int = 2, held: threading.Event | None = None) -> Any:
    """A stand-in for ``run_load_objects`` that needs no database.

    It reads the live objects it is handed, as the real one does: an incomplete
    Target is refused as ``run_selected_load`` refuses it, and a complete one
    "loads" ``rows``. Given ``held``, it waits for it first.
    """
    calls: list[tuple[Any, ...]] = []

    def load(ctx: Any, run_log: Any, source: Source, transform: Transform,
             target: Target) -> int:
        calls.append((source, transform, target))
        if held is not None:
            assert held.wait(WAIT)
        problems = target.validate()
        if problems:
            raise ConfigError(f"The load is not complete. Target: {', '.join(problems)}.")
        return rows

    load.calls = calls  # type: ignore[attr-defined]
    return load


def _serving(tmp_path: Path, run_log: _RunLog, ctx: Any = None) -> tuple[
        queue.Queue[Any], _Channel, threading.Thread, tuple[Source, Transform, Target]]:
    commands: queue.Queue[Any] = queue.Queue()
    channel = _Channel(commands)
    loaded = _load(_rows(tmp_path))
    served = threading.Thread(target=serve, args=(channel, *loaded, ctx or SimpleNamespace()),
                              kwargs={"run_log": run_log, "capabilities": _Capabilities(),
                                      "declared": _DECLARED},
                              daemon=True)
    served.start()
    assert "projection" in channel.pushed.get(timeout=WAIT)
    return commands, channel, served, loaded


def _answer(channel: _Channel, request_id: Any) -> dict[str, Any]:
    """The next pushed message carrying ``request_id``."""
    while True:
        message = channel.pushed.get(timeout=WAIT)
        if message.get("request_id") == request_id:
            return message


def test_a_failed_load_is_answered_and_serving_recovers_to_a_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acceptance sequence: fail, correct through operate, succeed, close normally.

    The failed load is the operation's -- recorded RUN_COMPLETE failed and answered
    -- and not the application's: ctx.run_failed is never set, so the serving Run
    ends successfully.
    """
    load = _complete_or_refuse(rows=2)
    monkeypatch.setattr("rey_loader.serve.run_load_objects", load)
    run_log, ctx = _RunLog(), SimpleNamespace()
    commands, channel, served, (_, _, target) = _serving(tmp_path, run_log, ctx)
    try:
        commands.put({"command": "run", "request_id": "b"})
        failed = _answer(channel, "b")
        assert failed["command"] == "run" and "not complete" in failed["error"]

        for name, value in (("table", "stage.rows"), ("connection", "rey_apps")):
            commands.put({"command": "operate", "object": "destination", "operation": "update",
                          "arguments": {"name": name, "value": value}})
            assert "projection" in channel.pushed.get(timeout=WAIT)

        commands.put({"command": "run", "request_id": "c"})
        assert _answer(channel, "c") == {"loaded": {"status": "SUCCEEDED", "rows": 2},
                                         "request_id": "c"}
        commands.put({"command": "close"})
    finally:
        commands.put(None)
        served.join(timeout=WAIT)
    assert not served.is_alive()
    assert run_log.completions() == ["failed", "success"]
    assert not getattr(ctx, "run_failed", False)
    # Every load read the one live Target the reader corrected: nothing rebuilt.
    assert all(called[2] is target for called in load.calls)


def test_a_dry_run_records_the_operation_and_skips_the_load_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As ``load --dry-run``: not validated, not executed, and a successful operation."""
    load = _complete_or_refuse()
    monkeypatch.setattr("rey_loader.serve.run_load_objects", load)
    run_log = _RunLog()
    commands, channel, served, _ = _serving(tmp_path, run_log)
    try:
        commands.put({"command": "run", "dry_run": True, "request_id": "d"})
        assert _answer(channel, "d") == {"loaded": {"status": "SUCCEEDED", "rows": 0},
                                         "request_id": "d"}
    finally:
        commands.put(None)
        served.join(timeout=WAIT)
    assert load.calls == []
    assert run_log.records[0] == ("RUN_START", {"operation": "load",
                                                "settings": {"apply": False}})
    assert run_log.completions() == ["success"]


def test_while_a_load_runs_only_the_projection_is_answered_and_close_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = threading.Event()
    monkeypatch.setattr("rey_loader.serve.run_load_objects", _complete_or_refuse(held=held))
    commands, channel, served, (source, transform, _) = _serving(tmp_path, _RunLog())
    try:
        commands.put({"command": "run", "request_id": "r"})
        for refused in ({"command": "run", "request_id": 1},
                        {"command": "operate", "object": "destination", "operation": "update",
                         "arguments": {"name": "table", "value": "x"}, "request_id": 2},
                        {"command": "preview", "request_id": 3}):
            commands.put(refused)
            answer = _answer(channel, refused["request_id"])
            assert answer["error"] == (f"A load is running; the {refused['command']} "
                                       "waits until it has finished.")
        commands.put({"command": "projection"})
        assert channel.pushed.get(timeout=WAIT)["projection"]["subject_key"] == "loader.file"

        commands.put({"command": "close"})
        served.join(timeout=0.5)
        assert served.is_alive()
        # Not released while the load still reads them.
        assert transform.preview(SimpleNamespace()).columns == ("a", "b")
    finally:
        held.set()
        served.join(timeout=WAIT)
        commands.put(None)
    assert not served.is_alive()
    assert "not complete" in _answer(channel, "r")["error"]
    with pytest.raises(StateError):
        transform.preview(SimpleNamespace())


def test_an_unexpected_load_failure_is_answered_and_serving_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _reports: list[AppError],
) -> None:
    """``_run`` is the hosting application's answer boundary for one load (#1151 S2).

    Requires the exceptions_are_caught_narrowly admission of
    rey_loader/rey_loader/serve.py _run.
    """
    def vanished(*_args: Any) -> int:
        raise RuntimeError("the destination's disk vanished")

    monkeypatch.setattr("rey_loader.serve.run_load_objects", vanished)
    run_log = _RunLog()
    commands, channel, served, _ = _serving(tmp_path, run_log)
    try:
        commands.put({"command": "run", "request_id": "u"})
        assert _answer(channel, "u")["error"] == (
            "rey_loader serve: the run failed: the destination's disk vanished")
        assert isinstance(_reports[-1].__cause__, RuntimeError)
        commands.put({"command": "projection"})
        assert channel.pushed.get(timeout=WAIT)["projection"]["subject_key"] == "loader.file"
    finally:
        commands.put(None)
        served.join(timeout=WAIT)
    assert run_log.completions() == ["failed"]


# -- the opening identity -------------------------------------------------------


class _Paths:
    """A stand-in PathResolver: authorizes beneath ``root`` only."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def authorize(self, raw_path: Any) -> Path:
        path = Path(str(raw_path)).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ConfigError(f"Path is outside allowed roots: {path}")
        return path


def test_a_handed_over_file_opens_a_file_source_on_that_path(tmp_path: Path) -> None:
    rows = _rows(tmp_path)

    source, transform, target = hosted_load(SimpleNamespace(paths=_Paths(tmp_path)),
                                            file=str(rows))

    assert source.selected_kind() == "file"
    assert source.value("file") == str(rows.resolve())
    # The suffix mapping's own answer, as the Console's handover took it.
    assert source.value("file-type") == "CSV"
    assert source.value("file-manifest-id") is None
    assert target.declaration()["values"] == {}
    assert transform.preview(SimpleNamespace()).columns == ("a", "b")


def test_a_handed_over_file_outside_the_permitted_roots_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="outside allowed roots"):
        hosted_load(SimpleNamespace(paths=_Paths(tmp_path / "allowed")),
                    file=str(_rows(tmp_path)))


def test_a_handed_over_statement_opens_a_database_source() -> None:
    source, _, _ = hosted_load(SimpleNamespace(), source_connection="rey_apps",
                               statement="select 1")

    assert source.selected_kind() == "database"
    assert (source.value("statement"), source.value("source-connection")) == (
        "select 1", "rey_apps")


def test_no_identity_is_refused() -> None:
    with pytest.raises(ConfigError, match="no load identity"):
        hosted_load(SimpleNamespace())


def test_a_governed_identity_reaches_the_governed_read_as_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launch inputs are text; the governed read is asked by id (Load on mutation 7183)."""
    asked: dict[str, Any] = {}

    def governed(ctx: Any, **identity: Any) -> Source:
        asked.update(identity)
        return Source.from_declaration({})

    monkeypatch.setattr(Source, "from_governed", governed)
    monkeypatch.setattr(Transform, "from_source", lambda *args, **kwargs: None)

    hosted_load(SimpleNamespace(), file_mutation_id="7183")

    assert asked == {"file_manifest_id": None, "file_mutation_id": 7183}


def test_a_governed_identity_that_is_not_an_id_is_refused() -> None:
    with pytest.raises(ConfigError, match="file_manifest_id is not an id"):
        hosted_load(SimpleNamespace(), file_manifest_id="seven")


# -- the published command -------------------------------------------------------


@pytest.mark.parametrize("identity, attribute, value", [
    (["--file-manifest-id", "15"], "file_manifest_id", "15"),
    (["--file-mutation-id", "9"], "file_mutation_id", "9"),
    (["--file", "/data/rows.csv"], "file", "/data/rows.csv"),
    (["--statement", "select 1", "--source-connection", "rey_apps"], "statement", "select 1"),
], ids=["manifest", "mutation", "file", "statement"])
def test_serve_takes_one_load_identity(
    monkeypatch: pytest.MonkeyPatch, identity: list[str], attribute: str, value: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--config-path", "/c", "serve", *identity,
                                      "--subject", "file"])

    args = loader_main._parse_args()

    assert (args.command, getattr(args, attribute), args.subject) == ("serve", value, "file")


def test_serve_refuses_a_load_without_the_selected_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1151: a Load opens on the selected subject it acts on."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--config-path", "/c", "serve",
                                      "--file-manifest-id", "15"])

    with pytest.raises(SystemExit):
        loader_main._parse_args()


@pytest.mark.parametrize("identity", [
    [],
    ["--file-manifest-id", "15", "--file", "/data/rows.csv"],
    ["--statement", "select 1"],
    ["--file", "/data/rows.csv", "--source-connection", "rey_apps"],
    ["--file", "/data/rows.csv", "--table", "stage.rows"],
    ["--file-manifest-id", "15", "--dry-run"],
], ids=["none", "two", "statement-alone", "connection-without-statement",
        "a-destination", "dry-run"])
def test_serve_refuses_anything_but_exactly_one_identity(
    monkeypatch: pytest.MonkeyPatch, identity: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--config-path", "/c", "serve", *identity])

    with pytest.raises(SystemExit):
        loader_main._parse_args()


def test_serve_is_published_as_a_hosted_command() -> None:
    published = {one["name"]: one for one in get_registration()["cli"]["commands"]}

    assert published["serve"]["invocation"] == "hosted"
    assert [p["name"] for p in published["serve"]["parameters"]] == [
        "file-manifest-id", "file-mutation-id", "file", "statement", "source-connection",
        "subject"]
    assert published["serve"]["parameter_groups"][0]["members"] == [
        "file-manifest-id", "file-mutation-id", "file", "statement"]


# -- over the real channel -------------------------------------------------------

#: A child process serving a real Load over the real channel.
CHILD = textwrap.dedent(f"""
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    sys.path.insert(0, {str(_ROOT)!r})
    from rey_lib.presentation import Projection
    from rey_lib.run import AppExecute
    from rey_lib.run.app_channel import AttachedApp
    from rey_loader.serve import hosted_load, serve

    class Paths:
        def authorize(self, raw_path):
            return Path(raw_path).resolve()

    class NoCapabilities:
        def invoke(self, capability, inputs):
            raise AssertionError(capability)

    ctx = SimpleNamespace(paths=Paths())
    application_run = AppExecute(run_id=100, control=None, subject_type="app",
                                 subject_id="rey_loader")
    channel = AttachedApp.attach(application_run.run_id)
    serve(channel, *hosted_load(ctx, file=sys.argv[1]), ctx, run_log=None,
          capabilities=NoCapabilities(),
          declared=Projection(subject_key="loader.file", panel="loader_panel",
                              panel_settings=dict(), content=dict()))
    channel.close()
""")


def test_the_launcher_operates_the_served_load_over_the_channel(tmp_path: Path) -> None:
    app = LaunchedApp.launch([sys.executable, "-c", CHILD, str(_rows(tmp_path))])
    try:
        assert app.connected(timeout=WAIT)
        assert app.run_id == 100
        events = app.events(timeout=WAIT)
        assert next(events)["projection"]["source"]["selected"] == "file"

        app.send({"command": "operate", "object": "destination", "operation": "update",
                  "arguments": {"name": "table", "value": "stage.rows"}})
        assert next(events)["projection"]["destination"]["values"]["table"] == "stage.rows"

        app.send({"command": "close"})
        assert app.wait(timeout=WAIT) == 0
    finally:
        app.close()


@pytest.mark.parametrize(("subject", "key"), [
    ("file", "loader.file"), ("mutation.record", "loader.mutation")])
def test_the_live_load_presents_itself_as_loader_and_the_selected_subject(
    subject: str, key: str,
) -> None:
    """#1151: the selected row's subject is transformed, never replaced by the button."""
    assert presentation_key(subject) == key


def test_a_load_with_no_selected_subject_is_refused() -> None:
    with pytest.raises(ConfigError, match="selected subject"):
        presentation_key("")


def test_serve_declares_the_selected_subjects_it_opens_a_load_on() -> None:
    """#1151: the Load button's reference kinds reach serve by its own declaration."""
    from rey_lib.config.applications import build_applications

    from rey_loader import registration

    built = build_applications(
        SimpleNamespace(apps=[{"name": "rey_loader", "app_path": "/apps/rey_loader"}],
                        connections=[]),
        {"rey_loader": registration.get_registration()})[0]

    command = built.command("serve")
    assert command.hosted_subject_kinds == ("governed_file", "mutation_file", "mutation_object")
    assert "subject" in {parameter.name for parameter in command.parameters}


# -- the declared actions (#1151, the Workflow pattern) ------------------------------


def _filled(action: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    """What a panel sends: the declared command, with each raw input at its declared path."""
    import copy

    command = copy.deepcopy(action["command"])
    for name, path in (action.get("inputs") or {}).items():
        place = command
        for key in path[:-1]:
            place = place.setdefault(key, {})
        place[path[-1]] = given[name]
    return command


def _first_projection(tmp_path: Path) -> dict[str, Any]:
    channel = _Channel([{"command": "close"}])
    serve(channel, *_load(_rows(tmp_path)), **_hosting())
    return channel.emitted[0]["projection"]


def _by_role(actions: list[dict[str, Any]], **role: str) -> list[dict[str, Any]]:
    """The declared actions of exactly that role -- how a surface finds one."""
    return [one for one in actions if one["role"] == role]


def test_each_action_is_found_by_its_role_never_by_an_operation_name(tmp_path: Path) -> None:
    """#1151 row 5: what an action does to which projected state; no id travels."""
    actions = _first_projection(tmp_path)["actions"]

    assert set(actions) == {"source", "transform", "destination", "load"}
    assert all("id" not in one for listed in actions.values() for one in listed)
    (choose,) = _by_role(actions["source"], act="choose", on="kinds")
    assert choose == {"role": {"act": "choose", "on": "kinds"},
                      "command": {"command": "operate", "object": "source",
                                  "operation": "select", "arguments": {}},
                      "inputs": {"choice": ["arguments", "kind"]}}
    (edit,) = _by_role(actions["transform"], act="set", on="columns")
    assert edit["inputs"] == {"index": ["arguments", "at"], "field": ["arguments", "field"],
                              "value": ["arguments", "value"]}
    (policy,) = _by_role(actions["destination"], act="choose", on="modes")
    assert policy["inputs"] == {"choice": ["arguments", "policy"]}
    assert [one["role"] for one in actions["load"]] == [
        {"act": "read", "on": "load"}, {"act": "read", "on": "preview"},
        {"act": "run", "on": "load"}]
    (run,) = _by_role(actions["load"], act="run", on="load")
    assert run["inputs"] == {"dry_run": ["dry_run"]}


def test_every_role_input_is_a_parameter_of_the_operation_it_fills() -> None:
    """A role is the routing table's, over operations it routes, onto real parameters."""
    for name, roles in _ROLES.items():
        for operation, (_, inputs) in roles.items():
            method = _OPERATIONS[name][operation]
            parameters = set(inspect.signature(method).parameters) - {"self", "ctx"}
            assert set(inputs.values()) <= parameters, (name, operation)


def test_a_field_is_its_own_action_and_its_object_says_which_operation_editing_it_is(
    tmp_path: Path,
) -> None:
    projection = _first_projection(tmp_path)
    (table,) = _by_role(projection["actions"]["destination"],
                        act="set", on="values", field="table")

    assert table == {"role": {"act": "set", "on": "values", "field": "table"},
                     "command": {"command": "operate", "object": "destination",
                                 "operation": "update", "arguments": {"name": "table"}},
                     "inputs": {"value": ["arguments", "value"]}}
    for name, operation in (projection["transform"].get("field_operations") or {}).items():
        (declared,) = _by_role(projection["actions"]["transform"],
                               act="set", on="values", field=name)
        assert declared["command"]["operation"] == operation


def test_a_field_drawn_with_a_request_has_its_own_action() -> None:
    """Choosing OpenFIGI held nothing: http-adapter is drawn with the request, not in the
    form fields, and had no action. Every drawn field has one -- with its own operation."""
    actions = _actions({"transform": {
        "fields": {"http": ["http-transform"]},
        "request_fields": {"http": ["http-adapter"]},
        "field_operations": {"http-adapter": "select_http_operation"},
    }})

    (adapter,) = _by_role(actions["transform"], act="set", on="values", field="http-adapter")
    assert adapter["command"] == {"command": "operate", "object": "transform",
                                  "operation": "select_http_operation",
                                  "arguments": {"name": "http-adapter"}}
    assert adapter["inputs"] == {"value": ["arguments", "value"]}


def test_an_operation_its_object_does_not_offer_is_not_declared(tmp_path: Path) -> None:
    projection = _first_projection(tmp_path)

    for name, gated, role in (
        ("source", "save_query", {"act": "save", "on": "values", "field": "statement"}),
        ("transform", "save", {"act": "save", "on": "columns"}),
    ):
        offered = gated in (projection[name].get("operations") or [])
        assert bool(_by_role(projection["actions"][name], **role)) is offered


def test_a_declared_action_filled_at_its_slots_is_answered_by_serve(tmp_path: Path) -> None:
    """The panel's whole part: copy, fill the declared slots, send unchanged."""
    source, transform, target = _load(_rows(tmp_path))
    first = _Channel([{"command": "close"}])
    serve(first, source, transform, target, **_hosting())
    (table,) = _by_role(first.emitted[0]["projection"]["actions"]["destination"],
                        act="set", on="values", field="table")
    channel = _Channel([{**_filled(table, {"value": "stage.rows"}), "request_id": "a1"},
                        {"command": "close"}])

    serve(channel, source, transform, target, **_hosting())

    assert target.value("table") == "stage.rows"
    assert channel.emitted[-1]["request_id"] == "a1"
    assert "error" not in channel.emitted[-1]
