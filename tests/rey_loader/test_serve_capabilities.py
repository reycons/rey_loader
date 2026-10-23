"""rey_loader answers invoke on the Source, Transform and Target its serve holds (#1199 S5).

Each capability reaches one held object's own definition -- never a composite
Load -- through HostedCapabilities, against this application's registration and
governed declarations (stood in here by rows mirroring the registration, as
path #941 publishes them). invoke is answered inline, a running load does not
refuse it, and preview, run and the objects' edits are not capabilities.
"""

from __future__ import annotations

import queue
import sys
import textwrap
import threading
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from rey_lib.config.applications import build_applications, with_choice_collections
from rey_lib.errors.error_utils import AppError
from rey_lib.load import Source, Target, Transform
from rey_lib.run.app_channel import LaunchedApp

import main as loader_main
from rey_loader import serve as serve_module
from rey_loader.registration import CAPABILITIES
from rey_loader.serve import hosted_capabilities, serve

_ROOT = Path(__file__).resolve().parents[2]

#: How long any one wait in these tests may take.
WAIT = 20.0

_KEYS = ("load_source.definition", "load_transform.definition", "load_target.definition")


def _rows(tmp_path: Path) -> Path:
    path = tmp_path / "rows.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    return path


def _load(path: Path) -> tuple[Source, Transform, Target]:
    """The three objects of a load on ``path``, built as ``hosted_load`` builds them."""
    source = Source.from_declaration(
        {"values": {"file": str(path), "file-type": "csv"}, "selected": "file"})
    target = Target.from_declaration({"values": {"connection": "warehouse"}})
    return source, Transform.from_source(SimpleNamespace(), source, {}, target=target), target


def _governed_control() -> Mock:
    """The governed read boundary, answering rows that mirror the registration (path #941)."""
    control = Mock()
    control.get_application_capabilities.return_value = [
        {"capability_key": one["key"], "description": one["description"],
         "target_kinds": list(one["target_kinds"]),
         "input_contract": one["input_contract"], "access": one["access"]}
        for one in CAPABILITIES
    ]
    return control


def _ctx() -> SimpleNamespace:
    """A runtime configuring rey_loader with exactly its published capabilities."""
    applications = build_applications(
        SimpleNamespace(**with_choice_collections(
            {"apps": [{"name": "rey_loader", "app_path": "/apps/rey_loader"}]})),
        registrations={"rey_loader": {"name": "rey_loader", "capabilities": CAPABILITIES}},
    )
    return SimpleNamespace(applications=applications)


def _held(loaded: tuple[Source, Transform, Target], kind: str = "file") -> Any:
    return hosted_capabilities(_ctx(), _governed_control(), *loaded, kind)


class _Channel:
    """This application's end of the channel, fed from a queue."""

    def __init__(self) -> None:
        self.commands_in: queue.Queue[Any] = queue.Queue()
        self.pushed: queue.Queue[dict[str, Any]] = queue.Queue()

    def commands(self) -> Any:
        while (command := self.commands_in.get(timeout=WAIT)) is not None:
            yield command

    def emit(self, message: dict[str, Any]) -> None:
        self.pushed.put(message)

    def answer_to(self, request_id: str) -> dict[str, Any]:
        while True:
            message = self.pushed.get(timeout=WAIT)
            if message.get("request_id") == request_id:
                return message


class _RunLog:
    """A stand-in run log: what was appended, and nothing else."""

    def append(self, record_type: str, **fields: Any) -> int:
        return 1

    def set_nest_level(self, level: str) -> None:
        del level

    def require_structural_record(self, run_log_id: Any, record_type: str) -> None:
        del run_log_id, record_type


# -- the catalogue -------------------------------------------------------------


def test_each_capability_is_one_held_objects_own_definition(tmp_path: Path) -> None:
    source, transform, target = loaded = _load(_rows(tmp_path))
    capabilities = _held(loaded)

    assert capabilities.invoke("load_source.definition", {}) == source.definition()
    assert capabilities.invoke("load_transform.definition", {}) == transform.definition()
    assert capabilities.invoke("load_target.definition", {}) == target.definition()


@pytest.mark.parametrize("kind", ["file_manifest", "file_mutation", "file", "statement"])
def test_every_identity_serve_opens_on_is_a_target_kind(tmp_path: Path, kind: str) -> None:
    capabilities = _held(_load(_rows(tmp_path)), kind)

    for key in _KEYS:
        assert capabilities.invoke(key, {})["kind"]


def test_preview_run_edits_and_a_composite_are_not_capabilities(tmp_path: Path) -> None:
    capabilities = _held(_load(_rows(tmp_path)))

    for key in ("load.definition", "load_transform.preview", "load.run",
                "load_target.update", "load_source.select"):
        with pytest.raises(AppError, match="is not invocable"):
            capabilities.invoke(key, {})


def test_a_definition_takes_no_inputs(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="refuses its inputs"):
        _held(_load(_rows(tmp_path))).invoke("load_target.definition", {"table": "x"})


# -- serve ----------------------------------------------------------------------


def _serving(loaded: tuple[Source, Transform, Target], channel: _Channel) -> threading.Thread:
    served = threading.Thread(
        target=serve, args=(channel, *loaded, SimpleNamespace()),
        kwargs={"run_log": _RunLog(), "capabilities": _held(loaded)}, daemon=True)
    served.start()
    return served


def test_invoke_is_answered_inline_with_its_request_id(tmp_path: Path) -> None:
    loaded = _load(_rows(tmp_path))
    channel = _Channel()
    served = _serving(loaded, channel)
    try:
        channel.commands_in.put({"command": "invoke", "capability": "load_target.definition",
                                 "inputs": {}, "request_id": "r1"})
        assert channel.answer_to("r1") == {"result": loaded[2].definition(),
                                           "request_id": "r1"}
        channel.commands_in.put({"command": "invoke", "capability": "load.run",
                                 "inputs": {}, "request_id": "r2"})
        refused = channel.answer_to("r2")
        assert refused["command"] == "invoke" and "is not invocable" in refused["error"]
    finally:
        channel.commands_in.put(None)
        served.join(timeout=WAIT)


def test_a_running_load_does_not_refuse_an_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = threading.Event()
    started = threading.Event()

    def load(ctx: Any, run_log: Any, source: Source, transform: Transform,
             target: Target) -> int:
        started.set()
        assert held.wait(WAIT)
        return 0

    monkeypatch.setattr(serve_module, "run_load_objects", load)
    loaded = _load(_rows(tmp_path))
    channel = _Channel()
    served = _serving(loaded, channel)
    try:
        # Not a dry run: a dry run skips the load, and this one must be running.
        channel.commands_in.put({"command": "run", "dry_run": False, "request_id": "run1"})
        assert started.wait(WAIT)
        channel.commands_in.put({"command": "invoke", "capability": "load_source.definition",
                                 "inputs": {}, "request_id": "r3"})
        assert channel.answer_to("r3")["result"] == loaded[0].definition()
    finally:
        held.set()
        channel.commands_in.put(None)
        served.join(timeout=WAIT)


# -- main: the hosted kind is the identity serve was opened by ---------------------


@pytest.mark.parametrize("identity, kind", [
    ({"file_manifest_id": "12"}, "file_manifest"),
    ({"file_mutation_id": "34"}, "file_mutation"),
    ({"file": "/rows.csv"}, "file"),
    ({"statement": "the statement", "source_connection": "warehouse"}, "statement"),
])
def test_serve_settles_the_capabilities_for_the_identity_it_was_opened_by(
    identity: dict[str, str], kind: str,
) -> None:
    args = Namespace(**{"file_manifest_id": None, "file_mutation_id": None, "file": None,
                        "statement": None, "source_connection": None, **identity})
    ctx = SimpleNamespace(run=SimpleNamespace(run_id=7))
    source = SimpleNamespace(selected_kind=lambda: "file")
    loaded = (source, "transform", "target")
    settled: list[tuple[Any, ...]] = []
    served: list[dict[str, Any]] = []
    with patch.object(loader_main, "hosted_load", return_value=loaded), patch.object(
        loader_main, "open_shared_control",
        return_value=SimpleNamespace(shared_control="control"),
    ), patch.object(
        loader_main, "hosted_capabilities",
        side_effect=lambda *a: settled.append(a) or "capabilities",
    ), patch.object(
        loader_main.AttachedApp, "attach", return_value=Mock(),
    ), patch.object(
        loader_main, "serve", new=lambda *a, **kw: served.append(kw),
    ):
        assert loader_main._cmd_serve(ctx, "run log", args, Mock()) == 0

    assert settled == [(ctx, "control", source, "transform", "target", kind)]
    assert served[0]["capabilities"] == "capabilities"


# -- over the real channel --------------------------------------------------------

#: A child process serving a real Load, with its real capabilities, over the real channel.
CHILD = textwrap.dedent(f"""
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    sys.path.insert(0, {str(_ROOT)!r})
    sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
    from rey_lib.run import AppExecute
    from rey_lib.run.app_channel import AttachedApp
    from rey_loader.serve import hosted_load, serve
    from test_serve_capabilities import _held

    class Paths:
        def authorize(self, raw_path):
            return Path(raw_path).resolve()

    ctx = SimpleNamespace(paths=Paths())
    application_run = AppExecute(run_id=300, control=None, subject_type="app",
                                 subject_id="rey_loader")
    channel = AttachedApp.attach(application_run.run_id)
    loaded = hosted_load(ctx, file=sys.argv[1])
    serve(channel, *loaded, ctx, run_log=None, capabilities=_held(loaded))
    channel.close()
""")


def test_the_launcher_invokes_each_held_objects_definition_over_the_channel(
    tmp_path: Path,
) -> None:
    app = LaunchedApp.launch([sys.executable, "-c", CHILD, str(_rows(tmp_path))])
    try:
        assert app.connected(timeout=WAIT)
        events = app.events(timeout=WAIT)
        assert "projection" in next(events)

        answered = {}
        for index, key in enumerate(_KEYS):
            app.send({"command": "invoke", "capability": key, "inputs": {},
                      "request_id": f"r{index}"})
            answer = next(events)
            assert answer["request_id"] == f"r{index}"
            answered[key] = answer["result"]
        app.send({"command": "close"})

        assert app.wait(timeout=WAIT) == 0
        assert answered["load_source.definition"]["kind"] == "file"
        assert answered["load_transform.definition"]["kind"] == "identity"
        assert answered["load_target.definition"]["write_policy"] == "append"
    finally:
        app.close()
