"""rey_loader serving one Load to the launcher (#1151 S1).

The Load is the canonical Source, Transform and Target themselves, on a CSV file in
a temporary directory, so these tests need no installation. serve() routes each
command to the object it names and composes the Load's projection from the three
objects' own projections.
"""

from __future__ import annotations

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
from rey_lib.run.app_channel import LaunchedApp

import main as loader_main
from rey_loader.registration import get_registration
from rey_loader.serve import PANEL_TYPE, hosted_load, serve

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


def _hosting() -> dict[str, Any]:
    """What a serve call in these tests is hosted with: a runtime, a run log, capabilities."""
    return {"ctx": SimpleNamespace(), "run_log": _RunLog(), "capabilities": _Capabilities()}


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


def test_serve_sends_the_composed_projection_first(tmp_path: Path) -> None:
    channel = _Channel([{"command": "close"}])

    serve(channel, *_load(_rows(tmp_path)), **_hosting())

    (first,) = channel.emitted
    projection = first["projection"]
    assert projection["panel_type"] == PANEL_TYPE == "load"
    assert set(projection) == {"panel_type", "source", "transform", "destination",
                               "connections"}
    # The host's runtime offers no configured connection here.
    assert projection["connections"] == []
    # Each object describes its own fields, and offers its own choices.
    assert projection["source"]["field_metadata"]["statement"]["value_type"] == "sql"
    assert projection["destination"]["field_metadata"]["table"]["placeholder"] == "schema.table"
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
    assert channel.emitted[2]["projection"]["panel_type"] == "load"


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
    assert answer["projection"]["panel_type"] == "load"


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
    assert channel.emitted[2]["projection"]["panel_type"] == "load"


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
                              kwargs={"run_log": _RunLog(), "capabilities": _Capabilities()},
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
                              kwargs={"run_log": run_log, "capabilities": _Capabilities()},
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
        assert channel.pushed.get(timeout=WAIT)["projection"]["panel_type"] == "load"

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
        assert channel.pushed.get(timeout=WAIT)["projection"]["panel_type"] == "load"
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
    monkeypatch.setattr(sys, "argv", ["main.py", "--config-path", "/c", "serve", *identity])

    args = loader_main._parse_args()

    assert (args.command, getattr(args, attribute)) == ("serve", value)


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
        "file-manifest-id", "file-mutation-id", "file", "statement", "source-connection"]
    assert published["serve"]["parameter_groups"][0]["members"] == [
        "file-manifest-id", "file-mutation-id", "file", "statement"]


# -- over the real channel -------------------------------------------------------

#: A child process serving a real Load over the real channel.
CHILD = textwrap.dedent(f"""
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    sys.path.insert(0, {str(_ROOT)!r})
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
          capabilities=NoCapabilities())
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
