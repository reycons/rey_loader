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

    serve(channel, *_load(_rows(tmp_path)), ctx=SimpleNamespace())

    (first,) = channel.emitted
    projection = first["projection"]
    assert projection["panel_type"] == PANEL_TYPE == "load"
    assert set(projection) == {"panel_type", "source", "transform", "destination"}
    assert projection["source"]["selected"] == "file"
    assert projection["transform"]["source_columns"] == ["a", "b"]
    assert projection["destination"]["selected"] == "database"


def test_operate_calls_the_named_objects_own_method_and_answers_the_projection(
    tmp_path: Path,
) -> None:
    source, transform, target = _load(_rows(tmp_path))
    channel = _Channel([
        {"command": "operate", "object": "destination", "operation": "update",
         "arguments": {"name": "table", "value": "stage.rows"}},
        {"command": "close"},
    ])

    serve(channel, source, transform, target, ctx=SimpleNamespace())

    assert target.value("table") == "stage.rows"
    assert channel.emitted[-1]["projection"]["destination"]["values"]["table"] == "stage.rows"


def test_a_change_to_one_object_is_what_the_others_project_next(tmp_path: Path) -> None:
    """The Transform holds the same Source the reader edits: no copy is answered."""
    other = tmp_path / "other.csv"
    other.write_text("x,y,z\n1,2,3\n", encoding="utf-8")
    channel = _Channel([
        {"command": "operate", "object": "source", "operation": "update",
         "arguments": {"name": "file", "value": str(other)}},
        {"command": "close"},
    ])

    serve(channel, *_load(_rows(tmp_path)), ctx=SimpleNamespace())

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

    serve(channel, *_load(_rows(tmp_path)), ctx=SimpleNamespace())

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

    serve(channel, *_load(_rows(tmp_path)), ctx=SimpleNamespace())

    assert channel.emitted[-1]["command"] == "operate"
    assert channel.emitted[-1]["request_id"] == 3
    assert len(_reports) == 1 and str(_reports[0]) == channel.emitted[-1]["error"]


def test_preview_answers_the_result_with_the_projection_of_the_same_state(
    tmp_path: Path,
) -> None:
    channel = _Channel([{"command": "preview", "request_id": "p1"}])

    serve(channel, *_load(_rows(tmp_path)), ctx=SimpleNamespace())

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

    serve(channel, *loaded, ctx=SimpleNamespace())

    assert channel.emitted[1]["command"] == "preview"
    assert channel.emitted[1]["request_id"] == "p2"
    assert channel.emitted[2]["projection"]["panel_type"] == "load"


def test_the_explicit_close_releases_the_transforms_source_and_target(
    tmp_path: Path,
) -> None:
    source, transform, target = _load(_rows(tmp_path))

    serve(_Channel([{"command": "close"}]), source, transform, target, ctx=SimpleNamespace())

    with pytest.raises(StateError):
        transform.preview(SimpleNamespace())


def test_the_launcher_detaching_releases_nothing(tmp_path: Path) -> None:
    """Connection lifetime is not the Load's: only the semantic close releases it."""
    source, transform, target = _load(_rows(tmp_path))

    serve(_Channel([]), source, transform, target, ctx=SimpleNamespace())

    assert transform.preview(SimpleNamespace()).columns == ("a", "b")


def test_a_projection_request_is_answered_while_serving(tmp_path: Path) -> None:
    """A view that has just attached asks; it is answered with what the objects hold."""
    commands: queue.Queue[Any] = queue.Queue()
    channel = _Channel(commands)
    served = threading.Thread(target=serve, args=(channel, *_load(_rows(tmp_path)),
                                                   SimpleNamespace()), daemon=True)
    served.start()
    try:
        first = channel.pushed.get(timeout=WAIT)
        commands.put({"command": "projection"})
        assert channel.pushed.get(timeout=WAIT) == first
    finally:
        commands.put(None)
        served.join(timeout=WAIT)
    assert not served.is_alive()


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

    ctx = SimpleNamespace(paths=Paths())
    application_run = AppExecute(run_id=100, control=None, subject_type="app",
                                 subject_id="rey_loader")
    channel = AttachedApp.attach(application_run.run_id)
    serve(channel, *hosted_load(ctx, file=sys.argv[1]), ctx)
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
